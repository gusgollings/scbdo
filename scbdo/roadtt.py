
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

"""Timing and data handling application for CSV road time trials."""

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
from scbdo import eventdb
from scbdo import riderdb
from scbdo import wheeltime
from scbdo import timy
from scbdo import unt4
from scbdo import strops
from scbdo import loghandler
from scbdo import irtt

LOGHANDLER_LEVEL = logging.DEBUG

class roadtt:
    """Road TT application class."""

    ## Meet Menu Callbacks
    def menu_meet_open_cb(self, menuitem, data=None):
        """Open a new meet."""
        if self.curevent is None:
            dlg = gtk.FileChooserDialog('Open new IRTT', self.window,
                gtk.FILE_CHOOSER_ACTION_SELECT_FOLDER, (gtk.STOCK_CANCEL,
                gtk.RESPONSE_CANCEL, gtk.STOCK_OPEN, gtk.RESPONSE_OK))
            response = dlg.run()
            if response == gtk.RESPONSE_OK:
                self.configpath = dlg.get_filename()
                self.loadconfig()
                self.log.info('IRTT data loaded from'
                               + repr(self.configpath) + '.')
            dlg.destroy()
        else:
            self.log.warn('Race in progress, please close to load new meet.')

    def menu_meet_save_cb(self, menuitem, data=None):
        """Save current all meet data to config."""
        self.saveconfig()
        self.log.info('IRTT data saved to ' + repr(self.configpath) + '.')

    def menu_meet_properties_cb(self, menuitem, data=None):
        """Edit meet properties."""
        b = gtk.Builder()
        b.add_from_file(os.path.join(scbdo.UI_PATH, 'roadtt_props.ui'))
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
            self.bibs_in_results = rb.get_active()
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

