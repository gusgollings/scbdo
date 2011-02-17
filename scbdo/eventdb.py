
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

"""Event 'database' container object with model and view.

Manage an event db with the following data columns (all string):

  Num		Event 'number' alphanumeric string, only chars A-Za-z0-9
  Info		Event information string (usually name/len/type)
  Xtra		Extra event info string (sponsor name, cat, length etc)
  Type		Event SCBdo type for runner purposes (not editable!)
  Series	Bib series to use with event
  Active	Is the event in-progress, mostly run-time, saved for ease
  Starters	A category name or a list of starters to transfer into
		event object on open. Note: this may be cleared once
		transfered

  NOTE:		gtk.TreeRowReference is used as the internal row
		reference technique in and out of methods. This
		adds some overhead converting to and from paths
		and iters, but is persistent and may be handed
		around modules safely

"Primary key" is (Num)

When Series is not present the empty series '' is assumed.

"""

import csv
import gtk
import gobject
import glib
import logging
import os

from scbdo import uiutil
from scbdo import strops

# Note: These are for the trackrace module, roadrace defines locally
defracetypes=['sprint', 'keirin',			# sprint types
           'scratch', 'motorpace',			# generic races
           'flying 200', 'flying lap',			# individual TTs
           'indiv tt', 'indiv pursuit',
           'pursuit race',				# indiv tt with twist
           #'team sprint', 'team pursuit',		# team time trials
           'points', 'madison',				# point score types
           'omnium',					# aggregate types
           'race' ]		# esoterics/generic

# Model column constants
COL_EVNO = 0
COL_PREFIX = 1
COL_INFO = 2
COL_SERIES = 3
COL_TYPE = 4
COL_OPEN = 5
COL_STARTERS = 6

