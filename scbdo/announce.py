
# simple announcer terminal for old scbdo track meet
#
# approx 80x28, addressed with UNT4/RTF style line/pos/erp/erl

import pygtk
pygtk.require("2.0")

import gtk
import glib
import gobject
import pango
import threading
import socket
import math
import random
import irclib
import time
import ConfigParser

import scbdo

from scbdo import unt4
from scbdo import tod
from scbdo import strops

import os
import sys

SCB_W = 80
SCB_H = 28

# Global Defaults
USCBSRV_HOST='localhost'
USCBSRV_PORT=6667
USCBSRV_CHANNEL='#announce'
USCBSRV_SRVNICK='uscbsrv'
USCBSRV_CLTNICK='tran_'+str(random.randint(100,999))

FONTSIZE=20     # font size in pixels
MOTD=''         # Message of the day

# Config filename
CONFIGFILE='track_announce.ini'

class uscbio(threading.Thread):
    def __init__(self):
        threading.Thread.__init__(self)
        self.running = False
        self.cb = None
        self.ih = irclib.IRC()
        self.ic = self.ih.server()
        self.np = tod.tod('now')+tod.tod('30')
        self.hasconnnected = False
        self.rdbuf = ''
        self.doreconnect = False
        self.chanstatus = False
        self.host = USCBSRV_HOST
        self.port = USCBSRV_PORT
        self.channel = USCBSRV_CHANNEL
        self.cltnick = USCBSRV_CLTNICK
        self.srvnick = USCBSRV_SRVNICK
        self._curpace = 0.0

    def setcb(self, cb):
        """Register the message callback function."""
        self.cb = cb

    def exit(self, msg=None):
        """Request thread termination."""
        self.running = False

    def irc_event_cb(self, c, e):
        """Collect and log all IRC events (debug)."""
        print('EVENT: ' + repr(e.source()) + '/' + repr(e.eventtype()) + '/' 
               + repr(e.target()) + ' :: ' + '/'.join(map(str, e.arguments())))

    def nicknameinuse_cb(self, c, e):
        """Handle nickname collision."""
        self.cltnick = 'roan_'+str(random.randint(100,999))
        self.doreconnect = True

    def channel_join_cb(self, c, e):
        """Register channel join."""
        tg = e.target().lower()
        if tg == self.channel:
            self.chanstatus = True
    def channel_part_cb(self, c, e):
        """Register channel part."""
        tg = e.target().lower()
        if tg == self.channel:
            self.chanstatus = False

    def unt_msg_cb(self, c, e):
        """Handle a message packet."""
        su = irclib.nm_to_n(e.source()).lower()
        tg = e.target().lower()
        if su == self.srvnick and tg == self.channel:
            self._pacing(0.0)
            # Have a 'broadcast' packet ... append and then search
            self.rdbuf += unt4.decode(''.join(e.arguments()))
            #print ('rdbuf = ' + repr(self.rdbuf))
            idx = self.rdbuf.find(chr(unt4.EOT))
            while idx >= 0:
                msgtxt = self.rdbuf[0:idx+1]
                self.rdbuf = self.rdbuf[idx+1:]
                if self.cb is not None:
                    glib.idle_add(self.cb, unt4.unt4(unt4str=msgtxt))
                idx = self.rdbuf.find(chr(unt4.EOT))

    def set_port(self, host=None, port=None, channel=None,
                       cltnick=None, srvnick=None):
        """Request change in irc connection."""
        reconnect = False
        if host is not None and host != self.host:
            self.host = host
            reconnect = True
        if port is not None and port != self.port:
            self.port = port
            reconnect = True
        if cltnick is not None and cltnick != self.port:
            self.cltnick = cltnick
            reconnect = True        
        if channel is not None and channel != self.channel:
            self.channel = channel
            reconnect = True
        if srvnick is not None:
            self.srvnick = srvnick.lower()
        if reconnect:
            self.doreconnect = True

    def _reconnect(self):
        self.ic.connect(self.host, self.port, self.cltnick)

    def in_channel(self):
        return self.chanstatus

    def _rejoin(self):
        self.ic.join(self.channel)

    def _pacing(self, delay=None):
        """Adjust internal pacing delay."""
        if delay is None:
            self._curpace += 0.1
            if self._curpace > 1.5:
                self._curpace = 1.5
        else:
            self._curpace = delay
        return self._curpace

    def run(self):
        """Called via threading.Thread.start()."""
        self.running = True
        self.ic.add_global_handler('pubmsg', self.unt_msg_cb, -10)
        self.ic.add_global_handler('pubnotice', self.unt_msg_cb, -10)
        self.ic.add_global_handler('join', self.channel_join_cb, -10)
        self.ic.add_global_handler('part', self.channel_part_cb, -10)
        self.ic.add_global_handler('kick', self.channel_part_cb, -10)
        self.ic.add_global_handler('nicknameinuse', self.nicknameinuse_cb, -10)
        #self.ic.add_global_handler('all_events', self.irc_event_cb, 0)
        while self.running:
            try:
                self.ih.process_once(0)
                if not self.ic.is_connected() or self.doreconnect:
                    self.doreconnect = False
                    self.chanstatus = False
                    time.sleep(2)
                    self._reconnect()
                    # skip over preliminary connect chatter ready to 
                    # poll channel status - avoids double channel join
                    if self.hasconnnected:
                        self.ih.process_once(0)
                        self.ih.process_once(0)
                        self.ih.process_once(0)
                        self.ih.process_once(0)
                        self.ih.process_once(0)
                        self.ih.process_once(0)
                        self.ih.process_once(0)
                        self.ih.process_once(1)
                    else:
                        self.hasconnnected = True
                if not self.in_channel():
                    time.sleep(2)
                    self._rejoin()
                now = tod.tod('now')
                if now > self.np:
                    self.ic.ctcp('PING', self.cltnick, str(int(time.time())))
                    self.np = now + tod.tod('30')
                time.sleep(self._pacing())
            except Exception as e:
                # TODO : FIX HERE?
                print ('Exception from uscbio: ' + str(e))

