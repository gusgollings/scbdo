
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

"""Road handicap race module.

This module provides a class 'rhcp' which implements the 'race'
interface and manages data, timing and rfid for generic road
handicap races.

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

# startlist model columns
COL_BIB = 0
COL_SERIES = 1
COL_NAMESTR = 2
COL_CAT = 3
COL_COMMENT = 4
COL_INRACE = 5
COL_HCAP = 6	# rider's handicap
COL_FINISH = 7  # 'measured' finish stop watch time (rel)
COL_CBUNCH = 8  # 'computed' bunch time
COL_MBUNCH = 9  # 'manual' bunch time
COL_PLACE = 10

# scb function key mappings
key_startlist = 'F6'                 # clear scratchpad (FIX)
key_results = 'F4'                   # recalc/show results? -> todo
key_starters = 'F3'                  # show start list? -> todo

# timing function key mappings
key_armstart = 'F5'                  # arm for start impulse
key_armfinish = 'F9'                 # arm finish

# extended function key mappings
key_reset = 'F5'                     # + ctrl for reset

class rhcp(object):
    """Data handling for road handicap."""
    def key_event(self, widget, event):
        """Race window key press handler."""
        if event.type == gtk.gdk.KEY_PRESS:
            key = gtk.gdk.keyval_name(event.keyval) or 'None'
            if event.state & gtk.gdk.CONTROL_MASK:
                if key == key_reset:    # override ctrl+f5
                    self.resetall()
                    return True
            elif key[0] == 'F':
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

    def getelapsed(self, iter):
        """Return a rider's tod elapsed time."""
        # man, then bunch time minus start oft TODO
        ret = None
        if self.limit_tod is not None:	 # sanity check
            bt = self.riders.get_value(iter, COL_MBUNCH)
            if bt is None:
                bt = self.riders.get_value(iter, COL_CBUNCH)
            st = self.limit_tod - self.riders.get_value(iter, COL_HCAP)
            ret = bt - st
        return ret

    def loadconfig(self):
        """Load race config from disk."""
        self.riders.clear()
        #self.results.clear()

        # defaults
        # +type specific overrides
        cr = ConfigParser.ConfigParser({'startlist':'',
					'start':'',
                                        'lstart':'',
                                        'places':'',
                                        'limit':''
                                       })
        cr.add_section('race')
        cr.add_section('riders')
        if os.path.isfile(self.configpath):
            self.log.debug('Attempting to read config from '
                               + repr(self.configpath))
            cr.read(self.configpath)

        # re-load starters/results
        for rs in cr.get('race', 'startlist').split():
            (r, s) = strops.bibstr2bibser(rs)
            self.addrider(r, s)
            if cr.has_option('riders', rs):
                # bbb.sss = comment,inrace,hcap,finish,mbunch
                nr = self.getrider(r, s)
                ril = csv.reader([cr.get('riders', rs)]).next()
                lr = len(ril)
                if lr > 0:
                    nr[COL_COMMENT] = ril[0]
                if lr > 1:
                    nr[COL_INRACE] = strops.confopt_bool(ril[1])
                if lr > 2:
                    nr[COL_HCAP] = tod.str2tod(ril[2])
                if lr > 3:
                    nr[COL_FINISH] = tod.str2tod(ril[3])
                if lr > 4:
                    nr[COL_MBUNCH] = tod.str2tod(ril[4])
                if nr[COL_HCAP] is None:
                    nr[COL_HCAP] = tod.ZERO		# default to 'scratch'
                if self.limit_tod is not None:
                    if nr[COL_HCAP] > self.limit_tod:
                        self.log.error('Handicap greater than limit for '
                                        + rs + ' set to limit.')
                        nr[COL_HCAP] = self.limit_tod

        places = strops.reformat_bibserplacelist(cr.get('race', 'places'))
