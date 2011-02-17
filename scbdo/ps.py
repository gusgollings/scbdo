
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

"""Point score module.

This module provides a class 'ps' which implements the 'race' interface
and manages data, timing and scoreboard for point score and Madison 
track races.

"""

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
from scbdo import timy
from scbdo import scbwin
from scbdo import tod
from scbdo import uiutil
from scbdo import eventdb
from scbdo import riderdb
from scbdo import strops

# Model columns
SPRINT_COL_ID = 0
SPRINT_COL_LABEL = 1
SPRINT_COL_200 = 2
SPRINT_COL_SPLIT = 3
SPRINT_COL_PLACES = 4
SPRINT_COL_POINTS = 5

RES_COL_BIB = 0
RES_COL_FIRST = 1
RES_COL_LAST = 2
RES_COL_CLUB = 3
RES_COL_INRACE = 4
RES_COL_POINTS = 5
RES_COL_LAPS = 6
RES_COL_TOTAL = 7
RES_COL_PLACE = 8
RES_COL_FINAL = 9
RES_COL_INFO = 10
RES_COL_STPTS = 11

# scb consts
SCB_INTSPRINT_NW = scbdo.SCB_LINELEN - 8
SCB_INTSPRINT_FMT = [(2, 'l'), (3, 'r'), ' ',
                  (SCB_INTSPRINT_NW, 'l'), ' ', (1, 'r')]
SCB_STARTERS_NW = scbdo.SCB_LINELEN - 9
SCB_STARTERS_FMT = [(3, 'r'), ' ', (SCB_STARTERS_NW,'l'), ' ', (4,'r')]
SCB_RESMADISON_NW = scbdo.SCB_LINELEN - 8
SCB_RESMADISON_FMT = [(2,'r'),' ',(SCB_RESMADISON_NW,'l'),
                      (2,'r'),(3,'r')]
SCB_RESPOINTS_NW = scbdo.SCB_LINELEN - 9
SCB_RESPOINTS_FMT = [(2,'l'),(3,'r'),' ',
                     (SCB_RESPOINTS_NW,'l'),(3,'r')]
SPRINT_PLACE_DELAY = 11		# about 11 seconds seems to work

# scb function key mappings
key_startlist = 'F3'
key_results = 'F4'

# timing function key mappings
key_armstart = 'F5'
key_showtimer = 'F6'
key_armfinish = 'F9'

# extended function key mappings
key_abort = 'F5'
key_falsestart = 'F6'

