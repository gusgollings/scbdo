
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

"""Track flying 200m Time Trial Module

This module provides a class 'f200' which implements the 'race'
interface and manages data, timing and scoreboard for the specific
case of the flying 200m time trial.

"""

import gtk
import glib
import gobject
import pango
import os
import logging
import csv
import ConfigParser

import scbdo
from scbdo import timy
from scbdo import scbwin
from scbdo import tod
from scbdo import uiutil
from scbdo import eventdb
from scbdo import riderdb
from scbdo import strops
from scbdo import timerpane

# startlist model columns
COL_BIB = 0
COL_FIRST = 1
COL_LAST = 2
COL_CLUB = 3
COL_COMMENT = 4
COL_PLACE = 5
COL_START = 6
COL_100M = 7
COL_FINISH = 8

# scb consts
SCB_NAME_WIDTH = scbdo.SCB_LINELEN - 8
SCB_RESNAME_WIDTH = scbdo.SCB_LINELEN - 10
SCB_RESULT_FMT = [(2, 'l'), (3, 'r'), ' ',
                  (SCB_RESNAME_WIDTH, 'l'), ' ', (3, 'r')]

# scb function key mappings
key_showrider = 'F6'                 # show next rider on track
key_results = 'F4'                   # recalc/show result window

# timing function key mappings
key_armstart = 'F5'                # arm for start impulse
key_armfinish = 'F9'               # manual arm finish

# extended function key mappings
key_abort = 'F5'                     # + ctrl for clear/abort

class f200(object):
    """Data handling for flying 200."""
    def key_event(self, widget, event):
        """Race window key press handler."""
        if event.type == gtk.gdk.KEY_PRESS:
            key = gtk.gdk.keyval_name(event.keyval) or 'None'
            if event.state & gtk.gdk.CONTROL_MASK:
                if key == key_abort:    # override ctrl+f5
                    self.toidle()
                    return True
            if key[0] == 'F':
                if key == key_armstart:
                    self.armstart()
                    return True
                elif key == key_armfinish:
                    self.armfinish()
                    return True
                elif key == key_showrider:
                    self.showtimerwin()
                    return True
                elif key == key_results:
                    self.do_places()
                    return True
        return False

    def do_places(self):
        """Show race result on scoreboard."""
        self.meet.scbwin = None
        self.timerwin = False     # TODO: bib width enhancement
        fmtplaces = []
        for r in self.riders:
            if r[COL_PLACE] is not None and r[COL_PLACE] != '':
                if r[COL_PLACE].isdigit() and int(r[COL_PLACE]) > 20:
                    break
                fmtplaces.append([r[COL_PLACE], r[COL_BIB],
                                  strops.fitname(r[COL_FIRST],
                                  r[COL_LAST], SCB_RESNAME_WIDTH),
                                  r[COL_CLUB]])
        self.meet.scbwin = scbwin.scbtable(self.meet.scb,
                       self.meet.racenamecat(self.event),
                       SCB_RESULT_FMT, fmtplaces, delay=90)
        self.meet.scbwin.reset()

    def todstr(self, col, cr, model, iter, data=None):
        """Format tod into text for listview."""
        ft = model.get_value(iter, COL_FINISH)
        if ft is not None:
            st = model.get_value(iter, COL_START)
            if st is None:
                st = tod.tod(0)
            if st == tod.tod(0):
                cr.set_property('style', pango.STYLE_OBLIQUE)
            else:
                cr.set_property('style', pango.STYLE_NORMAL)
            cr.set_property('text', (ft - st).timestr())
        else:
            cr.set_property('text', '')

    def loadconfig(self):
        """Load race config from disk."""
        self.riders.clear()
        self.results.clear()
