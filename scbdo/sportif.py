
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

"""Mass participartion 'sportif' ride handler.

This module provides a class 'sportif' which implements the sportif
ride handler. Written for the 2010 'Ride the Worlds' sportif, this
is a rather clumsy event handler but should serve as a starting
point for a custom event handler as it implements only the required
methods to fit into the roadmeet framework.

"""

## NOTES:
##
##  - THIS IS INCOMPLETE CODE, custom made for a specific event. Some
##    modification will be required for use with other sportif events.
##

import gtk
import glib
import gobject
import pango
import os
import logging
import csv
import decimal
import ConfigParser

import scbdo
from scbdo import tod
from scbdo import eventdb
from scbdo import riderdb
from scbdo import strops
from scbdo import printops
from scbdo import uiutil

# Model columns

# basic infos
COL_BIB = 0
COL_NAMESTR = 1
COL_CAT = 2
COL_COMMENT = 3

# timing infos
COL_RFTIME = 4		# one-off finish time (if relevant) by rfid
COL_RFSEEN = 5		# list of tods this rider 'seen' by rfid

# rider commands
RIDER_COMMMANDS = {'add':'Add riders',
                   'del':'Delete riders',
                   'que':'Query riders',
                   'com':'Add comment' }

# timing keys
key_armstart = 'F5'
key_clearscratch = 'F6'
key_armfinish = 'F9'
key_raceover = 'F10'

# extended fn keys	(ctrl + key)
key_abort = 'F5'

# config version string
EVENT_ID = 'sportif-1.0'

def sort_bib(x, y):
    """Rider bib sorter."""
    if x.isdigit():
        x = int(x)
    if y.isdigit():
        y = int(y)
    return cmp(x, y)