class ps(object):
    """Data handling for point score and Madison races."""
    def loadconfig(self):
        """Load race config from disk."""
        self.riders.clear()
        self.sprints.clear()
        self.sprintlaps = ''
        self.sperintpoints = {}
        defscoretype = 'points'
        defmasterslaps = 'No'		# for teams omit bibs?
        if self.evtype == 'madison':
            defscoretype = 'madison'
            defmasterslaps = 'No'
        cr = ConfigParser.ConfigParser({'startlist':'',
					'start':'',
                                        'lstart':'',
                                        'finish':'',
                                        'sprintlaps':'',
                                        'distance':'',
                                        'distunits':'laps',
                                        'masterslaps':defmasterslaps,
                                        'showinfo':'Yes',
                                        'scoring':defscoretype})
        cr.add_section('race')
        cr.add_section('sprintplaces')
        cr.add_section('sprintpoints')
        cr.add_section('points')

        if os.path.isfile(self.configpath):
            self.log.debug('Attempting to read points config from path='
                            + repr(self.configpath))
            cr.read(self.configpath)

        for r in cr.get('race', 'startlist').split():
            nr=[r, '', '', '', True, 0, 0, 0, '', -1, '', 0]
            if cr.has_option('points', r):
                ril = csv.reader([cr.get('points', r)]).next()
                for i in range(0,3):
                    if len(ril) > i:
                        nr[i+1] = ril[i].strip()
                if len(ril) >= RES_COL_INRACE:
                    nr[RES_COL_INRACE] = not(
                          ril[RES_COL_INRACE - 1].lower() == 'no')
                if len(ril) >= RES_COL_LAPS:
                    try:
                        nr[RES_COL_LAPS] = int(ril[RES_COL_LAPS - 1])
                    except ValueError:
                        pass
                if len(ril) >= RES_COL_LAPS+1:	# !! indices are confusing
                    nr[RES_COL_INFO] = ril[RES_COL_LAPS]
                if len(ril) >= RES_COL_LAPS+2:	# !! indices are confusing
                    spts = ril[RES_COL_LAPS+1]
                    if spts.isdigit():
                        nr[RES_COL_STPTS] = int(spts)

                # Re-patch names if all null and in dbr
                if (nr[RES_COL_FIRST] == ''
                     and nr[RES_COL_LAST] == ''
                     and nr[RES_COL_CLUB] == ''):
                    dbr = self.meet.rdb.getrider(r, self.series)
                    if dbr is not None:
                        for i in range(1,4):
                            nr[i] = self.meet.rdb.getvalue(dbr, i)
                # rest will be filled in by model
            else:
                dbr = self.meet.rdb.getrider(r, self.series)
                if dbr is not None:
                    for i in range(1,4):
                        nr[i] = self.meet.rdb.getvalue(dbr, i)
            self.riders.append(nr)
        if cr.get('race', 'scoring').lower() == 'madison':
            self.scoring = 'madison'
        else:
            self.scoring = 'points'
        self.type_lbl.set_text(self.scoring.capitalize())

        self.distance = strops.confopt_dist(cr.get('race', 'distance'))
        self.units = strops.confopt_distunits(cr.get('race', 'distunits'))
        self.masterslaps = strops.confopt_bool(cr.get('race', 'masterslaps'))
        self.reset_lappoints()

        self.sprintlaps = strops.reformat_biblist(
                            cr.get('race', 'sprintlaps'))

        # load any special purpose sprint points
        for (sid, spstr) in cr.items('sprintpoints'):
            self.sprintpoints[sid] = spstr	# validation in sprint model

        self.sprint_model_init()

        oft = 0
        for s in self.sprints:
            places = ''
            if cr.has_option('sprintplaces', s[SPRINT_COL_ID]):
                places = strops.reformat_placelist(cr.get('sprintplaces',
                                               s[SPRINT_COL_ID]))
                if len(places) > 0:
                    oft += 1
            s[SPRINT_COL_PLACES] = places
            if cr.has_option('sprintplaces', s[SPRINT_COL_ID] + '_200'):
                s[SPRINT_COL_200] = tod.str2tod(cr.get('sprintplaces',
                                          s[SPRINT_COL_ID] + '_200'))
            if cr.has_option('sprintplaces', s[SPRINT_COL_ID] + '_split'):
                s[SPRINT_COL_SPLIT] = tod.str2tod(cr.get('sprintplaces',
                                          s[SPRINT_COL_ID] + '_split'))
        if oft > 0:
            if oft >= len(self.sprints):
                oft = len(self.sprints) - 1 
            self.ctrl_place_combo.set_active(oft)
            self.onestart = True
        self.recalculate()

        self.info_expand.set_expanded(strops.confopt_bool(
                                       cr.get('race', 'showinfo')))
        self.set_start(cr.get('race', 'start'), cr.get('race', 'lstart'))
        self.set_finish(cr.get('race', 'finish'))
        self.set_elapsed()

    def get_startlist(self):
        """Return a list of bibs in the rider model."""
        ret = []
        for r in self.riders:
            ret.append(r[RES_COL_BIB])
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
        cw.set('race', 'startlist', self.get_startlist())
        if self.info_expand.get_expanded():
            cw.set('race', 'showinfo', 'Yes')
        else:
            cw.set('race', 'showinfo', 'No')
        cw.set('race', 'distance', self.distance)
        cw.set('race', 'distunits', self.units)
        cw.set('race', 'scoring', self.scoring)
        if self.masterslaps:
            cw.set('race', 'masterslaps', 'Yes')
        else:
            cw.set('race', 'masterslaps', 'No')
        cw.set('race', 'sprintlaps', self.sprintlaps)

        cw.add_section('sprintplaces')
        cw.add_section('sprintpoints')
        for s in self.sprints:
            cw.set('sprintplaces', s[SPRINT_COL_ID], s[SPRINT_COL_PLACES])
            if s[SPRINT_COL_200] is not None:
                cw.set('sprintplaces', s[SPRINT_COL_ID] + '_200',
                         s[SPRINT_COL_200].rawtime())
            if s[SPRINT_COL_SPLIT] is not None:
                cw.set('sprintplaces', s[SPRINT_COL_ID] + '_split',
                         s[SPRINT_COL_SPLIT].rawtime())
            if s[SPRINT_COL_POINTS] is not None:
                cw.set('sprintpoints', s[SPRINT_COL_ID], ' '.join(
                         map(str, s[SPRINT_COL_POINTS])))

        cw.add_section('points')
        for r in self.riders:
            bf = 'No'
            if r[RES_COL_INRACE]:
                bf='Yes'
            slice = [r[RES_COL_FIRST], r[RES_COL_LAST], r[RES_COL_CLUB], 
                     bf, str(r[RES_COL_POINTS]), str(r[RES_COL_LAPS]),
                     str(r[RES_COL_INFO]), str(r[RES_COL_STPTS])]
            cw.set('points', r[RES_COL_BIB], 
                ','.join(map(lambda i: str(i).replace(',', '\\,'), slice)))
        self.log.debug('Saving points config to: ' + self.configpath)
        with open(self.configpath, 'wb') as f:
            cw.write(f)

    def result_gen(self):
        """Generator function to export a final result."""
        for r in self.riders:
            bib = r[RES_COL_BIB]
            rank = None
            if self.onestart:
                if r[RES_COL_INRACE]:
                    if r[RES_COL_PLACE] is not None and r[RES_COL_PLACE] != '':
                        rank = int(r[RES_COL_PLACE])
                else:
                    rank = 'dnf'	# ps only handle did not finish
            time = None
            yield [bib, rank, time]

    def result_export(self, f):
        """Export results to supplied file handle."""
        cr = csv.writer(f)
        df = ''
        dist = self.meet.get_distance(self.distance, self.units)
        if dist is not None:
            df = str(dist) + 'm'
        hdr = ['Event ' + self.evno,
               ' '.join([
                  self.meet.edb.getvalue(self.event, eventdb.COL_PREFIX),
                  self.meet.edb.getvalue(self.event, eventdb.COL_INFO)
                        ]).strip(),
               '',
               df,
               'Lap', 'Pts']
        nopts = []
        for s in self.sprints:
            hdr.append("'" + s[SPRINT_COL_ID])
            nopts.append('')
        hdr.append('Fin')
        cr.writerow(hdr)
        fs = ''
        if self.finish is not None:
            fs = self.time_lbl.get_text().strip()
        if True:
            lapup = None
            for r in self.riders:
                infstr = ''
                if r[RES_COL_INFO] is not None and r[RES_COL_INFO] != '':
                    infstr = r[RES_COL_INFO]
                if lapup is None:
                    lapup = r[RES_COL_LAPS]
                else:
                    fs = ''
                lapcnt = 0
                if self.scoring == 'madison':
                    lapcnt = r[RES_COL_LAPS] - lapup
                else:
                    lapcnt = r[RES_COL_LAPS]
                lapstr = ''
                if lapcnt != 0:
                    lapstr = '{0:+}'.format(lapcnt)
                finplace = 'u/p'
                if r[RES_COL_FINAL] >= 0:
                   finplace = str(r[RES_COL_FINAL] + 1)
                plstr = ''
                if self.onestart and r[RES_COL_PLACE] is not None:
                    plstr = "'" + r[RES_COL_PLACE]
                    if r[RES_COL_PLACE].isdigit():
                        plstr += '.'
                ptstr = '-'
                if r[RES_COL_TOTAL] != 0:
                    ptstr = str(r[RES_COL_TOTAL])
                resrow = [plstr, "'" +
                          self.meet.resname(r[RES_COL_BIB], r[RES_COL_FIRST],
                                         r[RES_COL_LAST], r[RES_COL_CLUB]),
                          "'"+infstr, "'" + fs, "'" + lapstr, "'"+ptstr]

                if r[RES_COL_BIB] in self.auxmap:
                    resrow.extend(self.auxmap[r[RES_COL_BIB]])
                else:
                    resrow.extend(nopts)
                resrow.append(finplace)
                cr.writerow(resrow)

    def getrider(self, bib):
        """Return temporary reference to model row."""
        ret = None
        for r in self.riders:
            if r[RES_COL_BIB] == bib:
                ret = r
                break
        return ret

    def getiter(self, bib):
        """Return temporary iterator to model row."""
        i = self.riders.get_iter_first()
        while i is not None:
            if self.riders.get_value(i, RES_COL_BIB) == bib:
                break
            i = self.riders.iter_next(i)
        return i

    def addrider(self, bib=''):
        """Add specified rider to race model."""
        nr = [bib, '', '', '', True, 0, 0, 0, '', -1, '', 0]
        if bib == '' or self.getrider(bib) is None:
            dbr = self.meet.rdb.getrider(bib, self.series)
            if dbr is not None:
                for i in range(1,4):
                    nr[i] = self.meet.rdb.getvalue(dbr, i)
            return self.riders.append(nr)
        else:
            return None

    def delrider(self, bib):
        """Remove the specified rider from the model."""
        i = self.getiter(bib)
        if i is not None:
            self.riders.remove(i)

    def resettimer(self):
        """Reset race timer."""
        self.set_finish()
        self.set_start()
        self.timerstat = 'idle'
        self.meet.timer.dearm(timy.CHAN_START)
        self.meet.timer.dearm(timy.CHAN_FINISH)
        uiutil.buttonchg(self.stat_but, uiutil.bg_none, 'Idle')
        self.stat_but.set_sensitive(True)
        self.set_elapsed()
        
    def armstart(self):
        """Toggle timer arm start state."""
        if self.timerstat == 'idle':
            self.timerstat = 'armstart'
            uiutil.buttonchg(self.stat_but, uiutil.bg_armstart,
                             'Arm Start')
            self.meet.timer.arm(timy.CHAN_START)            
        elif self.timerstat == 'armstart':
            self.timerstat = 'idle'
            uiutil.buttonchg(self.stat_but, uiutil.bg_none, 'Idle') 
            self.meet.timer.dearm(timy.CHAN_START)
            self.curtimerstr = ''
        elif self.timerstat == 'running':
            pass
            # change to arsprintstart	-> TODO
        elif self.timerstat == 'armsprintstart':
            pass
            # change back to running	-> TODO

    def armfinish(self):
        """Toggle timer arm finish state."""
        if self.timerstat in ['running', 'armsprint', 'armsprintstart']:
            self.timerstat = 'armfinish'
            uiutil.buttonchg(self.stat_but, uiutil.bg_armfin, 'Arm Finish')
            self.meet.timer.arm(timy.CHAN_FINISH)
        elif self.timerstat == 'armfinish':
            self.timerstat = 'running'
            uiutil.buttonchg(self.stat_but, uiutil.bg_none, 'Running')
            self.meet.timer.dearm(timy.CHAN_FINISH)

    def do_startlist(self):
        """Show startlist on scoreboard."""
        self.meet.scbwin = None
        self.timerwin = False
        startlist = []
        for r in self.riders:
            if r[RES_COL_INRACE]:
                startlist.append([r[RES_COL_BIB],
                                  strops.fitname(r[RES_COL_FIRST],
                                                 r[RES_COL_LAST],
                                                 SCB_STARTERS_NW),
                                  r[RES_COL_CLUB]])
        self.meet.scbwin = scbwin.scbtable(self.meet.scb,
                                           self.meet.racenamecat(self.event),
                       SCB_STARTERS_FMT, startlist)
        self.meet.scbwin.reset()

    def key_event(self, widget, event):
        """Race window key press handler."""
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

    def delayed_announce(self):
        """Initialise the announcer's screen after a delay."""
        if self.winopen:
            self.meet.announce.clrall()
            self.meet.ann_title(' '.join([
                  self.meet.event_string(self.evno), ':',
                  self.meet.edb.getvalue(self.event, eventdb.COL_PREFIX),
                  self.meet.edb.getvalue(self.event, eventdb.COL_INFO)]))

            self.meet.announce.linefill(1, '-')
            self.meet.announce.linefill(7, '-')

            # fill in a sprint if not empty
            i = self.ctrl_place_combo.get_active_iter()
            if i is not None:
                pl = self.sprints.get_value(i, SPRINT_COL_PLACES)
                if pl is not None and pl != '':
                    sinfo = self.sprints.get_value(i, SPRINT_COL_LABEL)
                    self.meet.announce.setline(2, sinfo + ':')
                    sid = int(self.sprints.get_string_from_iter(i))
                    cnt = 0
                    for r in self.sprintresults[sid]:
                        pstr = ''
                        if r[3] != '':
                            pstr = r[3] + 'pt'
                        self.meet.announce.postxt(3+cnt,0, ' '.join([
                            strops.truncpad(r[0] + '.', 3),
                            strops.truncpad(r[1], 3, 'r'),
                            strops.truncpad(r[2], 20),
                            pstr]))
                        cnt += 1
                        if cnt > 3:	# is this required?
                            break

            tp = ''
            if self.start is not None and self.finish is not None:
                et = self.finish - self.start
                tp = 'Time: ' + et.timestr(3) + '    '
                dist = self.meet.get_distance(self.distance, self.units)
                if dist:
                    tp += 'Avg: ' + et.speedstr(dist)
            self.meet.announce.postxt(3, 40, tp)

            # do result standing
            mscount = len(self.sprints)
            if self.scoring == 'madison':
                rtype = 'Team '
                if self.evtype != 'madison':
                    rtype = 'Rider'
                hdr = '     # ' + rtype + '                   Lap Pt '
                nopts = ''
                scnt = mscount
                for s in self.sprints:
                    scnt -= 1
                    if scnt < 15:
                        hdr += strops.truncpad(s[SPRINT_COL_ID], 4, 'r')
                        nopts += '    '
                hdr += ' Fin'
                self.meet.announce.setline(8, hdr)
                curline = 9
                ldrlap = None
                for r in self.riders:                     
                    if ldrlap is None:
                        ldrlap = r[RES_COL_LAPS]
                    lapdwn = r[RES_COL_LAPS] - ldrlap
                    lapstr = '  '
                    if lapdwn != 0:
                        lapstr = strops.truncpad(str(lapdwn), 2, 'r')
                    
                    psrc = '-'
                    if r[RES_COL_TOTAL] != 0:
                        psrc = str(r[RES_COL_TOTAL])
                    ptstr = strops.truncpad(psrc, 2, 'r')

                    placestr = '   '
                    if self.onestart and r[RES_COL_PLACE] != '':
                        placestr = strops.truncpad(r[RES_COL_PLACE] + '.', 3)
                    elif not r[RES_COL_INRACE]:
                        placestr = 'dnf'

                    spstr = ''
                    if r[RES_COL_BIB] in self.auxmap:
                        scnt = mscount
                        for s in self.auxmap[r[RES_COL_BIB]]:
                            scnt -= 1
                            if scnt < 15:
                                spstr += str(s).rjust(4)
                    else:
                        spstr = nopts

                    finstr = 'u/p'
                    if r[RES_COL_FINAL] >= 0:
                       finstr = strops.truncpad(str(r[RES_COL_FINAL] + 1),
                                                3, 'r')

                    bibstr = strops.truncpad(r[RES_COL_BIB], 2, 'r')

                    clubstr = ''
                    if r[RES_COL_CLUB] != '':
                        clubstr = ' (' + r[RES_COL_CLUB] + ')'
                    namestr = strops.truncpad(strops.fitname(r[RES_COL_FIRST],
                                r[RES_COL_LAST], 24-len(clubstr))+clubstr, 24)

                    self.meet.announce.postxt(curline, 0, ' '.join([
                          placestr, bibstr, namestr, lapstr, ptstr,
                          spstr, finstr]))
                    curline += 1
                
            else:
                # use scratch race style layout for up to 26 riders
                count = 0       
                curline = 9       
                posoft = 0      
                for r in self.riders:                     
                    count += 1
                    if count == 14:
                        curline = 4
                        posoft = 41

                    psrc = '-'
                    if r[RES_COL_TOTAL] != 0:
                        psrc = str(r[RES_COL_TOTAL])

                    ptstr = strops.truncpad(psrc, 3, 'r')
                    clubstr = ''
                    if r[RES_COL_CLUB] != '':
                        clubstr = ' (' + r[RES_COL_CLUB] + ')'
                    namestr = strops.truncpad(strops.fitname(r[RES_COL_FIRST],
                                r[RES_COL_LAST], 27-len(clubstr))+clubstr, 27)
                    placestr = '   '
                    if self.onestart and r[RES_COL_PLACE] != '':
                        placestr = strops.truncpad(r[RES_COL_PLACE] + '.', 3)
                    elif not r[RES_COL_INRACE]:
                        placestr = 'dnf'
                    bibstr = strops.truncpad(r[RES_COL_BIB], 3, 'r')
                    self.meet.announce.postxt(curline, posoft, ' '.join([
                          placestr, bibstr, namestr, ptstr]))
                    curline += 1

                if posoft > 0:
                    self.meet.announce.postxt(8,0,'      # Rider                       Pts        # Rider                       Pts')
                else:
                    self.meet.announce.postxt(8,0,'      # Rider                       Pts')

        return False


    def do_places(self):
        """Show race result on scoreboard."""
        resvec = []
        fmt = ''
        hdr = ''
        if self.scoring == 'madison':
            fmt = SCB_RESMADISON_FMT
            hdr = ' # team           lap pt'
            llap = None
            for r in self.riders:
                if r[RES_COL_INRACE]:
                    if llap is None:
                        llap = r[RES_COL_LAPS]
                    lstr = str(r[RES_COL_LAPS] - llap)
                    if lstr == '0': lstr = ''
                    resvec.append([r[RES_COL_BIB],
                         strops.fitname('',
                            r[RES_COL_LAST].upper(), SCB_RESMADISON_NW),
                         lstr, str(r[RES_COL_TOTAL])])
        else:
            fmt = SCB_RESPOINTS_FMT
            hdr = self.meet.racenamecat(self.event,
                        scbdo.SCB_LINELEN - 3) + ' pt'
            for r in self.riders:
                if r[RES_COL_INRACE]:
                    resvec.append([r[RES_COL_PLACE], r[RES_COL_BIB],
                         strops.fitname(r[RES_COL_FIRST], r[RES_COL_LAST],
                                        SCB_RESPOINTS_NW),
                         str(r[RES_COL_TOTAL])])
            # cols are: rank, bib, name, pts
        self.meet.scbwin = None
        self.timerwin = False
        self.meet.scbwin = scbwin.scbtable(self.meet.scb,
                                           hdr, fmt, resvec, delay=90, pagesz=5)
        self.meet.scbwin.reset()
        return False

    def dnfriders(self, biblist=''):
        """Remove listed bibs from the race."""
        recalc = False
        for bib in biblist.split():
            r = self.getrider(bib)
            if r is not None:
                r[RES_COL_INRACE] = False
                recalc = True
                self.log.info('Rider ' + str(bib) + ' withdrawn')
            else:
                self.log.warn('Did not withdraw no. = ' + str(bib))
        if recalc:
            self.recalculate()
        return False
  
    def announce_packet(self, line, pos, txt):
        self.meet.announce.postxt(line, pos, txt)
        return False

    def gainlap(self, biblist=''):
        """Credit each rider listed in biblist with a lap on the field."""
        recalc = False
        rlines = []
        for bib in biblist.split():
            r = self.getrider(bib)
            if r is not None:
                r[RES_COL_LAPS] += 1
                recalc = True
                self.log.info('Rider ' + str(bib) + ' gain lap')
                rlines.append(' '.join([bib.rjust(3), 
                         strops.truncpad(strops.fitname(r[RES_COL_FIRST],
                                r[RES_COL_LAST], 30), 30)]))
            else:
                self.log.warn('Did not gain lap for no. = ' + str(bib))
        if recalc:
            self.recalculate()
            glib.timeout_add_seconds(2, self.announce_packet,
                                        2, 50, 'Gaining a lap:')
            cnt = 1
            for line in rlines:
                glib.timeout_add_seconds(2, self.announce_packet,
                                        2+cnt, 50, line)
                cnt+=1
                if cnt > 4:
                    break
        return False
        
    def loselap(self, biblist=''):
        """Deduct a lap from each rider listed in biblist."""
        recalc = False
        rlines = []
        for bib in biblist.split():
            r = self.getrider(bib)
            if r is not None:
                r[RES_COL_LAPS] -= 1
                recalc = True
                self.log.info('Rider ' + str(bib) + ' lose lap')
                rlines.append(' '.join([bib.rjust(3), 
                         strops.truncpad(strops.fitname(r[RES_COL_FIRST],
                                r[RES_COL_LAST], 30), 30)]))
            else:
                self.log.warn('Did not lose lap for no. = ' + str(bib))
        if recalc:
            self.recalculate()
            glib.timeout_add_seconds(2, self.announce_packet,
                                        2, 50, 'Losing a lap:')
            cnt = 1
            for line in rlines:
                glib.timeout_add_seconds(2, self.announce_packet,
                                        2+cnt, 50, line)
                cnt+=1
                if cnt > 4:
                    break
        return False
        
    def showtimer(self):
        """Show race timer on scoreboard."""
        tp = 'Time:'
        self.meet.scbwin = scbwin.scbtimer(self.meet.scb,
                    self.meet.edb.getvalue(self.event, eventdb.COL_PREFIX),
                    self.meet.edb.getvalue(self.event, eventdb.COL_INFO),
                               tp)
        self.timerwin = True
        self.meet.scbwin.reset()
        if self.timerstat == 'finished':
            elap = self.finish - self.start
            self.meet.scbwin.settime(elap.timestr(3))
            dist = self.meet.get_distance(self.distance, self.units)
            if dist:
                self.meet.scbwin.setavg(elap.speedstr(dist))
            self.meet.scbwin.update()

    def shutdown(self, win=None, msg='Exiting'):
        """Terminate race object."""
        self.log.debug('Race shutdown: ' + msg)
        self.meet.menu_race_properties.set_sensitive(False)
        if not self.readonly:
            self.saveconfig()
        self.meet.edb.editevent(self.event, winopen=False)
        self.winopen = False

    def starttrig(self, e):
        """React to start trigger."""
        if self.timerstat == 'armstart':
            self.set_start(e, tod.tod('now'))
        elif self.timerstat == 'armsprintstart':
            self.set_sprint_start(e, tod.tod('now'))

    def fintrig(self, e):
        """React to finish trigger."""
        if self.timerstat == 'armfinish':
            self.set_finish(e)
            self.set_elapsed()
            if self.timerwin and type(self.meet.scbwin) is scbwin.scbtimer:
                self.showtimer()
            glib.idle_add(self.delayed_announce)
        elif self.timerstat == 'armsprint':
            self.set_sprint_finish(e)

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
        if self.finish is None and self.start is not None:
            self.set_elapsed()
            if self.timerwin and type(self.meet.scbwin) is scbwin.scbtimer:
                self.meet.scbwin.settime(self.time_lbl.get_text())
        return True

    def do_properties(self):
        """Run race properties dialog."""
        b = gtk.Builder()
        b.add_from_file(os.path.join(scbdo.UI_PATH, 'ps_properties.ui'))
        dlg = b.get_object('properties')
        dlg.set_transient_for(self.meet.window)
        rle = b.get_object('race_laps_entry')
        rle.set_text(self.sprintlaps)
        if self.onestart:
            rle.set_sensitive(False)
        rsb = b.get_object('race_showbib_toggle')
        rsb.set_active(self.masterslaps)
        rt = b.get_object('race_score_type')
        if self.scoring == 'madison':
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

        response = dlg.run()
        if response == 1:       # id 1 set in glade for "Apply"
            self.log.debug('Updating race properties.')
            if not self.onestart:
                newlaps = strops.reformat_biblist(rle.get_text())
                if self.sprintlaps != newlaps:
                    self.sprintlaps = newlaps
                    self.log.info('Reset sprint model.')
                    self.sprint_model_init()
            self.masterslaps = rsb.get_active()
            if rt.get_active() == 0:
                self.scoring = 'madison'
            else:
                self.scoring = 'points'
            self.type_lbl.set_text(self.scoring.capitalize())
            dval = di.get_text()
            if dval.isdigit():
                self.distance = int(dval)
            else:
                self.distance = None
            if du.get_active() == 0:
                self.units = 'metres'
            else:
                self.units = 'laps'

            # update series
            ns = se.get_text()
            if ns != self.series:
                self.series = ns
                self.meet.edb.editevent(self.event, series=ns)

            # add starters
            for s in strops.reformat_biblist(
                 b.get_object('race_starters_entry').get_text()).split():
                self.addrider(s)

            # recalculate
            self.reset_lappoints()
            self.recalculate()
            glib.idle_add(self.delayed_announce)
        else:
            self.log.debug('Edit race properties cancelled.')

        # if prefix is empty, grab input focus
        if self.prefix_ent.get_text() == '':
            self.prefix_ent.grab_focus()
        dlg.destroy()

    ## Race timing manipulations
    def set_start(self, start='', lstart=None):
        """Set the race start time."""
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
            self.start_lbl.set_text('')
        else:
            self.start_lbl.set_text(self.start.timestr(4))
            if self.finish is None:
                self.set_running()

    def set_finish(self, finish=''):
        """Set the race finish time."""
        if type(finish) is tod.tod:
            self.finish = finish
        else:
            self.finish = tod.str2tod(finish)
        if self.finish is None:
            self.finish_lbl.set_text('')
            if self.start is not None:
                self.set_running()
        else:
            if self.start is None:
                self.set_start('0')
            self.finish_lbl.set_text(self.finish.timestr(4))
            self.set_finished()

    def set_elapsed(self):
        """Update elapsed race time."""
        if self.start is not None and self.finish is not None:
            self.time_lbl.set_text((self.finish - self.start).timestr(3))
        elif self.start is not None:    # Note: uses 'local start' for RT
            self.time_lbl.set_text((tod.tod('now') - self.lstart).timestr(1))
        elif self.timerstat == 'armstart':
            self.time_lbl.set_text(tod.tod(0).timestr(1))
        else:
            self.time_lbl.set_text('')

    def log_elapsed(self):
        """Log elapsed time on timy receipt."""
        self.meet.timer.printline(self.meet.racenamecat(self.event))
        self.meet.timer.printline('      ST: ' + self.start_lbl.get_text())
        self.meet.timer.printline('     FIN: ' + self.finish_lbl.get_text())
        self.meet.timer.printline('    TIME: ' + self.time_lbl.get_text())

    ## State manipulation
    def set_running(self):
        """Set timer to running."""
        self.timerstat = 'running'
        uiutil.buttonchg(self.stat_but, uiutil.bg_none, 'Running')

    def set_finished(self):
        """Set timer to finished."""
        self.timerstat = 'finished'
        uiutil.buttonchg(self.stat_but, uiutil.bg_none, 'Finished')
        self.stat_but.set_sensitive(False)
        self.ctrl_places.grab_focus()

    def update_expander_lbl_cb(self):
        """Update the expander label."""
        self.info_expand.set_label('Race Info : '
                    + self.meet.racenamecat(self.event, 64))

    def ps_info_prefix_changed_cb(self, entry, data=None):
        """Update event prefix."""
        self.meet.edb.editevent(self.event, prefix=entry.get_text())
        self.update_expander_lbl_cb()

    def ps_info_title_changed_cb(self, entry, data=None):
        """Update event title."""
        self.meet.edb.editevent(self.event, info=entry.get_text())
        self.update_expander_lbl_cb()

    def ps_info_time_edit_clicked_cb(self, button, data=None):
        """Run the edit times dialog."""
        (ret, stxt, ftxt) = uiutil.edit_times_dlg(self.meet.window,
                                self.start_lbl.get_text(),
                                self.finish_lbl.get_text())
        if ret == 1:       # id 1 set in glade for "Apply"
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
        else:
            self.log.info('Edit race times cancelled.')

    def ps_ctrl_place_combo_changed_cb(self, combo, data=None):
        """Handle sprint combo change."""
        i = self.ctrl_place_combo.get_active_iter()
        if i is not None:
            self.ctrl_places.set_text(self.sprints.get_value(
                         i, SPRINT_COL_PLACES) or '')
        else:
            self.ctrl_places.set_text('')
        self.ctrl_places.grab_focus()

    def ps_ctrl_places_activate_cb(self, entry, data=None):
        """Handle places entry."""
        entry.set_text(strops.reformat_placelist(entry.get_text()))
        i = self.ctrl_place_combo.get_active_iter()
        self.sprints.set_value(i, SPRINT_COL_PLACES, entry.get_text())
        sid = int(self.sprints.get_string_from_iter(i))
        sinfo = self.sprints.get_value(i, SPRINT_COL_LABEL)
        self.recalculate()
        self.meet.scbwin = None
        self.timerwin = False
        self.meet.scbwin = scbwin.scbintsprint(self.meet.scb,
                               self.meet.racenamecat(self.event), sinfo,
                               SCB_INTSPRINT_FMT,
                               self.sprintresults[sid][0:4])
        self.meet.scbwin.reset()
        glib.timeout_add_seconds(SPRINT_PLACE_DELAY, self.do_places)
        glib.timeout_add_seconds(1, self.delayed_announce)

    def ps_ctrl_action_combo_changed_cb(self, combo, data=None):
        """Handle change on action combo."""
        self.ctrl_action.set_text('')
        self.ctrl_action.grab_focus()

    def ps_ctrl_action_activate_cb(self, entry, data=None):
        """Perform current action on bibs listed."""
        rlist = strops.reformat_biblist(entry.get_text())
        acode = self.action_model.get_value(
                  self.ctrl_action_combo.get_active_iter(), 1)
        if acode == 'gain':
            self.gainlap(rlist)
            entry.set_text('')
        elif acode == 'lost':
            self.loselap(rlist)
            entry.set_text('')
        elif acode == 'dnf':
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
        glib.timeout_add_seconds(1, self.delayed_announce)

    def ps_sprint_cr_label_edited_cb(self, cr, path, new_text, data=None):
        """Sprint column edit."""
        self.sprints[path][SPRINT_COL_LABEL] = new_text

    def ps_sprint_cr_places_edited_cb(self, cr, path, new_text, data=None):
        """Sprint place edit."""
        new_text = strops.reformat_placelist(new_text)
        self.sprints[path][SPRINT_COL_PLACES] = new_text
        opath = self.sprints.get_string_from_iter(
                       self.ctrl_place_combo.get_active_iter())
        if opath == path:
            self.ctrl_places.set_text(new_text)
        self.recalculate()

    def ps_result_cr_first_edited_cb(self, cr, path, new_text, data=None):
        self.riders[path][RES_COL_FIRST] = new_text

    def ps_result_cr_last_edited_cb(self, cr, path, new_text, data=None):
        self.riders[path][RES_COL_LAST] = new_text

    def ps_result_cr_club_edited_cb(self, cr, path, new_text, data=None):
        self.riders[path][RES_COL_CLUB] = new_text

    def ps_result_cr_info_edited_cb(self, cr, path, new_text, data=None):
        self.riders[path][RES_COL_INFO] = new_text

    def ps_result_cr_inrace_toggled_cb(self, cr, path, data=None):
        self.riders[path][RES_COL_INRACE] = not(
                     self.riders[path][RES_COL_INRACE])
        self.recalculate()

    def ps_result_cr_laps_edited_cb(self, cr, path, new_text, data=None):
        try:
            laps = int(new_text)
            self.riders[path][RES_COL_LAPS] = laps
            self.recalculate()
        except ValueError:
            self.log.warn('Ignoring non-numeric lap count')

    def zeropoints(self):
        for r in self.riders:
            r[RES_COL_POINTS] = 0
            r[RES_COL_TOTAL] = 0
            r[RES_COL_PLACE] = ''
            r[RES_COL_FINAL] = -1  # Negative => Unplaced in final sprint

    def pointsxfer(self, placestr, final=False, index=0, points=None):
        """Transfer points from sprint placings to aggregate."""
        placeset = set()
        if points is None:
            points = [5, 3, 2, 1]	# Default is four places
        self.sprintresults[index] = []
        place = 0
        count = 0
        for placegroup in placestr.split():
            for bib in placegroup.split('-'):
                if bib not in placeset:
                    placeset.add(bib)
                    r = self.getrider(bib)
                    if r is not None:
                        ptsstr = ''
                        if place < len(points):
                            ptsstr = str(points[place])
                            r[RES_COL_POINTS] += points[place]
                            if bib not in self.auxmap:
                                self.auxmap[bib] = self.nopts[0:]
                            self.auxmap[bib][index] = str(points[place])
                        if final:
                            r[RES_COL_FINAL] = place
                        self.sprintresults[index].append([str(place + 1),
                               r[RES_COL_BIB],
                               strops.fitname(r[RES_COL_FIRST],
                                         r[RES_COL_LAST], SCB_INTSPRINT_NW),
                                                         ptsstr])
                        count += 1
                    else:
                        self.log.warn('Ignoring non-starter: ' + repr(bib))
                        # 'champs' mode -> only allow reg'd starters
                        #self.addrider(bib)
                        #r = self.getrider(bib)
                else:
                    self.log.error('Ignoring duplicate no: ' +repr(bib))
            place = count
        if count > 0:
            self.onestart = True
    
    def retotal(self, r):
        """Update totals."""
        if self.scoring == 'madison':
            r[RES_COL_TOTAL] = r[RES_COL_STPTS] + r[RES_COL_POINTS]
        else:
            r[RES_COL_TOTAL] = r[RES_COL_STPTS] + r[RES_COL_POINTS] + (self.lappoints
                                  * r[RES_COL_LAPS])

    # Sorting performed in-place on aux table with cols:
    #  0 INDEX		Index in main model
    #  1 BIB		Rider's bib
    #  2 INRACE		Bool rider still in race?
    #  3 LAPS		Rider's laps up/down
    #  4 TOTAL		Total points scored
    #  5 FINAL		Rider's place in final sprint (-1 for unplaced)

    # Point score sorting:
    # inrace / points / final sprint
    def sortpoints(self, x, y):
        if x[2] != y[2]:	# compare inrace
            if x[2]:
                return -1
            else:
                return 1
        else:			# defer to points
            return self.sortpointsonly(x, y)
                        
    def sortpointsonly(self, x, y):
        if x[4] > y[4]:
            return -1
        elif x[4] < y[4]:
            return 1
        else:		# defer to last sprint
            if x[5] == y[5]:
                #self.log.warn('Sort could not split riders.')
                return 0	# places same - or both unplaced
            else:
                xp = x[5]
                if xp < 0: xp = 9999
                yp = y[5]
                if yp < 0: yp = 9999
                return cmp(xp, yp)
        self.log.error('Sort comparison did not match any paths.')

    # Madison score sorting:
    # inrace / laps / points / final sprint
    def sortmadison(self, x, y):
        if x[2] != y[2]:	# compare inrace
            if x[2]:
                return -1
            else:
                return 1
        else:			# defer to distance (laps)
            if x[3] > y[3]:
                return -1
            elif x[3] < y[3]:
                return 1
            else:		# defer to points / final sprint
                return self.sortpointsonly(x, y)

    # result recalculation
    def recalculate(self):
        self.zeropoints()
        self.auxmap = {}
        idx = 0
        for s in self.sprints:
            self.pointsxfer(s[SPRINT_COL_PLACES],
                            s[SPRINT_COL_ID] == '0', idx, s[SPRINT_COL_POINTS])
            idx += 1

        if len(self.riders) == 0:
            return

        auxtbl = []
        idx = 0
        for r in self.riders:
            self.retotal(r)
            auxtbl.append([idx, r[RES_COL_BIB], r[RES_COL_INRACE],
                           r[RES_COL_LAPS], r[RES_COL_TOTAL],
                           r[RES_COL_FINAL] ])
            idx += 1
        if self.scoring == 'madison':
            auxtbl.sort(self.sortmadison)
        else:
            auxtbl.sort(self.sortpoints)
        self.riders.reorder([a[0] for a in auxtbl])
        place = 0
        idx = 0
        for r in self.riders:
            if r[RES_COL_INRACE]:
                if idx == 0:
                    place = 1
                else:
                    if self.scoring == 'madison':
                        if self.sortmadison(auxtbl[idx - 1], auxtbl[idx]) != 0:
                            place = idx + 1
                    else:
                        if self.sortpoints(auxtbl[idx - 1], auxtbl[idx]) != 0:
                            place = idx + 1
                r[RES_COL_PLACE] = str(place)
                idx += 1
            else:
                r[RES_COL_PLACE] = 'dnf'

    def sprint_model_init(self):
        """Initialise the sprint places model."""
        self.ctrl_place_combo.set_active(-1)
        self.ctrl_places.set_sensitive(False)
        self.sprints.clear()
        self.auxmap = {}
        self.nopts = []
        isone = False
        self.sprintresults = []
        for sl in self.sprintlaps.split():
            isone = True
            lt = sl
            if sl.isdigit():
                if int(sl) == 0:
                    lt = 'Final sprint'
                else:
                    lt = 'Sprint at ' + sl + ' to go'
            sp = None
            if sl in self.sprintpoints:
                nextp = []
                for nv in self.sprintpoints[sl].split():
                    if nv.isdigit():
                        nextp.append(int(nv))
                    else:
                        nextp = None
                        break
                sp = nextp
            nr = [sl, lt, None, None, '', sp]
            self.sprints.append(nr)
            self.sprintresults.append([])
            self.nopts.append('')
        if isone:
            self.ctrl_place_combo.set_active(0)
            self.ctrl_places.set_sensitive(True)

    def todstr(self, col, cr, model, iter, data=None):
        """Format tod into text for listview."""
        st = model.get_value(iter, SPRINT_COL_200)
        ft = model.get_value(iter, SPRINT_COL_SPLIT)
        if st is not None and ft is not None:
            cr.set_property('text', (ft - st).timestr(3))
        else:
            cr.set_property('text', '')

    def reset_lappoints(self):
        """Update lap points allocations."""
        if self.masterslaps:
            dist = self.meet.get_distance(self.distance, self.units)
            if dist is not None and dist < 20000:
                self.lappoints = 10
            else:
                self.lappoints = 20
        else:
            self.lappoints = 20

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
        """Constructor."""
        self.meet = meet
        self.event = event      # Note: now a treerowref
        self.evno = meet.edb.getvalue(event, eventdb.COL_EVNO)
        self.evtype = meet.edb.getvalue(event, eventdb.COL_TYPE)
        self.series = meet.edb.getvalue(event, eventdb.COL_SERIES)
        self.configpath = meet.event_configfile(self.evno)

        self.log = logging.getLogger('scbdo.points')
        self.log.setLevel(logging.DEBUG)
        self.log.debug('opening event: ' + str(self.evno))

        # race property attributes
        self.masterslaps = True
        self.lappoints = 20
        self.scoring = 'points'
        self.distance = None
        self.units = 'laps'
        self.sprintlaps = ''
        self.sprintpoints = {}
        self.nopts = []
        self.sprintresults = []
        self.auxmap = {}

        # race run time attributes
        self.onestart = False
        self.readonly = not ui
        self.start = None
        self.lstart = None
        self.finish = None
        self.winopen = True
        self.timerwin = False
        self.timerstat = 'idle'
        self.curtimerstr = ''
        self.sprintstart = None
        self.sprintlstart = None

        # data models
        self.sprints = gtk.ListStore(gobject.TYPE_STRING,   # ID = 0
                                     gobject.TYPE_STRING,   # LABEL = 1
                                     gobject.TYPE_PYOBJECT, # 200 = 2
                                     gobject.TYPE_PYOBJECT, # SPLITS = 3
                                     gobject.TYPE_STRING,   # PLACES = 4
                                     gobject.TYPE_PYOBJECT) # POINTS = 5

        self.riders = gtk.ListStore(gobject.TYPE_STRING, # BIB = 0
                                    gobject.TYPE_STRING, # FIRST = 1
                                    gobject.TYPE_STRING, # LAST = 2
                                    gobject.TYPE_STRING, # CLUB = 3
                                    gobject.TYPE_BOOLEAN, # INRACE = 4
                                    gobject.TYPE_INT, # POINTS = 5
                                    gobject.TYPE_INT, # LAPS = 6
                                    gobject.TYPE_INT, # TOTAL = 7
                                    gobject.TYPE_STRING, # PLACE = 8
                                    gobject.TYPE_INT, # FINAL = 9
                                    gobject.TYPE_STRING, # INFO = 10
                                    gobject.TYPE_INT) # STPTS = 11

        b = gtk.Builder()
        b.add_from_file(os.path.join(scbdo.UI_PATH, 'ps.ui'))

        self.frame = b.get_object('ps_vbox')
        self.frame.connect('destroy', self.shutdown)

        # info pane
        self.info_expand = b.get_object('info_expand')
        b.get_object('ps_info_evno').set_text(self.evno)
        self.showev = b.get_object('ps_info_evno_show')
        self.prefix_ent = b.get_object('ps_info_prefix')
        self.prefix_ent.set_text(self.meet.edb.getvalue(
                   self.event, eventdb.COL_PREFIX))
        self.info_ent = b.get_object('ps_info_title')
        self.info_ent.set_text(self.meet.edb.getvalue(
                   self.event, eventdb.COL_INFO))
        self.start_lbl = b.get_object('ps_info_start')
        self.start_lbl.modify_font(pango.FontDescription("monospace"))

        self.finish_lbl = b.get_object('ps_info_finish')
        self.finish_lbl.modify_font(pango.FontDescription("monospace"))
        self.time_lbl = b.get_object('ps_info_time')
        self.time_lbl.modify_font(pango.FontDescription("monospace bold"))
        self.update_expander_lbl_cb()	# signals get connected later...
        self.type_lbl = b.get_object('race_type')
        self.type_lbl.set_text(self.scoring.capitalize())

        # ctrl pane
        self.stat_but = b.get_object('ps_ctrl_stat_but')
        self.ctrl_place_combo = b.get_object('ps_ctrl_place_combo')
        self.ctrl_place_combo.set_model(self.sprints)
        self.ctrl_places = b.get_object('ps_ctrl_places')
        self.ctrl_action_combo = b.get_object('ps_ctrl_action_combo')
        self.ctrl_action = b.get_object('ps_ctrl_action')
        self.action_model = b.get_object('ps_action_model')

        # sprints pane
        t = gtk.TreeView(self.sprints)
        t.set_reorderable(True)
        t.set_enable_search(False)
        t.set_rules_hint(True)
        t.show()
        uiutil.mkviewcoltxt(t, 'Sprint', SPRINT_COL_LABEL,
                             self.ps_sprint_cr_label_edited_cb,
                             expand=True)
        uiutil.mkviewcoltod(t, '200m', cb=self.todstr)
        uiutil.mkviewcoltxt(t, 'Places', SPRINT_COL_PLACES,
                             self.ps_sprint_cr_places_edited_cb,
                             expand=True)
        b.get_object('ps_sprint_win').add(t)

        # results pane
        t = gtk.TreeView(self.riders)
        t.set_reorderable(True)
        t.set_enable_search(False)
        t.set_rules_hint(True)
        t.show()
        uiutil.mkviewcoltxt(t, 'No.', RES_COL_BIB, calign=1.0)
        uiutil.mkviewcoltxt(t, 'First Name', RES_COL_FIRST,
                               self.ps_result_cr_first_edited_cb,
                               expand=True)
        uiutil.mkviewcoltxt(t, 'Last Name', RES_COL_LAST,
                               self.ps_result_cr_last_edited_cb,
                               expand=True)
        uiutil.mkviewcoltxt(t, 'Club', RES_COL_CLUB,
                               self.ps_result_cr_club_edited_cb)
        uiutil.mkviewcoltxt(t, 'Info', RES_COL_INFO,
                               self.ps_result_cr_info_edited_cb)
        uiutil.mkviewcolbool(t, 'In', RES_COL_INRACE,
                               self.ps_result_cr_inrace_toggled_cb,
                               width=50)
        uiutil.mkviewcoltxt(t, 'Pts', RES_COL_POINTS, calign=1.0,
                               width=50)
        uiutil.mkviewcoltxt(t, 'Laps', RES_COL_LAPS, calign=1.0, width=50,
                                cb=self.ps_result_cr_laps_edited_cb)
        uiutil.mkviewcoltxt(t, 'Total', RES_COL_TOTAL, calign=1.0,
                                width=50)
        uiutil.mkviewcoltxt(t, 'Place', RES_COL_PLACE, calign=0.5,
                                width=50)
        b.get_object('ps_result_win').add(t)

        if ui:
            # connect signal handlers
            b.connect_signals(self)
            # update properties in meet
            self.meet.menu_race_properties.set_sensitive(True)
            self.meet.edb.editevent(event, winopen=True)
            glib.timeout_add_seconds(3, self.delayed_announce)
