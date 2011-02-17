
# preliminary road race announce 'stateful' terminal
# connects to IRC to receive UNT4 announce msg packs
#
# Notes:
#	- does not _yet_ do live stream negotiation
#	- server, port, channel, nick config via road_announce.ini
#
# TODO:
#	- properly mark private vars/methods to avoid leak to other thread
#	- configuration dialog and test facility -> query uSCBsrv
#	- configuration status icon for connect & status
#	- configure map colours via ini
#       - connect buttons to allow navigation of 'laps'
#       - touch screen scroll/zoom in map area
#       - touch screen scroll in tree
#       - more natural rider search
#	- connect riders and scale via mark on drawing area?

import pygtk
pygtk.require("2.0")

import gtk
import glib
import gobject
import pango
import threading
import random
import irclib
import ConfigParser
import time
import os
import sys

import scbdo
from scbdo import unt4
from scbdo import tod
from scbdo import uiutil
from scbdo import strops

# Global Defaults
USCBSRV_HOST='localhost'
USCBSRV_PORT=6667
USCBSRV_CHANNEL='#announce'
USCBSRV_SRVNICK='uscbsrv'
USCBSRV_CLTNICK='roan_'+str(random.randint(100,999))
TIMETICK=12	# pixels per second
FONTSIZE=20	# font size in pixels
MOTD=''		# Message of the day

# Config filename
CONFIGFILE='road_announce.ini'

# Bunches colourmap
COLOURMAP=[['#ffa0a0','red',1.0,0.1,0.1],
           ['#a0ffa0','green',0.1,1.0,0.1],
           ['#a0a0ff','blue',0.1,0.1,1.0],
           ['#f0b290','amber',0.9,0.6,0.1],
           ['#b290f0','violet',0.7,0.1,0.8],
           ['#f9ff10','yellow',0.9,1.0,0.1],
           ['#ff009b','pink',1.0,0.0,0.7],
           ['#00ffc3','cyan',0.1,1.0,0.8]]
COLOURMAPLEN=len(COLOURMAP)
STARTTIME=80	# in seconds
MAPWIDTH=STARTTIME*TIMETICK
MAPHMARGIN=8
MAPVMARGIN=6

def roundedrecMoonlight(cr,x,y,w,h,radius_x=4,radius_y=4):
    """Draw a rounded rectangle."""

    #from mono moonlight aka mono silverlight
    #test limits (without using multiplications)
    # http://graphics.stanford.edu/courses/cs248-98-fall/Final/q1.html
    ARC_TO_BEZIER = 0.55228475
    if radius_x > w - radius_x:
        radius_x = w / 2
    if radius_y > h - radius_y:
        radius_y = h / 2

    #approximate (quite close) the arc using a bezier curve
    c1 = ARC_TO_BEZIER * radius_x
    c2 = ARC_TO_BEZIER * radius_y

    cr.new_path();
    cr.move_to ( x + radius_x, y)
    cr.rel_line_to ( w - 2 * radius_x, 0.0)
    cr.rel_curve_to ( c1, 0.0, radius_x, c2, radius_x, radius_y)
    cr.rel_line_to ( 0, h - 2 * radius_y)
    cr.rel_curve_to ( 0.0, c2, c1 - radius_x, radius_y, -radius_x, radius_y)
    cr.rel_line_to ( -w + 2 * radius_x, 0)
    cr.rel_curve_to ( -c1, 0, -radius_x, -c2, -radius_x, -radius_y)
    cr.rel_line_to (0, -h + 2 * radius_y)
    cr.rel_curve_to (0.0, -c2, radius_x - c1, -radius_y, radius_x, -radius_y)
    cr.close_path ()

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
            idx = self.rdbuf.find(chr(unt4.EOT))
            if idx >= 0:
                msgtxt = self.rdbuf[0:idx+1]
                self.rdbuf = self.rdbuf[idx+1:]
                if self.cb is not None:
                    glib.idle_add(self.cb, unt4.unt4(unt4str=msgtxt))

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

