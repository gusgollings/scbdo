
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

"""Road Mass-start race module.

This module provides a class 'rms' which implements the race
interface and manages data, timing and scoreboard for generic
road race events:

 - Criterium
 - Kermesse
 - Road race

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
COL_INRACE = 4		# boolean in the race
COL_PLACE = 5		# Place assigned in result
COL_LAPS = 6		# Incremented if inrace and not finished

# timing infos
COL_RFTIME = 7		# one-off finish time by rfid
COL_CBUNCH = 8		# computed bunch time	-> derived from rftime
COL_MBUNCH = 9		# manual bunch time	-> manual overrive
COL_RFSEEN = 10		# list of tods this rider 'seen' by rfid

# rider commands
RIDER_COMMMANDS = {'dns':'Did not start',
                   'dnf':'Did not finish',
                   'add':'Add starters',
                   'del':'Remove starters',
                   'que':'Query riders',
                   'fin':'Final places',
                   'com':'Add comment',
                   'int':'Intermediate sprint' }

# timing keys
key_announce = 'F4'
key_armstart = 'F5'
key_clearscratch = 'F6'
key_markrider = 'F7'
key_promoterider = 'F8'
key_armfinish = 'F9'
key_raceover = 'F10'

# extended fn keys	(ctrl + key)
key_abort = 'F5'
key_undo = 'Z'

# config version string
EVENT_ID = 'roadrace-1.0'

## !! NOTE this function will break with py3+ -> change to < > comps
def sort_bib(x, y):
    """Rider bib sorter."""
    a = x[1]
    b = y[1]
    if a.isdigit():
        a = int(a)
    if b.isdigit():
        b = int(b)
    return cmp(a, b)

class rms(object):
    """Road race handler."""

    def loadconfig(self):
        """Load event config from disk."""
        self.riders.clear()
        self.resettimer()
        cr = ConfigParser.ConfigParser({'start':'',
                                        'lstart':'',
                                        'id':EVENT_ID,
                                        'finish':'',
                                        'finished':'No',
                                        'places':'',
                                        'comment':'',
                                        'resort':'No',
                                        'startlist':''})
        cr.add_section('event')
        cr.add_section('riders')
        if os.path.isfile(self.configpath):
            self.log.debug('Attempting to read config from path='
                            + repr(self.configpath))
            cr.read(self.configpath)
        starters = cr.get('event', 'startlist').split()
        if strops.confopt_bool(cr.get('event', 'resort')):
            starters.sort(cmp=lambda x,y: cmp(int(x), int(y)))
        for r in starters:
            self.addrider(r)
            if cr.has_option('riders', r):
                nr = self.getrider(r)
                # bib = comment,in,laps,rftod,mbunch,rfseen...
                ril = csv.reader([cr.get('riders', r)]).next()
                lr = len(ril)
                if lr > 0:
                    nr[COL_COMMENT] = ril[0]
                if lr > 1:
                    nr[COL_INRACE] = strops.confopt_bool(ril[1])
                if lr > 2:
                    if ril[2].isdigit():
                        nr[COL_LAPS] = int(ril[2])
                    else:
                        nr[COL_LAPS] = 0
                if lr > 3:
                    nr[COL_RFTIME] = tod.str2tod(ril[3])
                if lr > 4:
                    nr[COL_MBUNCH] = tod.str2tod(ril[4])
                if lr > 5:
                    for i in range(5, lr):
                        laptod = tod.str2tod(ril[i])
                        if laptod is not None:
                            nr[COL_RFSEEN].append(laptod)
        self.set_start(cr.get('event', 'start'), cr.get('event', 'lstart'))
        self.set_finish(cr.get('event', 'finish'))
        self.places = strops.reformat_placelist(cr.get('event', 'places'))
        self.comment = cr.get('event', 'comment').splitlines()
        if cr.get('event', 'finished') == 'Yes':
            self.set_finished()
        self.recalculate()

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
        ## TODO: Append points classifications to commands.
        return RIDER_COMMMANDS

    def get_startlist(self):
        """Return a list of all rider numbers 'registered' to event."""
        ret = []
        for r in self.riders:
            ret.append(r[COL_BIB])
        return ' '.join(ret)

    def checkpoint_model(self):
        """Write the current rider model to an undo buffer."""
        self.undomod.clear()
        self.placeundo = self.places
        for r in self.riders:
            self.undomod.append(r)
        self.canundo = True

    def undo_riders(self):
        """Roll back rider model to last checkpoint."""
        if self.canundo:
            self.riders.clear()
            for r in self.undomod:
                self.riders.append(r)
            self.places = self.placeundo
            self.canundo = False
          
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
        cw.set('event', 'places', self.places)
        cw.set('event', 'startlist', self.get_startlist())    
        cw.set('event', 'comment', '\n'.join(self.comment))

        cw.add_section('riders')
        for r in self.riders:
            bf = ''
            if r[COL_INRACE]:
                bf='True'
            rt = ''
            if r[COL_RFTIME] is not None:
                rt = r[COL_RFTIME].rawtime(2)
            mb = ''
            if r[COL_MBUNCH] is not None:
                mb = r[COL_MBUNCH].rawtime(0)
            # bib = comment,in,laps,rftod,mbunch,rfseen...
            slice = [r[COL_COMMENT], bf, r[COL_LAPS], rt, mb]
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
            titlestr = 'Mass Start Road Race'
        self.title_namestr.set_text(titlestr)

    def destroy(self):
        """Emit destroy signal to race handler."""
        self.frame.destroy()

    def get_results(self):
        """Extract results in flat mode (not yet implemented)."""
        return []

    def startlist_header(self):
        """Return the start list report header."""
        return '\
  no  rider                                                            cat'

    def startlist_report(self):
        """Return a startlist report."""
        ret = []
        aux = []
        cnt = 0
        for r in self.riders:
            aux.append([cnt, r[COL_BIB]])
            cnt += 1
        if len(aux) > 1:
            aux.sort(sort_bib)
            self.riders.reorder([a[0] for a in aux])
        for r in self.riders:
            ret.append(r[COL_BIB].rjust(4) + '  '
                       + strops.truncpad(r[COL_NAMESTR], 64) + ' '
                       + strops.truncpad(r[COL_CAT], 8))
        if cnt > 1:
            ret.append('')
            ret.append('Total riders: ' + str(cnt))

        return ret

    def camera_header(self):
        """Return the judges report header."""
        return '\
     no.  rider                                       cat lap  finish    rftime'

    def camera_report(self):
        """Return a judges (camera) report."""
        self.recalculate()	# fill places and bunch info
        ret = []
        totcount = 0
        dnscount = 0
        dnfcount = 0
        fincount = 0
        firstdnf = True
        firstdns = True
        if self.timerstat != 'idle':
            first = True
            ft = None
            lt = None
            for r in self.riders:
                totcount += 1
                marker = ' '
                #if r[COL_CAT].lower() == 'u23':
                    #marker = '*'
                es = ''
                bs = ''
                if r[COL_INRACE]:
                    comment = '___'
                    bt = self.vbunch(r[COL_CBUNCH], r[COL_MBUNCH])
                    if bt is not None:
                        fincount += 1
                        if r[COL_PLACE] != '':
                           comment = r[COL_PLACE] + '.'

                        # format 'elapsed' rftime
                        if r[COL_RFTIME] is not None:
                            if self.start is not None:
                                es =  (r[COL_RFTIME]-self.start).rawtime(1)
                            else:
                                es = r[COL_RFTIME].rawtime(1)

                        # format 'finish' time
                        if ft is None:
                            ft = bt
                            bs = ft.rawtime(0)
                        else:
                            if bt > lt:
                                # New bunch
                                ret.append('')
                                bs = "+" + (bt - ft).rawtime(0)
                            else:
                                # Same time
                                pass
                        lt = bt
                    else:
                        if r[COL_COMMENT].strip() != '':
                            comment = r[COL_COMMENT].strip()

                    ret.append(strops.truncpad(comment, 4) + ' '
                                 + r[riderdb.COL_BIB].rjust(3) + ' '
                                 + marker
                                 + strops.truncpad(r[COL_NAMESTR], 44)
                                 + strops.truncpad(r[COL_CAT], 3, 'r') + ' '
                                 + str(r[COL_LAPS]).rjust(3) + ' '
                                 + bs.rjust(7) + ' ' 
                                 + es.rjust(9))
                else:
                    comment = r[COL_COMMENT]
                    if comment == '':
                        comment = 'dnf'
                    if comment == 'dns':
                        if firstdns:
                            ret.append('')
                            firstdns = False
                        dnscount += 1
                    elif comment == 'dnf':
                        if firstdnf:
                            ret.append('')
                            firstdnf = False
                        dnfcount += 1
                    ret.append(strops.truncpad(comment, 4) + ' '
                                 + r[riderdb.COL_BIB].rjust(3) + ' '
                                 + marker
                                 + strops.truncpad(r[COL_NAMESTR], 44)
                                 + strops.truncpad(r[COL_CAT], 3, 'r') + ' '
                                 + str(r[COL_LAPS]).rjust(3))
                first = False
            if first:
                ret.append('     -- No Places --')
            ret.append('')
            ret.append('Total riders:    ' + str(totcount).rjust(8))
            ret.append('Did not start:   ' + str(dnscount).rjust(8))
            ret.append('Did not finish:  ' + str(dnfcount).rjust(8))
            ret.append('Finishers:       ' + str(fincount).rjust(8))
            residual = totcount - (fincount + dnfcount + dnscount)
            if residual > 0:
                ret.append('Unaccounted for: ' + str(residual).rjust(8))
        else:
            ret.append('     -- Not Started --')
        return ret

    def result_header(self):
        """Return a result report header."""
        return '\
     no  rider                                          cat     time'

    def result_report(self):
        """Return a race result report."""
        self.recalculate()
        ret = []
        wt = None
        totcount = 0
        dnscount = 0
        dnfcount = 0
        fincount = 0
        firstdnf = True
        firstdns = True
        lt = None
        if self.timerstat != 'idle':
            first = True
            for r in self.riders:
                totcount += 1
                bstr = r[COL_BIB].rjust(3)
                nstr = strops.truncpad(r[COL_NAMESTR], 45)
                cstr = strops.truncpad(r[COL_CAT], 4, align='r')
                pstr = '    '
                tstr = '        '
                dstr = '        '
                if r[COL_INRACE]:
                    if r[COL_PLACE] != '':
                        pstr = (r[COL_PLACE] + '.').ljust(4)
                    bt = self.vbunch(r[COL_CBUNCH], r[COL_MBUNCH])
                    if bt is not None:
                        fincount += 1
                        tstr = bt.rawtime(0).rjust(8)
                        if bt != lt:
                            if not first:
                                ret.append('')	# new bunch
                                dstr = ('+' + (bt - wt).rawtime(0)).rjust(8)
                        if wt is None:	# first finish time
                            wt = bt
                            first = False
                    lt = bt
                else:
                    pstr = strops.truncpad(r[COL_COMMENT], 4)
                    if pstr == 'dnf ':
                        dnfcount += 1
                        if firstdnf:
                            ret.append('')
                            firstdnf = False
                    elif pstr == 'dns ':
                        dnscount += 1
                        if firstdns:
                            ret.append('')
                            firstdns = False
                ret.append(' '.join([pstr, bstr, nstr, cstr, tstr, dstr]))
            if wt is not None:
                ret.append('')
                ret.append('Winning time:    ' + wt.rawtime(0).rjust(8))
            ret.append('')
            ret.append('Total riders:    ' + str(totcount).rjust(8))
            ret.append('Did not start:   ' + str(dnscount).rjust(8))
            ret.append('Did not finish:  ' + str(dnfcount).rjust(8))
            ret.append('Finishers:       ' + str(fincount).rjust(8))
            residual = totcount - (fincount + dnfcount + dnscount)
            if residual > 0:
                ret.append('Unaccounted for: ' + str(residual).rjust(8))
            if len(self.comment) > 0:
                ret.append('')
                for cl in self.comment:
                    ret.append('* ' + strops.truncpad(cl.strip(), 64))
        else:
            ret.append('     -- Not Started --')
        return ret

    def stat_but_clicked(self):
        """Deal with a status button click in the main container."""
        self.log.info('Stat button clicked.')

    def race_ctrl(self, acode='', rlist=''):
        """Apply the selected action to the provided bib list."""
        self.checkpoint_model()
        if acode == 'fin':
            rlist = strops.reformat_placelist(rlist)
            if self.checkplaces(rlist):
                self.places = rlist
                self.recalculate()
                self.finsprint(rlist)
                return True
            else:
                return False
        elif acode == 'dnf':
            self.dnfriders(strops.reformat_biblist(rlist))
            return True
        elif acode == 'dns':
            self.dnsriders(strops.reformat_biblist(rlist))
            return True
        elif acode == 'del':
            rlist = strops.reformat_biblist(rlist)
            for bib in rlist.split():
                self.delrider(bib)
            return True
        elif acode == 'add':
            rlist = strops.reformat_biblist(rlist)
            for bib in rlist.split():
                self.addrider(bib)
            return True
        elif acode == 'int':
            rlist = strops.reformat_placelist(rlist)
            self.intsprint(rlist)
            return True
        elif acode == 'que':
            rlist = strops.reformat_biblist(rlist)
            if rlist != '':
                self.meet.scratch_log('')
                for bib in rlist.split():
                    self.query_rider(bib)
            return True
        elif acode == 'com':
            self.add_comment(rlist)
            return True
        else:
            self.log.error('Ignoring invalid action.')
        return False

    def add_comment(self, comment=''):
        """Append a race comment."""
        self.comment.append(comment.strip())
        self.log.info('Added race comment: ' + repr(comment))

    def query_rider(self, bib=None):
        """List info on selected rider in the scratchpad."""
        self.log.info('Query rider: ' + repr(bib))
        r = self.getrider(bib)
        if r is not None:
            ns = strops.truncpad(r[COL_NAMESTR] + ' ' + r[COL_CAT], 30)
            bs = ''
            bt = self.vbunch(r[COL_CBUNCH], r[COL_MBUNCH])
            if bt is not None:
                bs = bt.timestr(0)
            ps = r[COL_COMMENT]
            if r[COL_PLACE] != '':
                ps = r[COL_PLACE]
            self.meet.scratch_log(' '.join([bib, ns, bs, ps]))
            lt = None
            if len(r[COL_RFSEEN]) > 0:
                for rft in r[COL_RFSEEN]:
                    nt = rft.truncate(0)
                    ns = rft.timestr(1)
                    ls = ''
                    if lt is not None:
                        ls = (nt - lt).timestr(0)
                    self.meet.scratch_log(' '.join(['\t', ns, ls]))
                    lt = nt
            if r[COL_RFTIME] is not None:
                self.meet.scratch_log(' '.join([' Finish:',
                                          r[COL_RFTIME].timestr(1)]))
        else:
            self.meet.scratch_log(bib.ljust(4) + ' ' + 'Not in startlist.')

    # main shared result export -> outputs text/csv lines for spreadsheet
    def result_export(self, f):
        """Export result for use with other systems."""
        self.recalculate()	# fix up ordering of rows
        cr = csv.writer(f)
 
        if self.timerstat != 'idle':
            first = True
            ft = None
            lt = None
            cr.writerow(['place', 'no.', 'time'])
            for r in self.riders:
                vbs = ''
                if r[COL_INRACE]:
                    bt = self.vbunch(r[COL_CBUNCH], r[COL_MBUNCH])
                    if bt is not None:
                        vbs = "'" + bt.rawtime(2, zeros=True)
                    cr.writerow([r[COL_PLACE], r[COL_BIB], vbs])
                else:
                    vbs = ''
                    comment = r[COL_COMMENT]
                    if comment == '':
                        comment = 'dnf'
                    if comment == 'dnf':
                        vbs = '11:11:11.11'
                    elif comment == 'dns':
                        vbs = '22:22:22.22'
                    cr.writerow(['', r[COL_BIB], vbs])

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
            nr = [bib, '', '', '', True, '', 0, None, None, None, []]
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
        self.meet.timer.dearm(0)
        self.meet.timer.dearm(1)
        uiutil.buttonchg(self.meet.stat_but, uiutil.bg_none, 'Idle')
        self.meet.stat_but.set_sensitive(True)
        self.set_elapsed()
        
    def armstart(self):
        """Process an armstart request."""
        if self.timerstat == 'idle':
            self.timerstat = 'armstart'
            uiutil.buttonchg(self.meet.stat_but,
                             uiutil.bg_armstart, 'Arm Start')
            self.meet.timer.arm(0)            
        elif self.timerstat == 'armstart':
            self.timerstat = 'idle'
            uiutil.buttonchg(self.meet.stat_but, uiutil.bg_none, 'Idle') 
            self.meet.timer.dearm(0)
        elif self.timerstat == 'running':
            # TODO: allow temporary inhibit of rfid??
            pass

    def armfinish(self):
        """Process an armfinish request."""
        if self.timerstat in ['running', 'finished']:
            self.timerstat = 'armfinish'
            uiutil.buttonchg(self.meet.stat_but,
                             uiutil.bg_armfin, 'Arm Finish')
            self.meet.stat_but.set_sensitive(True)
            self.meet.timer.arm(1)
            self.meet.rfu.arm()	# superfluous?
        elif self.timerstat == 'armfinish':
            self.timerstat = 'running'
            uiutil.buttonchg(self.meet.stat_but,
                             uiutil.bg_none, 'Running')
            self.meet.timer.dearm(1)

    def key_event(self, widget, event):
        """Handle global key presses in event."""
        if event.type == gtk.gdk.KEY_PRESS:
            key = gtk.gdk.keyval_name(event.keyval) or 'None'
            if event.state & gtk.gdk.CONTROL_MASK:
                if key == key_abort:    # override ctrl+f5
                    self.resettimer()
                    return True
                elif key.upper() == key_undo:	# Undo model change if possible
                    self.undo_riders()
                    return True
            if key[0] == 'F':
                if key == key_armstart:
                    self.armstart()
                    return True
                elif key == key_announce:
                    if self.timerstat == 'finished':
                        self.finsprint(self.places)
                    else:
                        self.reannounce_lap()
                    return True
                elif key == key_armfinish:
                    self.armfinish()
                    return True
                elif key == key_raceover:
                    self.set_finished()
                    return True
                elif key == key_clearscratch:
                    self.meet.scratch_clear()
                    if self.live_announce:
                        self.meet.scb.clrall()
                        self.meet.scb.set_title(self.title_namestr.get_text())
                    self.last_scratch = self.scratch_start
                    self.scratch_start = None
                    self.scratch_tot = 0
                    self.scratch_map = {}
                    self.scratch_ord = []
                    return True
                elif key == key_markrider:
                    self.set_ridermark()
                    return True
                elif key == key_promoterider:
                    self.promoterider()
                    return True
        return False

    def set_ridermark(self):
        """Mark the current position in the result."""
        self.ridermark = None
        sel = self.view.get_selection().get_selected()
        if sel is not None:
            self.ridermark = sel[1]
        
    def promoterider(self):
        """Promote the selected rider to the current ridermark."""
        if self.ridermark is not None:
            sel = self.view.get_selection().get_selected()
            if sel is not None:
                i = sel[1]
                self.riders.move_before(i, self.ridermark)
                self.fill_places_to(self.riders.get_value(self.ridermark,
                                      COL_BIB))

    # remove each rider from the race
    def dnfriders(self, biblist=''):
        recalc = False
        for bib in biblist.split():
            r = self.getrider(bib)
            if r is not None:
                r[COL_INRACE] = False
                r[COL_COMMENT] = 'dnf'
                recalc = True
                self.log.info('Rider ' + str(bib) + ' did not finish')
            else:
                self.log.warn('Unregistered Rider ' + str(bib) + ' unchanged.')
        if recalc:
            self.recalculate()
        return False
  
    # register non-starters
    def dnsriders(self, biblist=''):
        recalc = False
        for bib in biblist.split():
            r = self.getrider(bib)
            if r is not None:
                r[COL_INRACE] = False
                r[COL_COMMENT] = 'dns'
                recalc = True
                self.log.info('Rider ' + str(bib) + ' did not start')
            else:
                self.log.warn('Unregistered Rider ' + str(bib) + ' unchanged.')
        if recalc:
            self.recalculate()
        return False
  
    def shutdown(self, win=None, msg='Race Sutdown'):
        """Close event."""
        self.log.debug('Event shutdown: ' + msg)
        if not self.readonly:
            self.saveconfig()
        self.meet.edb.editevent(self.event, winopen=False)
        self.winopen = False

    def starttrig(self, e):
        """Process a 'start' trigger signal."""
        if self.timerstat == 'armstart':
            self.set_start(e, tod.tod('now'))
            self.meet.scb.set_start(self.start)

    def rfidtrig(self, e):
        """Process rfid event."""
        r = self.meet.rdb.getrefid(e.refid)
        if r is None:
            self.log.info('Unknown tag: ' + e.refid + '@' + e.rawtime(1))
            return

        bib = self.meet.rdb.getvalue(r, riderdb.COL_BIB)
        ser = self.meet.rdb.getvalue(r, riderdb.COL_SERIES)
        if ser != self.series:
            self.log.error('Ignored non-series rider: ' + bib + '.' + ser)
            return

        # at this point should always have a valid source rider vector
        lr = self.getrider(bib)
        if lr is None:
            self.log.warn('Ignoring non starter: ' + bib
                          + ' @ ' + e.rawtime(1))
            return
        assert(lr is not None)

        # save RF ToD into 'seen' vector and log
        lr[COL_RFSEEN].append(e)

        if not lr[COL_INRACE]:
            self.log.warn('Withdrawn rider: ' + lr[COL_BIB]
                          + ' @ ' + e.rawtime(1))
            # but continue anyway just in case it was not correct?
        else:
            self.log.info('Saw: ' + bib + ' @ ' + e.rawtime(1))

        # check run state
        if self.timerstat in ['idle', 'armstart']:
            return

        # scratch pad log
        et = e - self.start
        ct = et.truncate(0)
        if self.scratch_start is None:
            if self.last_scratch is None:
                self.last_scratch = tod.tod('0')
            self.scratch_start = ct
            self.scratch_last = et
            self.scratch_count = 1
            self.scratch_tot = 1
            # emit full record
            self.meet.scratch_log(' '.join([
                str(self.scratch_tot).ljust(3),
                str(self.scratch_count).ljust(3),
                bib.rjust(3),
                strops.truncpad(lr[COL_NAMESTR], 30),
                self.scratch_start.rawtime(1).rjust(9),
                (self.scratch_start - self.last_scratch).rawtime(0).rjust(7)]))
        else:
            self.scratch_tot += 1
            if et < self.scratch_last or et - self.scratch_last < tod.tod('1.12'): # same bunch
                self.scratch_count += 1
                self.meet.scratch_log(' '.join([
                    str(self.scratch_tot).ljust(3),
                    str(self.scratch_count).ljust(3),
                    bib.rjust(3),
                    strops.truncpad(lr[COL_NAMESTR], 30),
                    et.rawtime(1).rjust(9)]))
                # emit only rider and ft
            else:
                self.scratch_count = 1
                self.meet.scratch_log('')
                self.meet.scratch_log(' '.join([
                    str(self.scratch_tot).ljust(3),
                    str(self.scratch_count).ljust(3),
                    bib.rjust(3),
                    strops.truncpad(lr[COL_NAMESTR], 30),
                    et.rawtime(1).rjust(9),
                    ('+' + (ct - self.scratch_start).rawtime(0)).rjust(7)]))
            self.scratch_last = et

        if self.timerstat == 'armfinish':
            if self.finish is None:
                if self.live_announce:
                    self.meet.scb.set_title(self.title_namestr.get_text()
                                          + ' - ' + 'Final Lap')
                self.set_finish(e)
                self.set_elapsed()
            if lr[COL_RFTIME] is None:
                lr[COL_LAPS] += 1
                lr[COL_RFTIME] = e
                self.announce_rider('', bib, lr[COL_NAMESTR],
                                    lr[COL_CAT], e)
            else:
                self.log.error('Duplicate finish rider = ' + bib
                                  + ' @ ' + str(e))
        elif self.timerstat in 'running':
            lr[COL_LAPS] += 1
            self.announce_rider('', bib, lr[COL_NAMESTR],
                                lr[COL_CAT], e)

    def announce_rider(self, place, bib, namestr, cat, rftime):
        """Log a rider in the lap and emit to announce."""
        if bib not in self.scratch_map:
            self.scratch_map[bib] = rftime
            self.scratch_ord.append(bib)
        if self.live_announce:
            self.meet.scb.add_rider([place,bib,namestr,
                                     cat,rftime.rawtime()])

    def finsprint(self, places):
        """Display a final sprint 'official' result."""

        self.live_announce = False
        self.meet.scb.clrall()
        self.meet.scb.set_title(self.title_namestr.get_text()
                                + ' - Final Result')
        placeset = set()
        idx = 0
        st = tod.tod('0')
        if self.start is not None:
            st = self.start
        # result is sent in final units, not absolutes
        self.meet.scb.set_start(tod.tod(0))
        wt = None
        lb = None
        for placegroup in places.split():
            curplace = idx + 1
            for bib in placegroup.split('-'):
                if bib not in placeset:
                    placeset.add(bib)
                    r = self.getrider(bib)
                    if r is not None:
                        ft = self.vbunch(r[COL_CBUNCH],
                                         r[COL_MBUNCH])
                        fs = ''
                        if ft is not None:
                            if ft != lb:
                                fs = ft.rawtime()
                            else:
                                if r[COL_RFTIME] is not None:
                                    fs = (r[COL_RFTIME]-st).rawtime()
                                else:
                                    fs = ft.rawtime()
                            if wt is None:
                                wt = ft
                            lb = ft
                        self.meet.scb.add_rider([r[COL_PLACE]+'.',
                                                 bib,
                                                 r[COL_NAMESTR],
                                                 r[COL_CAT], fs])
                    idx += 1
        # set winner's time
        self.meet.scb.set_time(wt.rawtime(0))

    def intsprint(self, places):
        """Display an intermediate sprint 'official' result."""

        ## TODO : Fix offset time calcs - too many off by ones

        self.live_announce = False
        self.meet.scb.clrall()
        self.meet.scb.set_title(self.title_namestr.get_text()
                                + ' - Intermediate Sprint')
        placeset = set()
        idx = 0
        for placegroup in places.split():
            curplace = idx + 1
            for bib in placegroup.split('-'):
                if bib not in placeset:
                    placeset.add(bib)
                    r = self.getrider(bib)
                    if r is not None:
                        self.meet.scb.add_rider([str(curplace)+'.',
                                                 bib,
                                                 r[COL_NAMESTR],
                                                 r[COL_CAT], ''])
                    idx += 1
                else:
                    self.log.warn('Duplicate no. = ' + str(bib) + ' in places.')

        glib.timeout_add_seconds(30, self.reannounce_lap)

    def reannounce_lap(self):
        self.live_announce = False
        self.meet.scb.clrall()
        if self.timerstat == 'armfinish':
            self.meet.scb.set_title(self.title_namestr.get_text()
                                          + ' - ' + 'Final Lap')
        else:
            self.meet.scb.set_title(self.title_namestr.get_text())
        for bib in self.scratch_ord:
            r = self.getrider(bib)
            if r is not None:
                self.meet.scb.add_rider(['',bib,r[COL_NAMESTR],r[COL_CAT],
                                         self.scratch_map[bib].rawtime()])
        self.live_announce = True
        return False

    def cr_inrace_toggled(self, cr, path, data=None):
        """Update in the race status."""
        self.riders[path][COL_INRACE] = not self.riders[path][COL_INRACE]
        #self.recalculate()

    def timeout(self):
        """Poll for rfids and update elapsed time."""
        if not self.winopen:
            return False
        e = self.meet.rfu.response()
        while e is not None:
            if e.refid != 'trig':
                self.rfidtrig(e)
            else:
                self.starttrig(e)
            e = self.meet.rfu.response()
        if self.finish is None and self.start is not None:
            self.set_elapsed()
        return True

    def set_start(self, start='', lstart=''):
        """Set the start time."""
        if type(start) is tod.tod:
            self.start = start
        else:
            self.start = tod.str2tod(start)
        if type(lstart) is tod.tod:
            self.lstart = lstart
        else:
            self.lstart = tod.str2tod(lstart)
            if self.lstart is None:
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
        if self.live_announce:
            self.meet.scb.set_time(self.time_lbl.get_text())

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

    def title_place_xfer_clicked_cb(self, button, data=None):
        """Transfer current rider list order to places, and recalc."""
        nplaces = ''
        lplace = None
        for r in self.riders:
            if r[COL_INRACE]:
                if lplace == r[COL_PLACE] and r[COL_PLACE] != '':
                    nplaces += '-' + r[COL_BIB] # dead heat riders
                else:
                    nplaces += ' ' + r[COL_BIB]
                    lplace = r[COL_PLACE]
        self.places = strops.reformat_placelist(nplaces)
        # self.recalculate()
        self.meet.action_entry.set_text(self.places)
        
    def fill_places_to(self, bib):
        """Fill in finish places up to the nominated bib."""
        if self.places.find('-') > 0:
            self.log.warn('Will not automatically fill places with dead heat.')
            return
        oplaces = self.places.split()	# only patch if no dead heats
        nplaces = []
        for r in self.riders:
            if r[COL_BIB] == bib:
                break
            if r[COL_INRACE]:
                if r[COL_BIB] in oplaces:
                    oplaces.remove(r[COL_BIB])	# remove from old list
                nplaces.append(r[COL_BIB])      # add to new list
        nplaces.extend(oplaces)
        self.checkpoint_model()
        self.places = ' '.join(nplaces)
        self.recalculate()

    def info_time_edit_clicked_cb(self, button, data=None):
        """Run an edit times dialog to update race time."""
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

    def resetplaces(self):
        """Clear places off all riders."""
        for r in self.riders:
            r[COL_PLACE] = ''
            
    def sortrough(self, x, y):
        # aux cols: ind, bib, in, place, rftime, laps
        #             0    1   2      3       4     5
        if x[2] != y[2]:		# in the race?
            if x[2]:
                return -1
            else:
                return 1
        else:
            if x[3] != y[3]:		# places not same?
                if y[3] == '':
                    return -1
                elif x[3] == '':
                    return 1
                if int(x[3]) < int(y[3]):
                    return -1
                else:
                    return 1
            else:
                if x[4] == y[4]:	# same time?
                    if x[5] == y[5]:	# same laps?
                        return 0
                    else:
                        if x[5] > y[5]:
                            return -1
                        else:
                            return 1
                else:
                    if y[4] is None:
                        return -1
                    elif x[4] is None:
                        return 1
                    elif x[4] < y[4]:
                        return -1
                    else:
                        return 1
        return 0

    # do final sort on manual places then manual bunch entries
    def sortvbunch(self, x, y):
        # aux cols: ind, bib, in, place, vbunch, comment
        #             0    1   2      3       4        5
        if x[2] != y[2]:		# in the race?
            if x[2]:
                return -1
            else:
                return 1
        else:
            if x[2]:			# in the race...
                if x[3] != y[3]:		# places not same?
                    if y[3] == '':
                        return -1
                    elif x[3] == '':
                        return 1
                    if int(x[3]) < int(y[3]):
                        return -1
                    else:
                        return 1
                else:
                    if x[4] == y[4]:	# same time?
                        return 0
                    else:
                        if y[4] is None:
                            return -1
                        elif x[4] is None:
                            return 1
                        elif x[4] < y[4]:
                            return -1
                        else:
                            return 1
            else:			# not in the race
                if x[5] == y[5]:	# same 'comment'
                    return sort_bib(x, y)	# sort on bib !! BREAK
                else:
                    return cmp(x[5], y[5])	# sort comment !!BREAK!
        return 0

    # sort riders according to result rules
    # inrace -> bunch -> place -> rftime
    def sortauxtbl(self, x, y):
        if x[2] != y[2]:		# in the race?
            if x[2]:
                return -1
            else:
                return 1
        else:
            if x[3] != y[3]:
                if y[3] == '':
                    return -1
                elif x[3] == '':
                    return 1
                if int(x[3]) < int(y[3]):
                    return -1
                else:
                    return 1
            else:
                if x[4] == y[4]:	# same place?
                    if x[5] == y[5]:	# same rftime?
                        return 0
                    else:
                        if y[5] is None:
                            return -1
                        elif x[5] is None:
                            return 1
                        elif x[5] < y[5]:
                            return -1
                        else:
                            return 0
                else:
                    if y[4] == '':
                        return -1
                    elif x[4] == '':
                        return 1
                    elif int(x[4]) < int(y[4]):
                        return -1
                    else:
                        return 1

    # choose bunch time
    def vbunch(self, cbunch=None, mbunch=None):
        ret = None
        if mbunch is not None:
            ret = mbunch
        elif cbunch is not None:
            ret = cbunch
        return ret

    # recompute bunch col text from model values
    def showbunch_cb(self, col, cr, model, iter, data=None):
        cb = model.get_value(iter, COL_CBUNCH)
        mb = model.get_value(iter, COL_MBUNCH)
        if mb is not None:
            cr.set_property('text', mb.rawtime(0))
            cr.set_property('style', pango.STYLE_OBLIQUE)
        else:
            cr.set_property('style', pango.STYLE_NORMAL)
            if cb is not None:
                cr.set_property('text', cb.rawtime(0))
            else:
                cr.set_property('text', '')

    # edit bunch and store to mbunch if valid
    def editbunch_cb(self, cell, path, new_text, col=None):
        new_text = new_text.strip()
        dorecalc = False
        if new_text == '':	# user request to clear RFTIME?
            self.riders[path][COL_RFTIME] = None
            self.riders[path][COL_MBUNCH] = None
            self.riders[path][COL_CBUNCH] = None
            dorecalc = True
        else:
            # get 'current bunch time'
            omb = self.vbunch(self.riders[path][COL_CBUNCH],
                              self.riders[path][COL_MBUNCH])

            # assign new bunch time
            nmb = tod.str2tod(new_text)
            if self.riders[path][COL_MBUNCH] != nmb:
                self.riders[path][COL_MBUNCH] = nmb
                dorecalc = True
            if nmb is not None:
                i = int(path)+1
                tl = len (self.riders)
                # until next rider has mbunch set OR place clear assign new bt
                while i < tl:
                    ivb = self.vbunch(self.riders[i][COL_CBUNCH], 
                                      self.riders[i][COL_MBUNCH])
                    if (self.riders[i][COL_PLACE] != ''
                          and (ivb is None
                              or ivb == omb)):
                        self.riders[i][COL_MBUNCH] = nmb
                        dorecalc = True
                    else:
                        break
                    i += 1
        if dorecalc:
            self.recalculate()
    
    def checkplaces(self, rlist):
        self.log.info('Checkplaces not implemented.')
        return True

    def recalculate(self):
        # pass one: clear off old places
        self.resetplaces()

        # pass two: assign places
        placeset = set()
        idx = 0
        #placestr = self.ctrl_places.get_text()
        placestr = self.places
        for placegroup in placestr.split():
            curplace = idx + 1
            for bib in placegroup.split('-'):
                if bib not in placeset:
                    placeset.add(bib)
                    r = self.getrider(bib)
                    if r is None:
                        self.addrider(bib)
                        r = self.getrider(bib)
                    idx += 1
                    r[COL_PLACE] = str(curplace)
                else:
                    self.log.warn('Duplicate no. = ' + str(bib) + ' in places.')

        # pass three: do rough sort on in, place, rftime -> existing
        auxtbl = []
        idx = 0
        for r in self.riders:
            # aux cols: ind, bib, in, place, rftime, laps
            auxtbl.append([idx, r[COL_BIB], r[COL_INRACE], r[COL_PLACE],
                           r[COL_RFTIME], r[COL_LAPS]])
            idx += 1
        if len(auxtbl) > 1:
            auxtbl.sort(self.sortrough)
            self.riders.reorder([a[0] for a in auxtbl])

        # pass four: compute cbunch values on auto time gaps and manual inputs
        #            At this point all riders are assumed to be in finish order
        ft = None	# the finish or first bunch time
        lt = None	# the rftime of last competitor across line
        bt = None	# the 'current' bunch time
        if self.start is not None:
            for r in self.riders:
                if r[COL_INRACE]:
                    if r[COL_MBUNCH] is not None:
                        bt = r[COL_MBUNCH]	# override with manual bunch
                        r[COL_CBUNCH] = bt
                    elif r[COL_RFTIME] is not None:
                        # establish elapsed, but allow subsequent override
                        et = r[COL_RFTIME] - self.start
    
                        # establish bunch time
                        if ft is None:
                            ft = et.truncate(0)	# compute first time
                            bt = ft
                        else:
                            if et < lt or et - lt < tod.tod('1.12'): #NTG!
                                # same time
                                pass
                            else:
                                bt = et.truncate(0)

                        # assign and continue
                        r[COL_CBUNCH] = bt
                        lt = et
                    else:
                        # empty rftime with non-empty rank implies no time gap
                        if r[COL_PLACE] != '':
                            r[COL_CBUNCH] = bt	# use current bunch time
                        else: r[COL_CBUNCH] = None
                
        # pass five: resort on in,vbunch (todo -> check if place cmp reqd)
        #            at this point all riders will have valid bunch time
        auxtbl = []
        idx = 0
        for r in self.riders:
            # aux cols: ind, bib, in, place, vbunch
            auxtbl.append([idx, r[COL_BIB], r[COL_INRACE], r[COL_PLACE],
                           self.vbunch(r[COL_CBUNCH], r[COL_MBUNCH]),
                           r[COL_COMMENT]])
            idx += 1
        if len(auxtbl) > 1:
            auxtbl.sort(self.sortvbunch)
            self.riders.reorder([a[0] for a in auxtbl])
        return False	# allow idle add

    def __init__(self, meet, event, ui=True):
        self.meet = meet
        self.event = event      # Note: now a treerowref
        self.evno = meet.edb.getvalue(event, eventdb.COL_EVNO)
        self.series = meet.edb.getvalue(event, eventdb.COL_SERIES)
        self.configpath = os.path.join(self.meet.configpath,
                                       'event_' + self.evno)

        self.log = logging.getLogger('scbdo.mstart')
        self.log.setLevel(logging.DEBUG)
        self.log.debug('opening event: ' + str(self.evno))

        # race property attributes

        # race run time attributes
        self.readonly = not ui
        self.start = None
        self.lstart = None
        self.finish = None
        self.winopen = True
        self.timerstat = 'idle'
        self.places = ''
        self.comment = []
        self.ridermark = None

        # Scratch pad status variables - check if needed?
        self.last_scratch = None
        self.scratch_start = None
        self.scratch_last = None
        self.scratch_count = 0
        self.scratch_tot = 0
 
        # lap tracking
        self.scratch_map = {}
        self.scratch_ord = []
        self.live_announce = True

        self.riders = gtk.ListStore(gobject.TYPE_STRING, # BIB = 0
                                    gobject.TYPE_STRING, # NAMESTR = 1
                                    gobject.TYPE_STRING, # CAT = 2
                                    gobject.TYPE_STRING, # COMMENT = 3
                                    gobject.TYPE_BOOLEAN, # INRACE = 4
                                    gobject.TYPE_STRING,  # PLACE = 5
                                    gobject.TYPE_INT,  # LAP COUNT = 6
                                    gobject.TYPE_PYOBJECT, # RFTIME = 7
                                    gobject.TYPE_PYOBJECT, # CBUNCH = 8
                                    gobject.TYPE_PYOBJECT, # MBUNCH = 9
                                    gobject.TYPE_PYOBJECT) # RFSEEN = 10
        self.undomod = gtk.ListStore(gobject.TYPE_STRING, # BIB = 0
                                    gobject.TYPE_STRING, # NAMESTR = 1
                                    gobject.TYPE_STRING, # CAT = 2
                                    gobject.TYPE_STRING, # COMMENT = 3
                                    gobject.TYPE_BOOLEAN, # INRACE = 4
                                    gobject.TYPE_STRING,  # PLACE = 5
                                    gobject.TYPE_INT,  # LAP COUNT = 6
                                    gobject.TYPE_PYOBJECT, # RFTIME = 7
                                    gobject.TYPE_PYOBJECT, # CBUNCH = 8
                                    gobject.TYPE_PYOBJECT, # MBUNCH = 9
                                    gobject.TYPE_PYOBJECT) # RFSEEN = 10
        self.canundo = False
        self.placeundo = None

        # !! does this need a builder? perhaps make directly...
        b = gtk.Builder()
        b.add_from_file(os.path.join(scbdo.UI_PATH, 'rms.ui'))

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
        self.view = t
        uiutil.mkviewcoltxt(t, 'No.', COL_BIB, calign=1.0)
        uiutil.mkviewcoltxt(t, 'Rider', COL_NAMESTR, expand=True,maxwidth=500)
        uiutil.mkviewcoltxt(t, 'Com', COL_COMMENT,
                                cb=self.editcol_cb)
        uiutil.mkviewcolbool(t, 'In', COL_INRACE,
                                cb=self.cr_inrace_toggled, width=50)
        uiutil.mkviewcoltxt(t, 'Laps', COL_LAPS, width=40)
        uiutil.mkviewcoltod(t, 'Bunch', cb=self.showbunch_cb,
                                editcb=self.editbunch_cb,
                                width=50)
        uiutil.mkviewcoltxt(t, 'Place', COL_PLACE, calign=0.5, width=50)
        b.get_object('race_result_win').add(t)

        if ui:
            # connect signal handlers
            b.connect_signals(self)
            self.meet.edb.editevent(event, winopen=True)
            self.meet.rfu.arm()
