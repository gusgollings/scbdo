
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

"""Omnium 'aggregate' model.

This module provides a class 'omnium' which implements the 'race' interface
and manages data, timing and scoreboard for omnium style aggregates.

Notes:

  - Event state is rebuilt on load of model.
  - Model does not (at this stage) provide methods for altering stages
  - dnf/dns is handled only crudely and inferred by reading stage result
 
"""

import os
import logging
import csv
import ConfigParser
import gtk
import glib
import gobject

import scbdo
from scbdo import scbwin
from scbdo import tod
from scbdo import uiutil
from scbdo import eventdb
from scbdo import riderdb
from scbdo import strops

# Model columns
COL_BIB = 0
COL_FIRST = 1
COL_LAST = 2
COL_CLUB = 3
COL_COMMENT = 4
COL_TOTAL = 5
COL_TIME = 6
COL_PLACE = 7
COL_POINTS = 8		# array of points for display

# scb function key mappings
key_abort = 'F5'
key_startlist = 'F3'
key_results = 'F4'

# SCB constants
SCB_STARTERS_NW = scbdo.SCB_LINELEN - 9
SCB_STARTERS_FMT = [(3, 'r'), ' ', (SCB_STARTERS_NW,'l'), ' ', (4,'r')]

SCB_RESPOINTS_NW = scbdo.SCB_LINELEN - 10
SCB_RESPOINTS_FMT = [(3,'l'),(3,'r'),' ',
                     (SCB_RESPOINTS_NW,'l'),(3,'r')]

