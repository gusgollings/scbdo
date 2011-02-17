
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

"""Generic track race object.

This module  provides an example class 'race' that implements all
required methods of the race interface and demonstrates typical race
data handling patterns. 

The generic 'race' model requires the following interface:

  Constructor:

    racetype(meet, event_h, ui=True/False)

  Shared "Public" Methods:

    race.do_properties()           - display a race property edit dialog
					or Pass
    race.loadconfig()              - read event details off disk
    race.saveconfig()              - save event details to disk
    race.destroy()                 - send destroy signal to event window
    race.show()                    - show event window
    race.hide()                    - hide event window
    race.result_export(f)          - write event results to stream 'f'
    race.addrider(bib)             - add a new starter with given bib
    race.delrider(bib)             - remove starter with given bib
    race.key_event(widget, event)  - race key handler
    race.timeout()                 - race specific update callback

  Shared "Public" attributes:

    race.frame                     - top level race ui widget
    race.winopen                   - BOOL true if ui 'window' open
    race.event                     - Event db handle
    race.onestart                  - BOOL true if one starter/result
 
"""

import gtk
import glib
import gobject
import pango
import decimal
import logging
import ConfigParser
import csv
import os

import scbdo
from scbdo import tod
from scbdo import timy
from scbdo import eventdb
from scbdo import scbwin
from scbdo import uiutil
from scbdo import strops

# race model column constants
COL_BIB = 0
COL_FIRSTNAME = 1
COL_LASTNAME = 2
COL_CLUB = 3
COL_INFO = 4
COL_DNF = 5
COL_PLACE = 6

SCB_RESNAME_WIDTH = scbdo.SCB_LINELEN - 10
SCB_RESULT_FMT = [(2, 'l'), (3, 'r'), ' ',
                  (SCB_RESNAME_WIDTH, 'l'), ' ', (3, 'r')]

SCB_STARTNAME_WIDTH = scbdo.SCB_LINELEN - 9
SCB_STARTERS_FMT = [(3, 'r'), ' ', (SCB_STARTNAME_WIDTH,'l'),
                   ' ', (4,'r')]

# scb function key mappings
key_startlist = 'F3'			# show starters in table
key_results = 'F4'			# recalc/show result window

# timing function key mappings
key_armstart = 'F5'			# arm for start/200m impulse
key_showtimer = 'F6'			# show timer
key_armfinish = 'F9'			# arm for finish impulse

# extended function key mappings
key_abort = 'F5'			# + ctrl for clear/abort
key_falsestart = 'F6'                   # + ctrl for false start

