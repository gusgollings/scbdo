
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

"""Timing and data handling application for track meets at DISC."""

import pygtk
pygtk.require("2.0")

import gtk
import glib
import pango

import os
import sys
import csv
import logging
import ConfigParser

import scbdo

from scbdo import tod
from scbdo import riderdb
from scbdo import eventdb
from scbdo import scbwin
from scbdo import sender
from scbdo import uscbsrv
from scbdo import timy
from scbdo import unt4
from scbdo import strops
from scbdo import loghandler
from scbdo import race
from scbdo import ps
from scbdo import ittt
from scbdo import omnium

LOGHANDLER_LEVEL = logging.DEBUG
DEFANNOUNCE_PORT = ''
CONFIGFILE = 'config.ini'
TRACKMEET_ID = 'trackmeet_1.3'	# configuration versioning

def mkrace(meet, event, ui=True):
    """Return a race object of the correct type."""
    ret = None
    etype = meet.edb.getvalue(event, eventdb.COL_TYPE)
    if etype in ['flying 200', 'flying lap', 'indiv tt',
                 'indiv pursuit', 'pursuit race',
                 'team pursuit', 'team pursuit race']:
        ret = ittt.ittt(meet, event, ui)
    elif etype in ['points', 'madison']:
        ret = ps.ps(meet, event, ui)
    elif etype in ['omnium', 'aggregate']:
        ret = omnium.omnium(meet, event, ui)
    else:
        ret = race.race(meet, event, ui)
    return ret

