
# SCBdo : DISC Track Racing Management Software
# Copyright (C) 2010  Nathan Fraser
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program.  If not, see <http://www.gnu.org/licenses/>.

"""Wheeltime test application"""

import pygtk
pygtk.require("2.0")
import gtk
import glib
import pango

import os
import logging

import scbdo

from scbdo import wheeltime
from scbdo import tod
from scbdo import loghandler

class wheeltest(object):
    """Wheeltime test application class."""
    def start(self):
        """Start the tesp application."""
        self.wt.start()
        self.wt.arm()

    def shutdown(self, msg):
        """Terminate threads and shut down application."""
        self.wt.dearm()
        self.wt.exit(msg)
        self.wt.join()

    def __init__(self):
        self.log = logging.getLogger('scbdo')
        self.log.setLevel(logging.DEBUG)
        self.isconn = False
        b = gtk.Builder()
        b.add_from_file(os.path.join(scbdo.UI_PATH, 'wheeltime_test.ui'))
        self.status = b.get_object('status')
        self.log_buffer = b.get_object('log_buffer')
        self.log_view = b.get_object('log_view')
        self.log_view.modify_font(pango.FontDescription("monospace 9"))
        self.log_scroll = b.get_object('scrollbox').get_vadjustment()
        self.context = self.status.get_context_id('WheelTest')
        self.window = b.get_object('window')
        self.port_ent = b.get_object('port_ent')
        self.event_id = b.get_object('event_id')
        self.event_tod = b.get_object('event_tod')
        self.connect_but_img = b.get_object('connect_but_img')
        b.connect_signals(self)
        
        f = logging.Formatter('%(levelname)s:%(name)s: %(message)s')
        self.sh = loghandler.statusHandler(self.status, self.context)
        self.sh.setLevel(logging.INFO)  # show info upon status bar
        self.sh.setFormatter(f)
        self.log.addHandler(self.sh)

        self.lh = loghandler.textViewHandler(self.log_buffer,
                      self.log_view, self.log_scroll)
        self.lh.setLevel(logging.DEBUG)
        self.lh.setFormatter(f)
        self.log.addHandler(self.lh)
 
        self.wt = wheeltime.wheeltime(addr='localhost')
        self.port_ent.set_text('localhost')

        self.running = True
        glib.timeout_add(100, self.timeout)

    def reconnect_clicked_cb(self, button, data=None):
        """Re-connect to wheeltime."""
        self.wt.setaddr(self.port_ent.get_text())

    def port_ent_activate_cb(self, entry, data=None):
        """Re-connect to wheeltime."""
        self.wt.setaddr(self.port_ent.get_text())

    def menu_quit_activate_cb(self, menuitem, data=None):
        """Respond to menu->file->quit."""
        self.running = False
        self.window.destroy()

    def menu_about_activate_cb(self, menuitem, data=None):
        """Respond to menu->help->about."""
        scbdo.about_dlg(self.window)

    def window_destroy_cb(self, window, msg=''):
        """Terminate threads and exit."""
        self.shutdown(msg)
        self.running = False
        self.log.removeHandler(self.sh)
        self.log.removeHandler(self.lh)
        gtk.main_quit()

    def timeout(self, data=None):
        """Check connection and poll for RFID events."""
        if not self.running:
            return False
        nc = self.wt.connected()
        if nc != self.isconn:
            if nc:
                self.connect_but_img.set_from_stock(gtk.STOCK_CONNECT,
                                                    gtk.ICON_SIZE_MENU)
            else:
                self.connect_but_img.set_from_stock(gtk.STOCK_DISCONNECT,
                                                    gtk.ICON_SIZE_MENU)
            self.isconn = nc
        e = self.wt.response()
        while e is not None:
            self.event_id.set_text(e.refid)
            self.event_tod.set_text(e.timestr(2))
            e = self.wt.response()
        return True

def main():
    scbdo.init()
    app = wheeltest()
    app.window.show()
    app.start()
    try:
        gtk.main()
    except:
        app.shutdown('Exception from gtk.main()')
        raise

if __name__ == '__main__':
    main()