#!!!
        #self.ctrl_places.set_text(places)
        #self.ctrl_places.set_sensitive(False)
        #self.recalculate()

        # re-join an existing timer state
        self.set_start(tod.str2tod(cr.get('race', 'start')),
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
#!!! places?

        # save out all starters
        cw.add_section('riders')
        for r in self.riders:
            if r[COL_BIB] != '':
                # place is saved for info only
                wst = ''
                #if r[COL_WALLSTART] is not None:
                    #wst = r[COL_WALLSTART].rawtime()
                tst = ''
                #if r[COL_TODSTART] is not None:
                    #tst = r[COL_TODSTART].rawtime()
                tft = ''
                #if r[COL_TODFINISH] is not None:
                    #tft = r[COL_TODFINISH].rawtime()
                slice = [r[COL_COMMENT], wst, tst, tft, r[COL_PLACE]]
                cw.set('riders', strops.bibser2bibstr(r[COL_BIB], r[COL_SERIES]),
                    ','.join(map(lambda i: str(i).replace(',', '\\,'), slice)))
        self.log.debug('Saving race config to: ' + self.configpath)
        with open(self.configpath, 'wb') as f:
            cw.write(f)

    def get_startlist(self):
        """Return a list of bibs in the rider model as b.s."""
        ret = ''
        for r in self.riders:
            ret += ' ' + strops.bibser2bibstr(r[COL_BIB], r[COL_SERIES])
        return ret.strip()

    def shutdown(self, win=None, msg='Exiting'):
        """Terminate race object."""
        self.log.debug('Race Shutdown: ' + msg)
        if not self.readonly:
            self.meet.rfu.dearm()	# WHAT TO DO HERE??
            self.saveconfig()
        self.meet.edb.editevent(self.event, winopen=False)
        self.winopen = False

    def do_properties(self):
        """Properties placeholder."""
        pass

    def result_export(self, f):
        """Export results to supplied file handle."""
        # TODO
#!!!
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

    def set_start(self, start=None, lstart=None):
        if start is not None:
            if lstart is None:
                lstart = start
            self.start = start
            self.lstart = lstart
            self.timerstat = 'running'
            self.log.info('Timer started @ ' + start.rawtime(2))
            #!TODO -> set ctrl button

    def rfid_trig(self, e):
        """Register RFID crossing."""
        r = self.meet.rdb.getrefid(e.refid)
#!!! COPY FROM ROADRACE(old-scbdo)
        if r is not None:
            bib = self.meet.rdb.getvalue(r, riderdb.COL_BIB)
            series = self.meet.rdb.getvalue(r, riderdb.COL_SERIES)
            lr = self.getrider(bib, series)
            if lr is not None:
#!!!
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
#!!! not really needed?

    def start_trig(self, t):
        """Register start trigger."""
#!!! not really needed?

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
        if self.timerstat == 'running':
            nowoft = (tod.tod('now') - self.lstart).truncate(0)
            # !!! Update stopwatch? or in fast timeout?
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
            nr=[bib, series, '', '', '', True, tod.ZERO, None, None, None, '']
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
        self.riders[path][col] = new_text.strip()

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
#!!! is this relevant to road race? -> for clear of finish time perhaps
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
#!!!@ require road race specific editor dialog?
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

    def title_close_clicked_cb(self, button, entry=None):
        """Close and save the race."""
        self.meet.close_event()

    def set_titlestr(self, titlestr=None):
        """Update the title string label."""
        if titlestr is None or titlestr == '':
            titlestr = 'Road Handicap Race'
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

        self.log = logging.getLogger('scbdo.rhcp')
        self.log.setLevel(logging.DEBUG)
        self.log.debug('Creating new rhcp event: ' + str(self.evno))

        # race run time attributes
        self.limit_tod = None	# Maximum handicap ToD, set on START!
        self.readonly = not ui
        self.winopen = True
        self.timerstat = 'idle'
        self.start = None
        self.lstart = None
        self.riders = gtk.ListStore(gobject.TYPE_STRING,   # 0 bib
                                    gobject.TYPE_STRING,   # 1 series
                                    gobject.TYPE_STRING,   # 2 namestr
                                    gobject.TYPE_STRING,   # 3 cat
                                    gobject.TYPE_STRING,   # 4 comment
                                    gobject.TYPE_BOOLEAN,   # 5 inrace?
                                    gobject.TYPE_PYOBJECT, # 6 hcap
                                    gobject.TYPE_PYOBJECT, # 7 finish
                                    gobject.TYPE_PYOBJECT, # 8 c-bunch
                                    gobject.TYPE_PYOBJECT, # 9 m-bunch
                                    gobject.TYPE_STRING)   # 10 place

        b = gtk.Builder()
        b.add_from_file(os.path.join(scbdo.UI_PATH, 'rhcp.ui'))

        self.frame = b.get_object('race_vbox')
        self.frame.connect('destroy', self.shutdown)

        # meta info pane
        self.title_namestr = b.get_object('title_namestr')
        self.set_titlestr()

        # Control Pane
        # TODO -> ctrl, places, action

        # Result Pane
        t = gtk.TreeView(self.riders)
        self.view = t
        t.set_reorderable(True)
        t.set_rules_hint(True)
        t.connect('button_press_event', self.treeview_button_press)
     
        # TODO: show team name & club but pop up for rider list
        uiutil.mkviewcolbibser(t)
        uiutil.mkviewcoltxt(t, 'Rider', COL_NAMESTR, expand=True)
        #uiutil.mkviewcoltxt(t, 'Cat', COL_CAT, self.editcol_cb)
#!!!
        #uiutil.mkviewcoltod(t, 'Hcap', cb=self.hcapstr, width=60)
        #uiutil.mkviewcoltod(t, 'RFtime', cb=self.rftimestr)
        #uiutil.mkviewcoltod(t, 'Bunch', cb=self.bunchstr)
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