!!!
        self.splits = []

        # failsafe defaults -> dual timer, C0 start, PA/PB
        deftimetype = 'dual'
        defdistance = ''
        defdistunits = 'metres'
        defchans = str(timy.CHAN_START)
        defchana = str(timy.CHAN_PA)
        defchanb = str(timy.CHAN_PB)
        defautoarm = 'No'

        # type specific overrides
        if self.evtype == 'flying 200':
            deftimetype = 'single'
            defdistance = '200'
            defchana = str(timy.CHAN_FINISH)
            defchanb = str(timy.CHAN_100)
            defautoarm = 'Yes'
        elif self.evtype == 'flying lap':
            deftimetype = 'single'
            defdistance = '1'
            defdistunits = 'laps'
            defchans = str(timy.CHAN_FINISH)
            defchana = str(timy.CHAN_FINISH)
            defchanb = str(timy.CHAN_100)
        elif self.evtype == 'pursuit race':
            self.difftime = True	# NOT CONFIGURABLE

        cr = ConfigParser.ConfigParser({'startlist':'',
					'start':'',
                                        'lstart':'',
                                        'fsbib':'',
                                        'fsstat':'idle',
                                        'bsbib':'',
                                        'bsstat':'idle',
                                        'showinfo':'Yes',
                                        'distance':defdistance,
					'distunits':defdistunits,
                                        'chan_S':defchans,
                                        'chan_A':defchana,
                                        'chan_B':defchanb,
                                        'autoarm':defautoarm,
                                        'timetype':deftimetype})
        cr.add_section('race')
        cr.add_section('riders')
        if os.path.isfile(self.configpath):
            self.log.debug('Attempting to read config from '
                               + repr(self.configpath))
            cr.read(self.configpath)

        self.set_timetype(cr.get('race', 'timetype'))
        self.distance = strops.confopt_dist(cr.get('race', 'distance'))
        self.units = strops.confopt_distunits(cr.get('race', 'distunits'))
        self.chan_S = strops.confopt_chan(cr.get('race', 'chan_S'), defchans)
        self.chan_A = strops.confopt_chan(cr.get('race', 'chan_A'), defchana)
        self.chan_B = strops.confopt_chan(cr.get('race', 'chan_B'), defchanb)
        self.autoarm = strops.confopt_bool(cr.get('race', 'autoarm'))
        self.info_expand.set_expanded(strops.confopt_bool(
                                       cr.get('race', 'showinfo')))
        # re-load starters/results
        self.onestart = False
        for r in cr.get('race', 'startlist').split():
            nr=[r, '', '', '', '', '', '', None, None, None]
            co = ''
            st = None
            ft = None
            sp = []
            if cr.has_option('riders', r):
                ril = csv.reader([cr.get('riders', r)]).next()
                for i in range(0,3):	# firstname, lastname, club
                    if len(ril) > i:	# assigned directlt, but...
                        nr[i+1] = ril[i].strip()
                if len(ril) >= COL_COMMENT:	# save comment for stimes
                    co = ril[COL_COMMENT - 1]
                if len(ril) >= COL_LANE:	# write lane into rec
                    nr[COL_LANE] = ril[COL_LANE - 1]
                if len(ril) >= COL_START:	# Start ToD and others
                    st = tod.str2tod(ril[COL_START - 1])
                    if st is not None:		# assigned in settimes
                        self.onestart = True
                if len(ril) >= COL_FINISH:	# Finish ToD
                    ft = tod.str2tod(ril[COL_FINISH - 1])
                j = COL_SPLITS - 1
                while j < len(ril):	# Split ToDs
                    spt = tod.str2tod(ril[j])
                    sp.append(spt)
                    j += 1
                # Re-patch names if all null and in dbr
                if (nr[COL_FIRSTNAME] == ''
                     and nr[COL_LASTNAME] == ''
                     and nr[COL_CLUB] == ''):
                    dbr = self.meet.rdb.getrider(r, self.series)
                    if dbr is not None:
                        for i in range(1,4):
                            nr[i] = self.meet.rdb.getvalue(dbr, i)
            else:
                dbr = self.meet.rdb.getrider(r, self.series)
                if dbr is not None:
                    for i in range(1,4):
                        nr[i] = self.meet.rdb.getvalue(dbr, i)
            nri = self.riders.append(nr)
            self.settimes(nri, st, ft, sp, doplaces=False, comment=co)
        self.placexfer()

        # re-join any existing timer state
        curstart = tod.str2tod(cr.get('race', 'start'))
        lstart = tod.str2tod(cr.get('race', 'lstart'))
        if lstart is None:
            lstart = curstart	# can still be None if start not set
        dorejoin = False
        # Front straight
        fsstat = cr.get('race', 'fsstat')
        if fsstat in ['running', 'load']: # running with no start gets load
            self.fs.setrider(cr.get('race', 'fsbib')) # will set 'load'
            if fsstat == 'running' and curstart is not None:     
                self.fs.start(curstart)  # overrides to 'running'
                dorejoin = True
        # Back straight
        bsstat = cr.get('race', 'bsstat')
        if bsstat in ['running', 'load']: # running with no start gets load
            self.bs.setrider(cr.get('race', 'bsbib')) # will set 'load'
            if bsstat == 'running' and curstart is not None:     
                self.bs.start(curstart)  # overrides to 'running'
                dorejoin = True
        if dorejoin:
            self.torunning(curstart, lstart)
        elif self.timerstat == 'idle':
            glib.idle_add(self.fs.grab_focus)

    def saveconfig(self):
        """Save race to disk."""
        if self.readonly:
            self.log.error('Attempt to save readonly ob.')
            return
        cw = ConfigParser.ConfigParser()
        cw.add_section('race')

        # save basic race properties
        cw.set('race', 'timetype', self.timetype)
        cw.set('race', 'distance', self.distance)
        cw.set('race', 'distunits', self.units)
        cw.set('race', 'chan_S', self.chan_S)
        cw.set('race', 'chan_A', self.chan_A)
        cw.set('race', 'chan_B', self.chan_B)
        cw.set('race', 'autoarm', self.autoarm)
        cw.set('race', 'startlist', self.get_startlist())
        if self.info_expand.get_expanded():
            cw.set('race', 'showinfo', 'Yes')
        else:
            cw.set('race', 'showinfo', 'No')

        # extract and save timerpane config for interrupted run
        if self.curstart is not None:
            cw.set('race', 'start', self.curstart.rawtime())
        if self.lstart is not None:
            cw.set('race', 'lstart', self.lstart.rawtime())
        cw.set('race', 'fsstat', self.fs.getstatus())
        cw.set('race', 'fsbib', self.fs.getrider())
        cw.set('race', 'bsstat', self.bs.getstatus())
        cw.set('race', 'bsbib', self.bs.getrider())
        cw.add_section('riders')

        # save out all starters
        for r in self.riders:
            # place is saved for info only
            slice = [r[COL_FIRSTNAME], r[COL_LASTNAME], r[COL_CLUB],
                      r[COL_COMMENT], r[COL_LANE], r[COL_PLACE]]
            tl = [r[COL_START], r[COL_FINISH]]
            if r[COL_SPLITS] is not None:
                tl.extend(r[COL_SPLITS])
            for t in tl:
                if t is not None:
                    slice.append(t.rawtime())
                else:
                    slice.append('')
            cw.set('riders', r[COL_BIB],
                ','.join(map(lambda i: str(i).replace(',', '\\,'), slice)))
        self.log.debug('Saving race config to: ' + self.configpath)
        with open(self.configpath, 'wb') as f:
            cw.write(f)

    def get_startlist(self):
        """Return a list of bibs in the rider model."""
        ret = []
        for r in self.riders:
            ret.append(r[COL_BIB])
        return ' '.join(ret)

    def delayed_announce(self):
        """Initialise the announcer's screen after a delay."""
        if self.winopen:
            self.meet.announce.clrall()
            self.meet.ann_title(' '.join([
                  'Event', self.evno, ':',
                  self.meet.edb.getvalue(self.event, eventdb.COL_PREFIX),
                  self.meet.edb.getvalue(self.event, eventdb.COL_INFO)]))

            self.meet.announce.linefill(1, '_')
            self.meet.announce.linefill(7, '_')

            # fill in front straight
            fbib = self.fs.getrider()
            if fbib is not None and fbib != '':
                r = self.getrider(fbib)
                if r is not None:
                    clubstr = r[COL_CLUB][0:4]
                    if r[COL_CLUB] != '':
                        clubstr = '(' + clubstr + ')'
                    namestr = strops.fitname(r[COL_FIRSTNAME],
                                             r[COL_LASTNAME], 24, trunc=True)
                    placestr = '   ' # 3 ch
                    if r[COL_PLACE] != '':
                        placestr = strops.truncpad(r[COL_PLACE] + '.', 3)
                    bibstr = strops.truncpad(r[COL_BIB], 3, 'r')
                    tmstr = ''
                    if r[COL_START] is not None and r[COL_FINISH] is not None:
                        tmstr = (r[COL_FINISH] - r[COL_START]).rawtime(3)
                    cmtstr = ''
                    if r[COL_COMMENT] is not None and r[COL_COMMENT] != '':
                        cmtstr = strops.truncpad(
                                 '[' + r[COL_COMMENT].strip() + ']', 38, 'r')
                    self.meet.announce.postxt(3,0,'        Front Straight')
                    self.meet.announce.postxt(4,0,' '.join([placestr, bibstr,
                                                         namestr, clubstr]))
                    self.meet.announce.postxt(5,26,strops.truncpad(tmstr, 12, 'r'))
                    self.meet.announce.postxt(6,0,cmtstr)

            # fill in back straight
            bbib = self.bs.getrider()
            if bbib is not None and bbib != '':
                r = self.getrider(bbib)
                if r is not None:
                    clubstr = r[COL_CLUB][0:4]
                    if r[COL_CLUB] != '':
                        clubstr = '(' + clubstr + ')'
                    namestr = strops.fitname(r[COL_FIRSTNAME],
                                             r[COL_LASTNAME], 24, trunc=True)
                    placestr = '   ' # 3 ch
                    if r[COL_PLACE] != '':
                        placestr = strops.truncpad(r[COL_PLACE] + '.', 3)
                    bibstr = strops.truncpad(r[COL_BIB], 3, 'r')
                    tmstr = ''
                    if r[COL_START] is not None and r[COL_FINISH] is not None:
                        tmstr = (r[COL_FINISH] - r[COL_START]).rawtime(3)
                    cmtstr = ''
                    if r[COL_COMMENT] is not None and r[COL_COMMENT] != '':
                        cmtstr = strops.truncpad(
                                 '[' + r[COL_COMMENT].strip() + ']', 38, 'r')
                    self.meet.announce.postxt(3,42,'        Back Straight')
                    self.meet.announce.postxt(4,42,' '.join([placestr, bibstr,
                                                         namestr, clubstr]))
                    self.meet.announce.postxt(5,68,strops.truncpad(tmstr, 12, 'r'))
                    self.meet.announce.postxt(6,42,cmtstr)

            # fill in leaderboard/startlist
            count = 0
            curline = 9
            posoft = 0
            for r in self.riders:
                count += 1
                if count == 19:
                    curline = 9
                    posoft = 42

                clubstr = ''
                if r[COL_CLUB] != '':
                    clubstr = ' (' + r[COL_CLUB] + ')'
 
                namestr = strops.truncpad(strops.fitname(r[COL_FIRSTNAME],
                              r[COL_LASTNAME], 20-len(clubstr))+clubstr, 20)
                placestr = '   ' # 3 ch
                if r[COL_PLACE] != '':
                    placestr = strops.truncpad(r[COL_PLACE] + '.', 3)
                bibstr = strops.truncpad(r[COL_BIB], 3, 'r')
                tmstr = '         ' # 9 ch
                if r[COL_START] is not None and r[COL_FINISH] is not None:
                    tmstr = strops.truncpad(
                           (r[COL_FINISH] - r[COL_START]).rawtime(3), 9, 'r')
                self.meet.announce.postxt(curline, posoft, ' '.join([
                      placestr, bibstr, namestr, tmstr]))
                curline += 1

    def shutdown(self, win=None, msg='Exiting'):
        """Terminate race object."""
        self.log.debug('Race Shutdown: ' + msg)
        self.meet.menu_race_properties.set_sensitive(False)
        if not self.readonly:
            self.saveconfig()
        self.meet.edb.editevent(self.event, winopen=False)
        self.winopen = False

    def do_properties(self):
        """Run race properties dialog."""
        b = gtk.Builder()
        b.add_from_file(os.path.join(scbdo.UI_PATH, 'ittt_properties.ui'))
        dlg = b.get_object('properties')
        dlg.set_transient_for(self.meet.window)
        tt = b.get_object('race_score_type')
        if self.timetype == 'dual':
            tt.set_active(0)
        else:
            tt.set_active(1)
        di = b.get_object('race_dist_entry')
        if self.distance is not None:
            di.set_text(str(self.distance))
        else:
            di.set_text('')
        du = b.get_object('race_dist_type')
        if self.units == 'laps':
            du.set_active(1)
        else:
            du.set_active(0)
        chs = b.get_object('race_stchan_combo')
        chs.set_active(self.chan_S)
        cha = b.get_object('race_achan_combo')
        cha.set_active(self.chan_A)
        chb = b.get_object('race_bchan_combo')
        chb.set_active(self.chan_B)
        aa = b.get_object('race_autoarm_toggle')
        aa.set_active(self.autoarm)
        se = b.get_object('race_series_entry')
        se.set_text(self.series)

        response = dlg.run()
        if response == 1:       # id 1 set in glade for "Apply"
            if tt.get_active() == 1:
                self.set_timetype('single')
            else:
                self.set_timetype('dual')
            dval = di.get_text()
            if dval.isdigit():
                self.distance = int(dval)
            if du.get_active() == 0:
                self.units = 'metres'
            else:
                self.units = 'laps'
            self.chan_S = chs.get_active()
            self.chan_A = cha.get_active()
            self.chan_B = chb.get_active()
            self.autoarm = aa.get_active()           

            # update series
            ns = se.get_text()
            if ns != self.series:
                self.series = ns
                self.meet.edb.editevent(self.event, series=ns)

            # add starters
            for s in strops.reformat_biblist(
                 b.get_object('race_starters_entry').get_text()).split():
                self.addrider(s)

            self.log.debug('Edit race properties done.')
            glib.idle_add(self.delayed_announce)
        else:
            self.log.debug('Edit race properties cancelled.')

        # if prefix is empty, grab input focus
        if self.prefix_ent.get_text() == '':
            self.prefix_ent.grab_focus()
        dlg.destroy()

    def result_gen(self):
        """Generator function to export a final result."""
        for r in self.riders:
            bib = r[COL_BIB]
            rank = None
            time = None
            if self.onestart:
                if r[COL_PLACE] != '':
                    if r[COL_PLACE].isdigit():
                        rank = int(r[COL_PLACE])
                    else:
                        rank = r[COL_PLACE]
                if r[COL_FINISH] is not None:
                    time = (r[COL_FINISH]-r[COL_START]).truncate(3)

            yield [bib, rank, time]

    def result_export(self, f):
        """Export results to supplied file handle."""
        cr = csv.writer(f)
        header = ['Event ' + self.evno,
              self.meet.edb.getvalue(self.event, eventdb.COL_PREFIX) + ' '
              + self.meet.edb.getvalue(self.event, eventdb.COL_INFO),
              '',str(self.meet.get_distance(self.distance, self.units)) + 'm']
        nsplits = len(self.splits)
        if nsplits > 0:
            for i in range(0, nsplits+1): # last lap is not saved in splits
                header.append('Lap ' + str(i+1))
        cr.writerow(header)
        for r in self.riders:
            plstr = r[COL_PLACE]
            if plstr != '':
                plstr = "'" + plstr
                if r[COL_PLACE].isdigit():
                    plstr += '.'
            if r[COL_PLACE] != '' or r[COL_COMMENT] != '':
                if r[COL_START] is None:
                    r[COL_START] = tod.tod(0)
                elap = ''
                if r[COL_FINISH] is not None:
                    elap = (r[COL_FINISH]-r[COL_START]).rawtime(3)
                resrow = [plstr,
                          "'" + self.meet.resname(r[COL_BIB], r[COL_FIRSTNAME],
                           r[COL_LASTNAME], r[COL_CLUB]), r[COL_COMMENT],
                          "'" + elap]
                lt = r[COL_START]
                for st in r[COL_SPLITS]:
                    if st is not None:
                        resrow.append("'"
                                 + (st-lt).rawtime(2)) # lap
                        lt = st
                    else:
                        resrow.append('')	# lap
                if lt != r[COL_START] and r[COL_FINISH] is not None:
                    # avoid degenerate split or abort/catch
                    resrow.append("'"
                       + (r[COL_FINISH]-lt).rawtime(2)) # lap
                cr.writerow(resrow)
            else:
                cr.writerow([plstr,
                             "'" + self.meet.resname(r[COL_BIB],
                              r[COL_FIRSTNAME], r[COL_LASTNAME], r[COL_CLUB]),
                             '[ns]',
                             ''])

    def editent_cb(self, entry, col):
        """Shared event entry update callback."""
        if col == eventdb.COL_PREFIX:
            self.meet.edb.editevent(self.event, prefix=entry.get_text())
        elif col == eventdb.COL_INFO:
            self.meet.edb.editevent(self.event, info=entry.get_text())
        self.update_expander_lbl_cb()

    def update_expander_lbl_cb(self):
        """Update race info expander label."""
        self.info_expand.set_label('Race Info : '
                    + self.meet.racenamecat(self.event, 64))

    def clear_rank(self, cb):
        """Run callback once in main loop idle handler."""
        cb('')
        return False

    def lap_trig(self, sp, t):
        """Register lap trigger."""
        rank = self.insert_split(sp.lap, t-self.curstart, sp.getrider())
        prev = None
        if sp.lap > 0:
            prev = sp.splits[sp.lap-1]
        self.log_lap(sp.getrider(), sp.lap+1, self.curstart, t, prev)
        sp.intermed(t)
        if self.difftime:
            if self.diffstart is None or self.difflane is sp:
                self.diffstart = t
                self.difflane = sp
            else:
                so = self.t_other(sp)
                if so.lap == sp.lap and self.diffstart is not None:
                    dt = t - self.diffstart
                    if dt < 1:
                        sp.difftime(dt)
                    self.difflane = None
                    self.diffstart = None
        if self.timerwin and type(self.meet.scbwin) is scbwin.scbtt:
            lapstr = strops.num2ord(str(rank + 1)) + ' on lap ' + str(sp.lap)
            if sp is self.fs:
                self.meet.scbwin.setr1('(' + str(rank + 1) + ')')
                glib.timeout_add_seconds(4, self.clear_rank,
                                            self.meet.scbwin.setr1)
                # announce lap and rank to uSCBsrv
                self.meet.announce.postxt(5, 8, strops.truncpad(lapstr,17)
                                          + ' ' + self.fs.ck.get_text())
            else:
                self.meet.scbwin.setr2('(' + str(rank + 1) + ')')
                glib.timeout_add_seconds(4, self.clear_rank,
                                            self.meet.scbwin.setr2)
                self.meet.announce.postxt(5, 50, strops.truncpad(lapstr,17)
                                          + ' ' + self.bs.ck.get_text())

    def fin_trig(self, sp, t):
        """Register finish trigger."""
        sp.finish(t)
        ri = self.getiter(sp.getrider())
        self.riders.set_value(ri, COL_LANE, self.lanestr(sp))
        self.settimes(ri, self.curstart, t, sp.splits)
        prev = None
        if sp.lap > 0:
            prev = sp.getsplit(sp.lap - 1)
        self.log_elapsed(sp.getrider(), self.curstart, t, sp.lap+1, prev)
        if self.timerwin and type(self.meet.scbwin) is scbwin.scbtt:
            place = self.riders.get_value(ri, COL_PLACE)
            if sp is self.fs:
                self.meet.scbwin.setr1('(' + place + ')')
                self.meet.scbwin.sett1(self.fs.ck.get_text())
                if self.timetype == 'single': # TTB is hack mode
                    glib.timeout_add_seconds(2, self.clear_200_ttb,
                                                 self.meet.scbwin)
            else:
                self.meet.scbwin.setr2('(' + place + ')')
                self.meet.scbwin.sett2(self.bs.ck.get_text())
        # call for a delayed announce...
        glib.idle_add(self.delayed_announce)

    def timeout(self):
        """Update scoreboard and respond to timing events."""
        if not self.winopen:
            return False
        e = self.meet.timer.response()
        while e is not None:
            chan = e.chan[0:2]
            if self.timerstat == 'armstart':
                if chan == 'C' + str(self.chan_S):
                    self.torunning(e)
            elif self.timerstat == 'running':
                if chan == 'C' + str(self.chan_A):
                    stat = self.fs.getstatus()
                    if stat == 'armint':
                        self.lap_trig(self.fs, e)
                    elif stat == 'armfin':
                        self.fin_trig(self.fs, e)
                elif chan == 'C' + str(self.chan_B):
                    stat = self.bs.getstatus()
                    if stat == 'armint':
                        self.lap_trig(self.bs, e)
                    elif stat == 'armfin':
                        self.fin_trig(self.bs, e)
            e = self.meet.timer.response()
        now = tod.tod('now')
        if self.fs.status in ['running', 'armint', 'armfin']:
            self.fs.runtime(now - self.lstart)
            if self.timerwin and type(self.meet.scbwin) is scbwin.scbtt:
                self.meet.scbwin.sett1(self.fs.ck.get_text())
        if self.bs.status in ['running', 'armint', 'armfin']:
            self.bs.runtime(now - self.lstart)
            if self.timerwin and type(self.meet.scbwin) is scbwin.scbtt:
                self.meet.scbwin.sett2(self.bs.ck.get_text())
        return True

    def show_200_ttb(self, scb):
        """Display time to beat."""
        if len(self.results) > 0:
            scb.setr2('Fastest:')
            scb.sett2(self.results[0].timestr(3))
        return False

    def clear_200_ttb(self, scb):
        """Clear time to beat."""
        scb.setr2('')
        scb.sett2('')
        return False

    def torunning(self, st, lst=None):
        """Set timer running."""
        if self.fs.status == 'armstart':
            self.fs.start(st)
        if self.bs.status == 'armstart':
            self.bs.start(st)
        self.curstart = st
        if lst is None:
            lst = tod.tod('now')
        self.lstart = lst
        self.diffstart = None
        self.difflane = None
        self.timerstat = 'running'
        self.onestart = True
        if self.timetype == 'single':
            if self.autoarm:
                self.armfinish(self.fs, self.chan_A)
            if self.timerwin and type(self.meet.scbwin) is scbwin.scbtt:
                glib.timeout_add_seconds(3, self.show_200_ttb,
                        self.meet.scbwin)

    def clearplaces(self):
        """Clear rider places."""
        for r in self.riders:
            r[COL_PLACE] = ''

    def getrider(self, bib):
        """Return temporary reference to model row."""
        ret = None
        for r in self.riders:
            if r[COL_BIB] == bib:
                ret = r
                break
        return ret

    def addrider(self, bib=''):
        """Add specified rider to race model."""
        nr=[bib, '', '', '', '', '', '', None, None, None]
        if bib == '' or self.getrider(bib) is None:
            dbr = self.meet.rdb.getrider(bib, self.series)
            if dbr is not None:
                for i in range(1,4):
                    nr[i] = self.meet.rdb.getvalue(dbr, i)
            return self.riders.append(nr)
        else:
            return None

    def editcol_cb(self, cell, path, new_text, col):
        """Update value in edited cell."""
        new_text = new_text.strip()
        if col == COL_BIB:
            if new_text.isalnum():
                if self.getrider(new_text) is None:
                    self.riders[path][COL_BIB] = new_text
                    dbr = self.meet.rdb.getrider(new_text, self.series)
                    if dbr is not None:
                        for i in range(1,4):
                            self.riders[path][i] = self.meet.rdb.getvalue(
                                                                    dbr, i)
        else:
            self.riders[path][col] = new_text.strip()

    def placexfer(self):
        """Transfer places into model."""
        self.clearplaces()
        count = 0
        place = 1
        lt = None
        for t in self.results:
            if lt is not None:
                if lt != t:
                    place = count + 1
                if t > tod.FAKETIMES['max']:
                    place = 'dnf'
            i = self.getiter(t.refid)
            self.riders.set_value(i, COL_PLACE, str(place))
            self.riders.swap(self.riders.get_iter(count), i)
            count += 1
            lt = t
            
    def getiter(self, bib):
        """Return temporary iterator to model row."""
        i = self.riders.get_iter_first()
        while i is not None:
            if self.riders.get_value(i, COL_BIB) == bib:
                break
            i = self.riders.iter_next(i)
        return i

    def settimes(self, iter, st=None, ft=None, splits=None,
                             doplaces=True, comment=None):
        """Transfer race times into rider model."""
        bib = self.riders.get_value(iter, COL_BIB)
        # clear result for this bib
        self.results.remove(bib)
        # assign tods
        self.riders.set_value(iter, COL_START, st)
        self.riders.set_value(iter, COL_FINISH, ft)
        # save result
        if st is None:
            st = tod.tod(0)
        if ft is not None:
            self.results.insert(ft-st, bib)
        else:	# DNF/Catch/etc
            self.results.insert(comment, bib)
        # clear any stale splits
        for sl in self.splits:		# for each split, remove this bib
            if sl is not None:
                sl.remove(bib)
        # transfer splits
        sl = []
        if splits is not None:
            i = 0
            for s in splits:
                if not len(self.splits) > i:
                    self.splits.append(tod.todlist(str(i)))
                sl.append(s)
                if s is not None:
                    self.splits[i].insert(s-st, bib)
                i += 1
        # save split tod list into rider
        self.riders.set_value(iter, COL_SPLITS, sl)
        # copy annotation into model if provided, or clear
        if comment:
            self.riders.set_value(iter, COL_COMMENT, comment)
        else:
            self.riders.set_value(iter, COL_COMMENT, '')
        # if reqd, do places
        if doplaces:
            self.placexfer()

    def insert_split(self, i, st, bib):
        """Insert rider split into correct lap."""
        if not len(self.splits) > i:
            self.splits.append(tod.todlist(str(i)))
        self.splits[i].insert(st, bib)
        return self.splits[i].rank(bib)
        
    def armstart(self):
        """Arm timer for start trigger."""
        if self.timerstat == 'armstart':
            self.toload()
        elif self.timerstat in ['load', 'idle']:
            self.toarmstart()

    def armlap(self, sp, cid):
        """Arm timer for a lap split."""
        if self.timerstat == 'running':
            if sp.getstatus() == 'running':
                sp.toarmint()
                self.meet.timer.arm(cid)
            elif sp.getstatus() == 'armint':
                sp.torunning()
                self.meet.timer.dearm(cid)

    def lanestr(self, sp):
        """Return f for front and b for back straight."""
        ret = 'f'
        if sp is self.bs:
            ret = 'b'
        return ret
        
    def abortrider(self, sp):
        """Abort the selected lane."""
        if sp.getstatus() not in ['idle', 'finish']:
            bib = sp.getrider()
            ri = self.getiter(bib)
            if ri is not None:
                self.riders.set_value(ri, COL_LANE, self.lanestr(sp))
                self.settimes(ri, st=self.curstart, splits=sp.splits,
                                  comment='abort')
            sp.tofinish()
            self.meet.timer_log_msg(bib, '- Abort -')
            # update main state? No, leave run... for unabort
            #if self.t_other(sp).getstatus() in ['idle', 'finish']:
                 #self.toidle() -> to finished
            glib.idle_add(self.delayed_announce)

    def catchrider(self, sp):
        """Selected lane has caught other rider."""
        if self.timetype != 'single':
            op = self.t_other(sp)
            if op.getstatus() not in ['idle', 'finish']:
                bib = op.getrider()
                ri = self.getiter(bib)
                if ri is not None:
                    self.riders.set_value(ri, COL_LANE, self.lanestr(op))
                    self.settimes(ri, st=self.curstart,
                                      splits=op.splits, comment='caught')
                op.tofinish()
                self.meet.timer_log_msg(bib, '- Caught -')
                if self.timerwin and type(self.meet.scbwin) is scbwin.scbtt:
                    if op is self.fs:
                        self.meet.scbwin.sett1(' [caught]     ')
                    else:
                        self.meet.scbwin.sett2(' [caught]     ')
            if sp.getstatus() not in ['idle', 'finish']:
                bib = sp.getrider()
                ri = self.getiter(bib)
                if ri is not None:
                    self.settimes(ri, st=self.curstart,
                                      splits=sp.splits, comment='catch')
                self.meet.timer_log_msg(bib, '- Catch -')
                # but continue by default - manual abort to override.
            glib.idle_add(self.delayed_announce)
        else:
            self.log.warn('Unable to catch with single rider.')

    def falsestart(self):
        """Register false start."""
        if self.timerstat == 'running':
            if self.fs.getstatus() not in ['idle', 'finish']:
                self.fs.toload()
                self.meet.timer_log_msg(self.fs.getrider(),
                                        '- False start -')
                if self.timerwin and type(self.meet.scbwin) is scbwin.scbtt:
                    self.meet.scbwin.setr1('False')
                    self.meet.scbwin.sett1('Start')
            if self.bs.getstatus() not in ['idle', 'finish']:
                self.bs.toload()
                self.meet.timer_log_msg(self.bs.getrider(),
                                        '- False start -')
                if self.timerwin and type(self.meet.scbwin) is scbwin.scbtt:
                    self.meet.scbwin.setr2('False')
                    self.meet.scbwin.sett2('Start')
            self.toidle(idletimers=False)
        elif self.timerstat == 'armstart':
            if self.timerwin and type(self.meet.scbwin) is scbwin.scbtt:
                self.meet.scbwin.sett1('            ')
                self.meet.scbwin.sett2('            ')
            self.toload()

    def armfinish(self, sp, cid):
        """Arm timer for finish trigger."""
        if self.timerstat == 'running':
            if sp.getstatus() in ['running', 'finish']:
                if sp.getstatus() == 'finish':
                     self.meet.timer_log_msg(sp.getrider(),
                                             '- False finish -')
                     self.meet.scbwin.setr1('')
                     self.meet.scbwin.setr2('')
                sp.toarmfin()
                self.meet.timer.arm(cid)
            elif sp.getstatus() == 'armfin':
                sp.torunning()
                self.meet.timer.dearm(cid)

    def toload(self):
        """Set timer status to load."""
        if self.fs.status == 'armstart':
            self.fs.toload()
        if self.bs.status == 'armstart':
            self.bs.toload()
        self.toidle(idletimers=False)

    def fmtridername(self, tp):
        """Prepare rider name for display on scoreboard."""
        bib = tp.getrider().strip()
        if bib != '':
            name = '[New Rider]'
            r = self.getrider(bib)
            if r is not None and r[COL_BIB] != '':
                name = strops.fitname(r[COL_FIRSTNAME], r[COL_LASTNAME],
                                      SCB_NAME_WIDTH)
            return ' '.join([strops.truncpad(r[COL_BIB], 3, 'r'),
                             strops.truncpad(name, SCB_NAME_WIDTH),
                             strops.truncpad(r[COL_CLUB], 3, 'r')])
        else:
            return ''
        
    def showtimerwin(self):
        """Show timer window on scoreboard."""
        self.meet.scbwin = None
        self.meet.scbwin = scbwin.scbtt(self.meet.scb,
                                self.meet.racenamecat(self.event),
                                self.fmtridername(self.fs),
                                self.fmtridername(self.bs))
        self.timerwin = True
        self.meet.scbwin.reset()

    def toarmstart(self):
        """Set timer to arm start."""
        doarm = False
        if self.fs.status == 'load':
            self.fs.toarmstart()
            doarm = True
        if self.bs.status == 'load' and self.timetype != 'single':
            self.bs.toarmstart()
            doarm = True
        if doarm:
            self.timerstat = 'armstart'
            self.curstart = None
            self.lstart = None
            self.meet.timer.arm(self.chan_S)
            self.showtimerwin()
            self.meet.printimp(True)
            if self.fs.status == 'armstart':
                self.meet.scbwin.sett1('       0.0     ')
            if self.bs.status == 'armstart':
                self.meet.scbwin.sett2('       0.0     ')
            if self.timetype == 'single':
                self.bs.toidle()
                self.bs.disable()
            glib.idle_add(self.delayed_announce)

    def toidle(self, idletimers=True):
        """Set timer to idle state."""
        if idletimers:
            self.fs.toidle()
            self.bs.toidle()
        self.timerstat = 'idle'
        self.meet.printimp(False)
        self.curstart = None
        self.lstart = None
        self.diffstart = None
        for i in range(0,8):
            self.meet.timer.dearm(i)
        if not self.onestart:
            pass
        self.fs.grab_focus()

    def t_other(self, tp=None):
        """Return reference to 'other' timer."""
        if tp is self.fs:
            return self.bs
        else:
            return self.fs

    def lanelookup(self, bib=None):
        """Prepare name string for timer lane."""
        r = self.getrider(bib)
        if r is None:
            return None
            # 'champs' mode -> ignore non-reg'd rider
            #self.addrider(bib)
            #r = self.getrider(bib)
        rtxt = '[New Rider]'
        if r is not None and (r[COL_FIRSTNAME] != ''
                              or r[COL_LASTNAME] != ''):
            rtxt = r[COL_FIRSTNAME] + ' ' + r[COL_LASTNAME]
            if r[3] != '':
                rtxt += '(' + r[3] + ')'
        return rtxt

    def bibent_cb(self, entry, tp):
        """Bib entry callback."""
        bib = entry.get_text().strip()
        if bib != '' and bib.isalnum():
            nstr = self.lanelookup(bib)
            if nstr is not None:
                tp.biblbl.set_text(nstr)
                if tp.status == 'idle':
                    tp.toload()
                if self.timerstat == 'running':
                    tp.start(self.curstart)
                if self.timetype != 'single':
                    self.t_other(tp).grab_focus()
            else:
                self.log.warn('Ignoring non-starter: ' + repr(bib))
                tp.toidle()
        else:
            tp.toidle()
    
    def time_context_menu(self, widget, event, data=None):
        """Popup menu for result list."""
        self.context_menu.popup(None, None, None, event.button,
                                event.time, selpath)

    def treeview_button_press(self, treeview, event):
        """Set callback for mouse press on model view."""
        if event.button == 3:
            pathinfo = treeview.get_path_at_pos(int(event.x), int(event.y))
            if pathinfo is not None:
                path, col, cellx, celly = pathinfo
                treeview.grab_focus()
                treeview.set_cursor(path, col, 0)
                self.context_menu.popup(None, None, None,
                                        event.button, event.time)
                return True
        return False

    def tod_context_clear_activate_cb(self, menuitem, data=None):
        """Clear times for selected rider."""
        sel = self.view.get_selection().get_selected()
        if sel is not None:
            self.settimes(sel[1])
            self.log_clear(self.riders.get_value(sel[1], COL_BIB))
            glib.idle_add(self.delayed_announce)

    def now_button_clicked_cb(self, button, entry=None):
        """Set specified entry to the 'now' time."""
        if entry is not None:
            entry.set_text(tod.tod('now').timestr())

    def tod_context_edit_activate_cb(self, menuitem, data=None):
        """Run edit time dialog."""
        sel = self.view.get_selection().get_selected()
        if sel is not None:
            i = sel[1]	# grab off row iter
            stod = self.riders.get_value(i, COL_START)
            st = ''
            if stod is not None:
                st = stod.timestr()
            ftod = self.riders.get_value(i, COL_FINISH)
            ft = ''
            if ftod is not None:
                ft = ftod.timestr()
            (ret, st, ft) = uiutil.edit_times_dlg(self.meet.window,st,ft)
            if ret == 1:
                stod = tod.str2tod(st)
                ftod = tod.str2tod(ft)
                bib = self.riders.get_value(i, COL_BIB)
                if stod is not None and ftod is not None:
                    self.settimes(i, stod, ftod)	# set times
                    self.log_elapsed(bib, stod, ftod, manual=True)
                else:
                    self.settimes(i)			# clear times
                    self.log_clear(bib)
                self.log.info('Race times manually adjusted for no. %s', bib)
            else:
                self.log.info('Edit race times cancelled.')
            glib.idle_add(self.delayed_announce)

    def tod_context_del_activate_cb(self, menuitem, data=None):
        """Delete selected row from race model."""
        sel = self.view.get_selection().get_selected()
        if sel is not None:
            i = sel[1]	# grab off row iter
            if self.riders.remove(i):
                pass	# re-select?
            glib.idle_add(self.delayed_announce)

    def log_clear(self, bib):
        """Print clear time log."""
        self.meet.timer_log_msg(bib, '- Time Cleared -')

    def log_lap(self, bib, lap, start, split, prev=None):
        """Print lap split log."""
        if prev is None:
            prev = start
        self.meet.timer_log_straight(bib, str(lap), split-prev, 3)
        if lap > 1 and prev != start:
            self.meet.timer_log_straight(bib, 'time', split - start, 3)
        
    def log_elapsed(self, bib, start, finish,
                          lap=None, prev=None, manual=False):
        """Print elapsed log info."""
        if manual:
            self.meet.timer_log_msg(bib, '- Manual Adjust -')
        if prev is not None and prev != start:
            self.meet.timer_log_straight(bib, str(lap), finish - prev, 3)
        self.meet.timer_log_straight(bib, 'ST', start)
        self.meet.timer_log_straight(bib, 'FIN', finish)
        self.meet.timer_log_straight(bib, 'TIME', finish - start, 3)

    def set_timetype(self, data=None):
        """Update timer panes to match timetype or data if provided."""
        if data is not None:
            self.timetype = strops.confopt_pair(data, 'single', 'dual')
        if self.timetype == 'single':
            self.bs.frame.hide()
            self.bs.hide_laps()
            self.fs.frame.set_label('Timer')
            self.fs.hide_laps()
        else:
            self.bs.frame.show()
            self.bs.show_laps()
            self.fs.frame.set_label('Front Straight')
            self.fs.show_laps()
        self.type_lbl.set_text(self.timetype.capitalize())

    def destroy(self):
        """Signal race shutdown."""
        self.context_menu.destroy()
        self.frame.destroy()

    def show(self):
        """Show race window."""
        self.frame.show()

    def hide(self):
        """Hide race window."""
        self.frame.hide()

    def __init__(self, meet, event, ui=True):
        """Constructor."""
        self.meet = meet
        self.event = event      # Note: now a treerowref
        self.evno = meet.edb.getvalue(event, eventdb.COL_EVNO)
        self.evtype = meet.edb.getvalue(event, eventdb.COL_TYPE)
        self.series = meet.edb.getvalue(event, eventdb.COL_SERIES)
        self.configpath = os.path.join(self.meet.configpath,
                                       'event_' + self.evno)

        self.log = logging.getLogger('scbdo.f200')
        self.log.setLevel(logging.DEBUG)

        # properties
        self.distance = 200
        self.units = 'metres'
        self.autoarm = True

        # race run time attributes
        self.onestart = False
        self.readonly = not ui
        self.winopen = True
        self.timerwin = False
        self.timerstat = 'idle'
        self.curstart = None
        self.lstart = None
        self.results = tod.todlist('FIN')
        self.first100 = tod.todlist('1st')
        self.second100 = tod.todlist('2nd')

        self.riders = gtk.ListStore(gobject.TYPE_STRING,   # 0 bib
                                    gobject.TYPE_STRING,   # 1 first
                                    gobject.TYPE_STRING,   # 2 last
                                    gobject.TYPE_STRING,   # 3 club
                                    gobject.TYPE_STRING,   # 4 Comment
                                    gobject.TYPE_STRING,   # 5 place
                                    gobject.TYPE_PYOBJECT, # 6 Start
                                    gobject.TYPE_PYOBJECT, # 7 100
                                    gobject.TYPE_PYOBJECT) # 8 Finish

        b = gtk.Builder()
        b.add_from_file(os.path.join(scbdo.UI_PATH, 'f200.ui'))

        self.frame = b.get_object('race_vbox')
        self.frame.connect('destroy', self.shutdown)

        # meta info pane
        self.info_expand = b.get_object('info_expand')
        b.get_object('race_info_evno').set_text(self.evno)
        self.showev = b.get_object('race_info_evno_show')
        self.prefix_ent = b.get_object('race_info_prefix')
        self.prefix_ent.connect('changed', self.editent_cb,
                                 eventdb.COL_PREFIX)
        self.prefix_ent.set_text(self.meet.edb.getvalue(
                   self.event, eventdb.COL_PREFIX))
        self.info_ent = b.get_object('race_info_title')
        self.info_ent.connect('changed', self.editent_cb,
                               eventdb.COL_INFO)
        self.info_ent.set_text(self.meet.edb.getvalue(
                   self.event, eventdb.COL_INFO))
        self.type_lbl = b.get_object('race_type')

        # Timer Pane