class rr_announce(object):
    """Road race announcer application."""
 
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

    def window_destroy_cb(self, window):
        """Handle destroy signal."""
        if self.started:
            self.shutdown()
        self.running = False
        gtk.main_quit()
    
    def map_area_expose_event_cb(self, widget, event):
        """Update desired portion of drawing area."""
        x , y, width, height = event.area
        widget.window.draw_drawable(widget.get_style().fg_gc[gtk.STATE_NORMAL],
                                    self.map_src, x, y, x, y, width, height)
        return False

    def do_bubble(self, cr, cnt, x1, x2):
        """Draw a rider bubble from x1 to x2 on the map."""
        rx = int(self.timetick*float(x1.timeval))	# conversion to
        rx2 = int(self.timetick*float(x2.timeval))     # device units
        rw = rx2 - rx
        if rw < 8:			# clamp min width
            rw = 8
        cidx = cnt%COLOURMAPLEN
        roundedrecMoonlight(cr,rx+MAPHMARGIN,8+MAPVMARGIN,rw,30)
        cr.set_source_rgba(COLOURMAP[cidx][2],
                           COLOURMAP[cidx][3],
                           COLOURMAP[cidx][4],0.8)
        cr.fill_preserve()
        cr.set_source_rgb(0.2,0.2,0.2)
        cr.stroke()

    def map_redraw(self):
        """Lazy full map redraw method."""
        cr = self.map_src.cairo_create()

        width = self.map_winsz
        height = 80
        cr.identity_matrix()

        # bg filled
        cr.set_source_rgb(0.85,0.85,0.9)
        cr.paint()

        # scale: | . . . . i . . . . | . . . 
        cr.set_line_width(1.0)
        cr.set_font_size(15.0)
        xof = 0
        dw = width - (2 * MAPHMARGIN)
        dh = height - (2 * MAPVMARGIN)
        cnt = 0
        while xof < dw:
            lh = 4
            if cnt % 10 == 0:
                lh = 12
                cr.set_source_rgb(0.05,0.05,0.05)
                cr.move_to(xof+MAPHMARGIN+1,
                           MAPVMARGIN+dh-lh-2)
                cr.show_text(tod.tod(int(cnt)).rawtime(0))
            elif cnt % 5 == 0:
                lh = 8
            cr.set_source_rgb(0.05,0.05,0.05)
            cr.move_to(xof+MAPHMARGIN, MAPVMARGIN+dh-lh)
            cr.line_to(xof+MAPHMARGIN, MAPVMARGIN+dh)
            cr.stroke()
            if cnt % 5 == 0:
                cr.set_source_rgb(0.96,0.96,0.96)
                cr.move_to(xof+MAPHMARGIN, MAPVMARGIN)
                cr.line_to(xof+MAPHMARGIN, MAPVMARGIN+dh-lh-2)
                cr.stroke()
            cnt += 1
            xof += self.timetick

        cr.set_line_width(2.0)
        inbox = False
        cnt = 0
        st=None
        x1=None
        x2=None
        for r in self.riders:
            if r[7] is not None:	# have a row
                if st is None:
                    st = r[7].truncate(0)	# save lap split
                if not inbox:
                    x1 = r[7].truncate(0)-st
                    inbox = True
                x2 = r[7]-st
            else:			# have a break
                if inbox:
                    self.do_bubble(cr, cnt, x1, x2)
                    cnt += 1
                inbox = False
        if inbox:
            self.do_bubble(cr, cnt, x1, x2)

    def map_area_configure_event_cb(self, widget, event):
        """Re-configure the drawing area and redraw the base image."""
        x, y, width, height = widget.get_allocation()
        self.map_winsz = width
        if width > self.map_w:
            nw = MAPWIDTH
            if width > MAPWIDTH:
                nw = width
            self.map_src = gtk.gdk.Pixmap(widget.window, nw, height)
            self.map_w = nw
            self.map_redraw()
        return True

    def clear(self):
        self.lbl_header.set_text(self.motd)
        self.elap_lbl.set_text('')
        self.riders.clear()
        self.map_redraw()		# update src map
        self.map_area.queue_draw()	# queue copy to screen
        
    def append_rider(self, msg):
        sr = msg.split(chr(unt4.US))
        if len(sr) == 5:
            rftime = tod.str2tod(sr[4])
            if rftime is not None:
                if len(self.riders) == 0:
                    # Case 1: Starting a new lap
                    self.cur_lap = (rftime-self.cur_split).truncate(0)
                    self.cur_split = rftime.truncate(0)
                    self.cur_bunchid = 0
                    self.cur_bunchcnt = 1
                    self.last_time = rftime
                    nr=[sr[0],sr[1],sr[2],sr[3],
                        self.cur_lap.rawtime(0),
                        self.cur_bunchcnt,
                        COLOURMAP[self.cur_bunchid][0],
                        rftime]
                elif rftime < self.last_time or rftime - self.last_time < tod.tod('1.12'):
                    # Case 2: Same bunch
                    self.last_time = rftime
                    self.cur_bunchcnt += 1
                    nr=[sr[0],sr[1],sr[2],sr[3],
                        '',
                        self.cur_bunchcnt,
                        COLOURMAP[self.cur_bunchid][0],
                        rftime]
                else:
                    # Case 3: New bunch
                    self.riders.append(['','','','','','','#fefefe',None])
                    self.cur_bunchid = (self.cur_bunchid + 1)%COLOURMAPLEN
                    self.cur_bunchcnt = 1
                    self.last_time = rftime
                    nr=[sr[0],sr[1],sr[2],sr[3],
                        '+' + (rftime - self.cur_split).rawtime(0),
                        self.cur_bunchcnt,
                        COLOURMAP[self.cur_bunchid][0],
                        rftime]
            else: 
                # Informative non-timeline record
                nr=[sr[0],sr[1],sr[2],sr[3],
                        '', '', '#fefefe',None]
                
            self.riders.append(nr)
            self.map_redraw()		# update src map
            self.map_area.queue_draw()	# queue copy to screen

    def msg_cb(self, m):
        """Handle message packet in main thread."""
        redraw = False
        if m.header == 'rider':
            self.append_rider(m.text)
        elif m.header == 'time':
            self.elap_lbl.set_text(m.text)
        elif m.header == 'title':
            self.lbl_header.set_text(m.text)
        elif m.header == 'start':
            self.cur_split = tod.str2tod(m.text)
        elif m.erp:
            self.clear()
        return False
        
    def loadconfig(self):
        """Load config from disk."""
        cr = ConfigParser.ConfigParser({'host':USCBSRV_HOST,
                                        'port':str(USCBSRV_PORT),
                                        'channel':USCBSRV_CHANNEL,
                                        'srvnick':USCBSRV_SRVNICK,
                                        'cltnick':USCBSRV_CLTNICK,
                                        'timetick':str(TIMETICK),
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
        except e:
            print('Error reading config: ' + str(e))

        self.timetick = strops.confopt_posint(cr.get('announce', 'timetick'),
                                              TIMETICK)
        self.fontsize = strops.confopt_posint(cr.get('announce', 'fontsize'),
                                              FONTSIZE)
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

        fnszstr = str(self.fontsize)+'px'
        self.lbl_header.modify_font(pango.FontDescription('bold '+fnszstr))
        self.elap_lbl.modify_font(pango.FontDescription('monospace bold '+fnszstr))
        self.search_lbl.modify_font(pango.FontDescription(fnszstr))
        self.search_entry.modify_font(pango.FontDescription(fnszstr))
        self.view.modify_font(pango.FontDescription('bold '+fnszstr))

    def __init__(self):
        self.io = uscbio()
        self.io.setcb(self.msg_cb)
        self.started = False
        self.running = True

        self.timetick = TIMETICK
        self.fontsize = FONTSIZE
        fnszstr = str(self.fontsize)+'px'

        b = gtk.Builder()
        b.add_from_file(os.path.join(scbdo.UI_PATH, 'rr_announce.ui'))
        self.window = b.get_object('window')

        self.lbl_header = b.get_object('lbl_header')
        self.lbl_header.modify_font(pango.FontDescription('bold '+fnszstr))
        self.lbl_header.set_text('SCBdo road announce ' + scbdo.VERSION)
        self.elap_lbl = b.get_object('elap_lbl')
        self.elap_lbl.set_text('--:--')
        self.elap_lbl.modify_font(pango.FontDescription('monospace bold '+fnszstr))
        self.map_winsz = 0
        self.map_xoft = 0
        self.map_w = 0
        self.map_area = b.get_object('map_area')
        self.map_src = None
        self.map_area.set_size_request(-1, 80)
        self.map_area.show()

        # lap & bunch status values
        self.cur_lap = tod.tod(0)
        self.cur_split = tod.tod(0)
        self.cur_bunchid = 0
        self.cur_bunchcnt = 0

        self.riders = gtk.ListStore(gobject.TYPE_STRING,  # rank
                                    gobject.TYPE_STRING,  # no.
                                    gobject.TYPE_STRING,  # namestr
                                    gobject.TYPE_STRING,  # cat/com
                                    gobject.TYPE_STRING,  # timestr
                                    gobject.TYPE_STRING,  # bunchcnt
                                    gobject.TYPE_STRING,  # colour
                                    gobject.TYPE_PYOBJECT) # rftod

        t = gtk.TreeView(self.riders)
        self.view = t
        t.set_reorderable(False)
        t.set_rules_hint(False)
        t.set_headers_visible(False)
        self.search_lbl = b.get_object('search_lbl')
        self.search_lbl.modify_font(pango.FontDescription(fnszstr))
        self.search_entry = b.get_object('search_entry')
        self.search_entry.modify_font(pango.FontDescription(fnszstr))
        t.set_search_entry(b.get_object('search_entry'))
        t.set_search_column(1)
        t.modify_font(pango.FontDescription('bold '+fnszstr))
        uiutil.mkviewcoltxt(t, 'Rank', 0,width=60)
        uiutil.mkviewcoltxt(t, 'No.', 1,calign=1.0,width=60)
        uiutil.mkviewcoltxt(t, 'Rider', 2,expand=True,fixed=True)
        uiutil.mkviewcoltxt(t, 'Cat', 3,calign=0.0)
        uiutil.mkviewcoltxt(t, 'Time', 4,calign=1.0,width=100,
                                        fontdesc='monospace bold')
        uiutil.mkviewcoltxt(t, 'Bunch', 5,width=50,bgcol=6,calign=0.5)
        t.show()
        b.get_object('text_scroll').add(t)
        b.connect_signals(self)

def main():
    """Run the announce application."""
    scbdo.init()
    app = rr_announce()
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

