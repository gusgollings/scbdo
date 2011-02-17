
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

"""Lane timer module.

This module provides a lane timer container object.
timerpane is a UI object which collects external commands and
displays them in a consistent fashion. Logic for state transitions
is up to calling app, timerpane ensures that each transition
into a new state is complete and defined. Which states can happen
when is entirely up to user code.

Note: this object should be re-coded as a gtk.Widget

"""

import gtk
import gobject
import pango

import scbdo
from scbdo import tod
from scbdo import uiutil

class timerpane(object):
    def setrider(self, bib=None, ser=None):
        """Set bib for timer."""
        if bib is not None:
            self.bibent.set_text(bib)
            if ser is not None:
                self.serent.set_text(ser)
            self.bibent.activate()	# and chain events

    def grab_focus(self, data=None):
        """Steal focus into bib entry."""
        self.bibent.grab_focus()
        return False	# allow addition to idle_add or delay

    def getrider(self):
        """Return bib loaded into timer."""
        return self.bibent.get_text()

    def getstatus(self):
        """Return timer status.

        Timer status may be one of:

          'idle'	-- lane empty or ready for new rider
          'load'	-- rider loaded into lane
          'armstart'	-- armed for start trigger
          'running'	-- timer running
          'armint'	-- armed for intermediate split
          'armfin'	-- armed for finish trigger
          'finish'	-- timer finished

        """
        return self.status

    def set_time(self, tstr='             '):
        """Set timer string."""
        self.ck.set_text(tstr)

    def show_laps(self):
        """Show the lapup button and lap label."""
        self.ls.show()
        self.lb.show()

    def hide_laps(self):
        """Hide the lapup button and lap label."""
        self.ls.hide()
        self.lb.hide()

    def set_lap(self):
        """Set the lap string."""
        self.ls.set_text('Lap ' + str(self.lap))

    def lap_up(self):
        """Increment the current lap."""
        self.lap += 1
        self.set_lap()

    def lap_up_clicked_cb(self, button, data=None):
        """Respond to lap up button press."""
        if self.status in ['running', 'armint', 'armfin']:
            self.missedlap()

    def runtime(self, runtod):
        """Update timer run time."""
        if runtod > self.recovtod:
            self.set_time(runtod.timestr(1))

    def missedlap(self):
        """Flag a missed lap to allow 'catchup'."""
        self.splits.append(None)
        self.lap_up()

    def intermed(self, inttod):
        """Trigger an intermediate time."""
        self.splits.append(inttod)
        self.lap_up()
        nt = inttod-self.starttod
        self.recovtod.timeval = nt.timeval + 4
        self.set_time(nt.timestr(3))
        self.torunning()

    def difftime(self, dt):
        """Overwrite split time with a difference time."""
        dstr = dt.timestr(2).replace('       0', '      +0')
        self.set_time(dstr)

    def getsplit(self, lapno):
        """Return split for specified lap."""
        return self.splits[lapno]

    def finish(self, fintod):
        """Trigger finish on timer."""
        self.finishtod = fintod
        self.ls.set_text('Lap ' + str(self.lap + 1))	# Fudge last lap
        self.set_time((self.finishtod-self.starttod).timestr(3))
        self.tofinish()

    def tofinish(self):
        """Set timer to finished."""
        self.status = 'finish'
        uiutil.buttonchg(self.b, uiutil.bg_none, 'Finished')

    def toarmfin(self):
        """Arm timer for finish."""
        self.status = 'armfin'
        uiutil.buttonchg(self.b, uiutil.bg_armfin, 'Finish Armed')

    def toarmint(self):
        """Arm timer for intermediate."""
        self.status = 'armint'
        uiutil.buttonchg(self.b, uiutil.bg_armint, 'Intermediate Armed')

    def torunning(self):
        """Update timer state to running."""
        self.bibent.set_sensitive(False)
        self.serent.set_sensitive(False)
        self.status = 'running'
        uiutil.buttonchg(self.b, uiutil.bg_none, 'Running')

    def start(self, starttod):
        """Trigger start on timer."""
        self.starttod = starttod
	self.torunning()

    def toload(self, bib=None):
        """Load timer."""
        self.status = 'load'
        self.starttod = None
        self.recovtod = tod.tod(0)
        self.finishtod = None
        self.set_time()
	self.lap = 0
        self.set_lap()
        self.splits = []
        if bib is not None:
            self.setrider(bib)
        uiutil.buttonchg(self.b, uiutil.bg_none, 'Ready')
     
    def toarmstart(self):
        """Set state to armstart."""
	self.status = 'armstart'
	self.set_time('       0.0   ')
        uiutil.buttonchg(self.b, uiutil.bg_armstart, 'Start Armed')

    def disable(self):
        """Disable rider bib entry field."""
        self.bibent.set_sensitive(False)
        self.serent.set_sensitive(False)

    def enable(self):
        """Enable rider bib entry field."""
        self.bibent.set_sensitive(True)
        self.serent.set_sensitive(True)

    def toidle(self):
        """Set timer state to idle."""
        self.status = 'idle'
        self.bib = None
        self.bibent.set_text('')
        self.bibent.set_sensitive(True)
        self.serent.set_sensitive(True)
        self.biblbl.set_text('')
        self.starttod = None
        self.recovtod = tod.tod(0)
        self.finishtod = None
	self.lap = 0
        self.set_lap()
        self.splits = []
        self.set_time()
        uiutil.buttonchg(self.b, uiutil.bg_none, 'Idle')

    def __init__(self, label='Timer', doser=False):
        """Constructor."""
        s = gtk.Frame(label)
        s.set_border_width(5)
        s.set_shadow_type(gtk.SHADOW_IN)
        s.show()
        self.doser = doser

        v = gtk.VBox(False, 5)
        v.set_border_width(5)

        # Bib and name label
        h = gtk.HBox(False, 5)
	l = gtk.Label('Rider #:')
        l.show()
        h.pack_start(l, False)
        self.bibent = gtk.Entry(6)
        self.bibent.set_width_chars(3)
        self.bibent.show()
        h.pack_start(self.bibent, False)
        self.serent = gtk.Entry(6)
        self.serent.set_width_chars(2)
        if self.doser:
            self.serent.show()
        h.pack_start(self.serent, False)
        self.biblbl = gtk.Label('')
        self.biblbl.show()
        h.pack_start(self.biblbl, True)
        h.show()
        v.pack_start(h, False)

        # Clock row
        self.ck = gtk.Label('       0.000 ')
        self.ck.set_alignment(0.5, 0.5)
        self.ck.modify_font(pango.FontDescription("monospace bold 24"))
        self.ck.show()
        v.pack_start(self.ck, True)

        # Timer ctrl/status button
        h = gtk.HBox(False, 5)
        self.b = gtk.Button('Idle')
        self.b.set_border_width(5)
        self.b.show()
        self.b.set_property('can-focus', False)
        h.pack_start(self.b, True)
        self.ls = gtk.Label('')
        #self.ls.show()	-> hide till shown in caller
        h.pack_start(self.ls, False)
        self.lb = gtk.Button('+')
        self.lb.set_border_width(5)
        self.lb.set_property('can-focus', False)
        #self.lb.show()
        self.lb.connect('clicked', self.lap_up_clicked_cb)
        h.pack_start(self.lb, False)
        h.show()

        v.pack_start(h, False)
        v.show()
        s.add(v)
        self.frame = s
        self.toidle()