class announce(object):
 
    def loadconfig(self):
        """Load config from disk."""
        cr = ConfigParser.ConfigParser({'host':USCBSRV_HOST,
                                        'port':str(USCBSRV_PORT),
                                        'channel':USCBSRV_CHANNEL,
                                        'srvnick':USCBSRV_SRVNICK,
                                        'cltnick':USCBSRV_CLTNICK,
                                        'fontsize':str(FONTSIZE),
                                        'fullscreen':'Yes',
                                        'motd':MOTD})
        cr.add_section('uscbsrv')
        cr.add_section('announce')
        # check for config file
        try:
            a = len(cr.read(CONFIGFILE))
            if a == 0:
                print('No config file found - loading default values.')
        except Exception as e:
            print('Error reading config: ' + str(e))

        self.motd = cr.get('announce', 'motd')
        if strops.confopt_bool(cr.get('announce', 'fullscreen')):
            self.window.fullscreen()

        nhost = cr.get('uscbsrv', 'host')
        nport = strops.confopt_posint(cr.get('uscbsrv', 'port'),
                                      USCBSRV_PORT)
        nchannel = cr.get('uscbsrv', 'channel')
        ncltnick =cr.get('uscbsrv', 'cltnick')
        nsrvnick = cr.get('uscbsrv', 'srvnick')
        self.io.set_port(nhost, nport, nchannel, ncltnick, nsrvnick)

    def intro(self):
        m = unt4.unt4()
        m.yy=SCB_H-1
        m.text='SCBdo track announce ' + scbdo.VERSION
        m.xx=SCB_W-len(m.text)
        self.msg_cb(m)
        
    def show(self):
        self.window.show()

    def hide(self):
        self.window.show()

    def start(self):
        """Start io thread."""
        if not self.started:
            self.io.start()
            self.started = True

    def shutdown(self):
        """Cleanly shutdown."""
        self.io.exit()
        self.io.join()
        self.started = False

    def destroy_cb(self, window):
        """Handle destroy signal."""
        if self.started:
            self.shutdown()
        self.running = False
        gtk.main_quit()
    
    def clear(self):
        """Re-set all lines and draw a 'welcome'."""
        ntxt = ''
        for i in range(0,SCB_H-1):
            ntxt += ''.ljust(SCB_W) + '\n'
        ntxt += ''.ljust(SCB_W)
        self.buffer.set_text(ntxt)
        if self.motd != '':
            m = unt4.unt4(yy=0, xx=0, text=self.motd, erl=True)
            self.msg_cb(m)
        
    def delayed_cursor(self):
        """Remove the mouse cursor from the text area."""
        pixmap = gtk.gdk.Pixmap(None, 1, 1, 1)
        color = gtk.gdk.Color()
        cursor = gtk.gdk.Cursor(pixmap, pixmap, color, color, 0, 0)
        self.view.get_window(gtk.TEXT_WINDOW_TEXT).set_cursor(cursor)
        self.clear()
        return False

    def msg_cb(self, m):
        """Handle message packet in main thread."""
        if m.erp:
            self.clear()
        if m.yy is not None:
            if m.erl:
                m.text += ' '* (SCB_W - (m.xx + len(m.text)))
                
            j = self.buffer.get_iter_at_line_offset(m.yy, m.xx)
            k = self.buffer.get_iter_at_line_offset(m.yy,
                                                    m.xx + len(m.text))
            self.buffer.delete(j, k)
            self.buffer.insert(j, m.text)
        return False

    def view_size_allocate_cb(self, widget, alloc, data=None):
        """Respond to window resize."""
        cw = alloc.width // SCB_W
        ch = alloc.height // SCB_H
        lh = ch
        if cw * 2 < ch:
            lh = cw * 2
        fh = int(math.floor(0.80 * lh))
        if fh != self.fh:
            widget.modify_font(
                    pango.FontDescription('monospace bold {0}px'.format(fh)))
            self.fh = fh
        
    def __init__(self):
        self.io = uscbio()
        self.io.setcb(self.msg_cb)
        self.started = False
        self.running = True
        self.rscount = 0
        self.fh = 0
        self.motd = ''
        b = gtk.Builder()
        b.add_from_file(os.path.join(scbdo.UI_PATH, 'announce.ui'))
        self.window = b.get_object('window')
        self.buffer = b.get_object('buffer')
        self.view = b.get_object('view')
        self.view.modify_base(gtk.STATE_NORMAL, gtk.gdk.Color('#001'))
        self.view.modify_fg(gtk.STATE_NORMAL, gtk.gdk.Color('#001'))
        self.view.modify_bg(gtk.STATE_NORMAL, gtk.gdk.Color('#001'))
        self.view.modify_text(gtk.STATE_NORMAL, gtk.gdk.Color('#eef'))
        self.clear() # compulsory clear -> fills all lines
        self.intro()
        glib.timeout_add_seconds(5,self.delayed_cursor)
        b.connect_signals(self)

def main():
    """Run the announce application."""
    scbdo.init()
    app = announce()
    app.loadconfig()
    app.show()
    app.start()
    try:
        gtk.main()
    except:
        app.shutdown()
        raise

if __name__ == '__main__':
    main()