class omnium(object):
    def loadconfig(self):
        """Load race config from disk."""
        self.riders.clear()
        cr = ConfigParser.ConfigParser({'startlist':'',
                                        'showinfo':'Yes',
                                        'events':'',
                                        'evnicks':''})
        cr.add_section('race')
        cr.add_section('riders') # no need fr omnium??

        if os.path.isfile(self.configpath):
            self.log.debug('Attempting to read config from '
                               + repr(self.configpath))
            cr.read(self.configpath)
        for r in cr.get('race', 'startlist').split():
            self.addrider(r)
            ## TODO : load/save comment for rider

        self.info_expand.set_expanded(strops.confopt_bool(
                                       cr.get('race', 'showinfo')))

        self.events = strops.reformat_bibserlist(cr.get('race', 'events'))
        self.nicknames = cr.get('race', 'evnicks').split()
        self.recalculate()

    def get_startlist(self):
        """Return a list of bibs in the rider model."""
        ret = []
        for r in self.riders:
            ret.append(r[COL_BIB])
        return ' '.join(ret)

    def saveconfig(self):
        """Save race to disk."""
        if self.readonly:
            self.log.error('Attempt to save readonly ob.')
            return
        cw = ConfigParser.ConfigParser()
        cw.add_section('race')
        cw.set('race', 'startlist', self.get_startlist())
        cw.set('race', 'events', self.events)
        cw.set('race', 'evnicks', ' '.join(self.nicknames))
        if self.info_expand.get_expanded():
            cw.set('race', 'showinfo', 'Yes')
        else:
            cw.set('race', 'showinfo', 'No')
        self.log.debug('Saving race config to: ' + self.configpath)
        with open(self.configpath, 'wb') as f:
            cw.write(f)

    def result_gen(self):
        """Generator function to export a final result."""
        for r in self.riders:
            bib = r[COL_BIB]
            rank = None
            if r[COL_PLACE] != '':
                if r[COL_PLACE].isdigit():
                    rank = int(r[COL_PLACE])
                else:
                    rank = r[COL_PLACE]
            time = None

            yield [bib, rank, time]

    def result_export(self, f):
        """Export results to supplied file handle."""
        cr = csv.writer(f)
        header = ['Event ' + self.evno,
              self.meet.edb.getvalue(self.event, eventdb.COL_PREFIX) + ' '
              + self.meet.edb.getvalue(self.event, eventdb.COL_INFO),
              '','Pts','Time']
        for c in self.nicknames:
            header.append(c)
        cr.writerow(header)

        for r in self.riders:
            plstr = ''
            if r[COL_PLACE] != '':
                plstr = r[COL_PLACE]
                if plstr.isdigit():
                    plstr += '.'
            namstr = self.meet.resname(r[COL_BIB], r[COL_FIRST],
                                     r[COL_LAST], r[COL_CLUB])
            ptsstr = ''
            if r[COL_TOTAL] > 0:
                ptsstr = str(r[COL_TOTAL])
            tmstr = ''
            if r[COL_TIME] != tod.ZERO:
                tmstr = r[COL_TIME].rawtime(3)
            orow = ["'"+plstr, "'"+namstr,'',"'"+ptsstr, "'"+tmstr]
            for c in r[COL_POINTS]:
                orow.append("'"+c)
            cr.writerow(orow)

    def addrider(self, bib=''):
        """Add specified rider to race model."""
        nr=[bib, '', '', '', '', 0, tod.tod(0), '', []]
        if bib == '' or self.getrider(bib) is None:
            dbr = self.meet.rdb.getrider(bib, self.series)
            if dbr is not None:
                for i in range(1,5):
                    nr[i] = self.meet.rdb.getvalue(dbr, i)
            return self.riders.append(nr)
        else:
            return None

    def getrider(self, bib):
        """Return temporary reference to model row."""
        ret = None
        for r in self.riders:
            if r[COL_BIB] == bib:
                ret = r         ## DANGER- Leaky ref
                break
        return ret

    def delrider(self, bib):
        """Remove the specified rider from the model."""
        i = self.getiter(bib)
        if i is not None:
            self.riders.remove(i)

    def getiter(self, bib):
        """Return temporary iterator to model row."""
        i = self.riders.get_iter_first()
        while i is not None:
            if self.riders.get_value(i, COL_BIB) == bib:
                break
            i = self.riders.iter_next(i)
        return i

    def clearplaces(self):
        """Zero internal model for recalculate."""
        for r in self.riders:
            r[COL_PLACE] = ''
            r[COL_TOTAL] = 0
            r[COL_TIME] = tod.tod(0)
            r[COL_POINTS] = []

    def sortomnium(self, x, y):
        """Sort results according to omnium rules."""

        # Comparison vecs: [idx, bib, rcnt, dnf, r[COL_TOTAL], r[COL_TIME]
        if x[2] == y[2]:	# Same number of results so far
            if x[3] == y[3]:	# Both dnf or not
                if x[3] == 'dnf':
                    return cmp(x[1], y[1])		# revert to bib
                else:
                    if x[4] == y[4]:			# same pts
                        if x[5] == y[5]:		# same aggregate time
                            return cmp(x[1], y[1])	# revert to bib
                        else:
                            return cmp(x[5], y[5])
                    else:
                        return cmp(x[4], y[4])
            else:
                return cmp(x[3], y[3])		# In then DNF
        else:
            return cmp(y[2], x[2]) # Sort descending on rcount

    def recalculate(self):
        """Update internal model."""
        self.clearplaces()

        # Pass one: Fill in points for all events
        rescount = {}
        ecnt = 0
        for eno in self.events.split():
            if eno != self.evno:
                r = self.meet.get_event(eno, False)
                r.loadconfig()
                for res in r.result_gen():
                    bib = res[0]
                    lr = self.getrider(bib)
                    if lr is not None:
                        while len(lr[COL_POINTS]) < ecnt:
                            self.log.warn('Filling in points for rider ' + repr(bib))
                            lr[COL_POINTS].append('')
                        if len(lr[COL_POINTS]) == ecnt:
                            if res[1] is not None and lr[COL_PLACE] != 'dnf':
                                self.onestart = True
                                if type(res[1]) is int:
                                    lr[COL_TOTAL] += res[1]
                                    if bib not in rescount:
                                        rescount[bib] = 1
                                    else:
                                        rescount[bib] += 1
                                elif res[1] in ['dsq', 'dnf', 'dns']:
                                    lr[COL_PLACE] = 'dnf'
                                lr[COL_POINTS].append(str(res[1]))

                                if type(res[2]) is tod.tod:
                                    lr[COL_TIME] = lr[COL_TIME] + res[2]
                            else:
                                lr[COL_POINTS].append('')
                        else:
                            self.log.error('Ignoring duplicate result for rider ' + repr(bib))
                    else:
                        self.log.warn('Result for rider not in aggregate: ' + repr(bib))
            else:	# serious problem... but ignore for now
                self.log.error('Ignoring self in list of aggregate events.')
            ecnt += 1

        # Pass 2: Create aux map and sort model
        auxtbl = []
        idx = 0
        for r in self.riders:
            bib = r[COL_BIB]
            rcnt = 0
            if bib in rescount:
                rcnt = rescount[bib]
            dnf = False
            if r[COL_PLACE] != '':	# dnf
                dnf = True
            arow = [idx, bib, rcnt, dnf, r[COL_TOTAL], r[COL_TIME]]
            auxtbl.append(arow)
            idx += 1
        if len(auxtbl) > 1:
            auxtbl.sort(self.sortomnium)
            self.riders.reorder([a[0] for a in auxtbl])

        # Pass 3: Fill in places
        idx = 0
        place = 0
        lp = 0
        lt = tod.tod(0)
        for r in self.riders:
            if r[COL_TOTAL] != lp or r[COL_TIME] > lt:
                place = idx + 1
            if r[COL_PLACE] != '':
                break
            if place > 0:
                r[COL_PLACE] = place
            idx += 1
            lp = r[COL_TOTAL]
            lt = r[COL_TIME]

    def key_event(self, widget, event):
        """Race window key press handler."""
        if event.type == gtk.gdk.KEY_PRESS:
            key = gtk.gdk.keyval_name(event.keyval) or 'None'
            if event.state & gtk.gdk.CONTROL_MASK:
                if key == key_abort:    # override ctrl+f5
                    self.recalculate()
                    return True
            if key[0] == 'F':
                if key == key_startlist:
                    self.do_startlist()
                    return True
                elif key == key_results:
                    self.do_places()
                    return True
        return False

    def delayed_announce(self):
        """Initialise the announcer's screen after a delay."""
        if self.winopen:
            self.meet.announce.clrall()

            self.meet.ann_title(' '.join([
                  'Event', self.evno, ':',
                  self.meet.edb.getvalue(self.event, eventdb.COL_PREFIX),
                  self.meet.edb.getvalue(self.event, eventdb.COL_INFO),
                  '- Standings']))
            self.meet.announce.linefill(1, '_')
            ha = [ '   ', '  #', 'Rider'.ljust(25), ' Pts']
            for n in self.nicknames:
                ha.append(strops.truncpad(n, 4, 'r'))
            ha.append('Tot Time'.rjust(10))
            self.meet.announce.setline(3, ' '.join(ha))

            l = 4
            for r in self.riders:
                plstr = ''
                if r[COL_PLACE] != '':
                    plstr = r[COL_PLACE]
                    if plstr.isdigit():
                        plstr += '.'
                plstr = strops.truncpad(plstr, 3, 'l')
                bibstr = strops.truncpad(r[COL_BIB], 3, 'r')
                clubstr = ''
                if r[COL_CLUB] != '':
                    clubstr = ' (' + r[COL_CLUB] + ')'
                namestr = strops.truncpad(strops.fitname(r[COL_FIRST],
                              r[COL_LAST], 25-len(clubstr))+clubstr, 25)
                ptsstr = '    '
                if r[COL_TOTAL] > 0:
                    ptsstr = strops.truncpad(str(r[COL_TOTAL]), 4, 'r')
                ol = [plstr, bibstr, namestr, ptsstr]
                for c in range(0, len(self.nicknames)):
                    if len(r[COL_POINTS]) > c:
                        ol.append(strops.truncpad(r[COL_POINTS][c], 4, 'r'))
                    else:
                        ol.append('    ')
                if r[COL_TIME] != tod.ZERO:
                    ol.append(strops.truncpad(r[COL_TIME].rawtime(3), 10, 'r'))
                else:
                    ol.append('          ')
                self.meet.announce.setline(l, ' '.join(ol))
                l += 1

        return False

    def do_startlist(self):
        """Show startlist on scoreboard."""
        self.meet.scbwin = None
        self.timerwin = False
        startlist = []
        for r in self.riders:
            startlist.append([r[COL_BIB],
                              strops.fitname(r[COL_FIRST],
                                             r[COL_LAST],
                                             SCB_STARTERS_NW),
                                  r[COL_CLUB]])
        self.meet.scbwin = scbwin.scbtable(self.meet.scb,
                                           self.meet.racenamecat(self.event),
                       SCB_STARTERS_FMT, startlist)
        self.meet.scbwin.reset()

    def do_places(self):
        """Show race result on scoreboard."""
        resvec = []
        hdr = self.meet.racenamecat(self.event,
                        scbdo.SCB_LINELEN - 3) + ' pt'
        for r in self.riders:
            resvec.append([r[COL_PLACE], r[COL_BIB],
                         strops.fitname(r[COL_FIRST], r[COL_LAST],
                                        SCB_RESPOINTS_NW),
                         str(r[COL_TOTAL])])
        self.meet.scbwin = None
        self.meet.scbwin = scbwin.scbtable(self.meet.scb,
                                           hdr,
                                SCB_RESPOINTS_FMT,
                                resvec, delay=90, pagesz=5)
        self.meet.scbwin.reset()
        return False

    def shutdown(self, win=None, msg='Exiting'):
        """Terminate race object."""
        self.log.debug('Race shutdown: ' + msg)
        self.meet.menu_race_properties.set_sensitive(False)
        if not self.readonly:
            self.saveconfig()
        self.meet.edb.editevent(self.event, winopen=False)
        self.winopen = False

    def timeout(self):
        """Update scoreboard and respond to timing events."""
        if not self.winopen:
            return False
        e = self.meet.timer.response()
        while e is not None:
            e = self.meet.timer.response()

        return True

    def do_properties(self):
        """Run race properties dialog."""
        pass

    def destroy(self):
        """Signal race shutdown."""
        self.frame.destroy()

    def show(self):
        """Show race window."""
        self.frame.show()

    def hide(self):
        """Hide race window."""
        self.frame.hide()

    def update_expander_lbl_cb(self):
        """Update race info expander label."""
        self.info_expand.set_label('Race Info : '
                    + self.meet.racenamecat(self.event, 64))

    def editent_cb(self, entry, col):
        """Shared event entry update callback."""
        if col == eventdb.COL_PREFIX:
            self.meet.edb.editevent(self.event, prefix=entry.get_text())
        elif col == eventdb.COL_INFO:
            self.meet.edb.editevent(self.event, info=entry.get_text())
        self.update_expander_lbl_cb()

    def todstr(self, col, cr, model, iter, data=None):
        """Format tod into text for listview."""
        at = model.get_value(iter, COL_TIME)
        if at is not None and at != tod.ZERO:
            cr.set_property('text', at.timestr(3))
        else:
            cr.set_property('text', '')

    def __init__(self, meet, event, ui=True):
        """Constructor."""
        self.meet = meet
        self.event = event      # Note: now a treerowref
        self.evno = meet.edb.getvalue(event, eventdb.COL_EVNO)
        self.evtype = meet.edb.getvalue(event, eventdb.COL_TYPE)
        self.series = meet.edb.getvalue(event, eventdb.COL_SERIES)
        self.configpath = os.path.join(self.meet.configpath,
                                       'event_' + self.evno)
        self.log = logging.getLogger('scbdo.points')
        self.log.setLevel(logging.DEBUG)
        self.log.debug('opening event: ' + str(self.evno))

        # race run time attributes
        self.onestart = False
        self.readonly = not ui
        self.winopen = True

        self.riders = gtk.ListStore(gobject.TYPE_STRING, # 0 bib
                                    gobject.TYPE_STRING, # 1 first name
                                    gobject.TYPE_STRING, # 2 last name
                                    gobject.TYPE_STRING, # 3 club
                                    gobject.TYPE_STRING, # 4 comment
                                    gobject.TYPE_INT,    # 5 total
                                    gobject.TYPE_PYOBJECT, # 6 time total
                                    gobject.TYPE_STRING, # 7 place
                                    gobject.TYPE_PYOBJECT) # event points

        b = gtk.Builder()
        b.add_from_file(os.path.join(scbdo.UI_PATH, 'omnium.ui'))

        self.frame = b.get_object('omnium_vbox')
        self.frame.connect('destroy', self.shutdown)

        # info pane
        self.info_expand = b.get_object('info_expand')
        b.get_object('omnium_info_evno').set_text(self.evno)
        self.showev = b.get_object('omnium_info_evno_show')
        self.prefix_ent = b.get_object('omnium_info_prefix')
        self.prefix_ent.set_text(self.meet.edb.getvalue(
                   self.event, eventdb.COL_PREFIX))
        self.prefix_ent.connect('changed', self.editent_cb,
                                 eventdb.COL_PREFIX)
        self.info_ent = b.get_object('omnium_info_title')
        self.info_ent.set_text(self.meet.edb.getvalue(
                   self.event, eventdb.COL_INFO))
        self.info_ent.connect('changed', self.editent_cb,
                               eventdb.COL_INFO)
        self.update_expander_lbl_cb()

        # riders pane
        t = gtk.TreeView(self.riders)
        self.view = t
        t.set_reorderable(True)
        t.set_enable_search(False)
        t.set_rules_hint(True)

        # riders columns
        uiutil.mkviewcoltxt(t, 'No.', COL_BIB, calign=1.0)
        uiutil.mkviewcoltxt(t, 'First Name', COL_FIRST,
                                expand=True)
        uiutil.mkviewcoltxt(t, 'Last Name', COL_LAST,
                                expand=True)
        uiutil.mkviewcoltxt(t, 'Club', COL_CLUB)
        uiutil.mkviewcoltxt(t, 'Points', COL_TOTAL, calign=1.0)
        uiutil.mkviewcoltod(t, 'Time', cb=self.todstr)
        uiutil.mkviewcoltxt(t, 'Rank', COL_PLACE,
                                halign=0.5, calign=0.5)
        t.show()
        b.get_object('omnium_result_win').add(t)

        if ui:
            # connect signal handlers
            b.connect_signals(self)
            # update properties in meet
            self.meet.menu_race_properties.set_sensitive(True)
            self.meet.edb.editevent(event, winopen=True)
            glib.timeout_add_seconds(3, self.delayed_announce)
