
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

"""Individual road time trial module.

This module provides a class 'irtt' which implements the 'race'
interface and manages data, timing and rfid for generic individual
road time trial.

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
from scbdo import wheeltime
from scbdo import tod
from scbdo import uiutil
from scbdo import eventdb
from scbdo import riderdb
from scbdo import strops
from scbdo import timerpane


# rider commands
RIDER_COMMMANDS = {'dns':'Did not start',
                   'dnf':'Did not finish',
                   'add':'Add starters',
                   'del':'Remove starters',
                   'que':'Query riders',
                   'fin':'Final places',
                   'com':'Add comment' }

# startlist model columns
COL_BIB = 0
COL_SERIES = 1
COL_NAMESTR = 2
COL_CAT = 3
COL_COMMENT = 4
COL_WALLSTART = 5
COL_TODSTART = 6
COL_TODFINISH = 7
COL_PLACE = 8

# scb function key mappings
key_startlist = 'F6'                 # clear scratchpad (FIX)
key_results = 'F4'                   # recalc/show results in scratchpad
key_starters = 'F3'                  # show next few starters in scratchpad

# timing function key mappings
key_armsync = 'F1'                   # arm for clock sync start
key_armstart = 'F5'                  # arm for start impulse
key_armfinish = 'F9'                 # arm for finish impulse

# extended function key mappings
key_reset = 'F5'                     # + ctrl for clear/abort
key_falsestart = 'F6'		     # + ctrl for false start
key_abort_start = 'F7'		     # + ctrl abort A
key_abort_finish = 'F8'		     # + ctrl abort B

class irtt(object):
    """Data handling for road time trial."""
    def key_event(self, widget, event):
        """Race window key press handler."""
        if event.type == gtk.gdk.KEY_PRESS:
            key = gtk.gdk.keyval_name(event.keyval) or 'None'
            if event.state & gtk.gdk.CONTROL_MASK:
                if key == key_reset:    # override ctrl+f5
                    self.resetall()
                    return True
                elif key == key_falsestart:	# false start both lanes
                    #self.falsestart()
                    return True
                elif key == key_abort_start:	# abort start line
                    #self.abortstarter()
                    return True
                elif key == key_abort_finish:	# abort finish line
                    #self.abortfinisher()
                    return True
            if key[0] == 'F':
                if key == key_armstart:
                    self.armstart()
                    return True
                elif key == key_armfinish:
                    self.armfinish()
                    return True
                elif key == key_startlist:
                    self.meet.scratch_clear()
                    return True
                elif key == key_results:
                    #self.showresults()
                    return True
        return False

    def resetall(self):
        self.start = None
        self.lstart = None
        self.sl.toidle()
        self.sl.disable()
        self.fl.toidle()
        self.fl.disable()
        self.timerstat = 'idle'
        self.meet.timer.dearm(0)	# 'unarm'
        self.meet.timer.dearm(1)	# 'unarm'
        self.log.info('Reset to IDLE')

    def armfinish(self):
        if self.timerstat == 'running':
            if self.fl.getstatus() != 'finish' and self.fl.getstatus() != 'armfin':
                self.meet.timer.arm(1)
                self.fl.toarmfin()
            else:
                self.meet.timer.dearm(1)
                self.fl.toidle()

    def armstart(self):
        if self.timerstat == 'idle':
            self.log.info('Armed for timing sync.')
            self.timerstat = 'armstart'
            self.meet.timer.arm(0)	# 'arm'
        elif self.timerstat == 'armstart':
            self.resetall()
        elif self.timerstat == 'running':
            if self.sl.getstatus() in ['armstart', 'running']:
                self.meet.timer.dearm(0) # 'arm'
                self.sl.toidle()
            elif self.sl.getstatus() != 'running':
                self.meet.timer.arm(0)	# 'arm'
                self.sl.toarmstart()

    def wallstartstr(self, col, cr, model, iter, data=None):
        """Format start time into text for listview."""
        st = model.get_value(iter, COL_WALLSTART)
        if st is not None:
            cr.set_property('text', st.timestr(0).rstrip()) 
        else:
            cr.set_property('text', '')

    def getelapsed(self, iter):
        """Return a tod elapsed time."""
        ret = None
        ft = self.riders.get_value(iter, COL_TODFINISH)
        if ft is not None:
            st = self.riders.get_value(iter, COL_TODSTART)
            if st is None: # defer to start time
                st = self.riders.get_value(iter, COL_WALLSTART)
            if st is not None:	# still none is error
                ret = (ft - st)
        return ret

    def elapstr(self, col, cr, model, iter, data=None):
        """Format elapsed time into text for listview."""
        ft = model.get_value(iter, COL_TODFINISH)
        if ft is not None:
            st = model.get_value(iter, COL_TODSTART)
            if st is None: # defer to strart time
                st = model.get_value(iter, COL_WALLSTART)
                cr.set_property('style', pango.STYLE_OBLIQUE)
            else:
                cr.set_property('style', pango.STYLE_NORMAL)
            if st is not None:	# still none is error
                cr.set_property('text', (ft - st).timestr(2))
            else:
                cr.set_property('text', '[ERR]')
                bib = self.riders.get_value(iter, COL_BIB)
                series = self.riders.get_value(iter, COL_SERIES)
        else:
            cr.set_property('text', '')

    def loadconfig(self):
        """Load race config from disk."""
        self.riders.clear()
        self.results.clear()

        # failsafe defaults -> dual timer, C0 start, PA/PB
        # type specific overrides

        cr = ConfigParser.ConfigParser({'startlist':'',
					'start':'',
                                        'lstart':''
                                       })
        cr.add_section('race')
        cr.add_section('riders')
        if os.path.isfile(self.configpath):
            self.log.debug('Attempting to read config from '
                               + repr(self.configpath))
            cr.read(self.configpath)

        # re-load starters/results
        self.onestart = False
        for rs in cr.get('race', 'startlist').split():
            (r, s) = strops.bibstr2bibser(rs)
            self.addrider(r, s)
            wst = None
            tst = None
            ft = None
            if cr.has_option('riders', rs):
                # bbb.sss = comment,wall_start,timy_start,finish,place
                nr = self.getrider(r, s)
                ril = csv.reader([cr.get('riders', rs)]).next()
                lr = len(ril)
                if lr > 0:
                    nr[COL_COMMENT] = ril[0]
                if lr > 1:
                    wst = tod.str2tod(ril[1])
                if lr > 2:
                    tst = tod.str2tod(ril[2])
                if lr > 3:
                    ft = tod.str2tod(ril[3])
            nri = self.getiter(r, s)
            self.settimes(nri, wst, tst, ft, doplaces=False)
        self.placexfer()

        # re-join any existing timer state -> no, just do a start
        self.set_syncstart(tod.str2tod(cr.get('race', 'start')),
                           tod.str2tod(cr.get('race', 'lstart')))

    def saveconfig(self):
        """Save race to disk."""
        if self.readonly:
            self.log.error('Attempt to save readonly ob.')
            return
        cw = ConfigParser.ConfigParser()

        # save basic race properties
        cw.add_section('race')
        tstr = ''
        if self.start is not None:
            tstr = self.start.rawtime()
        lstr = ''
        if self.lstart is not None:
            lstr = self.lstart.rawtime()
        cw.set('race', 'start', tstr)
        cw.set('race', 'lstart', lstr)
        cw.set('race', 'startlist', self.get_startlist())

        # save out all starters
        cw.add_section('riders')
        for r in self.riders:
            if r[COL_BIB] != '':
                # place is saved for info only
                wst = ''
                if r[COL_WALLSTART] is not None:
                    wst = r[COL_WALLSTART].rawtime()
                tst = ''
                if r[COL_TODSTART] is not None:
                    tst = r[COL_TODSTART].rawtime()
                tft = ''
                if r[COL_TODFINISH] is not None:
                    tft = r[COL_TODFINISH].rawtime()
                slice = [r[COL_COMMENT], wst, tst, tft, r[COL_PLACE]]
                cw.set('riders', strops.bibser2bibstr(r[COL_BIB], r[COL_SERIES]),
                    ','.join(map(lambda i: str(i).replace(',', '\\,'), slice)))
        self.log.debug('Saving race config to: ' + self.configpath)
        with open(self.configpath, 'wb') as f:
            cw.write(f)

    def get_ridercmds(self):
        """Return a dict of rider bib commands for container ui."""
        ## TODO: Append points classifications to commands.
        return RIDER_COMMMANDS

    def get_startlist(self):
        """Return a list of bibs in the rider model as b.s."""
        ret = ''
        for r in self.riders:
            ret += ' ' + strops.bibser2bibstr(r[COL_BIB], r[COL_SERIES])
        return ret.strip()

    def shutdown(self, win=None, msg='Exiting'):
        """Terminate race object."""
        self.log.debug('Race Shutdown: ' + msg)
        self.meet.rfu.dearm()
        #self.meet.menu_race_properties.set_sensitive(False)
        if not self.readonly:
            self.saveconfig()
        self.meet.edb.editevent(self.event, winopen=False)
        self.winopen = False

    def do_properties(self):
        """Properties placeholder."""
        pass

    def result_export(self, f):
        """Export results to supplied file handle."""
        # TODO
        cr = csv.writer(f)
        cr.writerow(['rank', 'bib', 'rider', 'time'])
        for r in self.riders:
            bibstr = strops.bibser2bibstr(r[COL_BIB], r[COL_SERIES])
            i = self.getiter(r[COL_BIB], r[COL_SERIES])
            ft = self.getelapsed(i)
            fs = ''
            if ft is not None:
                fs = "'" + ft.rawtime(2, zeros=True)
            cr.writerow([r[COL_PLACE], bibstr, r[COL_NAMESTR], fs])

    def main_loop(self, cb):
        """Run callback once in main loop idle handler."""
        cb('')
        return False

    def set_syncstart(self, start=None, lstart=None):
        if start is not None:
            if lstart is None:
                lstart = start
            self.start = start
            self.lstart = lstart
            self.timerstat = 'running'
            self.log.info('Timer sync @ ' + start.rawtime(2))
            self.sl.toidle()
            self.fl.toidle()

    def rfid_trig(self, e):
        """Register RFID crossing."""
        r = self.meet.rdb.getrefid(e.refid)
        if r is not None:
            bib = self.meet.rdb.getvalue(r, riderdb.COL_BIB)
            series = self.meet.rdb.getvalue(r, riderdb.COL_SERIES)
            lr = self.getrider(bib, series)
            if lr is not None:
                bibstr = strops.bibser2bibstr(lr[COL_BIB], lr[COL_SERIES])
                self.meet.scratch_log(' '.join([
                   bibstr.ljust(5),
                   strops.truncpad(lr[COL_NAMESTR], 30)
                                              ]))
                if self.fl.getstatus() in ['idle', 'finish']:
                    if bibstr in self.recent_starts:
                        self.fl.setrider(lr[COL_BIB], lr[COL_SERIES])
                        self.fl.toload()
                        del self.recent_starts[bibstr]
                    else:
                        self.log.info('Ignoring unseen rider: ' + bibstr
                                      + '@' + e.rawtime(1))
            else:
                self.log.info('Non start rider: ' + bib + '.' + series + '@'
                               + e.rawtime(1))
        else:
            self.log.info('Unkown tag: ' + e.refid + '@' + e.rawtime(1))


    def fin_trig(self, t):
        """Register finish trigger."""
        if self.timerstat == 'running':
            if self.fl.getstatus() == 'armfin':
                bib = self.fl.bibent.get_text()
                series = self.fl.serent.get_text()
                i = self.getiter(bib, series)
                if i is not None:
                    self.settimes(i, tst=self.riders.get_value(i,
                                                COL_TODSTART), tft=t)
                    self.fl.tofinish()
                    ft = self.getelapsed(i)
                    if ft is not None:
                        self.fl.set_time(ft.timestr(2))
                        self.meet.scratch_log(' '.join([
                           strops.bibser2bibstr(bib, series).ljust(5),
                           strops.truncpad(self.riders.get_value(i,
                                  COL_NAMESTR), 20),
                           ft.timestr(2),
                           '(' + str(self.results.rank(bib, series) + 1) + ')'
                                                      ]))
                    else:
                        self.fl.set_time('[err]')

                else:
                    self.log.error('Missing rider at finish')
                    self.sl.toidle()
        elif self.timerstat == 'armstart':
            self.set_syncstart(t)

    def start_trig(self, t):
        """Register start trigger."""
        if self.timerstat == 'running':
            # check lane to apply pulse.
            if self.sl.getstatus() == 'armstart':
                i = self.getiter(self.sl.bibent.get_text(),
                                 self.sl.serent.get_text())
                if i is not None:
                    self.settimes(i, tst=t)
                    self.sl.torunning()
                else:
                    self.log.error('Missing rider at start')
                    self.sl.toidle()
            pass
        elif self.timerstat == 'armstart':
            self.set_syncstart(t, tod.tod('now'))

    def add_starter(self, bibid):
        self.recent_starts[bibid]=tod.tod('now')
        return False	# run once only

    def on_start(self, curoft):
        for i in self.unstarters:
            if curoft + tod.tod('10') == self.unstarters[i]:
                self.log.info('about to load rider ' + i)
                (bib, series) = strops.bibstr2bibser(i)
                #!!! TODO -> use bib.ser ?
                self.sl.setrider(bib, series)
                self.sl.toarmstart()
                self.meet.timer.arm(0)
                self.start_unload = self.unstarters[i] + tod.tod('10')
                glib.timeout_add_seconds(180, self.add_starter, i)
                break

    def slow_timeout(self):
        """Update slow changing aspects of race."""
        if not self.winopen:
            return False
        if self.timerstat == 'running':
            nowoft = (tod.tod('now') - self.lstart).truncate(0)
            if self.sl.getstatus() == 'idle':
                if nowoft.timeval % 10 == tod.tod('0'):	# every ten.
                    self.on_start(nowoft)
            else:
                if nowoft == self.start_unload:
                    self.sl.toidle()

            # after manips, then re-set start time
            self.sl.set_time(nowoft.timestr(0))
                
            
        # maintain expiry of 'not finishing' set -> ~120 secs after start
        # loads starters into start channel and arm
	# clear starters from start channel
        pass

    def timeout(self):
        """Respond to timing events."""
        if not self.winopen:
            return False
        # Collect any queued timing impulses
        e = self.meet.timer.response()
        while e is not None:
            chan = e.chan[0:2]
            if chan == 'C0':
                self.start_trig(e)
            elif chan == 'C1':
                self.fin_trig(e)
            e = self.meet.timer.response()
        # Collect any RFID triggers
        e = self.meet.rfu.response()
        while e is not None:
            self.rfid_trig(e)
            e = self.meet.rfu.response()
        return True

    def clearplaces(self):
        """Clear rider places."""
        for r in self.riders:
            r[COL_PLACE] = ''

    def getrider(self, bib, series=''):
        """Return temporary reference to model row."""
        ret = None
        for r in self.riders:
            if r[COL_BIB] == bib and r[COL_SERIES] == series:
                ret = r
                break
        return ret

    def addrider(self, bib='', series=''):
        """Add specified rider to race model."""
        if bib == '' or self.getrider(bib, series) is None:
            nr=[bib, series, '', '', '', None, None, None, '']
            dbr = self.meet.rdb.getrider(bib, series)
            if dbr is not None:
                nr[COL_NAMESTR] = strops.listname(
                      self.meet.rdb.getvalue(dbr, riderdb.COL_FIRST),
                      self.meet.rdb.getvalue(dbr, riderdb.COL_LAST),
                      self.meet.rdb.getvalue(dbr, riderdb.COL_CLUB))
                nr[COL_CAT] = self.meet.rdb.getvalue(dbr, riderdb.COL_CAT)
            return self.riders.append(nr)
        else:
            return None

    def editcol_cb(self, cell, path, new_text, col):
        """Update value in edited cell."""
        new_text = new_text.strip()
        if col == COL_BIB:
            if new_text.isalnum():
                if self.getrider(new_text,
                                  self.riders[path][COL_SERIES]) is None:
                    self.riders[path][COL_BIB] = new_text
                    dbr = self.meet.rdb.getrider(new_text, self.series)
                    if dbr is not None:
                        nr[COL_NAMESTR] = strops.listname(
                              self.meet.rdb.getvalue(dbr, riderdb.COL_FIRST),
                              self.meet.rdb.getvalue(dbr, riderdb.COL_LAST),
                              self.meet.rdb.getvalue(dbr, riderdb.COL_CLUB))
                        nr[COL_CAT] = self.meet.rdb.getvalue(dbr, 
                                                   riderdb.COL_CAT)
        else:
            self.riders[path][col] = new_text.strip()

    def placexfer(self):
        """Transfer places into model."""
        self.clearplaces()
        count = 0
        place = 1
        lt = None
        for t in self.results:
            i = self.getiter(t.refid, t.index)
            if i is not None:
                if lt is not None:
                    if lt != t:
                        place = count + 1
                self.riders.set_value(i, COL_PLACE, str(place))
                self.riders.swap(self.riders.get_iter(count), i)
                count += 1
                lt = t
            else:
                self.log.error('Extra result for rider' 
                                + strops.bibser2bibstr(t.refid, t.index))
            
    def getiter(self, bib, series=''):
        """Return temporary iterator to model row."""
        i = self.riders.get_iter_first()
        while i is not None:
            if self.riders.get_value(i,
                     COL_BIB) == bib and self.riders.get_value(i,
                     COL_SERIES) == series:
                break
            i = self.riders.iter_next(i)
        return i

    def unstart(self, bib='', series='', wst=None):
        """Register a rider as not yet started."""
        idx = strops.bibser2bibstr(bib, series)
        self.unstarters[idx] = wst

    def oncourse(self, bib='', series=''):
        """Remove rider from the not yet started list."""
        idx = strops.bibser2bibstr(bib, series)
        if idx in self.unstarters:
            del(self.unstarters[idx])
        
    def settimes(self, iter, wst=None, tst=None, tft=None, doplaces=True):
        """Transfer race times into rider model."""
        bib = self.riders.get_value(iter, COL_BIB)
        series = self.riders.get_value(iter, COL_SERIES)

        # clear result for this bib
        self.results.remove(bib, series)

        # assign tods
        if wst is not None:	# Don't clear a set wall start time!
            self.riders.set_value(iter, COL_WALLSTART, wst)
        else:
            wst = self.riders.get_value(iter, COL_WALLSTART)
        self.unstart(bib, series, wst)	# reg ignorer
        # but allow others to be cleared no worries
        self.riders.set_value(iter, COL_TODSTART, tst)
        self.riders.set_value(iter, COL_TODFINISH, tft)

        # save result
        if tft is not None:
            if tst is not None:		# got a start trigger
                self.results.insert(tft - tst, bib, series)
            elif wst is not None:	# start on wall time
                self.results.insert(tft - wst, bib, series)
            else:
                self.log.error('No start time for rider '
                                + strops.bibser2bibstr(bib, series))
        elif tst is not None:
            self.oncourse(bib, series)	# started but not finished

        # if reqd, do places
        if doplaces:
            self.placexfer()

    def bibent_cb(self, entry, tp):
        """Bib entry callback."""
        bib = tp.bibent.get_text().strip()
        series = tp.serent.get_text().strip()
        tp.biblbl.set_text(self.lanelookup(bib, series))
    
    def lanelookup(self, bib=None, series=''):
        """Prepare name string for timer lane."""
        r = self.getrider(bib, series)
        if r is None:
            self.addrider(bib, series)
            rtxt = '[New Rider]'
        else:
            rtxt = strops.truncpad(r[COL_NAMESTR], 35)
        return rtxt
        
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
            self.settimes(sel[1])	# clear iter to empty vals
            self.log_clear(self.riders.get_value(sel[1], COL_BIB),
                           self.riders.get_value(sel[1], COL_SERIES))

    def now_button_clicked_cb(self, button, entry=None):
        """Set specified entry to the 'now' time."""
        if entry is not None:
            entry.set_text(tod.tod('now').timestr())

    def tod_context_edit_activate_cb(self, menuitem, data=None):
        """Run edit time dialog."""
        sel = self.view.get_selection().get_selected()
        if sel is not None:
            i = sel[1]	# grab off row iter and read in cur times
            tst = self.riders.get_value(i, COL_TODSTART)
            tft = self.riders.get_value(i, COL_TODFINISH)

            # prepare text entry boxes
            st = ''
            if tst is not None:
                st = tst.timestr()
            ft = ''
            if tft is not None:
                ft = tft.timestr()

            # run the dialog
            (ret, st, ft) = uiutil.edit_times_dlg(self.meet.window, st, ft)
            if ret == 1:
                stod = tod.str2tod(st)
                ftod = tod.str2tod(ft)
                bib = self.riders.get_value(i, COL_BIB)
                series = self.riders.get_value(i, COL_SERIES)
                self.settimes(i, tst=stod, tft=ftod) # update model
                self.log.info('Race times manually adjusted for rider '
                               + strops.bibser2bibstr(bib, series))
            else:
                self.log.info('Edit race times cancelled.')

    def tod_context_del_activate_cb(self, menuitem, data=None):
        """Delete selected row from race model."""
        sel = self.view.get_selection().get_selected()
        if sel is not None:
            i = sel[1]	# grab off row iter
            self.settimes(i) # clear times
            if self.riders.remove(i):
                pass	# re-select?

    def log_clear(self, bib, series):
        """Print clear time log."""
        self.log.info('Time cleared for rider ' + strops.bibser2bibstr(bib, series))

    def title_close_clicked_cb(self, button, entry=None):
        """Close and save the race."""
        self.meet.close_event()

    def set_titlestr(self, titlestr=None):
        """Update the title string label."""
        if titlestr is None or titlestr == '':
            titlestr = 'Individual Road Time Trial'
        self.title_namestr.set_text(titlestr)

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
        self.configpath = os.path.join(self.meet.configpath,
                                       'event_' + self.evno)

        self.log = logging.getLogger('scbdo.irtt')
        self.log.setLevel(logging.DEBUG)
        self.log.debug('Creating new irtt event: ' + str(self.evno))

        # properties

        # race run time attributes
        self.onestart = False
        self.readonly = not ui
        self.winopen = True
        self.timerstat = 'idle'
        self.start = None
        self.lstart = None
        self.start_unload = None
        self.results = tod.todlist('NET')
        self.unstarters = {}
        self.curfintod = None
        self.recent_starts = {}

        self.riders = gtk.ListStore(gobject.TYPE_STRING,   # 0 bib
                                    gobject.TYPE_STRING,   # 1 series
                                    gobject.TYPE_STRING,   # 2 namestr
                                    gobject.TYPE_STRING,   # 3 cat
                                    gobject.TYPE_STRING,   # 4 comment
                                    gobject.TYPE_PYOBJECT, # 5 wstart
                                    gobject.TYPE_PYOBJECT, # 6 tstart
                                    gobject.TYPE_PYOBJECT, # 7 finish
                                    gobject.TYPE_STRING)   # 8 place

        b = gtk.Builder()
        b.add_from_file(os.path.join(scbdo.UI_PATH, 'irtt.ui'))

        self.frame = b.get_object('race_vbox')
        self.frame.connect('destroy', self.shutdown)

        # meta info pane
        self.title_namestr = b.get_object('title_namestr')
        self.set_titlestr()

        # Timer Panes
        mf = b.get_object('race_timer_pane')
        self.sl = timerpane.timerpane('Start Line', doser=True)
        self.sl.disable()
        self.sl.bibent.connect('activate', self.bibent_cb, self.sl)
        self.sl.serent.connect('activate', self.bibent_cb, self.sl)
        self.fl = timerpane.timerpane('Finish Line', doser=True)
        self.fl.disable()
        self.fl.bibent.connect('activate', self.bibent_cb, self.fl)
        self.fl.serent.connect('activate', self.bibent_cb, self.fl)
        mf.pack_start(self.sl.frame)
        mf.pack_start(self.fl.frame)
        mf.set_focus_chain([self.sl.frame, self.fl.frame, self.sl.frame])

        # Result Pane
        t = gtk.TreeView(self.riders)
        self.view = t
        t.set_reorderable(True)
        t.set_rules_hint(True)
        t.connect('button_press_event', self.treeview_button_press)
     
        # TODO: show team name & club but pop up for rider list
        uiutil.mkviewcolbibser(t)
        uiutil.mkviewcoltxt(t, 'Rider', COL_NAMESTR, expand=True)
        uiutil.mkviewcoltxt(t, 'Cat', COL_CAT, self.editcol_cb)
# -> Add in start time field with edit!
        uiutil.mkviewcoltod(t, 'Start', cb=self.wallstartstr, width=90)
        uiutil.mkviewcoltod(t, 'Time', cb=self.elapstr)
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
            self.meet.edb.editevent(event, winopen=True)
            self.meet.rfu.arm()

