#!/usr/bin/python
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

import glib
import signal
import dbus
import dbus.service
import dbus.mainloop.glib
from dbus.mainloop.glib import DBusGMainLoop
from deepin_utils.ipc import is_dbus_name_exists
from datetime import datetime
import traceback
import sys
import pynotify

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
    with open(LOG_PATH, "a") as file_handler:
        now = datetime.now().strftime("[%Y-%m-%d %H:%M:%S]")
        file_handler.write("%s %s\n" % (now, message))

def start_updater(loop=True):
    try:
        dbus.mainloop.glib.DBusGMainLoop(set_as_default = True)
        
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



class UpdateList(dbus.service.Object):
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

        log("Start Update List Daemon")

    def run(self):
        self.update_handler()
        return False

    def set_delay_update(self, seconds):
        if self.delay_update_id:
            glib.source_remove(self.delay_update_id)
        self.delay_update_id = glib.timeout_add_seconds(seconds, self.update_handler)

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
                if update_num != self.update_num:
                    self.show_notify("There is %s packages to update" % update_num)
                self.bus_interface.request_quit()
                self.set_delay_update(UPDATE_INTERVAL)
                log("Update List Finish")
                print "update finished!"
                log("Deepin Software Service Quit!")
            elif signal_type == "update-list-failed":
                self.is_in_update_list = False
                self.update_status = "failed"
                self.bus_interface.request_quit()
                self.set_delay_update(DELAY_UPDATE_INTERVAL)
                print "update failed, daemon will try again next time"
                log("update failed, daemon will try again next time")
        return True

    def update_handler(self):
        if self.is_fontend_running():
            self.set_delay_update(DELAY_UPDATE_INTERVAL)
        else:
            self.start_dsc_backend()
            glib.timeout_add_seconds(1, self.start_update_list, self.bus_interface)
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
        if pynotify and message:
            notification = pynotify.Notification('Update Notice', message)
            if timeout:
                notification.set_timeout(timeout)
            try:
                notification.show()
            except:
                pass

if __name__ == "__main__" :
    pynotify.init("Update Notice")
    DBusGMainLoop(set_as_default=True)
    session_bus = dbus.SessionBus()
    
    mainloop = glib.MainLoop()
    signal.signal(signal.SIGINT, lambda : mainloop.quit()) # capture "Ctrl + c" signal

    if is_dbus_name_exists(DSC_UPDATELIST_NAME, True):
        print "Daemon is running"
    else:
        bus_name = dbus.service.BusName(DSC_UPDATELIST_NAME, session_bus)
            
        update_list = UpdateList(session_bus, mainloop)
        try:
            glib.timeout_add_seconds(15, start_updater, False) # first run
            glib.timeout_add_seconds(UPDATE_INTERVAL, start_updater)
            glib.timeout_add_seconds(15, update_list.run)
            mainloop.run()
        except KeyboardInterrupt:
            update_list.exit_loop()
