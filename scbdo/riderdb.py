
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

"""Rider 'database' container object with model and view.

Manage a rider db with the following data columns (all string):

  Bib		Bib 'number' alphanumeric string, only chars A-Za-z0-9
  First Name	Rider's full first name
  Last Name	Rider's full last name
  Club		Rider's club or affiliation for the meet
  Category	Riders racing category FOR THE MEET
  Series	A non-overlapping series of bib numbers
		may be the empty string '' (default)
  Refid		A unique reference string for the rider - used for RFID
 
"Primary key" is (Bib, Series)

When Series is not present the empty series is assumed: ''
A bib number conflict should raise error on import, this will force
explicit series confirmation before import into meet succeeds.

"""

import csv
import gtk
import glib
import gobject
import logging
import os

from scbdo import uiutil
from scbdo import strops

# Model column constants
COL_BIB = 0
COL_FIRST = 1
COL_LAST = 2
COL_CLUB = 3
COL_CAT = 4
COL_SERIES = 5
COL_REFID = 6

class riderdb(object):
    """Rider database."""
    def addempty(self, bib='', series=''):
        """Add a new empty row in the rider model."""
        i = self.model.append([bib, '', '', '', '', series, ''])
        ref = gtk.TreeRowReference(self.model, self.model.get_path(i))
        if self.view is not None:
            self.postedit = None
            self.gotorow(ref)
        return ref

    def clear(self):
        """Clear rider model."""
        self.log.debug('Rider model cleared.')
        self.model.clear()

    def load(self, csvfile=None):
        """Load riders from supplied CSV file."""
        if os.path.isfile(csvfile):
            self.log.debug('Loading riders from %s', csvfile)
            with open(csvfile, 'rb') as f:
                cr = csv.reader(f)
                for row in cr:
                    ir = [cell.translate(strops.PRINT_TRANS) for cell in row]
                    if len(ir) > 0 and ir[0] != 'Bib' and ir[0] != 'No.':
                        bib = ir[COL_BIB].strip()
                        if bib.isalnum():
                            nr = [bib, '', '', '', '', '', '']
                            for i in range(1,7):
                                if len(ir) > i:
                                    nr[i] = ir[i].strip()
                            if self.getrider(bib, nr[COL_SERIES]) is None:
                                self.model.append(nr)
                            else:
                                self.log.warn('Duplicate No.: %s', bib)
                        else:
                            self.log.warn('Invalid No.: %s', bib)
            self.log.debug('Load riders done.')

    def save(self, csvfile=None):
        """Save current model to supplied CSV file."""
        self.log.debug('Saving riders to %s', csvfile)
        with open(csvfile, 'wb') as f:
            cr = csv.writer(f)
            cr.writerow(["No.","First Name","Last Name","Club",
                         "Category","Series(optional)","Refid"])
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
                ref = None
                if self.model.remove(iter):
                    ref = gtk.TreeRowReference(self.model,
                                         self.model.get_path(iter))
                self.gotorow(ref)

    def getselected(self):
        """Return a reference to the currently selected row, or None."""
        ref = None
        if self.view is not None:
            model, iter = self.view.get_selection().get_selected()
            if iter is not None:
                ref = gtk.TreeRowReference(self.model,
                                           self.model.get_path(iter))
        return ref

    def mkview(self, bib=True, first=True, last=True, club=True,
                     cat=False, series=True, refid=False):
        """Create and return view object for the model."""
        if self.view is not None:
            return self.view
        v = gtk.TreeView(self.model)
        v.set_reorderable(True)
        v.set_enable_search(False)
        v.set_rules_hint(True)
        v.connect('key-press-event', self.__view_key)
        v.show()
        self.colmap = {}
        colcnt = 0
        if bib:
            uiutil.mkviewcoltxt(v, 'No.', COL_BIB, self.__editcol_cb,
                      halign=0.5, calign=0.5, editcb=self.__editstart_cb)
            self.colmap[COL_BIB] = colcnt
            colcnt += 1
        if first:
            uiutil.mkviewcoltxt(v, 'First Name', COL_FIRST, self.__editcol_cb,
                            expand=True, editcb=self.__editstart_cb)
            self.colmap[COL_FIRST] = colcnt
            colcnt += 1
        if last:
            uiutil.mkviewcoltxt(v, 'Last Name', COL_LAST, self.__editcol_cb,
                            expand=True, editcb=self.__editstart_cb)
            self.colmap[COL_LAST] = colcnt
            colcnt += 1
        if club:
            uiutil.mkviewcoltxt(v, 'Club', COL_CLUB, self.__editcol_cb,
                            editcb=self.__editstart_cb)
            self.colmap[COL_CLUB] = colcnt
            colcnt += 1
        if cat:
            uiutil.mkviewcoltxt(v, 'Cat', COL_CAT, self.__editcol_cb,
                            editcb=self.__editstart_cb)
            self.colmap[COL_CAT] = colcnt
            colcnt += 1
        if series:
            uiutil.mkviewcoltxt(v, 'Ser', COL_SERIES, self.__editcol_cb, 
                            editcb=self.__editstart_cb)
            self.colmap[COL_SERIES] = colcnt
            colcnt += 1
        if refid:
            uiutil.mkviewcoltxt(v, 'Refid', COL_REFID, self.__editcol_cb, 
                            editcb=self.__editstart_cb)
            self.colmap[COL_REFID] = colcnt
            colcnt += 1
        self.view = v
        return self.view

    def getrider(self, bib, series=''):
        """Return a reference to the row with the given bib and series."""
        ret = None
        i = self.model.get_iter_first()
        while i is not None:
            if (self.model.get_value(i, COL_BIB) == bib
                and self.model.get_value(i, COL_SERIES) == series):
                ret = gtk.TreeRowReference(self.model,
                                           self.model.get_path(i))
                break
            i = self.model.iter_next(i)
        return ret

    def nextriderno(self):
        """Try and return a new unique rider number string."""
        lmax = 1
        for r in self.model:
            if r[COL_BIB].isdigit() and int(r[COL_BIB]) >= lmax:
                lmax = int(r[COL_BIB]) + 1
        return str(lmax)

    def getrefid(self, refid):
        """Return a reference to the row with the given refid."""
        ret = None
        ck = refid.lower()
        i = self.model.get_iter_first()
        while i is not None:
            if self.model.get_value(i, COL_REFID).lower() == ck:
                ret = gtk.TreeRowReference(self.model,
                                           self.model.get_path(i))
                break
            i = self.model.iter_next(i)
        return ret
        
    def getbibs(self, cat, series=''):
        """Return a list of refs to riders in the given cat and series."""
        ret = []
        i = self.model.get_iter_first()
        while i is not None:
            if (self.model.get_value(i, COL_CAT) == cat
               and self.model.get_value(i, COL_SERIES) == series):
                ret.append(gtk.TreeRowReference(self.model,
                                           self.model.get_path(i)))
            i = self.model.iter_next(i)
        return ret

    def listseries(self):
        """Return a list of all the series in the rider db."""
        ret = []
        for row in self.model:
            if row[COL_SERIES] not in ret:
                ret.append(row[COL_SERIES])
        return ret

    def listcats(self, series=None):
        """Return a list of all the categories in the specified series."""
        ret = []
        for row in self.model:
            if row[COL_CAT] not in ret and (
                    series is None or row[COL_SERIES] == series):
                ret.append(row[COL_CAT])
        return ret

    def getvalue(self, ref, col):
        """Return the specified column from the supplied row."""
        ret = None
        if ref.valid():
            ret = self.model[ref.get_path()][col]
        return ret

    def editrider(self, ref=None, first=None, last=None,
                  club=None, cat=None, refid=None):
        """Create or update the rider with supplied parameters."""
        i = None
        if ref is None:
            i = self.model.append([num, '', '', '', '', False])
            ref = gtk.TreeRowReference(self.model,
                                           self.model.get_path(i))
        if ref.valid():
            i = self.model.get_iter(ref.get_path())
            if first is not None:
                self.model.set_value(i, COL_FIRST, first)
            if last is not None:
                self.model.set_value(i, COL_LAST, last)
            if club is not None:
                self.model.set_value(i, COL_CLUB, club)
            if cat is not None:
                self.model.set_value(i, COL_CAT, cat)
            if refid is not None:
                self.model.set_value(i, COL_REFID, refid)
        return ref

    def filter_nonempty(self, col=None):
        """Return a filter model with col non empty."""
        ret = self.model.filter_new()
        ret.set_visible_func(self.__filtercol, col)
        return ret
        
    def __editcol_cb(self, cell, path, new_text, col):
        """Update model if possible and request post-edit movement."""
        ret = False
        if new_text is not None:
            new_text = new_text.strip()
            if new_text != self.model[path][col]:
                if col == COL_BIB:
                    if new_text.isalnum():
                        if not self.getrider(new_text,
                                             self.model[path][COL_SERIES]):
                            self.model[path][COL_BIB] = new_text
                            ret = True
                        else:
                            self.log.warn(
                              'Refusing to update no. to duplicate rider.')
                            self.postedit='same'
                            ret = True	# re-focus on the entry
                    else:
                        self.log.warn('Invalid no. number ignored.')
                elif col == COL_SERIES:
                    if not self.getrider(self.model[path][COL_BIB], new_text):
                        self.model[path][COL_SERIES] = new_text
                        ret = True
                    else:  # This path is almost never a real problem
                        self.log.debug(
                          'Refusing to update series to duplicate rider.')
                        ret = True
                else:
                    self.model[path][col] = new_text
                    ret = True
            else:	# No Change, but entry 'accepted'
                ret = True
        if ret and self.postedit is not None:
            glib.idle_add(self.__postedit_move, path, self.colmap[col])
        return ret

    def __postedit_move(self, path, col):
        """Perform a post-edit movement of the selection.

           NOTE: This 'col' refers to VIEW column index and not the
                 model's column index.

        """
        if self.postedit is None:	# race possible here
            return False

        # step 1: process left/right
        if self.postedit == 'left':
            col -= 1
            self.postedit = None
        elif self.postedit == 'right':
            col += 1
            self.postedit = None

        if col < 0:
            col = len(self.colmap) - 1
            self.postedit = 'up'    # followup with a upward movement
        elif col >= len(self.colmap):
            col = 0
            self.postedit = 'down'  # followup with a downward movement

        # step 2: check for additional up/down
        i = self.model.get_iter(path)
        if self.postedit == 'up':
            p = int(self.model.get_string_from_iter(i)) - 1
            if p >= 0:
                path = self.model.get_path(
                            self.model.get_iter_from_string(str(p)))
            else:
                return False    # can't move any further 'up'
        elif self.postedit == 'down':
            i = self.model.iter_next(i)
            if i is not None:
                path = self.model.get_path(i)
            else:
                return False    # no more rows to scroll to -> perhaps add?
        self.postedit = None    # suppress any further change
        return self.__moveto_col(path, col)

    def __moveto_col(self, path, col):
        """Move selection to supplied path and column.

           NOTE: This 'col' refers to VIEW column index and not the
                 model's column index.

        """
        self.view.scroll_to_cell(path,
                                 self.view.get_column(col),
                                 False)
        self.view.set_cursor(path,
                             self.view.get_column(col), True)
        return False

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
            elif key in ['Return', 'Escape']:   # allow cancel to handle
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
        if type(editable) is gtk.Entry:
            self.editwasempty = len(editable.get_text()) == 0
            editable.connect('key-press-event', self.__edit_entry_key_cb)
        else:   # this is crap - but don't know the type
            self.editwasempty = False

    def __filtercol(self, model, iter, data=None):
        return bool(self.model.get_value(iter, data))

    def __iter__(self):
        """Return a generator for the rider model."""
        return uiutil.liststore_inorder(self.model)

    def __init__(self):
        """Constructor for the rider db.

        Constructs a new rider database object. This function does
        not create the view object, use the mkview() function to
        create and return a valid treeview.

        """

        self.log = logging.getLogger('scbdo.riderdb')
        self.log.setLevel(logging.DEBUG)
        self.model = gtk.ListStore(gobject.TYPE_STRING,	# 0 bib
                                   gobject.TYPE_STRING, # 1 first name
                                   gobject.TYPE_STRING, # 2 last name
                                   gobject.TYPE_STRING, # 3 club
                                   gobject.TYPE_STRING, # 4 category
                                   gobject.TYPE_STRING, # 5 series
                                   gobject.TYPE_STRING) # 6 refid
        self.view = None
        self.colvec = []
        self.postedit = None
        self.editwasempty = False

if __name__ == "__main__":
    import sys
    import pygtk
    pygtk.require('2.0')
    
    rdb = riderdb()

    # Check cmd line
    filename = 'riders.csv'
    if len(sys.argv) == 2:
        filename = sys.argv[1]
    print("loading from " + repr(filename))
    rdb.load(filename)

    win = gtk.Window()
    win.set_title('SCBdo :: Rider DB test')
    win.add(uiutil.vscroller(rdb.mkview()))
    win.connect('destroy', lambda *x: gtk.main_quit())
    win.show()

    gtk.main()