class sportif(object):
    """Sportif ride handler."""

    def loadconfig(self):
        """Load race config from disk."""
        self.riders.clear()
        self.resettimer()
        cr = ConfigParser.ConfigParser({'start':'',
                                        'lstart':'',
                                        'id':EVENT_ID,
                                        'finish':'',
                                        'finished':'No',
                                        'startlist':''})
        cr.add_section('event')
        cr.add_section('riders')
        if os.path.isfile(self.configpath):
            self.log.debug('Attempting to read config from path='
                            + repr(self.configpath))
            cr.read(self.configpath)
        starters = cr.get('event', 'startlist').split()
        # for a sportif - always sort by bib
        starters.sort(cmp=sort_bib)
        for r in starters:
            self.addrider(r)
            if cr.has_option('riders', r):
                nr = self.getrider(r)
                # bib = comment,rftod,rfseen...
                ril = csv.reader([cr.get('riders', r)]).next()
                lr = len(ril)
                if lr > 0:
                    nr[COL_COMMENT] = ril[0]
                if lr > 1:
                    nr[COL_RFTIME] = tod.str2tod(ril[1])
                if lr > 2:
                    for i in range(2, lr):
                        laptod = tod.str2tod(ril[i])
                        if laptod is not None:
                            nr[COL_RFSEEN].append(laptod)
        self.set_start(cr.get('event', 'start'), cr.get('event', 'lstart'))
        self.set_finish(cr.get('event', 'finish'))
        if cr.get('event', 'finished') == 'Yes':
            self.set_finished()

        # After load complete - check config and report. This ensures
        # an error message is left on top of status stack. This is not
        # always a hard fail and the user should be left to determine
        # an appropriate outcome.
        eid = cr.get('event', 'id')
        if eid != EVENT_ID:
            self.log.error('Event configuration mismatch: '
                           + repr(eid) + ' != ' + repr(EVENT_ID))

    def get_ridercmds(self):
        """Return a dict of rider bib commands for container ui."""
        return RIDER_COMMMANDS

    def get_startlist(self):
        """Return a list of all rider numbers 'registered' to event."""
        ret = []
        for r in self.riders:
            ret.append(r[COL_BIB])
        return ' '.join(ret)

    def saveconfig(self):
        """Save event config to disk."""
        if self.readonly:
            self.log.error('Attempt to save readonly ob.')
            return
        cw = ConfigParser.ConfigParser()
        cw.add_section('event')
        if self.start is not None:
            cw.set('event', 'start', self.start.rawtime())
        if self.lstart is not None:
            cw.set('event', 'lstart', self.lstart.rawtime())
        if self.finish is not None:
            cw.set('event', 'finish', self.finish.rawtime())
        if self.timerstat == 'finished':
            cw.set('event', 'finished', 'Yes')
        else:
            cw.set('event', 'finished', 'No')
        cw.set('event', 'startlist', self.get_startlist())    

        cw.add_section('riders')
        for r in self.riders:
            rt = ''
            if r[COL_RFTIME] is not None:
                rt = r[COL_RFTIME].rawtime(2)
            # bib = comment,rftod,rfseen...
            slice = [r[COL_COMMENT], rt]
            for t in r[COL_RFSEEN]:
                if t is not None:
                    slice.append(t.rawtime(2))
            cw.set('riders', r[COL_BIB],
                    ','.join(map(lambda i: str(i).replace(',', '\\,'), slice)))
        cw.set('event', 'id', EVENT_ID)
        self.log.debug('Saving config to: ' + self.configpath)
        with open(self.configpath, 'wb') as f:
            cw.write(f)

    def show(self):
        """Show event container."""
        self.frame.show()

    def hide(self):
        """Hide event container."""
        self.frame.hide()

    def title_close_clicked_cb(self, button, entry=None):
        """Close and save the race."""
        self.meet.close_event()

    def set_titlestr(self, titlestr=None):
        """Update the title string label."""
        if titlestr is None or titlestr == '':
            titlestr = 'Sportif Ride'
        self.title_namestr.set_text(titlestr)

    def destroy(self):
        """Emit destroy signal to race handler."""
        self.frame.destroy()

    def get_results(self):
        """Extract results in flat mode (not yet implemented)."""
        return []

    def startlist_header(self):
        """Return a startlist header."""
        return('no.   rider')

    def startlist_report(self):
        """Return a startlist."""
        ret = []
        for r in self.riders:
            ret.append(r[riderdb.COL_BIB].rjust(4) + '  '
                                 + strops.truncpad(r[COL_NAMESTR], 48)
                                 + str(r[COL_CAT]).rjust(10))
        return ret

    def result_header(self):
        """Return the result header."""
        return('\
no.   rider                              lap 1   lap 2   lap 3   lap 4')

    def result_report(self):
        """Return a result report."""
        ret =  []

        # set the start time
        st = tod.tod(0)
        if self.start is not None:
            st = self.start

        # resort -> ??

        # scan registered riders
        for r in self.riders:
            ret.append(self.fmt_rider_result(r, st))
        return ret

    def camera_header(self):
        """Return the judges report header."""
        return ''

    def camera_report(self):
        """Return a judges (camera) report."""
        self.log.error('Judges report not implemented for sportif rides.')
        return ['     -- No Judges Report for Sportif Ride --']

    def stat_but_clicked(self):
        """Deal with a status button click in the main container."""
        self.log.debug('Stat button clicked.')

    def fmt_rider_result(self, r, st):
        """Return a result string for the provided rider reference."""
        ret = r[COL_BIB].rjust(4) + '  ' + strops.truncpad(r[COL_NAMESTR], 32)
        lt = st
        for split in r[COL_RFSEEN]:
            ret += ' ' + (split - lt).rawtime(0).rjust(7)
            lt = split
        return(ret)

    def query_rider(self, bib=None):
        """List info on selected rider in the scratchpad."""

        # set the start time
        st = tod.tod(0)
        if self.start is not None:
            st = self.start

        # get the rider
        r = self.getrider(bib)
        if r is not None:
            self.meet.scratch_log(self.fmt_rider_result(r, st))
        else:
            self.log.info('Rider = ' + repr(bib) + ' not in startlist.')

        return False # allow push via idle_add(...

    def add_comment(self, comment=''):
        """Append a race comment."""
        self.log.info('Add comment: ' + repr(comment))

    def race_ctrl(self, acode='', rlist=''):
        """Apply the selected action to the provided bib list."""
        if acode == 'del':
            rlist = strops.reformat_biblist(rlist)
            for bib in rlist.split():
                self.delrider(bib)
            return True
        elif acode == 'add':
            rlist = strops.reformat_biblist(rlist)
            for bib in rlist.split():
                self.addrider(bib)
            return True
        elif acode == 'que':
            rlist = strops.reformat_biblist(rlist)
            for bib in rlist.split():
                self.query_rider(bib)
            return True
        elif acode == 'com':
            self.add_comment(rlist)
            return True
        else:
            self.log.error('Ignoring invalid action.')
        return False

    def result_export(self, f):
        """Export result for use with other systems."""
        cr = csv.writer(f)
 
        cr.writerow(['no', 'rider', 'email', 'laps', 
                     'Split 1', 'Lap 1', 'Split 2', 'Lap 2',
                     'Split 3', 'Lap 3', 'Split 4', 'Lap 4'])

        # set the start time
        st = tod.tod(0)
        if self.start is not None:
            st = self.start

        # scan start list
        for r in self.riders:
            res = [r[COL_BIB], r[COL_NAMESTR], r[COL_COMMENT],
                   str(len(r[COL_RFSEEN]))]

            # scan lap splits
            lt = st
            for split in r[COL_RFSEEN]:
                laptime = split - lt
                lapstr = laptime.rawtime(0)
                splitstr = split.rawtime(0)
                if laptime < self.minlap:
                    self.log.warn('Suspect lap for rider ' 
                                  + repr(r[COL_BIB]) + ':'
                                  + lapstr)
                res.append(splitstr)
                res.append(lapstr)
                lt = split

            # emit row
            cr.writerow(res)

    def clear_results(self):
        """Clear all data from event model."""
        self.log.debug('Clear results not implemented.')

    def getrider(self, bib):
        """Return reference to selected rider no."""
        ret = None
        for r in self.riders:
            if r[COL_BIB] == bib:
                ret = r
                break
        return ret

    def getiter(self, bib):
        """Return temporary iterator to model row."""
        i = self.riders.get_iter_first()
        while i is not None:
            if self.riders.get_value(i, COL_BIB) == bib:
                break
            i = self.riders.iter_next(i)
        return i

    def delrider(self, bib=''):
        """Remove the specified rider from the model."""
        i = self.getiter(bib)
        if i is not None:
            self.riders.remove(i)

    def addrider(self, bib=''):
        """Add specified rider to race model."""
        if bib == '' or self.getrider(bib) is None:
            nr = [bib, '', '', '', None, []]
            dbr = self.meet.rdb.getrider(bib, self.series)
            if dbr is not None:
                nr[COL_NAMESTR] = strops.listname(
                      self.meet.rdb.getvalue(dbr, riderdb.COL_FIRST),
                      self.meet.rdb.getvalue(dbr, riderdb.COL_LAST),
                      self.meet.rdb.getvalue(dbr, riderdb.COL_CLUB))
                nr[COL_CAT] = self.meet.rdb.getvalue(dbr, riderdb.COL_CAT)
            return self.riders.append(nr)
        else:
            return None

    def resettimer(self):
        """Reset race timer."""
        self.set_finish()
        self.set_start()
        self.clear_results()
        self.timerstat = 'idle'
        self.meet.rfu.dearm()
        uiutil.buttonchg(self.meet.stat_but, uiutil.bg_none, 'Idle')
        self.meet.stat_but.set_sensitive(True)
        self.set_elapsed()
        
    def armstart(self):
        """Process an armstart request."""
        if self.timerstat == 'idle':
            self.timerstat = 'armstart'
            self.meet.rfu.arm()
            uiutil.buttonchg(self.meet.stat_but, uiutil.bg_armstart,
                                    'Arm Start')
        elif self.timerstat == 'armstart':
            self.timerstat = 'idle'
            uiutil.buttonchg(self.meet.stat_but, uiutil.bg_none, 'Idle') 
            self.meet.rfu.dearm()	# superfluous?
        elif self.timerstat == 'running':
            # Possible extra state transition here in response to F5
            pass

    def armfinish(self):
        """Process an armfinish request."""
        if self.timerstat in ['running', 'finished']:
            self.timerstat = 'armfinish'
            uiutil.buttonchg(self.meet.stat_but, uiutil.bg_armfin, 'Arm Finish')
            self.meet.stat_but.set_sensitive(True)
            self.meet.rfu.arm()
        elif self.timerstat == 'armfinish':
            self.timerstat = 'running'
            uiutil.buttonchg(self.meet.stat_but, uiutil.bg_none, 'Running')

    def key_event(self, widget, event):
        """Handle global key presses in event."""
        if event.type == gtk.gdk.KEY_PRESS:
            key = gtk.gdk.keyval_name(event.keyval) or 'None'
            if event.state & gtk.gdk.CONTROL_MASK:
                if key == key_abort:    # override ctrl+f5
                    self.resettimer()
                    return True
            if key[0] == 'F':
                if key == key_armstart:
                    self.armstart()
                    return True
                elif key == key_armfinish:
                    self.armfinish()
                    return True
                elif key == key_raceover:
                    self.set_finished()
                    return True
                elif key == key_clearscratch:
                    self.meet.scratch_clear()
                    return True
        return False

    def shutdown(self, win=None, msg='Race Sutdown'):
        """Close event."""
        self.log.debug('ms shutdown: ' + msg)
        if not self.readonly:
            self.saveconfig()
        self.meet.edb.editevent(self.event, winopen=False)
        self.winopen = False

    def starttrig(self, e):
        """Process a 'start' trigger signal."""
        if self.timerstat == 'armstart':
            self.set_start(e, tod.tod('now'))

    def rfidtrig(self, e):
        """Process rfid event."""
        if e.refid == 'trig':
            self.starttrig(e)
            return

        r = self.meet.rdb.getrefid(e.refid)
        if r is None:
            r = self.meet.rdb.addempty(e.refid, self.series)
            self.meet.rdb.editrider(r, refid=e.refid)

        bib = self.meet.rdb.getvalue(r, riderdb.COL_BIB)
        ser = self.meet.rdb.getvalue(r, riderdb.COL_SERIES)
        if ser != self.series:
            self.log.error('Ignored non-series rider: ' + bib + '.' + ser)
            return

        lr = self.getrider(bib)
        if lr is None:
            self.addrider(bib)
            lr = self.getrider(bib)
            self.log.info('Added non starter: ' + bib
                          + ' @ ' + e.rawtime(1))

        # at this point should always have a valid rider vector
        assert(lr is not None)

        if self.timerstat not in ['idle', 'finished']:
            # save RF ToD into 'seen' vector and log
            lr[COL_RFSEEN].append(e)
            self.log.info('Saw: ' + bib + ' @ ' + e.rawtime(1))
            glib.idle_add(self.query_rider, bib)

            # record finish time if required
            if self.timerstat == 'armfinish':
                if lr[COL_RFTIME] is None:
                    lr[COL_RFTIME] = e
                else:
                    self.log.error('Duplicate finish rider = ' + bib
                                      + ' @ ' + str(e))

    def timeout(self):
        """Poll for rfids and update elapsed time."""
        if not self.winopen:
            return False
        e = self.meet.rfu.response()
        while e is not None:
            self.rfidtrig(e)
            e = self.meet.rfu.response()
        if self.finish is None and self.start is not None:
            self.set_elapsed()
        return True

    def set_start(self, start='', lstart=None):
        """Set the start time."""
        if type(start) is tod.tod:
            self.start = start
            if lstart is not None:
                self.lstart = lstart
            else:
                self.lstart = self.start
        else:
            self.start = tod.str2tod(start)
            if lstart is not None:
                self.lstart = tod.str2tod(lstart)
            else:
                self.lstart = self.start
        if self.start is not None and self.finish is None:
            self.set_running()

    def set_finish(self, finish=''):
        """Set the finish time."""
        if type(finish) is tod.tod:
            self.finish = finish
        else:
            self.finish = tod.str2tod(finish)
        if self.finish is None:
            if self.start is not None:
                self.set_running()
        else:
            if self.start is None:
                self.set_start('0')

    def set_elapsed(self):
        """Update the elapsed time field."""
        if self.start is not None and self.finish is not None:
            self.time_lbl.set_text((self.finish - self.start).timestr(0))
        elif self.start is not None:    # Note: uses 'local start' for RT
            self.time_lbl.set_text((tod.tod('now') - self.lstart).timestr(0))
        elif self.timerstat == 'armstart':
            self.time_lbl.set_text(tod.tod(0).timestr(0))
        else:
            self.time_lbl.set_text('')

    def set_running(self):
        """Update event status to running."""
        self.timerstat = 'running'
        self.meet.rfu.arm()
        uiutil.buttonchg(self.meet.stat_but, uiutil.bg_none, 'Running')

    def set_finished(self):
        """Update event status to finished."""
        self.timerstat = 'finished'
        self.meet.rfu.dearm()
        uiutil.buttonchg(self.meet.stat_but, uiutil.bg_none, 'Finished')
        self.meet.stat_but.set_sensitive(False)
        if self.finish is None:
            self.set_finish(tod.tod('now'))
        self.set_elapsed()

    def info_time_edit_clicked_cb(self, button, data=None):
        """Run the edit times dialog."""
        st = ''
        if self.start is not None:
            st = self.start.rawtime(2)
        ft = ''
        if self.finish is not None:
            ft = self.finish.rawtime(2)
        (ret, st, ft) = uiutil.edit_times_dlg(self.meet.window, st, ft)
        if ret == 1:
            self.set_start(st)
            self.set_finish(ft)
            self.log.info('Adjusted race times.')

    def editcol_cb(self, cell, path, new_text, col):
        """Edit column callback."""
        new_text = new_text.strip()
        self.riders[path][col] = new_text

    def __init__(self, meet, event, ui=True):
        self.meet = meet
        self.event = event      # Note: now a treerowref
        self.evno = meet.edb.getvalue(event, eventdb.COL_EVNO)
        self.series = meet.edb.getvalue(event, eventdb.COL_SERIES)
        self.configpath = os.path.join(self.meet.configpath,
                                       'event_' + self.evno)

        self.log = logging.getLogger('scbdo.sportif')
        self.log.setLevel(logging.DEBUG)
        self.log.debug('opening event: ' + str(self.evno))

        # race run time attributes
        self.readonly = not ui
        self.start = None
        self.lstart = None
        self.finish = None
        self.winopen = True
        self.timerstat = 'idle'
        self.minlap = tod.tod('20:00.0')

        self.riders = gtk.ListStore(gobject.TYPE_STRING, # BIB = 0
                                    gobject.TYPE_STRING, # NAMESTR = 1
                                    gobject.TYPE_STRING, # CAT = 2
                                    gobject.TYPE_STRING, # COMMENT = 3
                                    gobject.TYPE_PYOBJECT, # RFTIME = 4
                                    gobject.TYPE_PYOBJECT) # RFSEEN = 5

        b = gtk.Builder()
        b.add_from_file(os.path.join(scbdo.UI_PATH, 'sportif.ui'))

        # !! destroy??
        self.frame = b.get_object('race_vbox')
        self.frame.connect('destroy', self.shutdown)

        # meta info pane
        self.title_namestr = b.get_object('title_namestr')
        self.set_titlestr()
        self.time_lbl = b.get_object('time_lbl')
        self.time_lbl.modify_font(pango.FontDescription("monospace bold"))

        # results pane
        t = gtk.TreeView(self.riders)
        t.set_reorderable(True)
        t.set_rules_hint(True)
        t.show()
        uiutil.mkviewcoltxt(t, 'No.', COL_BIB, calign=1.0)
        uiutil.mkviewcoltxt(t, 'Rider', COL_NAMESTR, expand=True)
        uiutil.mkviewcoltxt(t, 'Comment', COL_COMMENT,
                                cb=self.editcol_cb, width=120)
        b.get_object('race_result_win').add(t)

        if ui:
            # connect signal handlers
            b.connect_signals(self)
            self.meet.edb.editevent(event, winopen=True)
            self.meet.rfu.arm()
