#! /usr/bin/env python
# -*- coding: utf-8 -*-

# Copyright (C) 2011 ~ 2012 Deepin, Inc.
#               2011 ~ 2012 Wang Yong
# 
# Author:     Wang Yong <lazycat.manatee@gmail.com>
# Maintainer: Wang Yong <lazycat.manatee@gmail.com>
# 
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# any later version.
# 
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
# 
# You should have received a copy of the GNU General Public License
# along with this program.  If not, see <http://www.gnu.org/licenses/>.

import os
from skin import app_theme
from nls import _

import glib
from detail_page import DetailPage
from split_word import init_jieba
from dtk.ui.button import LinkButton
from dtk.ui.navigatebar import Navigatebar
from deepin_utils.ipc import is_dbus_name_exists
from dtk.ui.utils import container_remove_all, set_cursor, touch_file, read_file, write_file
from dtk.ui.application import Application
from dtk.ui.statusbar import Statusbar
from home_page import HomePage
from uninstall_page import UninstallPage
from install_page import InstallPage
from upgrade_page import UpgradePage
from data_manager import DataManager
import gtk
from dbus.mainloop.glib import DBusGMainLoop
import dbus
import dbus.service
import time
from constant import DSC_SERVICE_NAME, DSC_SERVICE_PATH, DSC_FRONTEND_NAME, DSC_FRONTEND_PATH, ACTION_INSTALL, ACTION_UNINSTALL, ACTION_UPGRADE, CONFIG_DIR, ONE_DAY_SECONDS
from dtk.ui.new_slider import HSlider
from dtk.ui.threads import AnonymityThread
from events import global_event
import dtk.ui.tooltip as Tooltip
from dtk.ui.label import Label
from dtk.ui.gio_utils import start_desktop_file
from start_desktop_window import StartDesktopWindow

def jump_to_category(page_switcher, page_box, home_page, detail_page, first_category_name, second_category_name):
    switch_page(page_switcher, page_box, home_page, detail_page)
    home_page.jump_to_category(first_category_name, second_category_name)

def start_pkg(pkg_name, desktop_infos, (offset_x, offset_y, popup_x, popup_y), window):
    desktop_infos = filter(lambda desktop_info: os.path.exists(desktop_info[0]) != None, desktop_infos)
    desktop_infos_num = len(desktop_infos)
    if desktop_infos_num == 0:
        global_event.emit("show-message", "%s haven't any desktop file" % (pkg_name))
    elif desktop_infos_num == 1:
        start_desktop(pkg_name, desktop_infos[0][0])
    else:
        (screen, px, py, modifier_type) = window.get_display().get_pointer()
        StartDesktopWindow().start(pkg_name, desktop_infos, (px - offset_x + popup_x, py - offset_y + popup_y))
        
def start_desktop(pkg_name, desktop_path):
    global_event.emit("show-message", "%s: 已经发送启动请求" % (pkg_name))
    result = start_desktop_file(desktop_path)                    
    if result != True:
        global_event.emit("show-message", result)
    
def show_message(statusbar, message_box, message):
    hide_message(message_box)
    
    label = Label("%s" % message, enable_gaussian=True)
    label_align = gtk.Alignment()
    label_align.set(0.0, 0.5, 0, 0)
    label_align.set_padding(0, 0, 10, 0)
    label_align.add(label)
    message_box.add(label_align)
    
    statusbar.show_all()
    
    gtk.timeout_add(5000, lambda : hide_message(message_box))
    
def hide_message(message_box):
    container_remove_all(message_box)
    
    return False

def request_status(bus_interface, install_page, upgrade_page, uninstall_page):
    (download_status, action_status) = map(eval, bus_interface.request_status())
    
    install_page.update_download_status(download_status[ACTION_INSTALL])
    install_page.update_action_status(action_status[ACTION_INSTALL])
    
    upgrade_page.update_download_status(download_status[ACTION_UPGRADE])
    upgrade_page.update_action_status(action_status[ACTION_UPGRADE])
    
    uninstall_page.update_action_status(action_status[ACTION_UNINSTALL])
    
    return False

def grade_pkg(window, pkg_name, star):
    grade_config_path = os.path.join(CONFIG_DIR, "grade_pkgs")
    if not os.path.exists(grade_config_path):
        touch_file(grade_config_path)
        
    grade_config_str = read_file(grade_config_path)
    try:
        grade_config = eval(grade_config_str)

        if type(grade_config).__name__ != "dict":
            grade_config = {}
    except Exception:
        grade_config = {}
        
    current_time = time.time()    
    if not grade_config.has_key(pkg_name) or (current_time - grade_config[pkg_name]) > ONE_DAY_SECONDS:
        show_tooltip(window, "发送评分...")
        
        # Send grade to server.
        result = True
        
        if result:
            show_tooltip(window, "评分成功， 感谢您的参与！ :)")
            
            grade_config[pkg_name] = current_time
            write_file(grade_config_path, str(grade_config))
    else:
        show_tooltip(window, "您已经评过分了哟！ ;)")

