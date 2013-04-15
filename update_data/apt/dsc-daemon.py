#!/usr/bin/env python
# -*- coding: utf-8 -*-

# Copyright (C) 2012 ~ 2013 Deepin, Inc.
#               2012 ~ 2013 Kaisheng Ye
# 
# Author:     Kaisheng Ye <kaisheng.ye@gmail.com>
# Maintainer: Kaisheng Ye <kaisheng.ye@gmail.com>
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

import gobject
import signal
import dbus
import dbus.service
import dbus.mainloop.glib
from dbus.mainloop.glib import DBusGMainLoop
from deepin_utils.ipc import is_dbus_name_exists
from dtk.ui.dbus_notify import DbusNotify
from datetime import datetime
import traceback
import sys, os
import subprocess
import apt_pkg


DSC_SERVICE_NAME = "com.linuxdeepin.softwarecenter"
DSC_SERVICE_PATH = "/com/linuxdeepin/softwarecenter"

DSC_FRONTEND_NAME = "com.linuxdeepin.softwarecenter_frontend"
DSC_FRONTEND_PATH = "/com/linuxdeepin/softwarecenter_frontend"

DSC_UPDATELIST_NAME = "com.linuxdeepin.softwarecenter_updatelist"
DSC_UPDATELIST_PATH = "/com/linuxdeepin/softwarecenter_updatelist"

DSC_UPDATER_NAME = "com.linuxdeepin.softwarecenterupdater"
DSC_UPDATER_PATH = "/com/linuxdeepin/softwarecenterupdater"

LOG_PATH = "/tmp/dsc-update-list.log"

UPDATE_INTERVAL = 3600*1
DELAY_UPDATE_INTERVAL = 600

def log(message):
    if not os.path.exists(LOG_PATH):
        open(LOG_PATH, "w").close()
        os.chmod(LOG_PATH, 0777)
    with open(LOG_PATH, "a") as file_handler:
        now = datetime.now().strftime("[%Y-%m-%d %H:%M:%S]")
        file_handler.write("%s %s\n" % (now, message))

def start_updater(loop=True):
    try:
        if is_dbus_name_exists(DSC_UPDATER_NAME, False):
            log("Deepin software center updater has running!")
            print "Deepin software center updater has running!"
        else:
            system_bus = dbus.SystemBus()
            bus_object = system_bus.get_object(DSC_UPDATER_NAME, DSC_UPDATER_PATH)
            dbus.Interface(bus_object, DSC_UPDATER_NAME)
            log("Start updater finish.")
            print "Start updater finish."
    except Exception, e:
        log("got error: %s" % (e))
        print "got error: %s" % (e)
        traceback.print_exc(file=sys.stdout)

    return loop

class NetworkDetector(gobject.GObject):

    NETWORK_STATUS_OK = 0
    NETWORK_STATUS_FAILED = 1

    __gsignals__ = {
            "network-status-changed":(gobject.SIGNAL_RUN_LAST, 
                                      gobject.TYPE_NONE,
                                      (gobject.TYPE_INT, ))
        }

    def __init__(self):
        gobject.GObject.__init__(self)
        self.network_status = self.NETWORK_STATUS_FAILED

    def start_detect_source_available(self):
        apt_pkg.init_config()
        apt_pkg.init_system()
        source_list_obj = apt_pkg.SourceList()
        source_list_obj.read_main_list()
        uri = source_list_obj.list[0].uri.split("/")[2]
        gobject.timeout_add(1000, self.network_detect_loop, uri)

    def network_detect_loop(self, uri):
        current_status = None
        if self.ping_uri(uri):
            current_status = self.NETWORK_STATUS_OK
            if self.network_status != current_status:
                self.network_status = current_status
                self.emit("network-status-changed", self.network_status)
            return False
        else:
            current_status = self.NETWORK_STATUS_FAILED
            if self.network_status != current_status:
                self.network_status = current_status
                self.emit("network-status-changed", self.network_status)
            return True

    def ping_uri(self, uri):
        fnull = open(os.devnull, 'w')
        return1 = subprocess.call('ping -c 1 %s' % uri, shell = True, stdout = fnull, stderr = fnull)
        if return1:
            fnull.close()
            return False
        else:
            fnull.close()
            return True