class race(object):
    """Data handling for scratch, handicap, keirin, derby, etc races."""
    def clearplaces(self):
        """Clear places from data model."""
        for r in self.riders:
            r[COL_PLACE] = ''

    def getrider(self, bib):
        """Return temporary reference to model row."""
        ret = None
        for r in self.riders:
            if r[COL_BIB] == bib:
                ret = r		## DANGER- Leaky ref
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

    def addrider(self, bib=''):
        """Add specified rider to race model."""
        nr=[bib, '', '', '', '', False, '']
        if bib == '' or self.getrider(bib) is None:
            dbr = self.meet.rdb.getrider(bib, self.series)
            if dbr is not None:
                for i in range(1,4):
                    nr[i] = self.meet.rdb.getvalue(dbr, i)
            return self.riders.append(nr)
        else:
            return None

    def dnfriders(self, biblist=''):
        """Remove listed bibs from the race."""
        for bib in biblist.split():
            r = self.getrider(bib)
            if r is not None:
                r[COL_DNF] = True
                self.log.info('Rider ' + str(bib) + ' withdrawn')
            else:
                self.log.warn('Did not withdraw no. = ' + str(bib))
        return False

    def delrider(self, bib):
        """Remove the specified rider from the model."""
        i = self.getiter(bib)
        if i is not None:
            self.riders.remove(i)

    def placexfer(self, placestr):
        """Transfer places in placestr to model."""
        self.clearplaces()
        self.results = []
        placeset = set()
        place = 1
        count = 0
        for placegroup in placestr.split():
            for bib in placegroup.split('-'):
                if bib not in placeset:
                    placeset.add(bib)
                    r = self.getrider(bib)
                    if r is not None:
                        r[COL_PLACE] = place
                        self.results.append([str(place), r[COL_BIB],
                           strops.fitname(r[COL_FIRSTNAME],
                           r[COL_LASTNAME], SCB_RESNAME_WIDTH),
                           r[COL_CLUB]])
                        i = self.getiter(bib)
                        self.riders.swap(self.riders.get_iter(count), i)
                        count += 1
                    else:
                        self.log.warn('Ignoring non-starter: ' + repr(bib))
                        # 'champs' mode -> only allow reg'd starters
                        #self.addrider(bib) 
                        #r = self.getrider(bib)
                else:
                    self.log.error('Ignoring duplicate no: ' +repr(bib))
            place = count+1	## FIX FOR incorrect deat heats testit
        if count > 0:
            self.onestart = True

    def loadconfig(self):
        """Load race config from disk."""
        self.riders.clear()
        # set defaults timetype based on event type
        deftimetype = 'start/finish'
        defdistance = ''
        defdistunits = 'laps'
        if self.evtype in ['sprint', 'keirin']:
            deftimetype = '200m'
            defdistunits = 'metres'
            defdistance = '200'
        cr = ConfigParser.ConfigParser({'startlist':'',
                                        'ctrl_places':'',
                                        'start':'',
                                        'lstart':'',
                                        'finish':'',
					'distance':defdistance,
					'distunits':defdistunits,
                                        'topn_places':'0',
                                        'topn_event':'',
                                        'showinfo':'Yes',
                                        'timetype':deftimetype})
        cr.add_section('race')
        cr.add_section('riders')
        if os.path.isfile(self.configpath):
            self.log.debug('Attempting to read race config from path='
                           + repr(self.configpath))
            cr.read(self.configpath)
        for r in cr.get('race', 'startlist').split():
            nr=[r, '', '', '', '', False, '']
            if cr.has_option('riders', r):
                ril = csv.reader([cr.get('riders', r)]).next()
                for i in range(0,6):
                    if len(ril) > i:
                        nr[i+1] = ril[i].strip()
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
            self.riders.append(nr)

        # race infos
        self.set_timetype(cr.get('race', 'timetype'))
        self.distance = strops.confopt_dist(cr.get('race', 'distance'))
        self.units = strops.confopt_distunits(cr.get('race', 'distunits'))
        self.topn_places = strops.confopt_dist(cr.get('race', 'topn_places'), 0)
        self.topn_event = cr.get('race', 'topn_event')
        self.info_expand.set_expanded(strops.confopt_bool(
                                       cr.get('race', 'showinfo')))
        self.set_start(cr.get('race', 'start'), cr.get('race', 'lstart'))
        self.set_finish(cr.get('race', 'finish'))
        self.set_elapsed()
        places = strops.reformat_placelist(cr.get('race', 'ctrl_places'))
        self.ctrl_places.set_text(places)
        self.placexfer(places)
        if places:
            self.setfinished()

    def set_timetype(self, data=None):
        """Update state and ui to match timetype."""
        if data is not None:
            self.timetype = strops.confopt_pair(data, '200m', 'start/finish')
        self.type_lbl.set_text(self.timetype.capitalize())

    def set_start(self, start='', lstart=None):
        """Set the race start."""
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
        if self.start is None:
            pass
        else:
            if self.finish is None:
                self.setrunning()

    def set_finish(self, finish=''):
        """Set the race finish."""
        if type(finish) is tod.tod:
            self.finish = finish
        else:
            self.finish = tod.str2tod(finish)
        if self.finish is None:
            if self.start is not None:
                self.setrunning()
        else:
            if self.start is None:
                self.set_start('0')
            self.setfinished()

    def log_elapsed(self):
        """Log race elapsed time on Timy."""
        self.meet.timer.printline(self.meet.racenamecat(self.event))
        self.meet.timer.printline('      ST: ' + self.start.timestr(4))
        self.meet.timer.printline('     FIN: ' + self.finish.timestr(4))
        self.meet.timer.printline('    TIME: ' + (self.finish - self.start).timestr(3))

    def set_elapsed(self):
        """Update elapsed time in race ui and announcer."""
        if self.start is not None and self.finish is not None:
            et = self.finish - self.start
            self.time_lbl.set_text(et.timestr(3))
        elif self.start is not None:	# Note: uses 'local start' for RT
            self.time_lbl.set_text((tod.tod('now')
                                      - self.lstart).timestr(1))
        elif self.timerstat == 'armstart':
            self.time_lbl.set_text(tod.tod(0).timestr(1))
        else:
            self.time_lbl.set_text('')

    def delayed_announce(self):
        """Initialise the announcer's screen after a delay."""
        if self.winopen:
            self.meet.announce.clrall()
            self.meet.ann_title(' '.join([
                  'Event', self.evno, ':',
                  self.meet.edb.getvalue(self.event, eventdb.COL_PREFIX),
                  self.meet.edb.getvalue(self.event, eventdb.COL_INFO)]))

            # clear page
            self.meet.announce.linefill(1, '_')
            self.meet.announce.linefill(19, '_')

            # write out riders
            count = 0
            curline = 4
            posoft = 0
            for r in self.riders:
                count += 1
                if count == 14:
                    curline = 4
                    posoft = 41
                xtra = '    '
                if r[COL_INFO] is not None and r[COL_INFO] != '':
                    xtra = strops.truncpad(r[COL_INFO], 4, 'r')

                clubstr = ''
                if r[COL_CLUB] != '':
                    clubstr = ' (' + r[COL_CLUB] + ')'
                namestr = strops.truncpad(strops.fitname(r[COL_FIRSTNAME],
                              r[COL_LASTNAME], 25-len(clubstr))+clubstr, 25)

                placestr = '   '
                if r[COL_PLACE] != '':
                    placestr = strops.truncpad(r[COL_PLACE] + '.', 3)
                elif r[COL_DNF]:
                    placestr = 'dnf'
                bibstr = strops.truncpad(r[COL_BIB], 3, 'r')
                self.meet.announce.postxt(curline, posoft, ' '.join([
                      placestr, bibstr, namestr, xtra]))
                curline += 1

            tp = ''
            if self.start is not None and self.finish is not None:
                et = self.finish - self.start
                if self.timetype == '200m':
                    tp = '200m: '
                else:
                    tp = 'Time: '
                tp += et.timestr(3) + '    '
                dist = self.meet.get_distance(self.distance, self.units)
                if dist:
                    tp += 'Avg: ' + et.speedstr(dist)
            self.meet.announce.setline(21, tp)
        return False

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
        if self.start is not None:
            cw.set('race', 'start', self.start.rawtime())
        if self.lstart is not None:
            cw.set('race', 'lstart', self.lstart.rawtime())
        if self.finish is not None:
            cw.set('race', 'finish', self.finish.rawtime())
        cw.set('race', 'ctrl_places', self.ctrl_places.get_text())
        cw.set('race', 'startlist', self.get_startlist())
        if self.info_expand.get_expanded():
            cw.set('race', 'showinfo', 'Yes')
        else:
            cw.set('race', 'showinfo', 'No')
        cw.set('race', 'distance', self.distance)
        cw.set('race', 'distunits', self.units)
        cw.set('race', 'timetype', self.timetype)
        cw.set('race', 'topn_places', self.topn_places)
        cw.set('race', 'topn_event', self.topn_event)

        cw.add_section('riders')
        for r in self.riders:
            bf = ''
            if r[COL_DNF]:
                bf='True'
            slice = [r[COL_FIRSTNAME], r[COL_LASTNAME],
                     r[COL_CLUB], r[COL_INFO], bf, r[COL_PLACE]]
            cw.set('riders', r[COL_BIB], 
                ','.join(map(lambda i: str(i).replace(',', '\\,'), slice)))
        self.log.debug('Saving race config to: ' + self.configpath)
        with open(self.configpath, 'wb') as f:
            cw.write(f)

        # to a topn transfer if flag set - and then clear it
        if self.topn_transfer:
            if self.topn_places > 0:
                evt = self.meet.edb.getevent(self.topn_event)
                if evt is not None:
                    osl = self.meet.edb.getvalue(evt, eventdb.COL_STARTERS)
                    osn = ''
                    for r in self.results:
                        if not r[0].isdigit() or int(r[0]) > self.topn_places:
                            break
                        osn += ' ' + r[1]
                    self.log.info('Transferred riders '
                                + repr(strops.reformat_biblist(osn))
                                + ' to event ' + repr(self.topn_event))
                    self.meet.edb.editevent(evt, starters=osl+osn)
                else:
                    self.log.warn('Riders not transferred, event ' 
                                   + repr(self.topn_event)
                                   + ' not found.')
            self.topn_transfer = False

    def shutdown(self, win=None, msg='Exiting'):
        """Terminate race object."""
        self.log.debug('Race shutdown: ' + msg)
        self.meet.menu_race_properties.set_sensitive(False)
        if not self.readonly:
            self.saveconfig()
        self.meet.edb.editevent(self.event, winopen=False)
        self.winopen = False

    def do_properties(self):
        """Run race properties dialog."""
        b = gtk.Builder()
        b.add_from_file(os.path.join(scbdo.UI_PATH, 'race_properties.ui'))
        dlg = b.get_object('properties')
        dlg.set_transient_for(self.meet.window)
        rt = b.get_object('race_score_type')
        if self.timetype != '200m':
            rt.set_active(0)
        else:
            rt.set_active(1)
        di = b.get_object('race_dist_entry')
        if self.distance is not None:
            di.set_text(str(self.distance))
        else:
            di.set_text('')
        du = b.get_object('race_dist_type')
        if self.units == 'metres':
            du.set_active(0)
        else:
            du.set_active(1)
        se = b.get_object('race_series_entry')
        se.set_text(self.series)
        topn_p = b.get_object('topn_places_adjust')
        topn_p.set_value(self.topn_places)
        topn_e = b.get_object('topn_event')
        topn_e.set_text(self.topn_event)
        response = dlg.run()
        if response == 1:       # id 1 set in glade for "Apply"
            self.log.debug('Updating race properties.')
            if rt.get_active() == 0:
                self.set_timetype('start/finish')
            else:
                self.set_timetype('200m')
            dval = di.get_text()
            if dval.isdigit():
                self.distance = int(dval)
            if du.get_active() == 0:
                self.units = 'metres'
            else:
                self.units = 'laps'

            # update topn transfer
            self.topn_places = int(topn_p.get_value())
            self.topn_event = topn_e.get_text()
            if self.meet.edb.getevent(self.topn_event) is None:
                self.log.warn('Transfer places event '
                               + repr(self.topn_event) + ' not found.')
                # But allow it, since it will be checked again on placexfer

            # update series
            ns = se.get_text()
            if ns != self.series:
                self.series = ns
                self.meet.edb.editevent(self.event, series=ns)

            # xfer starters if not empty
            for s in strops.reformat_biblist(
                 b.get_object('race_starters_entry').get_text()).split():
                self.addrider(s)

            glib.idle_add(self.delayed_announce)
        else:
            self.log.debug('Edit race properties cancelled.')

        # if prefix is empty, grab input focus
        if self.prefix_ent.get_text() == '':
            self.prefix_ent.grab_focus()
        dlg.destroy()

    def resettimer(self):
        """Reset race timer."""
        self.finish = None
        self.start = None
        self.lstart = None
        self.timerstat = 'idle'
        self.ctrl_places.set_text('')
        self.placexfer('')
        self.meet.timer.dearm(0)
        self.meet.timer.dearm(1)
        uiutil.buttonchg(self.stat_but, uiutil.bg_none, 'Idle')
        self.stat_but.set_sensitive(True)
        self.set_elapsed()

    def setrunning(self):
        """Set timer state to 'running'."""
        self.timerstat = 'running'
        uiutil.buttonchg(self.stat_but, uiutil.bg_none, 'Running')

    def setfinished(self):
        """Set timer state to 'finished'."""
        self.timerstat = 'finished'
        uiutil.buttonchg(self.stat_but, uiutil.bg_none, 'Finished')
        self.stat_but.set_sensitive(False)
        self.ctrl_places.grab_focus()

    def armstart(self):
        """Toggle timer arm start state."""
        if self.timerstat == 'idle':
            self.timerstat = 'armstart'
            uiutil.buttonchg(self.stat_but, uiutil.bg_armstart, 'Arm Start')
            self.meet.timer.arm(timy.CHAN_START)
        elif self.timerstat == 'armstart':
            self.timerstat = 'idle'
            self.time_lbl.set_text('')
            uiutil.buttonchg(self.stat_but, uiutil.bg_none, 'Idle')
            self.meet.timer.dearm(timy.CHAN_START)

    def armfinish(self):
        """Toggle timer arm finish state."""
        if self.timerstat == 'running':
            self.timerstat = 'armfinish'
            uiutil.buttonchg(self.stat_but, uiutil.bg_armfin, 'Arm Finish')
            self.meet.timer.arm(timy.CHAN_FINISH)
        elif self.timerstat == 'armfinish':
            self.timerstat = 'running'
            uiutil.buttonchg(self.stat_but, uiutil.bg_none, 'Running')
            self.meet.timer.dearm(timy.CHAN_FINISH)

    def showtimer(self):
        """Display the running time on the scoreboard."""
        if self.timerstat == 'idle':
            self.armstart()
        tp = 'Time:'
        if self.timetype == '200m':
            tp = '200m:'
        self.meet.scbwin = scbwin.scbtimer(self.meet.scb,
                   self.meet.edb.getvalue(self.event, eventdb.COL_PREFIX),
                   self.meet.edb.getvalue(self.event, eventdb.COL_INFO),
                                           tp)
        self.timerwin = True
        self.meet.scbwin.reset()
        if self.timerstat == 'finished':
            self.meet.scbwin.settime(self.time_lbl.get_text())
            dist = self.meet.get_distance(self.distance, self.units)
            if dist:
                self.meet.scbwin.setavg((self.finish
                                         - self.start).speedstr(dist))
            self.meet.scbwin.update()

    def key_event(self, widget, event):
        """Race window key press handler."""
        if event.type == gtk.gdk.KEY_PRESS:
            key = gtk.gdk.keyval_name(event.keyval) or 'None'
            if event.state & gtk.gdk.CONTROL_MASK:
                if key == key_abort:	# override ctrl+f5
                    self.resettimer()
                    return True
            if key[0] == 'F':
                if key == key_armstart:
                    self.armstart()
                    return True
                elif key == key_armfinish:
                    self.armfinish()
                    return True
                elif key == key_showtimer:
                    self.showtimer()
                    return True
                elif key == key_startlist:
                    self.do_startlist()
                    return True
                elif key == key_results:
                    self.do_places()
                    return True
        return False

    def do_places(self):
        """Show race result on scoreboard."""
        self.placexfer(self.ctrl_places.get_text())
        self.meet.scbwin = None
        self.timerwin = False
        ts = None
        tp = 'Time:'
        if self.start is not None and self.finish is None:
            self.finish = tod.tod('now')
            self.set_elapsed()
        if self.timetype == '200m':
            tp = '200m:'
        et = self.time_lbl.get_text()
        if et is not None and et != '':
            ts = et
        self.meet.scbwin = scbwin.scbtable(self.meet.scb,
                              self.meet.racenamecat(self.event),
                              SCB_RESULT_FMT, self.results[0:4],
                              timepfx=tp, timestr=ts,pagesz=5)
        self.meet.scbwin.reset()
        # !! is this a bug? what if there are no places/time yet?
        self.setfinished()

    def do_startlist(self):
        """Show start list on scoreboard."""
        self.meet.scbwin = None
        self.timerwin = False
        startlist = []
        for r in self.riders:
            if not r[5]:
                nfo = r[4]			# Try info field
                if nfo is None or nfo == '':
                    nfo = r[3]			# fall back on club/affil
                startlist.append([r[0], strops.fitname(r[1], r[2],
                                 SCB_STARTNAME_WIDTH), nfo])
        self.meet.scbwin = scbwin.scbtable(self.meet.scb,
                             self.meet.racenamecat(self.event),
                             SCB_STARTERS_FMT, startlist)
        self.meet.scbwin.reset()

    def stat_but_cb(self, button):
        """Race ctrl button callback."""
        if self.timerstat in ('idle', 'armstart'):
            self.armstart()
        elif self.timerstat in ('running', 'armfinish'):
            self.armfinish()

    def race_ctrl_places_activate_cb(self, entry, data=None):
        """Respond to activate on place entry."""
        entry.set_text(strops.reformat_placelist(entry.get_text()))
        self.topn_transfer = True	# flag topn place xfer on save
        self.do_places()
        glib.idle_add(self.delayed_announce)

    def race_ctrl_action_activate_cb(self, entry, data=None):
        """Perform current action on bibs listed."""
        rlist = strops.reformat_biblist(entry.get_text())
        acode = self.action_model.get_value(
                  self.ctrl_action_combo.get_active_iter(), 1)
        if acode == 'dnf':
            self.dnfriders(rlist)
            entry.set_text('')
        elif acode == 'add':
            for bib in rlist.split():
                self.addrider(bib)
            entry.set_text('')
        elif acode == 'del':
            for bib in rlist.split():
                self.delrider(bib)
            entry.set_text('')
        else:
            self.log.error('Ignoring invalid action.')
        glib.idle_add(self.delayed_announce)

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

    def editcol_cb(self, cell, path, new_text, col):
        """Startlist cell update callback."""
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

    def gotorow(self, i=None):
        """Select row for specified iterator."""
        if i is None:
            i = self.riders.get_iter_first()
        if i is not None:
            self.view.scroll_to_cell(self.riders.get_path(i))
            self.view.set_cursor_on_cell(self.riders.get_path(i))

    def dnf_cb(self, cell, path, col):
        """Toggle rider dnf flag."""
        self.riders[path][col] = not self.riders[path][col]

    def starttrig(self, e):
        """React to start trigger."""
        if self.timerstat == 'armstart':
            self.start = e
            self.lstart = tod.tod('now')
            self.setrunning()
            if self.timetype == '200m':
                self.armfinish()

    def fintrig(self, e):
        """React to finish trigger."""
        if self.timerstat == 'armfinish':
            self.finish = e
            self.setfinished()
            self.set_elapsed()
            self.log_elapsed()
            if self.timerwin and type(self.meet.scbwin) is scbwin.scbtimer:
                self.showtimer()
            glib.idle_add(self.delayed_announce)

    def timeout(self):
        """Update scoreboard and respond to timing events."""
        if not self.winopen:
            return False
        e = self.meet.timer.response()
        while e is not None:
            chan = e.chan[0:2]
            if chan == 'C0':
                self.log.debug('Got a start impulse.')
                self.starttrig(e)
            elif chan == 'C1':
                self.log.debug('Got a finish impulse.')
                self.fintrig(e)
            e = self.meet.timer.response()
        if self.finish is None:
            self.set_elapsed()
            if self.timerwin and type(self.meet.scbwin) is scbwin.scbtimer:
                self.meet.scbwin.settime(self.time_lbl.get_text())
        return True

    def race_info_time_edit_activate_cb(self, button):
        """Display race timing edit dialog."""
        ostx = ''
        oftx = ''
        if self.start is not None:
            ostx =  self.start.rawtime(4)
        if self.finish is not None:
            oftx = self.finish.rawtime(4)
        (ret, stxt, ftxt) = uiutil.edit_times_dlg(self.meet.window,
                                ostx, oftx)
        if ret == 1:
            try:
                stod = None
                if stxt:
                    stod = tod.tod(stxt, 'MANU', 'C0i')
                    self.meet.timer.printline(' ' + str(stod))
                ftod = None
                if ftxt:
                    ftod = tod.tod(ftxt, 'MANU', 'C1i')
                    self.meet.timer.printline(' ' + str(ftod))
                self.set_start(stod)
                self.set_finish(ftod)
                self.set_elapsed()
                if self.start is not None and self.finish is not None:
                    self.log_elapsed()
                self.log.info('Updated race times.')
            except (decimal.InvalidOperation, ValueError), v:
                self.log.error('Error updating times: ' + str(v))

            glib.idle_add(self.delayed_announce)
        else:
            self.log.info('Edit race times cancelled.')

    def result_gen(self):
        """Generator function to export a final result."""
        for r in self.riders:
            bib = r[COL_BIB]
            rank = None
            if self.onestart:
                if not r[COL_DNF]:
                    if r[COL_PLACE] is not None and r[COL_PLACE] != '':
                        rank = int(r[COL_PLACE])
                else:
                    rank = 'dnf'    # only handle did not finish for now
            time = None
            yield [bib, rank, time]

    def result_export(self, f):
        """Export results to supplied file handle."""
        cr = csv.writer(f)
        df = ''
        dist = self.meet.get_distance(self.distance, self.units)
        if dist:
            df = str(dist) + 'm'
        cr.writerow(['Event ' + self.evno,
                     ' '.join([
                       self.meet.edb.getvalue(self.event, eventdb.COL_PREFIX),
                       self.meet.edb.getvalue(self.event, eventdb.COL_INFO)
                              ]).strip(),
                     '',
                     df])
        if self.timerstat != 'finished':
            # emit a start list -> tempo!
            for r in self.riders:
                inf = r[COL_INFO].strip()
                if inf != '':
                    inf = "'" + inf
                cr.writerow(['',
                        "'" + self.meet.resname(r[COL_BIB],
                    r[COL_FIRSTNAME], r[COL_LASTNAME], r[COL_CLUB]), inf])
        else:
            first = True
            fs = ''
            if self.finish is not None:
                fs = "'" + self.time_lbl.get_text().strip()
            for r in self.riders:
                inf = r[COL_INFO].strip()
                if inf != '':
                    inf = "'" + inf
                if not r[COL_DNF] and r[COL_PLACE] != '':
                    plstr = ''
                    if self.onestart and r[COL_PLACE] != '':
                        plstr = "'" + r[COL_PLACE] + '.'
  
                    if not first:
                        cr.writerow([plstr,
                            "'" + self.meet.resname(r[COL_BIB],
                        r[COL_FIRSTNAME], r[COL_LASTNAME], r[COL_CLUB]), inf])
                    else:
                        cr.writerow([plstr,
                         "'" + self.meet.resname(r[COL_BIB], r[COL_FIRSTNAME],
                                      r[COL_LASTNAME], r[COL_CLUB]), inf, fs])
                        first = False
                elif r[COL_DNF]:
                    cr.writerow(["'dnf",
                       "'" + self.meet.resname(r[COL_BIB], r[COL_FIRSTNAME],
                                          r[COL_LASTNAME], r[COL_CLUB]), inf])
            if first:
                if fs != '':
                    cr.writerow(['','[No Places]','',fs])
                else:
                    cr.writerow(['','[No Result]'])

    def destroy(self):
        """Signal race shutdown."""
        self.frame.destroy()

    def show(self):
        """Show race window."""
        self.frame.show()
  
    def hide(self):
        """Hide race window."""
        self.frame.hide()

    def __init__(self, meet, event, ui=True):
        """Constructor.

        Parameters:

            meet -- handle to meet object
            event -- event object handle
            ui -- display user interface?

        """
        self.meet = meet
        self.event = event	# Note: now a treerowref
        self.evno = meet.edb.getvalue(event, eventdb.COL_EVNO)
        self.evtype = meet.edb.getvalue(event, eventdb.COL_TYPE)
        self.series = meet.edb.getvalue(event, eventdb.COL_SERIES)
        self.configpath = meet.event_configfile(self.evno)

        self.log = logging.getLogger('scbdo.race')
        self.log.setLevel(logging.DEBUG)        # config may override?
        self.log.debug('Creating new event: ' + str(self.evno))
        self.results = []

        self.readonly = not ui
        self.onestart = False
        self.start = None
        self.lstart = None
        self.finish = None
        self.winopen = True
        self.timerwin = False
        self.timerstat = 'idle'
        self.distance = None
        self.units = 'laps'
        self.timetype = 'start/finish'
        self.topn_places = 0
        self.topn_event = ''
        self.topn_transfer = False

        self.riders = gtk.ListStore(gobject.TYPE_STRING, # 0 bib
                                    gobject.TYPE_STRING, # 1 first name
                                    gobject.TYPE_STRING, # 2 last name
                                    gobject.TYPE_STRING, # 3 club
                                    gobject.TYPE_STRING, # 4 xtra info
                                    gobject.TYPE_BOOLEAN,# 5 DNF/DNS
                                    gobject.TYPE_STRING) # 6 placing

        b = gtk.Builder()
        b.add_from_file(os.path.join(scbdo.UI_PATH, 'race.ui'))

        self.frame = b.get_object('race_vbox')
        self.frame.connect('destroy', self.shutdown)

        # info pane
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

        self.time_lbl = b.get_object('race_info_time')
        self.time_lbl.modify_font(pango.FontDescription("monospace bold"))
        self.type_lbl = b.get_object('race_type')
        self.type_lbl.set_text(self.meet.edb.getvalue(
                                 self.event, eventdb.COL_TYPE).capitalize())

        # ctrl pane
        self.stat_but = b.get_object('race_ctrl_stat_but')
        self.ctrl_places = b.get_object('race_ctrl_places')
        self.ctrl_action_combo = b.get_object('race_ctrl_action_combo')
        self.ctrl_action = b.get_object('race_ctrl_action')
        self.action_model = b.get_object('race_action_model')

        # riders pane
        t = gtk.TreeView(self.riders)
        self.view = t
        t.set_reorderable(True)
        t.set_enable_search(False)
        t.set_rules_hint(True)

        # riders columns
        uiutil.mkviewcoltxt(t, 'No.', COL_BIB, self.editcol_cb, calign=1.0)
        uiutil.mkviewcoltxt(t, 'First Name', COL_FIRSTNAME,
                               self.editcol_cb, expand=True)
        uiutil.mkviewcoltxt(t, 'Last Name', COL_LASTNAME,
                               self.editcol_cb, expand=True)
        uiutil.mkviewcoltxt(t, 'Club', COL_CLUB, self.editcol_cb)
        uiutil.mkviewcoltxt(t, 'Info', COL_INFO, self.editcol_cb)
        uiutil.mkviewcolbool(t, 'DNF', COL_DNF, self.dnf_cb)
        uiutil.mkviewcoltxt(t, 'Place', COL_PLACE, self.editcol_cb,
                                halign=0.5, calign=0.5)
        t.show()
        b.get_object('race_result_win').add(t)

        # start timer and show window
        if ui:
            # connect signal handlers
            b.connect_signals(self)
            self.meet.menu_race_properties.set_sensitive(True)
            self.meet.edb.editevent(event, winopen=True)
            glib.timeout_add_seconds(3, self.delayed_announce)