class trackmeet:
    """Track meet application class."""

    ## Meet Menu Callbacks
    def menu_meet_open_cb(self, menuitem, data=None):
        """Open a new meet."""
        self.close_event()

        dlg = gtk.FileChooserDialog('Open new track meet', self.window,
            gtk.FILE_CHOOSER_ACTION_SELECT_FOLDER, (gtk.STOCK_CANCEL,
            gtk.RESPONSE_CANCEL, gtk.STOCK_OPEN, gtk.RESPONSE_OK))
        response = dlg.run()
        if response == gtk.RESPONSE_OK:
            self.configpath = dlg.get_filename()
            self.loadconfig()
            self.log.debug('Meet data loaded from'
                           + repr(self.configpath) + '.')
        dlg.destroy()

    def get_event(self, evno, ui=False):
        """Return an event object for the given event number."""
        ret = None
        eh = self.edb.getevent(evno)
        if eh is not None:
            ret = mkrace(self, eh, ui)
        return ret

    def menu_meet_save_cb(self, menuitem, data=None):
        """Save current meet data and open event."""
        self.saveconfig()

    def menu_meet_info_cb(self, menuitem, data=None):
        """Display meet information on scoreboard."""
        self.clock.clicked()

    def menu_meet_properties_cb(self, menuitem, data=None):
        """Edit meet properties."""
        b = gtk.Builder()
        b.add_from_file(os.path.join(scbdo.UI_PATH, 'trackmeet_props.ui'))
        dlg = b.get_object('properties')
        dlg.set_transient_for(self.window)
        l1 = b.get_object('meet_line1_entry')
        l1.set_text(self.line1)
        l2 = b.get_object('meet_line2_entry')
        l2.set_text(self.line2)
        l3 = b.get_object('meet_line3_entry')
        l3.set_text(self.line3)
        lo = b.get_object('meet_logos_entry')
        lo.set_text(self.logos)
        rb = b.get_object('data_bib_result')
        rb.set_active(self.bibs_in_results)
        re = b.get_object('data_showevno')
        re.set_active(self.showevno)
        tln = b.get_object('tracklen_total')
        tln.set_value(self.tracklen_n)
        tld = b.get_object('tracklen_laps')
        tldl = b.get_object('tracklen_lap_label')
        tld.connect('value-changed',
                    self.tracklen_laps_value_changed_cb, tldl)
        tld.set_value(self.tracklen_d)
        spe = b.get_object('scb_port_entry')
        spe.set_text(self.scbport)
        upe = b.get_object('uscb_port_entry')
        upe.set_text(self.annport)
        spb = b.get_object('scb_port_dfl')
        spb.connect('clicked', self.set_default, spe, 'SCBDO')
        mte = b.get_object('timing_main_entry')
        mte.set_text(self.main_port)
        mtb = b.get_object('timing_main_dfl')
        mtb.connect('clicked', self.set_default, mte, timy.MAINPORT)
        bte = b.get_object('timing_backup_entry')
        bte.set_text(self.backup_port)
        btb = b.get_object('timing_backup_dfl')
        btb.connect('clicked', self.set_default, bte, timy.BACKUPPORT)
        response = dlg.run()
        if response == 1:	# id 1 set in glade for "Apply"
            self.log.debug('Updating meet properties.')
            self.line1 = l1.get_text()
            self.line2 = l2.get_text()
            self.line3 = l3.get_text()
            self.logos = lo.get_text()
            self.set_title()
            self.bibs_in_results = rb.get_active()
            self.showevno = re.get_active()
            self.tracklen_n = tln.get_value_as_int()
            self.tracklen_d = tld.get_value_as_int()
            nport = spe.get_text()
            if nport != self.scbport:
                self.scbport = nport
                self.scb.setport(nport)
            nport = upe.get_text()
            if nport != self.annport:
                self.annport = nport
                self.announce.set_portstr(self.annport)
            nport = mte.get_text()
            if nport != self.main_port:
                self.main_port = nport
                self.main_timer.setport(nport)
            nport = bte.get_text()
            if nport != self.backup_port:
                self.backup_port = nport
                self.backup_timer.setport(nport)
            self.log.debug('Properties updated.')
        else:
            self.log.debug('Edit properties cancelled.')
        dlg.destroy()

    def menu_meet_fullscreen_toggled_cb(self, button, data=None):
        """Update fullscreen window view."""
        if button.get_active():
            self.window.fullscreen()
        else:
            self.window.unfullscreen()

    def tracklen_laps_value_changed_cb(self, spin, lbl):
        """Laps changed in properties callback."""
        if int(spin.get_value()) > 1:
            lbl.set_text(' laps = ')
        else:
            lbl.set_text(' lap = ')

    def set_default(self, button, dest, val):
        """Update dest to default value val."""
        dest.set_text(val)

    def menu_meet_quit_cb(self, menuitem, data=None):
        """Quit the track meet application."""
        self.running = False
        self.window.destroy()

    ## Race menu callbacks.
    def menu_race_make_activate_cb(self, menuitem, data=None):
        """Create and open a new race of the chosen type."""
        event = self.edb.addempty()
        self.edb.editevent(event, etype=data)
        # Backup an existing config
        oldconf = self.event_configfile(self.edb.getvalue(event,
                                           eventdb.COL_EVNO))
        if os.path.isfile(oldconf):
            os.rename(oldconf, oldconf + '.old')
        self.open_event(event)
        self.menu_race_properties.activate()

    def menu_race_info_activate_cb(self, menuitem, data=None):
        """Show race information on scoreboard."""
        if self.curevent is not None:
            self.scbwin = None
            eh = self.curevent.event
            if self.showevno:
                self.scbwin = scbwin.scbclock(self.scb,
                  'Event ' + self.edb.getvalue(eh, eventdb.COL_EVNO),
                             self.edb.getvalue(eh, eventdb.COL_PREFIX),
                             self.edb.getvalue(eh, eventdb.COL_INFO))
            else:
                self.scbwin = scbwin.scbclock(self.scb,
                                self.edb.getvalue(eh, eventdb.COL_PREFIX),
                                self.edb.getvalue(eh, eventdb.COL_INFO))
            self.scbwin.reset()

    def menu_race_properties_activate_cb(self, menuitem, data=None):
        """Edit properties of open race if possible."""
        if self.curevent is not None:
            self.curevent.do_properties()

    def menu_race_run_activate_cb(self, menuitem=None, data=None):
        """Open currently selected event."""
        eh = self.edb.getselected()
        if eh is not None:
            self.open_event(eh)

    def event_row_activated_cb(self, view, path, col, data=None):
        """Respond to activate signal on event row."""
        self.menu_race_run_activate_cb()

    def menu_race_next_activate_cb(self, menuitem, data=None):
        """Open the next event on the program."""
        if self.curevent is not None:
            nh = self.edb.getnextrow(self.curevent.event)
            if nh is not None:
                self.open_event(nh)
            else:
                self.log.warn('No next event to open.')
        else:
            eh = self.edb.getselected()
            if eh is not None:
                self.open_event(eh)
            else:
                self.log.warn('No next event to open.')

    def menu_race_prev_activate_cb(self, menuitem, data=None):
        """Open the previous event on the program."""
        if self.curevent is not None:
            ph = self.edb.getprevrow(self.curevent.event)
            if ph is not None:
                self.open_event(ph)
            else:
                self.log.warn('No previous event to open.')
        else:
            eh = self.edb.getselected()
            if eh is not None:
                self.open_event(eh)
            else:
                self.log.warn('No previous event to open.')

    def menu_race_close_activate_cb(self, menuitem, data=None):
        """Close currently open event."""
        self.close_event()
    
    def menu_race_abort_activate_cb(self, menuitem, data=None):
        """Close currently open event without saving."""
        if self.curevent is not None:
            self.curevent.readonly = True
        self.close_event()

    def open_event(self, eventhdl=None):
        """Open provided event handle."""
        if eventhdl is not None:
            self.close_event()
            self.curevent = mkrace(self, eventhdl)
            self.curevent.loadconfig()
            self.race_box.add(self.curevent.frame)
            self.menu_race_info.set_sensitive(True)
            self.menu_race_close.set_sensitive(True)
            self.menu_race_abort.set_sensitive(True)
            starters = self.edb.getvalue(eventhdl, eventdb.COL_STARTERS)
            if starters is not None and starters != '':
                self.addstarters(self.curevent, eventhdl, # xfer starters
                                 strops.reformat_biblist(starters))
                self.edb.editevent(eventhdl, starters='') # and clear
            self.curevent.show()

    def addstarters(self, race, event, startlist):
        """Add each of the riders in startlist to the opened race."""
        starters = startlist.split()
        for st in starters:
            race.addrider(st)

    def close_event(self):
        """Close the currently opened race."""
        if self.curevent is not None:
            self.curevent.hide()
            self.race_box.remove(self.curevent.frame)
            self.curevent.destroy()
            self.menu_race_info.set_sensitive(False)
            self.menu_race_close.set_sensitive(False)
            self.menu_race_abort.set_sensitive(False)
            self.curevent = None
        self.ann_default()

    def race_evno_change(self, old_no, new_no):
        """Handle a change in a race number."""
        oldconf = self.event_configfile(old_no)
        if os.path.isfile(oldconf):
            newconf = self.event_configfile(new_no)
            if os.path.isfile(newconf):
                os.rename(newconf, newconf + '.old')
            os.rename(oldconf, newconf)
        self.log.info('Race ' + repr(old_no) + ' changed to ' + repr(new_no))

    ## Data menu callbacks.
    def menu_data_rego_activate_cb(self, menuitem, data=None):
        """Open rider registration dialog."""
        self.log.warn('TODO :: Rider registration dlg...')
        pass

    def menu_data_import_activate_cb(self, menuitem, data=None):
        """Open rider import dialog."""
        self.log.warn('TODO :: Rider import dlg...')
        pass

    def menu_data_export_activate_cb(self, menuitem, data=None):
        """Open rider export dialog."""
        self.log.warn('TODO :: Export proc...')
        # New style:
        #   if not working (or return)
        #   set a working flag
        #   in a thread:
        #       create export dir if required
        #       [opt]create html export
            #       for each event:
            #           write the event analysis file
            #       create the meet summary (aka index)
        #       [opt]create pdf export
        #       [opt]create xls export
        #       clear working flag

    def menu_data_results_cb(self, menuitem, data=None):
        """Export live results to disk."""
        self.log.error('DEPRECATED FUNCTION')
        return False
        
        #rfilename = os.path.join(self.configpath, 'results.csv')
        #with open(rfilename , 'wb') as f:
            #f.write(',' + '\n,'.join((self.line1,
                                      #self.line2,
                                      #self.line3)) + '\n\n')
            #for e in self.edb:
                #r = mkrace(self, e, False)
                #r.loadconfig()
                #r.result_export(f)
                #f.write('\n')
        #self.log.info('Exported meet results to ' + repr(rfilename))

    ## SCB menu callbacks
    def menu_scb_enable_toggled_cb(self, button, data=None):
        """Update scoreboard enable setting."""
        if button.get_active():
            self.scb.set_ignore(False)
            self.scb.setport(self.scbport)
            self.announce.set_portstr(self.annport)
            if self.scbwin is not None:
                self.scbwin.reset()
        else:
            self.scb.set_ignore(True)

    def menu_scb_clock_cb(self, menuitem, data=None):
        """Select timer scoreboard overlay."""
        self.scbwin = None
        self.scb.setoverlay(unt4.OVERLAY_CLOCK)
        self.log.debug('Selected scoreboard timer overlay.')

    def menu_scb_logo_activate_cb(self, menuitem, data=None):
        """Select logo and display overlay."""
        self.scbwin = scbwin.logoanim(self.scb, self.logos)
        self.scbwin.reset()
        self.log.debug('Running scoreboard logo anim.')

    def menu_scb_blank_cb(self, menuitem, data=None):
        """Select blank scoreboard overlay."""
        self.scbwin = None
        self.scb.setoverlay(unt4.OVERLAY_BLANK)
        self.log.debug('Selected scoreboard blank overlay.')

    def menu_scb_test_cb(self, menuitem, data=None):
        """Run the scoreboard test pattern."""
        self.scbwin = scbwin.scbtest(self.scb)
        self.scbwin.reset()
        self.log.debug('Running scoreboard test pattern.')

    def menu_scb_connect_activate_cb(self, menuitem, data=None):
        """Force a reconnect to scoreboard."""
        self.scb.setport(self.scbport)
        self.announce.set_portstr(self.annport)
        self.log.debug('Re-connect scoreboard.')

    ## Timing menu callbacks
    def menu_timing_subtract_activate_cb(self, menuitem, data=None):
        """Run the time of day subtraction dialog."""
        b = gtk.Builder()
        b.add_from_file(os.path.join(scbdo.UI_PATH, 'tod_subtract.ui'))
        ste = b.get_object('timing_start_entry')
        ste.modify_font(pango.FontDescription("monospace"))
        fte = b.get_object('timing_finish_entry')
        fte.modify_font(pango.FontDescription("monospace"))
        nte = b.get_object('timing_net_entry')
        nte.modify_font(pango.FontDescription("monospace"))
        b.get_object('timing_start_now').connect('clicked',
                                                 self.entry_set_now, ste)
        b.get_object('timing_finish_now').connect('clicked',
                                                 self.entry_set_now, fte)
        ste.connect('activate', self.menu_timing_recalc, ste, fte, nte)
        fte.connect('activate', self.menu_timing_recalc, ste, fte, nte)
        dlg = b.get_object('timing')
        dlg.set_transient_for(self.window)
        dlg.run()
        dlg.destroy()

    def entry_set_now(self, button, entry=None):
        """Enter the 'now' time in the provided entry."""
        entry.set_text(tod.tod('now').timestr())
        entry.activate()

    def menu_timing_recalc(self, entry, ste, fte, nte):
        """Update the net time entry for the supplied start and finish."""
        st = tod.str2tod(ste.get_text())
        ft = tod.str2tod(fte.get_text())
        if st is not None and ft is not None:
            ste.set_text(st.timestr())
            fte.set_text(ft.timestr())
            nte.set_text((ft - st).timestr())

    def menu_timing_main_toggled_cb(self, button, data=None):
        """Update the selected primary timer."""
        if button.get_active():
            self.log.info('Selected main timer as race time source')
            self.timer = self.main_timer
        else:
            self.log.info('Selected backup timer as race time source')
            self.timer = self.backup_timer

    def menu_timing_clear_activate_cb(self, menuitem, data=None):
        """Clear memory in attached timing devices."""
        self.main_timer.clrmem()
        self.backup_timer.clrmem()
        self.log.info('Clear attached timer memories')

    def menu_timing_reconnect_activate_cb(self, menuitem, data=None):
        """Reconnect timers and initialise."""
        self.main_timer.setport(self.main_port)
        self.main_timer.sane()
        self.backup_timer.setport(self.backup_port)
        self.backup_timer.sane()
        self.log.info('Re-connect and initialise attached timers.')

    ## Help menu callbacks
    def menu_help_docs_cb(self, menuitem, data=None):
        """Display program help."""
        scbdo.help_docs(self.window)

    def menu_help_about_cb(self, menuitem, data=None):
        """Display scbdo about dialog."""
        scbdo.about_dlg(self.window)
  
    ## Menu button callbacks
    def menu_clock_clicked_cb(self, button, data=None):
        """Handle click on menubar clock."""
        self.scbwin = scbwin.scbclock(self.scb,
                         self.line1, self.line2, self.line3)
        self.scbwin.reset()
        self.log.debug('Displaying meet info and clock on scoreboard.')

    ## Directory utilities
    def event_configfile(self, evno):
        """Return a config filename for the given event no."""
        return os.path.join(self.configpath, 'event_' + str(evno) + '.ini')

    ## Timer callbacks
    def menu_clock_timeout(self):
        """Update time of day on clock button."""
        if not self.running:
            return False
        else:
            tt = tod.tod('now').rawtime(places=0,zeros=True)
            self.clock_label.set_text(tt)
            #self.announce.postxt(0,72,tt)
        return True

    def timeout(self):
        """Update internal state and call into race timeout."""
        if not self.running:
            return False
        if self.curevent is not None:      # this is expected to
            self.curevent.timeout()        # collect any timer events
        else:
            e = self.timer.response()
            while e is not None:           # consume and disregard
                e = self.timer.response()  # timy log will log to TIMER
        if self.scbwin is not None:
            self.scbwin.update()
        return True

    ## Timy utility methods.
    def printimp(self, printimps=True):
        """Enable or disable printing of timing impulses on Timy."""
        self.main_timer.printimp(printimps)
        self.backup_timer.printimp(printimps)

    def timer_log_straight(self, bib, msg, tod, prec=4):
        """Print a tod log entry on the Timy receipt."""
        self.timer.printline('{0:3} {1: >4}: '.format(bib[0:3],
                              str(msg)[0:4]) + tod.timestr(prec))

    def timer_log_msg(self, bib, msg):
        """Print the given msg entry on the Timy receipt."""
        self.timer.printline('{0:3} '.format(bib[0:3]) + str(msg)[0:20])

    def resname(self, bib, first, last, club):
        """Meet switch for bib or no bib in result names."""
        if self.bibs_in_results:
            return strops.resname_bib(bib, first, last, club)
        else:
            return strops.resname(first, last, club)

    def event_string(self, evno):
        """Switch to suppress event no in delayed announce screens."""
        ret = ''
        if self.showevno:
            ret = 'Event ' + str(evno)
        else:
            ret = ' '.join([self.line1, self.line2, self.line3]).strip()
        return ret

    def racenamecat(self, event, slen=None):
        """Concatentate race info for display on scoreboard header line."""
        if slen is None:
            slen = scbdo.SCB_LINELEN
        evno = ''
        if self.showevno:
            evno = 'Ev ' + self.edb.getvalue(event, eventdb.COL_EVNO)
        info = self.edb.getvalue(event, eventdb.COL_INFO)
        prefix = self.edb.getvalue(event, eventdb.COL_PREFIX)
        ret = ' '.join([evno, prefix, info]).strip()
        if len(ret) > slen + 1:
            ret = ' '.join([evno, info]).strip()
        return strops.truncpad(ret, slen)

    ## Announcer methods
    def ann_default(self):
        self.announce.setline(0, strops.truncpad(' '.join([self.line1,
                                 self.line2, self.line3]).strip(), 70, 'c'))

    def ann_title(self, titlestr=''):
        self.announce.setline(0, strops.truncpad(titlestr.strip(), 70, 'c'))

    ## Window methods
    def set_title(self, extra=''):
        """Update window title from meet properties."""
        self.window.set_title('SCBdo :: ' 
               + ' '.join([self.line1, self.line2,
                           self.line3, extra]).strip())
        self.ann_default()

    def meet_destroy_cb(self, window, msg=''):
        """Handle destroy signal and exit application."""
        self.scb.setoverlay(unt4.OVERLAY_CLOCK)
        self.announce.clrall()
        if self.started:
            self.saveconfig()	# should come before event close!
            self.log.info('Meet shutdown: ' + msg)
            self.shutdown(msg)
        self.close_event()
        self.log.removeHandler(self.sh)
        self.log.removeHandler(self.lh)
        if self.loghandler is not None:
            self.log.removeHandler(self.loghandler)
        self.running = False
        gtk.main_quit()

    def key_event(self, widget, event):
        """Collect key events on main window and send to race."""
        if event.type == gtk.gdk.KEY_PRESS:
            key = gtk.gdk.keyval_name(event.keyval) or 'None'
            if event.state & gtk.gdk.CONTROL_MASK:
                key = key.lower()
                if key in ['0','1','2','3','4','5','6','7']:
                    self.timer.trig(int(key), tod.tod('now'))
                    return True
            if self.curevent is not None:
                return self.curevent.key_event(widget, event)
        return False

    def shutdown(self, msg):
        """Cleanly shutdown threads and close application."""
        self.scb.exit(msg)
        self.announce.exit(msg)
        self.main_timer.exit(msg)
        self.backup_timer.exit(msg)
        self.timer.join()	# Wait on closure of main timer thread
        self.announce.join()	# Wait on closure of announce thread
        self.started = False

    def start(self):
        """Start the timer and scoreboard threads."""
        if not self.started:
            self.log.debug('Meet startup.')
            self.scb.start()
            self.announce.start()
            self.main_timer.start()
            self.backup_timer.start()
            self.started = True

    ## Track meet functions
    def saveconfig(self):
        """Save current meet data to disk."""
        cw = ConfigParser.ConfigParser()
        cw.add_section('meet')
        cw.set('meet', 'id', TRACKMEET_ID)
        if self.curevent is not None and self.curevent.winopen:
            self.curevent.saveconfig()
            cw.set('meet', 'curevent', self.curevent.evno)
        cw.set('meet', 'maintimer', self.main_port)
        cw.set('meet', 'backuptimer', self.backup_port)
        if self.timer is self.main_timer:
            cw.set('meet', 'racetimer', 'main')
        else:
            cw.set('meet', 'racetimer', 'backup')
        cw.set('meet', 'scbport', self.scbport)
        cw.set('meet', 'uscbport', self.annport)
        cw.set('meet', 'line1', self.line1)
        cw.set('meet', 'line2', self.line2)
        cw.set('meet', 'line3', self.line3)
        cw.set('meet', 'logos', self.logos)
        if self.showevno:
            cw.set('meet', 'showevno', 'Yes')
        else:
            cw.set('meet', 'showevno', 'No')
        if self.bibs_in_results:
            cw.set('meet', 'resultbibs', 'Yes')
        else:
            cw.set('meet', 'resultbibs', 'No')
        cw.set('meet', 'tracklen_n', str(self.tracklen_n))
        cw.set('meet', 'tracklen_d', str(self.tracklen_d))
        cwfilename = os.path.join(self.configpath, CONFIGFILE)
        self.log.debug('Saving meet config to ' + repr(cwfilename))
        with open(cwfilename , 'wb') as f:
            cw.write(f)
        self.rdb.save(os.path.join(self.configpath, 'riders.csv'))
        self.edb.save(os.path.join(self.configpath, 'events.csv'))

    def loadconfig(self):
        """Load meet config from disk."""
        cr = ConfigParser.ConfigParser({'maintimer':timy.MAINPORT,
                                        'backuptimer':timy.BACKUPPORT,
                                        'racetimer':'main',
                                        'scbport':'SCBDO',
                                        'uscbport':DEFANNOUNCE_PORT,
                                        'showevno':'Yes',
					'resultbibs':'Yes',
                                        'tracklen_n':'250',
                                        'tracklen_d':'1',
                                        'line1':'',
                                        'line2':'',
                                        'line3':'',
                                        'logos':'',
                                        'curevent':'',
                                        'id':''})
        cr.add_section('meet')
        cwfilename = os.path.join(self.configpath, CONFIGFILE)

        # re-set main log file
        if self.loghandler is not None:
            self.log.removeHandler(self.loghandler)
            self.loghandler.close()
            self.loghandler = None
        self.loghandler = logging.FileHandler(
                             os.path.join(self.configpath, 'log'))
        self.loghandler.setLevel(LOGHANDLER_LEVEL)
        self.loghandler.setFormatter(logging.Formatter(
                       '%(asctime)s %(levelname)s:%(name)s: %(message)s'))
        self.log.addHandler(self.loghandler)

        # check for config file
        try:
            a = len(cr.read(cwfilename))
            if a == 0:
                self.log.warn('No config file found - loading default values.')
        except e:
            self.log.error('Error reading meet config: ' + str(e))

        # set main timer port
        nport = cr.get('meet', 'maintimer')
        if nport != self.main_port:
            self.main_port = nport
            self.main_timer.setport(nport)
            self.main_timer.sane()

        # set backup timer port
        nport = cr.get('meet', 'backuptimer')
        if nport != self.backup_port:
            self.backup_port = nport
            self.backup_timer.setport(nport)
            self.backup_timer.sane()

        # choose race timer
        if cr.get('meet', 'racetimer') == 'main':
            if self.timer is self.backup_timer:
                self.menubut_main.activate()
        else:
            if self.timer is self.main_timer:
                self.menubut_backup.activate()

        # choose scoreboard port
        nport = cr.get('meet', 'scbport')
        if self.scbport != nport:
            self.scbport = nport
            self.scb.setport(nport)
        self.annport = cr.get('meet', 'uscbport')
        self.announce.set_portstr(self.annport)
        self.announce.clrall()

        # set meet meta infos, and then copy into text entries
        self.line1 = cr.get('meet', 'line1')
        self.line2 = cr.get('meet', 'line2')
        self.line3 = cr.get('meet', 'line3')
        self.logos = cr.get('meet', 'logos')
        self.set_title()

        # result options
        if cr.get('meet', 'resultbibs').lower() == 'yes':
            self.bibs_in_results = True
        else:
            self.bibs_in_results = False
        if cr.get('meet', 'showevno').lower() == 'yes':
            self.showevno = True
        else:
            self.showevno = False

        # track length
        n = cr.get('meet', 'tracklen_n')
        d = cr.get('meet', 'tracklen_d')
        setlen = False
        if n.isdigit() and d.isdigit():
            n = int(n)
            d = int(d)
            if n > 0 and n < 2000 and d > 0 and d < 10: # sanity check
                self.tracklen_n = n
                self.tracklen_d = d
                setlen = True
        if not setlen:
            self.log.warn('Ignoring invalid track length - default used.')

        self.rdb.clear()
        self.edb.clear()
        self.rdb.load(os.path.join(self.configpath, 'riders.csv'))
        self.edb.load(os.path.join(self.configpath, 'events.csv'))

        cureventno = cr.get('meet', 'curevent')
        if cureventno != '':
            self.open_event(self.edb.getevent(cureventno))

        # After load complete - check config and report. This ensures
        # an error message is left on top of status stack. This is not
        # always a hard fail and the user should be left to determine
        # an appropriate outcome.
        cid = cr.get('meet', 'id')
        if cid != TRACKMEET_ID:
            self.log.error('Meet configuration mismatch: '
                           + repr(cid) + ' != ' + repr(TRACKMEET_ID))

    def get_distance(self, count=None, units='metres'):
        """Convert race distance units to metres."""
        ret = None
        if count is not None:
            try:
                if units == 'metres':
                    ret = int(count)
                elif units == 'laps':
                    ret = self.tracklen_n * int(count)
                    if self.tracklen_d != 1 and self.tracklen_d > 0:
                        ret //= self.tracklen_d
            except (ValueError, TypeError, ArithmeticError), v:
                self.log.warn('Error computing race distance: ' + repr(v))
        return ret

    def __init__(self, configpath=None):
        """Meet constructor."""
        # logger and log handler
        self.log = logging.getLogger('scbdo')
        self.log.setLevel(logging.DEBUG)
        self.loghandler = None	# set in loadconfig to meet dir

        # meet configuration path and options
        if configpath is None:
            configpath = '.'	# None assumes 'current dir'
        self.configpath = configpath
        self.line1 = ''
        self.line2 = ''
        self.line3 = ''
        self.bibs_in_results = True
        self.showevno = True
        self.tracklen_n = 250	# numerator
        self.tracklen_d = 1	# d3nominator
        self.logos = ''		# string list of logo filenames

        # hardware connections
        self.scb = sender.sender('NULL')
        self.announce = uscbsrv.uscbsrv(80)
        self.scbport = 'NULL'
        self.annport = ''
        self.main_timer = timy.timy('', name='main')
        self.main_port = ''
        self.backup_timer = timy.timy('', name='bkup')
        self.backup_port = ''
        self.timer = self.main_timer

        b = gtk.Builder()
        b.add_from_file(os.path.join(scbdo.UI_PATH, 'trackmeet.ui'))
        self.window = b.get_object('meet')
        self.window.connect('key-press-event', self.key_event)
        self.clock = b.get_object('menu_clock')
        self.clock_label = b.get_object('menu_clock_label')
        self.clock_label.modify_font(pango.FontDescription("monospace"))
        self.status = b.get_object('status')
        self.log_buffer = b.get_object('log_buffer')
        self.log_view = b.get_object('log_view')
        self.log_view.modify_font(pango.FontDescription("monospace 9"))
        self.log_scroll = b.get_object('log_box').get_vadjustment()
        self.context = self.status.get_context_id('SCBdo Meet')
        self.menubut_main = b.get_object('menu_timing_main')
        self.menubut_backup = b.get_object('menu_timing_backup')
        self.menu_race_info = b.get_object('menu_race_info')
        self.menu_race_properties = b.get_object('menu_race_properties')
        self.menu_race_close = b.get_object('menu_race_close')
        self.menu_race_abort = b.get_object('menu_race_abort')
        self.race_box = b.get_object('race_box')
        self.new_race_pop = b.get_object('menu_race_new_types')
        b.connect_signals(self)

        # additional obs
        self.scbwin = None

        # run state
        self.running = True
        self.started = False
        self.curevent = None

        # format and connect status and log handlers
        f = logging.Formatter('%(levelname)s:%(name)s: %(message)s')
        self.sh = loghandler.statusHandler(self.status, self.context)
        self.sh.setLevel(logging.INFO)	# show info upon status bar
        self.sh.setFormatter(f)
        self.log.addHandler(self.sh)
        self.lh = loghandler.textViewHandler(self.log_buffer,
                      self.log_view, self.log_scroll)
        self.lh.setLevel(logging.INFO)	# show info up in log view
        self.lh.setFormatter(f)
        self.log.addHandler(self.lh)

        # get rider db and pack into scrolled pane
        self.rdb = riderdb.riderdb()
        b.get_object('rider_box').add(self.rdb.mkview())

        # get event db and pack into scrolled pane
        self.edb = eventdb.eventdb()
        b.get_object('event_box').add(self.edb.mkview())
        self.edb.view.connect('row-activated', self.event_row_activated_cb)
        self.edb.set_evno_change_cb(self.race_evno_change)

	# now, connect each of the race menu types if present in builder
        for etype in self.edb.racetypes:
            lookup = 'mkrace_' + etype.replace(' ', '_')
            mi = b.get_object(lookup)
            if mi is not None:
                mi.connect('activate', self.menu_race_make_activate_cb, etype)

        # start timers
        glib.timeout_add_seconds(1, self.menu_clock_timeout)
        glib.timeout_add(50, self.timeout)

def main():
    """Run the trackmeet application."""
    configpath = None
    # expand config on cmd line to realpath _before_ doing chdir
    if len(sys.argv) > 2:
        print('usage: trackmeet [configdir]\n')
        sys.exit(1)
    elif len(sys.argv) == 2:
        configpath = os.path.realpath(os.path.dirname(sys.argv[1]))

    scbdo.init()
    app = trackmeet(configpath)
    app.loadconfig()
    app.window.show()
    app.start()
    try:
        gtk.main()
    except:
        app.shutdown('Exception from gtk.main()')
        raise

if __name__ == '__main__':
    main()