class Update(dbus.service.Object):
    def __init__(self, session_bus, mainloop):
        dbus.service.Object.__init__(self, session_bus, DSC_UPDATELIST_PATH)
        self.mainloop = mainloop

        self.exit_flag = False
        self.is_in_update_list = False
        self.update_status = None

        self.system_bus = None
        self.bus_interface = None
        self.delay_update_id = None
        self.sleep_time = UPDATE_INTERVAL

        self.update_num = 0

        self.net_detector = NetworkDetector()

        log("Start Update List Daemon")

    def run(self):
        self.update_handler()
        return False

    def set_delay_update(self, seconds):
        if self.delay_update_id:
            gobject.source_remove(self.delay_update_id)
        self.delay_update_id = gobject.timeout_add_seconds(seconds, self.update_handler)

    def start_dsc_backend(self):
        print "start dsc dbus service"
        self.system_bus = dbus.SystemBus()
        bus_object = self.system_bus.get_object(DSC_SERVICE_NAME, DSC_SERVICE_PATH)
        self.bus_interface = dbus.Interface(bus_object, DSC_SERVICE_NAME)
        self.system_bus.add_signal_receiver(
                self.signal_receiver, 
                signal_name="update_signal", 
                dbus_interface=DSC_SERVICE_NAME, 
                path=DSC_SERVICE_PATH)
        print "finish, ready for action"

    def signal_receiver(self, messages):
        for message in messages:
            (signal_type, action_content) = message
            
            if signal_type == "update-list-update":
                self.is_in_update_list = True
                self.update_status = "update"
            elif signal_type == "update-list-finish":
                self.is_in_update_list = False
                self.update_status = "finish"
                self.system_bus.remove_signal_receiver(
                        self.signal_receiver, 
                        signal_name="update_signal", 
                        dbus_interface=DSC_SERVICE_NAME, 
                        path=DSC_SERVICE_PATH)
                update_num = len(self.bus_interface.request_upgrade_pkgs())
                if update_num != 0 and update_num != self.update_num:
                    self.show_notify("您的系统有%s个软件包需要升级，请打开软件中心进行升级！" % update_num)
                self.update_num = update_num
                self.bus_interface.request_quit()
                self.set_delay_update(UPDATE_INTERVAL)
                log("Update List Finish")
                print "update finished!"
                log("Deepin Software Service Quit!")
            elif signal_type == "update-list-failed":
                self.is_in_update_list = False
                self.update_status = "failed"
                self.system_bus.remove_signal_receiver(
                        self.signal_receiver, 
                        signal_name="update_signal", 
                        dbus_interface=DSC_SERVICE_NAME, 
                        path=DSC_SERVICE_PATH)
                self.bus_interface.request_quit()
                self.start_detector()
                print "update failed, daemon will try when network is OK!"
                log("update failed, daemon will try when network is OK!")
        return True

    def start_detector(self):
        self.net_detector.start_detect_source_available()
        self.net_detector.connect("network-status-changed", self.network_changed_handler)

    def network_changed_handler(self, obj, status):
        if status == NetworkDetector.NETWORK_STATUS_OK:
            self.update_handler()

    def update_handler(self):
        if self.is_fontend_running():
            self.set_delay_update(DELAY_UPDATE_INTERVAL)
        else:
            self.start_dsc_backend()
            gobject.timeout_add_seconds(1, start_updater, False)
            gobject.timeout_add_seconds(1, self.start_update_list, self.bus_interface)
        return True

    def start_update_list(self, bus_interface):
        if not self.is_in_update_list:
            print "start updating"
            log("start updating")
            bus_interface.start_update_list()
        else:
            log("other app is running update list")
        return False

    def is_fontend_running(self):
        return is_dbus_name_exists(DSC_FRONTEND_NAME, True)

    def exit_loop(self):
        self.exit_flag = True

    @dbus.service.method(DSC_UPDATELIST_NAME, in_signature="", out_signature="b")    
    def get_update_list_status(self):
        return self.is_in_update_list

    def show_notify(self, message=None, timeout=None):
        notification = DbusNotify("deepin-software-center")
        notification.set_summary("更新提示")
        notification.set_body(message)
        notification.notify()

if __name__ == "__main__" :

    uid = os.geteuid()
    if uid == 0:
        sys.exit(0)

    DBusGMainLoop(set_as_default=True)
    session_bus = dbus.SessionBus()
    
    mainloop = gobject.MainLoop()
    signal.signal(signal.SIGINT, lambda : mainloop.quit()) # capture "Ctrl + c" signal

    if is_dbus_name_exists(DSC_UPDATELIST_NAME, True):
        print "Daemon is running"
    else:
        bus_name = dbus.service.BusName(DSC_UPDATELIST_NAME, session_bus)
            
        update = Update(session_bus, mainloop)
        try:
            gobject.timeout_add_seconds(30, update.run)
            mainloop.run()
        except KeyboardInterrupt:
            update.exit_loop()