!!! todo
        mf = b.get_object('race_timer_pane')
        self.fs = timerpane.timerpane('Front Straight')
        self.fs.bibent.connect('activate', self.bibent_cb, self.fs)
        self.bs = timerpane.timerpane('Back Straight')
        self.bs.bibent.connect('activate', self.bibent_cb, self.bs)
        mf.pack_start(self.fs.frame)
        mf.pack_start(self.bs.frame)
        mf.set_focus_chain([self.fs.frame, self.bs.frame, self.fs.frame])

        # Result Pane
        t = gtk.TreeView(self.riders)
        self.view = t
        t.set_reorderable(True)
        t.set_rules_hint(True)
        t.connect('button_press_event', self.treeview_button_press)
     
        # TODO: show team name & club but pop up for rider list
        uiutil.mkviewcoltxt(t, 'No.', COL_BIB, self.editcol_cb, calign=1.0)
        uiutil.mkviewcoltxt(t, 'First Name', COL_FIRSTNAME,
                               self.editcol_cb, expand=True)
        uiutil.mkviewcoltxt(t, 'Last Name', COL_LASTNAME,
                               self.editcol_cb, expand=True)
        uiutil.mkviewcoltxt(t, 'Club', COL_CLUB, self.editcol_cb)
        uiutil.mkviewcoltod(t, 'Time', cb=self.todstr)
        uiutil.mkviewcoltxt(t, 'Rank', COL_PLACE, halign=0.5, calign=0.5)
        t.show()
        b.get_object('race_result_win').add(t)

        # show window
        if ui:
            b.connect_signals(self)
            b = gtk.Builder()
            b.add_from_file(os.path.join(scbdo.UI_PATH, 'tod_context.ui'))
            self.context_menu = b.get_object('tod_context')
            b.connect_signals(self)
            self.meet.menu_race_properties.set_sensitive(True)
            self.meet.edb.editevent(event, winopen=True)
            glib.timeout_add_seconds(3, self.delayed_announce)