def show_tooltip(window, message):
    Tooltip.text(window, message)
    Tooltip.disable(window, False)
    Tooltip.show_now()
    Tooltip.disable(window, True)
    
def switch_from_detail_page(page_switcher, detail_page, page_box):
    page_switcher.slide_to_page(page_box, "left")
    
def switch_to_detail_page(page_switcher, detail_page, pkg_name):
    detail_page.update_pkg_info(pkg_name)
    page_switcher.slide_to_page(detail_page, "right")

def switch_page(page_switcher, page_box, page, detail_page):
    if page_switcher.active_widget == detail_page:
        page_switcher.slide_to_page(page_box, "left")
    else:
        page_switcher.slide_to_page(page_box, "right")
        
    container_remove_all(page_box)
    
    if isinstance(page, UpgradePage):
        if page.in_no_notify_page:
            page.show_upgrade_page()
    
    page_box.pack_start(page, True, True)
    page_box.show_all()

def handle_dbus_reply(*reply):
    print "handle_dbus_reply" % (str(reply))
    
def handle_dbus_error(*error):
    print "handle_dbus_error" % (str(error))
    
def message_handler(messages, bus_interface, upgrade_page, uninstall_page, install_page):
    for message in messages:
        (signal_type, action_content) = message
        
        if signal_type == "download-start":
            (pkg_name, action_type) = action_content
            if action_type == ACTION_INSTALL:
                install_page.download_start(pkg_name)
            elif action_type == ACTION_UPGRADE:
                upgrade_page.download_start(pkg_name)
        elif signal_type == "download-update":
            (pkg_name, action_type, percent, speed) = action_content
            if action_type == ACTION_INSTALL:
                install_page.download_update(pkg_name, percent, speed)
            elif action_type == ACTION_UPGRADE:
                upgrade_page.download_update(pkg_name, percent, speed)
        elif signal_type == "download-finish":
            (pkg_name, action_type) = action_content
            if action_type == ACTION_INSTALL:
                install_page.download_finish(pkg_name)
            elif action_type == ACTION_UPGRADE:
                upgrade_page.download_finish(pkg_name)
        elif signal_type == "download-stop":
            (pkg_name, action_type) = action_content
            if action_type == ACTION_INSTALL:
                install_page.download_stop(pkg_name)
            elif action_type == ACTION_UPGRADE:
                upgrade_page.download_stop(pkg_name)
        elif signal_type == "action-start":
            (pkg_name, action_type) = action_content
            if action_type == ACTION_UNINSTALL:
                uninstall_page.action_start(pkg_name)
            elif action_type == ACTION_UPGRADE:
                upgrade_page.action_start(pkg_name)
            elif action_type == ACTION_INSTALL:
                install_page.action_start(pkg_name)
        elif signal_type == "action-update":
            (pkg_name, action_type, percent, status) = action_content
            if action_type == ACTION_UNINSTALL:
                uninstall_page.action_update(pkg_name, percent)
            elif action_type == ACTION_UPGRADE:
                upgrade_page.action_update(pkg_name, percent)
            elif action_type == ACTION_INSTALL:
                install_page.action_update(pkg_name, percent)
        elif signal_type == "action-finish":
            (pkg_name, action_type, pkg_info_list) = action_content
            if action_type == ACTION_UNINSTALL:
                uninstall_page.action_finish(pkg_name, pkg_info_list)
            elif action_type == ACTION_UPGRADE:
                upgrade_page.action_finish(pkg_name, pkg_info_list)
            elif action_type == ACTION_INSTALL:
                install_page.action_finish(pkg_name, pkg_info_list)
        elif signal_type == "update-list-finish":
            upgrade_page.fetch_upgrade_info()
            
            request_status(bus_interface, install_page, upgrade_page, uninstall_page)
        elif signal_type == "update-list-update":
            upgrade_page.update_upgrade_progress(action_content)
        elif signal_type == "parse-download-error":
            (pkg_name, action_type) = action_content
            if action_type == ACTION_INSTALL:
                install_page.download_parse_failed(pkg_name)
                global_event.emit("show-message", "分析%s依赖出现问题， 安装停止" % pkg_name)
            elif action_type == ACTION_UPGRADE:
                upgrade_page.download_parse_failed(pkg_name)
                global_event.emit("show-message", "分析%s依赖出现问题， 升级停止" % pkg_name)
        elif signal_type == "got-install-deb-pkg-name":
            pkg_name = action_content
            install_page.add_install_actions([pkg_name])
    
    return True