# !!! TODO: print properties

    def menu_meet_quit_cb(self, menuitem, data=None):
        """Quit the road tt application."""
        self.running = False
        self.window.destroy()

    def menu_race_run_activate_cb(self, menuitem=None, data=None):
        """Open the TT event handler."""
        eh = self.edb.getevent('tt')	# the only event is 'tt'
        if eh is not None:
            self.open_event(eh)

    def menu_race_close_activate_cb(self, menuitem, data=None):
        """Close the TT event handler."""
        self.close_event()
    
    def menu_race_abort_activate_cb(self, menuitem, data=None):
        """Close the currently open event without saving."""
        if self.curevent is not None:
            self.curevent.readonly = True
        self.close_event()

    def open_event(self, eventhdl=None):
        """Open provided event handle."""
        if eventhdl is not None:
            self.close_event()
            self.curevent = irtt.irtt(self, eventhdl, True)
            self.curevent.loadconfig()
            self.race_box.add(self.curevent.frame)
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

    ## Data menu callbacks.
    def menu_data_rego_activate_cb(self, menuitem, data=None):
        """Open rider registration dialog."""
        self.log.info('Rider registration dlg...')
        pass

    def menu_data_import_activate_cb(self, menuitem, data=None):
        """Open rider import dialog."""
        self.log.info('Rider import dlg...')
        pass

    def menu_data_export_activate_cb(self, menuitem, data=None):
        """Open rider export dialog."""
        self.log.info('Rider export dlg...')
        pass

    def menu_data_results_cb(self, menuitem, data=None):
        """Export live results to disk."""
        rfilename = os.path.join(self.configpath, 'results.csv')
        with open(rfilename , 'wb') as f:
            f.write(',' + '\n,'.join((self.line1,
                                      self.line2,
                                      self.line3)) + '\n\n')
            for e in self.edb:
                r = irtt.irtt(self, e, False)
                r.loadconfig()
                r.result_export(f)
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
        self.log.info('Clear attached timer memories')

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

    ## Timer callbacks
    def menu_clock_timeout(self):
        """Update status buttons and time of day clock button."""
        if not self.running:
            return False
        else:
            # check wheeltime connection
            nstat = self.rfu.connected()
            if nstat != self.rfustat:
                if nstat:
                    self.menu_rfustat_img.set_from_stock(gtk.STOCK_CONNECT,
                                                         gtk.ICON_SIZE_BUTTON)
                else:
                    self.menu_rfustat_img.set_from_stock(gtk.STOCK_DISCONNECT,
                                                         gtk.ICON_SIZE_BUTTON)
                self.rfustat = nstat
            self.clock_label.set_text(
                  tod.tod('now').rawtime(places=0,zeros=True))
            if self.curevent is not None:      # call into race 'slow'
                self.curevent.slow_timeout()        # timeout
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
            e = self.rfu.response()       # clear rfid queue...
            while e is not None:
                if self.rfid_cb:           # ... and redirect events
                    self.rfid_cb(e)        #     if required
                e = self.rfu.response()
        return True

    ## Timy utility methods.
    def printimp(self, printimps=True):
        """Enable or disable printing of timing impulses on Timy."""
        self.timer.printimp(printimps)

    ## Scratch pad utils
    def scratch_log(self, msg):
        self.scratch_buf.insert(self.scratch_buf.get_end_iter(),
                                 msg.rstrip() + '\n')

    def scratch_clear(self):
        self.scratch_buf.delete(self.scratch_buf.get_start_iter(),
                                self.scratch_buf.get_end_iter())
    
    def scratch_print(self):
        self.log.warn('meet.scratch_print() ==> NOTIMPL')


    def resname(self, bib, first, last, club):
        """Meet switch for bib or no bib in result names."""
        if self.bibs_in_results:
            return strops.resname_bib(bib, first, last, club)
        else:
            return strops.resname(first, last, club)

    ## Window methods
    def set_title(self, extra=''):
        """Update window title from meet properties."""
        self.window.set_title('IRTT :: ' 
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
        self.rfu.exit(msg)
        self.timer.exit(msg)
        self.timer.join()	# Wait on closure of main timer thread
        self.started = False

    def start(self):
        """Start the timer and rfu threads."""
        if not self.started:
            self.log.debug('Meet startup.')
            self.timer.start()
            self.rfu.start()
            self.started = True

    ## Road tt functions
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
        cwfilename = os.path.join(self.configpath, 'config')
        self.log.debug('Saving meet config to ' + repr(cwfilename))
        with open(cwfilename , 'wb') as f:
            cw.write(f)
        self.rdb.save(os.path.join(self.configpath, 'riders.csv'))
        self.edb.save(os.path.join(self.configpath, 'events.csv'))

    def loadconfig(self):
        """Load meet config from disk."""
        cr = ConfigParser.ConfigParser({'maintimer':timy.MAINPORT,
                                        'rfunit':wheeltime.WHEELIP,
                                        'resultcats':'No',
					'resultbibs':'Yes',
                                        'distance':'20',
                                        'line1':'',
                                        'line2':'',
                                        'line3':'',
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

        # check for config file
        try:
            a = len(cr.read(cwfilename))
            if a == 0:
                self.log.warn('No config file found - loading default values.')
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

        self.rdb.clear()
        self.edb.clear()
        self.rdb.load(os.path.join(self.configpath, 'riders.csv'))
        self.edb.load(os.path.join(self.configpath, 'events.csv'))
        tt_event = self.edb.getevent('tt')
        if tt_event is None:	# add a new event to the model
            tt_event = self.edb.editevent(num='tt', etype='irtt')
        self.open_event(tt_event) # always open on load if possible

    def get_distance(self):
        """Return race distance in km."""
        return self.distance

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
        self.cats_in_results = False
        self.distance = 20	# Race distance in km (integer!)
        self.logos = ''		# string list of logo filenames

        # hardware connections
        self.timer = timy.timy('')
        self.timer_port = ''
        self.rfu = wheeltime.wheeltime('')
        self.rfu_addr = ''

        b = gtk.Builder()
        b.add_from_file(os.path.join(scbdo.UI_PATH, 'roadtt.ui'))
        self.window = b.get_object('meet')
        self.window.connect('key-press-event', self.key_event)
        self.clock = b.get_object('menu_clock')
        self.clock_label = b.get_object('menu_clock_label')
        self.clock_label.modify_font(pango.FontDescription("monospace"))
        self.menu_rfustat_img = b.get_object('menu_rfustat_img')
        self.status = b.get_object('status')
        self.log_buffer = b.get_object('log_buffer')
        self.log_view = b.get_object('log_view')
        self.log_view.modify_font(pango.FontDescription("monospace 9"))
        self.log_scroll = b.get_object('log_box').get_vadjustment()
        self.context = self.status.get_context_id('SCBdo Meet')
        self.menu_race_close = b.get_object('menu_race_close')
        self.menu_race_abort = b.get_object('menu_race_abort')
        self.race_box = b.get_object('race_box')
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
        b.get_object('scratch_view').modify_font(
                                       pango.FontDescription("monospace 9"))

        # get rider db and pack into scrolled pane
        self.rdb = riderdb.riderdb()
        b.get_object('rider_box').add(self.rdb.mkview(refid=True))

        # get event db -> loadconfig makes 'tt' event if not already made
        self.edb = eventdb.eventdb(['irtt'])

        # start timers
        glib.timeout_add_seconds(1, self.menu_clock_timeout)
        glib.timeout_add(50, self.timeout)

def main():
    """Run the roadtt application."""
    configpath = None
    # expand config on cmd line to realpath _before_ doing chdir
    if len(sys.argv) > 2:
        print('usage: roadtt [configdir]\n')
        sys.exit(1)
    elif len(sys.argv) == 2:
        configpath = os.path.realpath(os.path.dirname(sys.argv[1]))

    scbdo.init()
    app = roadtt(configpath)
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