class eventdb(object):
    """Event database."""
    def addempty(self):
        """Add a new empty row in the event model."""
        i = self.model.append([self.nextevno(), '', '', '', '', False, ''])
        ref = gtk.TreeRowReference(self.model, self.model.get_path(i))
        if self.view is not None:
            self.postedit = None
            self.gotorow(ref)
        return ref

    def nextevno(self):
        """Try and return a new unique event number string."""
        lmax = 1
        for r in self.model:
            if r[COL_EVNO].isdigit() and int(r[COL_EVNO]) >= lmax:
                lmax = int(r[COL_EVNO]) + 1
        return str(lmax)

    def clear(self):
        """Clear event model."""
        self.log.debug('Event model cleared.')
        self.model.clear()

    def load(self, csvfile=None):
        """Load events from supplied CSV file."""
        theopenevent = None
        if os.path.isfile(csvfile):
            self.log.debug('Loading events from %s', csvfile)
            with open(csvfile, 'rb') as f:
                cr = csv.reader(f)
                for row in cr:
                    ir = [cell.translate(strops.PRINT_TRANS) for cell in row]
                    if len(ir) > 0 and ir[COL_EVNO] != 'Num':
                        num = ir[COL_EVNO].strip()
                        if num.isalnum():
                            nr = [num, '', '', '', '', False, '']
                            for i in range(1,7):
                                if len(ir) > i:
                                    if i != COL_OPEN:
                                        nr[i] = ir[i].strip()
                                    else:
                                        if ir[i] == 'True':
                                            theopenevent = nr[COL_EVNO]
                            if self.getevent(num) is None:
                                self.model.append(nr)
                            else:
                                self.log.warn('Duplicate event #: %s', num)
                        else:
                            self.log.warn('Invalid event #: %s', num)
            self.log.debug('Load events done.')
        return self.getevent(theopenevent)

    def save(self, csvfile=None):
        """Save current model content to supplied CSV file."""
        self.log.debug('Saving events to %s', csvfile)
        with open(csvfile, 'wb') as f:
            cr = csv.writer(f)
            cr.writerow(["Num","Prefix","Info","Series",
                         "Type","Open","Starters"])
            cr.writerows(self.model)

    def gotorow(self, ref=None):
        """Move view selection to the specified row reference."""
        if ref is None and len(self.model) > 0:
            ref = gtk.TreeRowReference(self.model, 0)
        if ref is not None and ref.valid():
            path = ref.get_path()
            self.view.scroll_to_cell(path)
            self.view.set_cursor_on_cell(path)

    def delselected(self):
        """Delete the currently selected row."""
        if self.view is not None:
            model, iter = self.view.get_selection().get_selected()
            if iter is not None:
                if not self.model.get_value(iter,COL_OPEN):
                    evno = self.model.get_value(iter,COL_EVNO)
                    # TODO: find some way of moving event savefile to backup
                    ref = None
                    if self.model.remove(iter):
                        ref = gtk.TreeRowReference(self.model,
                                             self.model.get_path(iter))
                    self.gotorow(ref)
                else:
                    self.log.warn('Did not remove open event.')

    def getselected(self):
        """Return a reference to the currently selected row, or None."""
        ref = None
        if self.view is not None:
            model, iter = self.view.get_selection().get_selected()
            if iter is not None:
                ref = gtk.TreeRowReference(self.model,
                                           self.model.get_path(iter))
        return ref

    def getnextrow(self, ref, scroll=True):
        """Return reference to the row one after current selection."""
        ret = None
        if ref.valid():
            i = self.model.iter_next(self.model.get_iter(ref.get_path()))
            if i is not None:
                ret = gtk.TreeRowReference(self.model,
                                           self.model.get_path(i))
                if scroll:
                    self.gotorow(ret)
        return ret

    def getprevrow(self, ref, scroll=True):
        """Return reference to the row one before current selection."""
        ret = None
        if ref.valid():
            p = int(self.model.get_string_from_iter(
                      self.model.get_iter(ref.get_path()))) - 1
            if p >= 0:
                ret = gtk.TreeRowReference(self.model, p)
                if scroll:
                    self.gotorow(ret)
        return ret
            
    def mkview(self):
        """Create and return view object for the model."""
        if self.view is not None:
            return self.view
        v = gtk.TreeView(self.model)
        v.set_reorderable(True)
        v.set_enable_search(False)
        v.set_rules_hint(True)
        v.connect('key-press-event', self.__view_key)
        v.show()
        uiutil.mkviewcoltxt(v, 'No.', COL_EVNO, self.__editcol_cb,
                                editcb=self.__editstart_cb)
        uiutil.mkviewcoltxt(v, 'Prefix', COL_PREFIX, self.__editcol_cb,
                                 expand=True, editcb=self.__editstart_cb)
        uiutil.mkviewcoltxt(v, 'Info', COL_INFO, self.__editcol_cb,
                                expand=True, editcb=self.__editstart_cb)
        uiutil.mkviewcoltxt(v, 'Ser', COL_SERIES, self.__editcol_cb,
                                 editcb=self.__editstart_cb)
        i = gtk.CellRendererCombo()
        i.set_property('editable', True)
        m = gtk.ListStore(gobject.TYPE_STRING)
        for race in self.racetypes:
            m.append([race])
        i.set_property('model', m)
        i.set_property('text-column', 0)
        i.connect('edited', self.__editcol_cb, COL_TYPE)
        i.connect('editing-started', self.__editstart_cb, 'combo')
        j = gtk.TreeViewColumn('Type', i, text=COL_TYPE)
        j.set_min_width(90)
        v.append_column(j)
        self.view = v
        return self.view

    def getevent(self, num=None):
        """Return a reference to the row with the given event no."""
        ret = None
        if num is not None:
            i = self.model.get_iter_first()
            while i is not None:
                if self.model.get_value(i, COL_EVNO) == num:
                    ret = gtk.TreeRowReference(self.model,
                                               self.model.get_path(i))
                    break 
                i = self.model.iter_next(i)
        else:
            i = self.model.get_iter_first()
            if i is not None:
                    ret = gtk.TreeRowReference(self.model,
                                               self.model.get_path(i))
        return ret

    def set_evno_change_cb(self, cb):
        """Set the callback for change of event no."""
        self.evno_change_cb = cb

    def getvalue(self, ref, col):
        """Return the specified column from the supplied row."""
        ret = None
        if ref.valid():
            ret = self.model[ref.get_path()][col]
        return ret

    def editevent(self, ref=None, num=None, info=None, prefix=None, etype=None,
                        series=None, winopen=None, starters=None):
        """Create or update the event with supplied parameters."""
        i = None
        if ref is None:
            if num is None:	# failsafe, but awkward init
                num = ''
            i = self.model.append([num, '', '', '', '', False, ''])
            ref = gtk.TreeRowReference(self.model,
                                           self.model.get_path(i))
        if ref.valid():
            i = self.model.get_iter(ref.get_path())
            if prefix is not None:
                self.model.set_value(i, COL_PREFIX, prefix)
            if info is not None:
                self.model.set_value(i, COL_INFO, info)
            if etype is not None:
                self.model.set_value(i, COL_TYPE, etype)
            if series is not None:
                self.model.set_value(i, COL_SERIES, series)
            if winopen is not None:
                self.model.set_value(i, COL_OPEN, bool(winopen))
            if starters is not None:
                self.model.set_value(i, COL_STARTERS, starters)
        return ref

    def __editcol_cb(self, cell, path, new_text, col):
        """Update model if possible and request post-edit movement."""
        ret = False
        if new_text is not None:
            new_text = new_text.strip()
            if new_text != self.model[path][col]:
                if col == COL_EVNO:
                    if not self.model[path][COL_OPEN]:
                        if new_text.isalnum():
                            if self.getevent(new_text) is None:
                                old_text = self.model[path][COL_EVNO]
                                self.model[path][COL_EVNO] = new_text
                                if self.evno_change_cb is not None:
                                    glib.idle_add(self.evno_change_cb,
                                                  old_text, new_text)
                                ret = True
                            else:
                                self.log.warn(
                                  'Rejecting update to duplicate event.')
                                self.postedit = 'same'
                                ret = True
                        else:
                            self.log.warn('Rejecting invalid event number.')
                    else:
                        self.log.warn(
                          'Cannot change event number on open event.')
                else:
                    self.model[path][col] = new_text
                    ret = True
            else:	# No Change, but entry 'accepted'
                ret = True
        if ret and self.postedit is not None:
            glib.idle_add(self.__postedit_move, path, col)
        return ret

    def __postedit_move(self, path, col):
        """Perform a post-edit movement of the selection."""
        if self.postedit is None:
            return False

        # step 1: process left/right
        if self.postedit == 'left':
            col -= 1
            self.postedit = None
        elif self.postedit == 'right':
            col += 1
            self.postedit = None

        if col < COL_EVNO:
            col = COL_TYPE
            self.postedit = 'up'	# followup with a upward movement
        elif col > COL_TYPE:
            col = COL_EVNO
            self.postedit = 'down'	# followup with a downward movement

        # step 2: check for additional up/down
        i = self.model.get_iter(path)
        if self.postedit == 'up':
            p = int(self.model.get_string_from_iter(i)) - 1
            if p >= 0:
                path = self.model.get_path(self.model.get_iter_from_string(str(p)))
            else:
                return False	# can't move any further 'up'
        elif self.postedit == 'down':
            i = self.model.iter_next(i)
            if i is not None:
                path = self.model.get_path(i)
            else:
                return False	# no more rows to scroll to -> perhaps add?
        self.postedit = None	# suppress any further change
        return self.__moveto_col(path, col)

    def __moveto_col(self, path, col):
        """Move selection to supplied path and column."""
        self.view.scroll_to_cell(path,
                                 self.view.get_column(col),
                                 True, 0.5, 0.5)
        self.view.set_cursor(path,
                             self.view.get_column(col), True)
        return False	# called in main loop idle

    def __view_key(self, widget, event):
        """Handle key events on tree view."""
        if event.type == gtk.gdk.KEY_PRESS:
            if event.state & gtk.gdk.CONTROL_MASK:
                key = gtk.gdk.keyval_name(event.keyval) or 'None'
                if key.lower() == 'a':
                    self.addempty()
                    return True
                elif key == 'Delete':
                    self.delselected()
                    return True
        return False

    def __edit_entry_key_cb(self, widget, event, editable=None):
        """Check key press in cell edit for postedit move."""
        if event.type == gtk.gdk.KEY_PRESS:
            key = gtk.gdk.keyval_name(event.keyval) or 'None'
            if key == 'Tab':
                self.postedit = 'right'
            elif key in ['Return', 'Escape']:	# allow cancel to handle
                self.postedit = None
            elif key == 'Up':
                if editable is None:
                    self.postedit = 'up'
            elif key == 'Down':
                if editable is None:
                    self.postedit = 'down'
            elif key == 'Right':
                if self.editwasempty:
                    self.postedit = 'right'
                    if editable is not None:
                        editable.editing_done()
                    else:
                        widget.editing_done()
            elif key == 'Left':
                if self.editwasempty:
                    self.postedit = 'left'
                    if editable is not None:
                        editable.editing_done()
                    else:
                        widget.editing_done()
        return False

    def __editstart_cb(self, cr, editable, path, data=None):
        """Prepare cell entry for post-edit movement."""
        self.postedit = None
        if data == 'combo':
            editable.child.connect('key-press-event',
                                   self.__edit_entry_key_cb, editable)
            self.editwasempty = True
        elif type(editable) is gtk.Entry:
            self.editwasempty = len(editable.get_text()) == 0
            editable.connect('key-press-event', self.__edit_entry_key_cb)
        else:	# this is crap - but don't know the type
            self.editwasempty = False

    def __iter__(self):
        """Return a generator for the event model."""
        return uiutil.liststore_inorder(self.model)

    def __init__(self, racetypes=None):
        """Constructor for the event db.

        Constructs a new event database object. Optional argument
        racetypes specifies an alternate list of available race
        type strings.

        This function does not create the view object, use the
        mkview() function to create and return a valid treeview.

        """

        self.log = logging.getLogger('scbdo.eventdb')
        self.model = gtk.ListStore(gobject.TYPE_STRING,	# 0 num
                                   gobject.TYPE_STRING, # 1 info
                                   gobject.TYPE_STRING, # 2 xtra
                                   gobject.TYPE_STRING, # 3 etype
                                   gobject.TYPE_STRING, # 4 series
                                   gobject.TYPE_BOOLEAN,# 5 open
                                   gobject.TYPE_STRING) # 6 starters
        self.view = None
        self.postedit = None
        self.editwasempty = False
        self.evno_change_cb = None
        if racetypes is not None:
            self.racetypes = racetypes
        else:
            self.racetypes = defracetypes


if __name__ == "__main__":
    import sys
    import pygtk
    pygtk.require('2.0')
    
    edb = eventdb()

    # Check cmd line
    filename = 'events.csv'
    if len(sys.argv) == 2:
        filename = sys.argv[1]
    print("loading from " + repr(filename))
    edb.load(filename)

    win = gtk.Window()
    win.set_title('SCBdo :: Event DB test')
    win.add(uiutil.vscroller(edb.mkview()))
    win.connect('destroy', lambda *x: gtk.main_quit())
    win.show()

    gtk.main()