install_stop_list = []
def request_stop_install_actions(pkg_names):
    global install_stop_list
    
    install_stop_list += pkg_names
    
def clear_install_stop_list(install_page):
    global install_stop_list
    
    if len(install_stop_list) > 0:
        for pkg_name in install_stop_list:
            for item in install_page.treeview.visible_items:
                if item.pkg_name == pkg_name:
                    install_page.treeview.delete_items([item])
                    break
                
        install_stop_list = []        
        
    return True    

def install_pkg(bus_interface, install_page, pkg_names):
    install_page.add_install_actions(pkg_names)
    
    bus_interface.install_pkg(pkg_names)
    
clear_failed_action_dict = {
    ACTION_INSTALL : [],
    ACTION_UPGRADE : [],
    }
def request_clear_failed_action(pkg_name, action_type):
    global clear_failed_action_dict
    
    if action_type == ACTION_INSTALL:
        clear_failed_action_dict[ACTION_INSTALL].append(pkg_name)
    elif action_type == ACTION_UPGRADE:
        clear_failed_action_dict[ACTION_UPGRADE].append(pkg_name)
        
def clear_failed_action(install_page, upgrade_page):
    global clear_failed_action_dict
    
    install_items = []
    upgrade_items = []

    for pkg_name in clear_failed_action_dict[ACTION_INSTALL]:
        for item in install_page.treeview.visible_items:
            if item.pkg_name == pkg_name:
                install_items.append(item)

    for pkg_name in clear_failed_action_dict[ACTION_UPGRADE]:
        for item in upgrade_page.upgrade_treeview.visible_items:
            if item.pkg_name == pkg_name:
                upgrade_items.append(item)
                
    install_page.treeview.delete_items(install_items)            
    upgrade_page.upgrade_treeview.delete_items(upgrade_items)            
    
    clear_failed_action_dict = {
        ACTION_INSTALL : [],
        ACTION_UPGRADE : [],
        }
    
    return True
    
clear_action_list = []
def request_clear_action_pages(pkg_info_list):
    global clear_action_list
    
    clear_action_list += pkg_info_list

def clear_action_pages(bus_interface, upgrade_page, uninstall_page, install_page):
    global clear_action_list
    
    if len(clear_action_list) > 0:
        print "Clear: %s" % (str(clear_action_list))
        
        # Delete items from treeview.
        installed_items = []
        uninstalled_items = []
        upgraded_items = []
        install_pkgs = []
        
        for (pkg_name, marked_delete, marked_install, marked_upgrade) in clear_action_list:
            if marked_delete:
                for item in uninstall_page.treeview.visible_items:
                    if item.pkg_name == pkg_name:
                        uninstalled_items.append(item)
                        break
            elif marked_install:
                for item in install_page.treeview.visible_items:
                    if item.pkg_name == pkg_name:
                        installed_items.append(item)
                        
                        install_pkgs.append(pkg_name)
                        break
            elif marked_upgrade:
                for item in upgrade_page.upgrade_treeview.visible_items:
                    if item.pkg_name == pkg_name:
                        upgraded_items.append(item)
                        
                        install_pkgs.append(pkg_name)
                        break
                    
        uninstall_page.treeview.delete_items(uninstalled_items)
        install_page.treeview.delete_items(installed_items)
        upgrade_page.upgrade_treeview.delete_items(upgraded_items)
        
        # Add installed package in uninstall page.
        install_pkg_versions = bus_interface.request_pkgs_install_version(install_pkgs)
        install_pkg_infos = []
        for (pkg_name, pkg_version) in zip(install_pkgs, install_pkg_versions):
            install_pkg_infos.append(str((str(pkg_name), str(pkg_version))))
        uninstall_page.add_uninstall_items(install_pkg_infos)
        
        clear_action_list = []
        
    return True    
    
class DBusService(dbus.service.Object):
    def __init__(self, bus_interface, application):
        # Init dbus object.
        bus_name = dbus.service.BusName(DSC_FRONTEND_NAME, bus=dbus.SessionBus())
        dbus.service.Object.__init__(self, bus_name, DSC_FRONTEND_PATH)
        
        self.bus_interface = bus_interface
        self.application = application

    @dbus.service.method(DSC_FRONTEND_NAME, in_signature="s", out_signature="")    
    def message(self, message):
        (message_type, message_conent) = eval(message)
        if message_type == "hello":
            self.application.raise_to_top()
            
            deb_files = message_conent
            if len(deb_files) > 0:
                self.bus_interface.install_deb_files(message_conent)
        
