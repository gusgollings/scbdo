
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

"""Timing and data handling application wrapper for CSV road events."""

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
import random

import scbdo

from scbdo import tod
from scbdo import eventdb
from scbdo import riderdb
from scbdo import wheeltime
from scbdo import timy
from scbdo import uscbsrv
from scbdo import unt4
from scbdo import strops
from scbdo import loghandler
from scbdo import printops
from scbdo import uiutil

LOGHANDLER_LEVEL = logging.DEBUG
ROADRACE_TYPES = {'irtt':'Road Time Trial',
                  'rms':'Road Race',
                  'rhcp':'Handicap',
                  'sportif':'Sportif Ride'}

class roadmeet:
    """Road meet application class."""

    ## Meet Menu Callbacks
    def menu_meet_open_cb(self, menuitem, data=None):
        """Open a new meet."""
        if self.curevent is not None:
            self.close_event()

        dlg = gtk.FileChooserDialog('Open new road meet', self.window,
            gtk.FILE_CHOOSER_ACTION_SELECT_FOLDER, (gtk.STOCK_CANCEL,
            gtk.RESPONSE_CANCEL, gtk.STOCK_OPEN, gtk.RESPONSE_OK))
        response = dlg.run()
        if response == gtk.RESPONSE_OK:
            self.configpath = dlg.get_filename()
            self.loadconfig()
            self.log.info('Meet data loaded from'
                           + repr(self.configpath) + '.')
        else:
            self.log.info('Load new meet cancelled.')
        dlg.destroy()

    def menu_meet_save_cb(self, menuitem, data=None):
        """Save current all meet data to config."""
        self.saveconfig()
        self.log.info('Meet data saved to ' + repr(self.configpath) + '.')

    def menu_meet_properties_cb(self, menuitem, data=None):
        """Edit meet properties."""
        b = gtk.Builder()
        b.add_from_file(os.path.join(scbdo.UI_PATH, 'roadmeet_props.ui'))
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
        #rb = b.get_object('data_bib_result')
        #rb.set_active(self.bibs_in_results)
        rg = b.get_object('data_cat_result')
        rg.set_active(self.cats_in_results)
        rd = b.get_object('data_distance')
        rd.set_value(self.distance)
        mte = b.get_object('timing_main_entry')
        mte.set_text(self.timer_port)
        mtb = b.get_object('timing_main_dfl')
        mtb.connect('clicked', self.set_default, mte, timy.MAINPORT)
        rfe = b.get_object('timing_rfu_entry')
        rfe.set_text(self.rfu_addr)
        rfb = b.get_object('timing_rfu_dfl')
        rfb.connect('clicked', self.set_default, rfe, wheeltime.WHEELIP)
        response = dlg.run()
        if response == 1:	# id 1 set in glade for "Apply"
            self.log.debug('Updating meet properties.')
            self.line1 = l1.get_text()
            self.line2 = l2.get_text()
            self.line3 = l3.get_text()
            self.logos = lo.get_text()
            self.set_title()
            #self.bibs_in_results = rb.get_active()
            self.cats_in_results = rg.get_active()
            self.distance = rd.get_value_as_int()
            nport = mte.get_text()
            if nport != self.timer_port:
                self.timer_port = nport
                self.timer.setport(nport)
            nport = rfe.get_text()
            if nport != self.rfu_addr:
                self.rfu_addr = nport
                self.rfu.setaddr(nport)
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

    def set_default(self, button, dest, val):
        """Update dest to default value val."""
        dest.set_text(val)

    def print_report(self, title='', lines=[], header=''):
        """Print the pre-formatted text lines in a standard report."""
        self.log.info('Printing report ' + repr(title) + '...')

        ptupl = (title, lines, header)

        print_op = gtk.PrintOperation()
        print_op.set_print_settings(self.printprefs)
        print_op.connect("begin_print", self.begin_print, ptupl)
        print_op.connect("draw_page", self.draw_print_page, ptupl)
        res = print_op.run(gtk.PRINT_OPERATION_ACTION_PREVIEW,
                               self.window)
        self.docindex += 1
        return False

    def begin_print(self,  operation, context, ptupl=('',[],'')):
        """Set print pages and units."""
        (title, lines, header) = ptupl

        pg_cnt = 1		# at least one page even for no data
        if len(lines) > 54:	# define these consts??!
            a = len(lines) - 54
            (q, r) = divmod(a, 54)
            pg_cnt += q
            if r > 0:
                 pg_cnt += 1

        operation.set_n_pages(pg_cnt)
        operation.set_unit('points')

    def draw_print_page(self, operation, context, page_nr, ptupl=('',[],'')):
        """Use printops to draw to the nominated page."""
        import datetime
        (title, lines, header) = ptupl
        cr = context.get_cairo_context()
        width = context.get_width()
        height = context.get_height()
        pg_cnt = operation.get_property('n-pages')
        mainstr = ' '.join([self.line1, self.line2,
                              self.line3])
        if page_nr == 0:
            sid = 0
            pglen = 54
        else:
            sid = 54 + (page_nr - 1)*54
            pglen = 54

        # 'major' sponsor
        lfile = os.path.join(self.configpath, 'logo.jpg')
        if os.path.isfile(lfile):
            printops.pixmap(cr, lfile, 0, 0, h=40)

        # 'minor' sponsor
        lfile = os.path.join(self.configpath, 'sublogo.jpg')
        if os.path.isfile(lfile):
            printops.pixmap(cr, lfile, width, 0, h=40, align='r')

        printops.header(cr, context, width, mainstr, title)

        if header != '':
            header = header.rstrip() + '\n'
        msg = header + '\n'
        mx = len(lines)
        if sid+pglen < mx:
            mx = sid+pglen
        for i in range(sid, mx):
            msg += lines[i] + '\n'
        printops.bodyblock(cr, context, width, msg, True)
        d = datetime.date.today()
        lmsg = d.strftime("%A %d. %B %Y")
        rmsg = 'Page ' + str(page_nr + 1) + ' of ' + str(pg_cnt)

        # position footer and logo if present. Assumes reasonable aspect in
        # footer image - TODO: auto choose scale factor in printops.pixmap
        footy = 15
        lfile = os.path.join(self.configpath, 'footer.jpg')
        if os.path.isfile(lfile):
            printops.pixmap(cr, lfile, width//2, height-42, w=width, align='c')
            footy = 45
        printops.footer(cr, context, width, height, lmsg, rmsg, footy)

    def menu_meet_printprefs_activate_cb(self, menuitem=None, data=None):
        """Edit the printer properties."""
        dlg = gtk.PrintOperation()
        dlg.set_print_settings(self.printprefs)
        res = dlg.run(gtk.PRINT_OPERATION_ACTION_PRINT_DIALOG, self.window)
        if res == gtk.PRINT_OPERATION_RESULT_APPLY:
            self.printprefs = dlg.get_print_settings()
            self.log.info('Updated print preferences.')

    def menu_meet_quit_cb(self, menuitem, data=None):
        """Quit the application."""
        self.running = False
        self.window.destroy()

    ## Race Menu Callbacks
    def menu_race_run_activate_cb(self, menuitem=None, data=None):
        """Open the event handler."""
        eh = self.edb.getevent() # only one event
        if eh is not None:
            self.open_event(eh)

    def menu_race_close_activate_cb(self, menuitem, data=None):
        """Close callback - disabled in roadrace."""
        pass
    
    def menu_race_abort_activate_cb(self, menuitem, data=None):
        """Close the currently open event without saving."""
        if self.curevent is not None:
            self.curevent.readonly = True
        self.close_event()

    def open_event(self, eventhdl=None):
        """Open provided event handle."""
        if eventhdl is not None:
            self.close_event()
            if self.etype == 'irtt':
                from scbdo import irtt
                self.curevent = irtt.irtt(self, eventhdl, True)
            elif self.etype == 'sportif':
                from scbdo import sportif
                self.curevent = sportif.sportif(self, eventhdl, True)
            else:	# default is fall back to road mass start 'rms'
                from scbdo import rms
                self.curevent = rms.rms(self, eventhdl, True)
            
            assert(self.curevent is not None)
            self.curevent.loadconfig()
            self.race_box.add(self.curevent.frame)

            # re-populate the rider command model.
            cmds = self.curevent.get_ridercmds()
            if cmds is not None:
                self.action_model.clear()
                for cmd in cmds:
                    self.action_model.append([cmd, cmds[cmd]])
                self.action_combo.set_active(0)

            self.menu_race_close.set_sensitive(True)
            self.menu_race_abort.set_sensitive(True)
            starters = self.edb.getvalue(eventhdl, eventdb.COL_STARTERS)
            if starters is not None and starters != '':
                self.addstarters(self.curevent, eventhdl, # xfer starters
                                 strops.reformat_bibserlist(starters))
                self.edb.editevent(eventhdl, starters='') # and clear
            self.curevent.show()
            self.curevent.set_titlestr(' '.join([self.line1, self.line2,
                                           self.line3]).strip())

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
            self.menu_race_close.set_sensitive(False)
            self.menu_race_abort.set_sensitive(False)
            self.curevent = None
            uiutil.buttonchg(self.stat_but, uiutil.bg_none, 'Closed')
            self.stat_but.set_sensitive(False)

    ## Reports menu callbacks.
    def menu_reports_startlist_activate_cb(self, menuitem, data=None):
        """Generate a startlist."""
        lines = ['        - no data -']
        header = ''
        if self.curevent is not None:
            lines = self.curevent.startlist_report()
            header = self.curevent.startlist_header()
        title = 'Startlist [' + str(self.docindex) + ']'
        self.print_report(title, lines, header)

    def menu_reports_camera_activate_cb(self, menuitem, data=None):
        """Generate the camera operator report."""
        lines = ['        - no data -']
        header = ''
        if self.curevent is not None:
            lines = self.curevent.camera_report()
            header = self.curevent.camera_header()
        title = 'Judges Report [' + str(self.docindex) + ']'
        self.print_report(title, lines, header)

    def menu_reports_result_activate_cb(self, menuitem, data=None):
        """Generate the race result report."""
        lines = ['        - no data -']
        header = ''
        if self.curevent is not None:
            lines = self.curevent.result_report()
            header = self.curevent.result_header()
        title = 'Result [' + str(self.docindex) + ']'
        self.print_report(title, lines, header)

    def race_results_points_activate_cb(self, menuitem, data=None):
        """Generate the points classification report."""
        pass

    def menu_reports_scratch_print_activate_cb(self, menuitem, data=None):
        """Call the scratchpad print function."""
        self.scratch_print()

    def menu_reports_scratch_new_activate_cb(self, menuitem, data=None):
        """Clear scratch pad."""
        self.scratch_clear()

    def menu_reports_prefs_activate_cb(self, menuitem, data=None):
        """Run the report preferences dialog."""
        pass

    def menu_data_rego_activate_cb(self, menuitem, data=None):
        """Open rider registration dialog."""
        pass

    def menu_data_import_activate_cb(self, menuitem, data=None):
        """Open rider import dialog."""
        self.log.info('Rider import dlg...')
        # TYPE manip -> maybe need a way to import start times into race
        pass

    def menu_data_export_activate_cb(self, menuitem, data=None):
        """Open rider export dialog."""
        self.log.info('Rider export dlg...')
        # TYPE manip -> export 'startlist' type thing
        pass

    def menu_data_results_cb(self, menuitem, data=None):
        """Export raw unformatted results to disk."""
        rfilename = os.path.join(self.configpath, 'results.csv')
        with open(rfilename , 'wb') as f:
            f.write(',' + '\n,'.join((self.line1,
                                      self.line2,
                                      self.line3)) + '\n\n')
            if self.curevent is not None:
                self.curevent.result_export(f)
                f.write('\n')
        self.log.info('Exported meet results to ' + repr(rfilename))

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

    def menu_timing_clear_activate_cb(self, menuitem, data=None):
        """Clear memory in attached timing devices."""
        self.timer.clrmem()
        self.rfu.clrmem()
        self.log.info('Clear attached timer memory.')

    def menu_timing_sync_activate_cb(self, menuitem, data=None):
        """Roughly synchronise Wheeltime RTC."""
        self.rfu.sync()
        self.log.info('Rough sync Wheeltime clock.')
        
    def menu_timing_reconnect_activate_cb(self, menuitem, data=None):
        """Reconnect timers and initialise."""
        self.timer.setport(self.timer_port)
        self.timer.sane()
        self.rfu.setaddr(self.rfu_addr)
        self.log.info('Re-connect and initialise attached timers.')

    ## Help menu callbacks
    def menu_help_docs_cb(self, menuitem, data=None):
        """Display program help."""
        scbdo.help_docs(self.window)

    def menu_help_about_cb(self, menuitem, data=None):
        """Display scbdo about dialog."""
        scbdo.about_dlg(self.window)
  
    ## Race Control Elem callbacks
    def race_stat_but_clicked_cb(self, button, data=None):
        """Call through into event if open."""
        if self.curevent is not None:
            self.curevent.stat_but_clicked()
           
    def race_stat_entry_activate_cb(self, entry, data=None):
        """Pass the chosen action and bib list through to curevent,"""
        action = self.action_model.get_value(
                       self.action_combo.get_active_iter(), 0)
        if self.curevent is not None:
            if self.curevent.race_ctrl(action, self.action_entry.get_text()):
                self.action_entry.set_text('')
   
    ## Menu button callbacks
    def menu_rfustat_clicked_cb(self, button, data=None):
        """Re-connnect Wheeltime unit."""
        self.rfu.setaddr(self.rfu_addr)
        self.log.info('Re-connecting wheeltime unit.')

    def menu_clock_clicked_cb(self, button, data=None):
        """Handle click on menubar clock."""
        self.log.info('PC ToD: ' + self.clock_label.get_text())
        self.scratch_log('--- PC ToD: ' + self.clock_label.get_text() + ' ---')
        self.log.debug('Menubar clock click.')

    ## 'Slow' Timer callback - this is the main event poll routine
    def timeout(self):
        """Update status buttons and time of day clock button."""
        if not self.running:
            return False
        else:
            # update pc ToD label
            self.clock_label.set_text(
                  tod.tod('now').rawtime(places=0,zeros=True))

            # call into race timeout handler
            if self.curevent is not None:
                self.curevent.timeout()
            else: # otherwise collent and discard any pending events
                while self.rfu.response() is not None:
                    pass
                while self.timer.response() is not None:
                    pass

            # lastly display RFU status button
            nstat = self.rfu.connected()
            if nstat != self.rfustat:
                if nstat:
                    self.menu_rfustat_img.set_from_stock(
                           gtk.STOCK_CONNECT, gtk.ICON_SIZE_LARGE_TOOLBAR)
                else:
                    self.menu_rfustat_img.set_from_stock(
                           gtk.STOCK_DISCONNECT, gtk.ICON_SIZE_LARGE_TOOLBAR)
                self.rfustat = nstat
        return True

    ## Timy utility methods.
    def printimp(self, printimps=True):
        """Enable or disable printing of timing impulses on Timy."""
        self.timer.printimp(printimps)

    ## Scratch pad utils
    def scratch_log(self, msg):
        mbuf = msg.rstrip() + '\n'
        self.scratch_buf.insert(self.scratch_buf.get_end_iter(), mbuf)

    def scratch_filename(self):
        return os.path.join(self.configpath,
                                'scratchpad.' + str(self.scratch_idx))

    def find_next_scratchfile(self):
        """Search the config path to find the next available scratchpad."""
        savefile = self.scratch_filename()
        while os.path.exists(savefile):
            self.scratch_idx += 1
            savefile = self.scratch_filename()
        return savefile

    ### NOTE: scratch loading/saving and navigate requires some design

    def scratch_clear(self):
        """Dump the current scratchpad to file, then clear."""
        savefile = self.find_next_scratchfile()
        with open(savefile, 'wb') as f:
            f.write(self.scratch_buf.get_text(
                          self.scratch_buf.get_start_iter(),
                          self.scratch_buf.get_end_iter()))
        self.scratch_idx += 1
        self.scratch_buf.delete(self.scratch_buf.get_start_iter(),
                                self.scratch_buf.get_end_iter())
    
    def scratch_print(self):
        """Print the current scratch pad content."""
        lines = self.scratch_buf.get_text(self.scratch_buf.get_start_iter(),
                          self.scratch_buf.get_end_iter()).splitlines()
        title = ('Scratch Pad #' + str(self.scratch_idx) 
                  + ' [' + str(self.docindex) + ']')
        self.print_report(title, lines, '')

    def resname(self, bib, first, last, club):
        """Meet switch for bib or no bib in result names."""
        if self.bibs_in_results:
            return strops.resname_bib(bib, first, last, club)
        else:
            return strops.resname(first, last, club)

    ## Window methods
    def set_title(self, extra=''):
        """Update window title from meet properties."""
        self.window.set_title(ROADRACE_TYPES[self.etype]
                              + ' :: '
                              + ' '.join([self.line1, self.line2,
                                          self.line3, extra]).strip())

    def meet_destroy_cb(self, window, msg=''):
        """Handle destroy signal and exit application."""
        if self.started:
            self.saveconfig()
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
        self.scb.clrall()
        self.scb.wait()
        self.rfu.exit(msg)
        self.scb.exit(msg)
        self.timer.exit(msg)
        self.timer.join()	# Wait on closure of main timer thread
        self.started = False

    def start(self):
        """Start the timer and rfu threads."""
        if not self.started:
            self.log.debug('Meet startup.')
            self.scb.start()
            self.timer.start()
            self.rfu.start()
            self.started = True

    ## Roadmeet functions
    def saveconfig(self):
        """Save current meet data to disk."""
        if self.curevent is not None and self.curevent.winopen:
            self.curevent.saveconfig()
        cw = ConfigParser.ConfigParser()
        cw.add_section('meet')
        cw.set('meet', 'maintimer', self.timer_port)
        cw.set('meet', 'rfunit', self.rfu_addr)
        cw.set('meet', 'line1', self.line1)
        cw.set('meet', 'line2', self.line2)
        cw.set('meet', 'line3', self.line3)
        cw.set('meet', 'logos', self.logos)
        if self.bibs_in_results:
            cw.set('meet', 'resultbibs', 'Yes')
        else:
            cw.set('meet', 'resultbibs', 'No')
        if self.cats_in_results:
            cw.set('meet', 'resultcats', 'Yes')
        else:
            cw.set('meet', 'resultcats', 'No')
        cw.set('meet', 'distance', str(self.distance))
        cw.set('meet', 'docindex', str(self.docindex))
        cwfilename = os.path.join(self.configpath, 'config')
        self.log.debug('Saving meet config to ' + repr(cwfilename))
        with open(cwfilename , 'wb') as f:
            cw.write(f)
        self.rdb.save(os.path.join(self.configpath, 'riders.csv'))
        self.edb.save(os.path.join(self.configpath, 'events.csv'))
        # save out print settings
        self.printprefs.to_file(os.path.join(self.configpath, 'print.prf'))

    def loadconfig(self):

#!! FIX !! -> loading distance
	  #-> loading/saving uscbsrv port
	  #-> defaults for uscbsrv
	  #-> default timy port should be ''

        """Load meet config from disk."""
        cr = ConfigParser.ConfigParser({'maintimer':'',
                                        'rfunit':wheeltime.WHEELIP,
                                        'resultcats':'No',
					'resultbibs':'Yes',
                                        'distance':'1.0',
                                        'docindex':'0',
                                        'line1':'',
                                        'line2':'',
                                        'line3':'',
                                        'uscbsrv':'',
                                        'uscbchan':'#announce',
                                        'uscbopt':'No',
                                        'logos':''})
        cr.add_section('meet')
        cwfilename = os.path.join(self.configpath, 'config')

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

        # setup scratchpad? for later thought with load/save/prev/next
        self.find_next_scratchfile()
        self.log.info('Initialised scratchpad #' + str(self.scratch_idx))

        # check for config file
        try:
            a = len(cr.read(cwfilename))
            if a == 0:
                self.log.warn('No config file - loading default values.')
        except e:
            self.log.error('Error reading meet config: ' + str(e))

        # set timer port
        nport = cr.get('meet', 'maintimer')
        if nport != self.timer_port:
            self.timer_port = nport
            self.timer.setport(nport)
            self.timer.sane()

        # set rfunit addr
        nport = cr.get('meet', 'rfunit')
        if nport != self.rfu_addr:
            self.rfu_addr = nport
            self.rfu.setaddr(nport)

        # set meet meta infos, and then copy into text entries
        self.line1 = cr.get('meet', 'line1')
        self.line2 = cr.get('meet', 'line2')
        self.line3 = cr.get('meet', 'line3')
        self.logos = cr.get('meet', 'logos')
        self.set_title()

        # result options
        self.bibs_in_results = strops.confopt_bool(
                                        cr.get('meet', 'resultbibs'))
        self.cats_in_results = strops.confopt_bool(
                                        cr.get('meet', 'resultcats'))

        # race length
        self.distance = strops.confopt_dist(cr.get('meet', 'distance'), 20)

        # document id
        self.docindex = strops.confopt_dist(cr.get('meet', 'docindex'), 0)

        self.rdb.clear()
        self.edb.clear()
        self.rdb.load(os.path.join(self.configpath, 'riders.csv'))
        self.edb.load(os.path.join(self.configpath, 'events.csv'))
        event = self.edb.getevent()
        if event is None:	# add a new event to the model
            event = self.edb.editevent(num='00', etype=self.etype)
        self.open_event(event) # always open on load if posible

        # restore printer preferences
        psfilename = os.path.join(self.configpath, 'print.prf')
        if os.path.isfile(psfilename):
            try:
                self.printprefs.load_file(psfilename)
            except:
                self.log.warn('Error loading print preferences.')

    def get_distance(self):
        """Return race distance in km."""
        return self.distance

    def __init__(self, configpath=None, etype='rms'):
        """Meet constructor."""
        # logger and log handler
        self.log = logging.getLogger('scbdo')
        self.log.setLevel(logging.DEBUG)
        self.loghandler = None	# set in loadconfig to meet dir

        if etype not in ROADRACE_TYPES:
            etype = 'rms'	# Default is 'road mass start'
        self.etype = etype

        # meet configuration path and options
        if configpath is None:
            configpath = '.'	# None assumes 'current dir'
        self.configpath = configpath
        self.line1 = ''
        self.line2 = ''
        self.line3 = ''
        self.bibs_in_results = True
        self.cats_in_results = False
        self.distance = 20	# Race distance in km (integer!)
        self.logos = ''		# string list of logo filenames
        self.docindex = 0

        # printer preferences
        self.printprefs = gtk.PrintSettings()	# filled in with loadconfig

        # hardware connections
        self.timer = timy.timy()
        self.timer_port = ''
        self.rfu = wheeltime.wheeltime()
        self.rfu_addr = ''
        self.scb = uscbsrv.uscbsrv()

        b = gtk.Builder()
        b.add_from_file(os.path.join(scbdo.UI_PATH, 'roadmeet.ui'))
        self.window = b.get_object('meet')
        self.window.connect('key-press-event', self.key_event)
        self.clock = b.get_object('menu_clock')
        self.clock_label = b.get_object('menu_clock_label')
        self.clock_label.modify_font(pango.FontDescription("monospace"))
        self.menu_rfustat_img = b.get_object('menu_rfustat_img')
        self.status = b.get_object('status')
        self.log_buffer = b.get_object('log_buffer')
        self.log_view = b.get_object('log_view')
        self.log_view.modify_font(pango.FontDescription("monospace 12"))
        self.log_scroll = b.get_object('log_box').get_vadjustment()
        self.context = self.status.get_context_id('SCBdo Meet')
        self.menu_race_close = b.get_object('menu_race_close')
        self.menu_race_abort = b.get_object('menu_race_abort')
        self.race_box = b.get_object('race_box')
        self.stat_but = b.get_object('race_stat_but')
        self.action_model = b.get_object('race_action_model')
        self.action_combo = b.get_object('race_action_combo')
        self.action_entry = b.get_object('race_action_entry')
        b.get_object('race_tab_img').set_from_file(scbdo.SCB_LOGOFILE)
        b.connect_signals(self)

        # run state
        self.running = True
        self.started = False
        self.curevent = None
        self.rfustat = False
        self.rfid_cb = None

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

        # scrachpad buffer
        self.scratch_buf = b.get_object('scratch_buffer')
        self.scratch_idx = 0
        b.get_object('scratch_view').modify_font(
                                       pango.FontDescription("monospace 18"))

        # get rider db and pack into a dialog
        self.rdb = riderdb.riderdb()
        b.get_object('riders_box').add(self.rdb.mkview(cat=True,
                                                  series=False,refid=True))

        # select event page in notebook.
        b.get_object('meet_nb').set_current_page(1)

        # get event db -> loadconfig makes event if not already made
        self.edb = eventdb.eventdb([])

        # start timer
        glib.timeout_add_seconds(1, self.timeout)

def main(etype='rms'):
    """Run the road meet application."""
    configpath = None

    # expand configpath on cmd line to realpath _before_ doing chdir
    if len(sys.argv) > 2:
        print('usage: roadmeet [configdir]\n')
        sys.exit(1)
    elif len(sys.argv) == 2:
        rdir = sys.argv[1]
        if not os.path.isdir(rdir):
            rdir = os.path.dirname(rdir)
        configpath = os.path.realpath(rdir)

    scbdo.init()
    app = roadmeet(configpath, etype)
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