class DeepinSoftwareCenter(object):
    '''
    class docs
    '''
	
    def __init__(self, arguments):
        '''
        init docs
        '''
        # WARING: only use once in one process
        DBusGMainLoop(set_as_default=True)
        
        self.simulate = "--simulate" in arguments
        self.deb_files = filter(self.is_deb_file, arguments)
        
    def run(self):    
        # Exit if frontend has running.
        bus = dbus.SessionBus()
        if is_dbus_name_exists(DSC_FRONTEND_NAME):
            print "Deepin software center has running!"
            
            bus_object = bus.get_object(DSC_FRONTEND_NAME, DSC_FRONTEND_PATH)
            bus_interface = dbus.Interface(bus_object, DSC_FRONTEND_NAME)
            bus_interface.message(str(("hello", self.deb_files)))
           
            # Exit program.
            return
        
        # Init DBus.
        system_bus = dbus.SystemBus()
        bus_object = system_bus.get_object(DSC_SERVICE_NAME, DSC_SERVICE_PATH)
        self.bus_interface = dbus.Interface(bus_object, DSC_SERVICE_NAME)
        
        # Say hello to backend. 
        self.bus_interface.say_hello(self.simulate)
        
        # Install deb file.
        if len(self.deb_files) > 0:
            self.bus_interface.install_deb_files(self.deb_files)
        
        # Init application.
        self.application = Application(resizable=False)
        self.application.set_default_size(888, 608)
        self.application.set_skin_preview(app_theme.get_pixbuf("frame.png"))
        self.application.set_icon(app_theme.get_pixbuf("icon.ico"))
        self.application.add_titlebar(
                ["theme", "menu", "min", "close"],
                show_title=False
                )
        self.application.window.set_title(_("Deepin Software Center"))
        
        # Make window can received drop data.
        targets = [("text/uri-list", 0, 1)]        
        self.application.window.drag_dest_set(gtk.DEST_DEFAULT_MOTION | gtk.DEST_DEFAULT_DROP, targets, gtk.gdk.ACTION_COPY)
        self.application.window.connect_after("drag-data-received", self.on_drag_data_received)        
        
        # Build unique service.
        DBusService(self.bus_interface, self.application)
        
        # Init data manager.
        data_manager = DataManager(self.bus_interface)
        
        # Init page box.
        page_box = gtk.VBox()
        
        # Init detail view.
        detail_page = DetailPage(data_manager)
        
        # Init page switcher.
        page_switcher = HSlider()
        page_switcher.append_page(page_box)
        page_switcher.append_page(detail_page)
        page_switcher.set_to_page(page_box)
        
        # Init page align.
        page_align = gtk.Alignment()
        page_align.set(0.5, 0.5, 1, 1)
        page_align.set_padding(0, 0, 2, 2)
        
        # Append page to switcher.
        page_align.add(page_switcher)
        self.application.main_box.pack_start(page_align, True, True)
        
        # Init status bar.
        statusbar = Statusbar(24)
        status_box = gtk.HBox()
        message_box = gtk.HBox()
        join_us_button = LinkButton("加入我们", "http://www.linuxdeepin.com/joinus/job")
        join_us_button_align = gtk.Alignment()
        join_us_button_align.set(0.5, 0.5, 0, 0)
        join_us_button_align.set_padding(0, 0, 0, 10)
        join_us_button_align.add(join_us_button)
        status_box.pack_start(message_box, True, True)
        status_box.pack_start(join_us_button_align, False, False)
        statusbar.status_box.pack_start(status_box, True, True)
        self.application.main_box.pack_start(statusbar, False, False)
        
        # Init pages.
        home_page = HomePage(data_manager)
        upgrade_page = UpgradePage(self.bus_interface, data_manager)
        uninstall_page = UninstallPage(self.bus_interface, data_manager)
        install_page = InstallPage(self.bus_interface, data_manager)
        switch_page(page_switcher, page_box, home_page, detail_page)
        
        # Init navigatebar.
        navigatebar = Navigatebar(
                [(app_theme.get_pixbuf("navigatebar/nav_recommend.png"), "软件中心", lambda : switch_page(page_switcher, page_box, home_page, detail_page)),
                (app_theme.get_pixbuf("navigatebar/nav_update.png"), "系统升级", lambda : switch_page(page_switcher, page_box, upgrade_page, detail_page)),
                (app_theme.get_pixbuf("navigatebar/nav_uninstall.png"), "卸载软件", lambda : switch_page(page_switcher, page_box, uninstall_page, detail_page)),
                (app_theme.get_pixbuf("navigatebar/nav_download.png"), "安装管理", lambda : switch_page(page_switcher, page_box, install_page, detail_page)),
                ],
                font_size = 11,
                padding_x = 2,
                padding_y = 2,
                vertical=False,
                item_hover_pixbuf=app_theme.get_pixbuf("navigatebar/nav_hover.png"),
                item_press_pixbuf=app_theme.get_pixbuf("navigatebar/nav_press.png"),
                )
        navigatebar.set_size_request(-1, 56)
        navigatebar_align = gtk.Alignment(0, 0, 1, 1)
        navigatebar_align.set_padding(0, 0, 4, 0)
        navigatebar_align.add(navigatebar)
        self.application.titlebar.set_size_request(-1, 56)
        self.application.titlebar.left_box.pack_start(navigatebar_align, True, True)
        self.application.window.add_move_event(navigatebar)
        self.application.window.connect("realize", lambda w: AnonymityThread(init_jieba).start())
        self.application.window.connect("show", lambda w: request_status(self.bus_interface, install_page, upgrade_page, uninstall_page))
        
        # Handle global event.
        global_event.register_event("install-pkg", lambda pkg_names: install_pkg(self.bus_interface, install_page, pkg_names))
        global_event.register_event("upgrade-pkg", self.bus_interface.upgrade_pkg)
        global_event.register_event("uninstall-pkg", self.bus_interface.uninstall_pkg)
        global_event.register_event("stop-download-pkg", self.bus_interface.stop_download_pkg)
        global_event.register_event("switch-to-detail-page", lambda pkg_name : switch_to_detail_page(page_switcher, detail_page, pkg_name))
        global_event.register_event("switch-from-detail-page", lambda : switch_from_detail_page(page_switcher, detail_page, page_box))
        global_event.register_event("remove-wait-action", self.bus_interface.remove_wait_missions)
        global_event.register_event("remove-wait-download", self.bus_interface.remove_wait_downloads)
        global_event.register_event("request-clear-action-pages", request_clear_action_pages)
        global_event.register_event("request-stop-install-actions", request_stop_install_actions)
        global_event.register_event("request-clear-failed-action", request_clear_failed_action)
        global_event.register_event("jump-to-category", 
                                    lambda first_category_name, second_category_name: 
                                    jump_to_category(page_switcher, page_box, home_page, detail_page, first_category_name, second_category_name))
        global_event.register_event("grade-pkg", lambda pkg_name, star: grade_pkg(self.application.window, pkg_name, star))
        global_event.register_event("set-cursor", lambda cursor: set_cursor(self.application.window, cursor))
        global_event.register_event("show-message", lambda message: show_message(statusbar, message_box, message))
        global_event.register_event("start-pkg", lambda pkg_name, desktop_infos, offset: start_pkg(pkg_name, desktop_infos, offset, self.application.window))
        global_event.register_event("start-desktop", start_desktop)
        system_bus.add_signal_receiver(lambda messages: message_handler(messages, self.bus_interface, upgrade_page, uninstall_page, install_page),
                                       dbus_interface=DSC_SERVICE_NAME, path=DSC_SERVICE_PATH, signal_name="update_signal")
        glib.timeout_add(1000, lambda : clear_action_pages(self.bus_interface, upgrade_page, uninstall_page, install_page))
        glib.timeout_add(1000, lambda : clear_install_stop_list(install_page))
        glib.timeout_add(1000, lambda : clear_failed_action(install_page, upgrade_page))
        
        # Run.
        self.application.run()
        
        # Send exit request to backend when frontend exit.
        self.bus_interface.request_quit()

    def is_deb_file(self, path):
        return path.endswith(".deb") and os.path.exists(path)
        
    def on_drag_data_received(self, widget, context, x, y, selection, info, timestamp):    
        deb_files = []
        if selection.target in ["text/uri-list", "text/plain", "text/deepin-songs"]:
            if selection.target == "text/uri-list":    
                selected_uris = selection.get_uris()
                for selected_uri in selected_uris:
                    if selected_uri.startswith("file://"):
                        selected_uri = selected_uri.split("file://")[1]
                    if self.is_deb_file(selected_uri):
                        deb_files.append(selected_uri)
                        
        if len(deb_files) > 0:                
            self.bus_interface.install_deb_files(deb_files)
