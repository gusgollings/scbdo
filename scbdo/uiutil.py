
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

"""Shared gtk UI helper functions."""

import os
import gtk
import gobject
import pango
import scbdo
from scbdo import tod
from scbdo import strops

# Button BG colours
bg_none = None
bg_armstart = gtk.gdk.color_parse("#6fff9f")    # start time green
bg_armint = gtk.gdk.color_parse("#ff9f2f")      # intermediate time orange
bg_armfin = gtk.gdk.color_parse("#ff6f6f")      # finish time red

def liststore_inorder(model):
    """Generator for returning treeRowRefs from a list store."""
    if model:
        i = model.get_iter_first()
        while i is not None:
            yield gtk.TreeRowReference(model, model.get_path(i))
            i = model.iter_next(i)

def hvscroller(child):
    """Return a new scrolled window packed with the supplied child."""
    vs = gtk.ScrolledWindow()
    vs.show()
    vs.set_border_width(5)
    vs.set_shadow_type(gtk.SHADOW_IN)
    vs.set_policy(gtk.POLICY_AUTOMATIC, gtk.POLICY_AUTOMATIC)
    vs.add(child)
    return vs

def vscroller(child):
    """Return a new scrolled window packed with the supplied child."""
    vs = gtk.ScrolledWindow()
    vs.show()
    vs.set_border_width(5)
    vs.set_shadow_type(gtk.SHADOW_IN)
    vs.set_policy(gtk.POLICY_NEVER, gtk.POLICY_AUTOMATIC)
    vs.add(child)
    return vs

def buttonchg(b, c, t=None):
    """Change a button bg and text in the same cmd."""
    b.modify_bg(gtk.STATE_NORMAL, c)
    b.modify_bg(gtk.STATE_PRELIGHT, c)
    b.modify_bg(gtk.STATE_SELECTED, c)
    if t is not None:
        b.set_label(t)

def mkviewcoltod(view=None, header='', cb=None, width=120, editcb=None):
    """Return a Time of Day view column."""
    i = gtk.CellRendererText()
    i.set_property('xalign', 1.0)
    i.set_property('font_desc', pango.FontDescription('monospace'))
    j = gtk.TreeViewColumn(header, i)
    j.set_cell_data_func(i, cb)
    if editcb is not None:
        i.set_property('editable', True)
        i.connect('edited', editcb)
    #j.set_sizing(gtk.TREE_VIEW_COLUMN_FIXED)
    j.set_min_width(width)
    view.append_column(j)
    return j

def mkviewcoltxt(view=None, header='', colno=None, cb=None,
                  width=None, halign=None, calign=None,
                  expand=False, editcb=None, maxwidth=None,
                  bgcol=None, fontdesc=None, fixed=False):
    """Return a text view column."""
    i = gtk.CellRendererText()
    if cb is not None:
        i.set_property('editable', True)
        i.connect('edited', cb, colno)
    if calign is not None:
        i.set_property('xalign', calign)
    if fontdesc is not None:
        i.set_property('font_desc', pango.FontDescription(fontdesc))
    j = gtk.TreeViewColumn(header, i, text=colno)
    if bgcol is not None:
        j.add_attribute(i, 'background', bgcol)
    if halign is not None:
        j.set_alignment(halign)
    if fixed:
        j.set_sizing(gtk.TREE_VIEW_COLUMN_FIXED)
    if expand:
        if width is not None:
            j.set_min_width(width)
        j.set_expand(True)
    else:
        if width is not None:
            j.set_min_width(width)
    if maxwidth is not None:
        j.set_max_width(maxwidth)
    view.append_column(j)
    if editcb is not None:
        i.connect('editing-started', editcb)
    return i

def mkviewcolbg(view=None, header='', colno=None, cb=None,
                  width=None, halign=None, calign=None,
                  expand=False, editcb=None, maxwidth=None):
    """Return a text view column."""
    i = gtk.CellRendererText()
    if cb is not None:
        i.set_property('editable', True)
        i.connect('edited', cb, colno)
    if calign is not None:
        i.set_property('xalign', calign)
    j = gtk.TreeViewColumn(header, i, background=colno)
    if halign is not None:
        j.set_alignment(halign)
    #j.set_sizing(gtk.TREE_VIEW_COLUMN_FIXED)
    if expand:
        if width is not None:
            j.set_min_width(width)
        j.set_expand(True)
    else:
        if width is not None:
            j.set_min_width(width)
    if maxwidth is not None:
        j.set_max_width(maxwidth)
    view.append_column(j)
    if editcb is not None:
        i.connect('editing-started', editcb)
    return i

def mkviewcolbool(view=None, header='', colno=None, cb=None,
                  width=None, expand=False):
    """Return a boolean view column."""
    i = gtk.CellRendererToggle()
    i.set_property('activatable', True)
    if cb is not None:
        i.connect('toggled', cb, colno)
    j = gtk.TreeViewColumn(header, i, active=colno)
    #j.set_sizing(gtk.TREE_VIEW_COLUMN_FIXED)
    if expand:
        j.set_min_width(width)
        j.set_expand(True)
    else:
        if width is not None:
            j.set_min_width(width)
    view.append_column(j)
    return i

def coltxtbibser(col, cr, model, iter, data):
    """Display a bib.ser string in a tree view."""
    (bibcol, sercol) = data
    cr.set_property('text', 
                    strops.bibser2bibstr(model.get_value(iter, bibcol),
                                         model.get_value(iter, sercol)))

def mkviewcolbibser(view=None, header='No.', bibno=0, serno=1,
                    width=None, expand=False):
    """Return a column to display bib/series as a bib.ser string."""
    i = gtk.CellRendererText()
    i.set_property('xalign', 1.0)
    j = gtk.TreeViewColumn(header, i)
    j.set_cell_data_func(i, coltxtbibser, (bibno, serno))
    if expand:
        j.set_min_width(width)
        j.set_expand(True)
    else:
        if width is not None:
            j.set_min_width(width)
    view.append_column(j)
    return i

def mktextentry(prompt, row, table):
    """Create and return a text entry within a gtk table."""
    l = gtk.Label(prompt)
    l.set_alignment(1.0, 0.5)
    l.show()
    table.attach(l, 0, 1, row, row+1, gtk.FILL, gtk.FILL, xpadding=5)
    e = gtk.Entry()
    e.set_width_chars(18)
    e.show()
    table.attach(e, 1, 2, row, row+1, gtk.FILL, gtk.FILL, xpadding=5)
    return e

def mkcomboentry(prompt, row, table, options):
    """Create and return a combo entry within a gtk table."""
    l = gtk.Label(prompt)
    l.set_alignment(1.0, 0.5)
    l.show()
    table.attach(l, 0, 1, row, row+1, gtk.FILL, gtk.FILL, xpadding=5)
    c = gtk.combo_box_new_text()
    c.show()
    for opt in options:
        c.append_text(opt)
    table.attach(c, 1, 2, row, row+1, gtk.FILL, gtk.FILL, xpadding=5)
    return c

def mklbl(prompt, row, table):
    """Create and return label within a gtk table."""
    l = gtk.Label(prompt)
    l.set_alignment(1.0, 0.5)
    l.show()
    table.attach(l, 0, 1, row, row+1, gtk.FILL, gtk.FILL, xpadding=5)
    e = gtk.Label()
    e.set_alignment(0.0, 0.5)
    e.modify_font(pango.FontDescription("monospace"))
    e.show()
    table.attach(e, 1, 2, row, row+1, gtk.FILL, gtk.FILL, xpadding=5)
    return e

def mkbutintbl(prompt, row, col, table):
    """Create and return button within a gtk table."""
    b = gtk.Button(prompt)
    b.show()
    table.attach(b, col, col+1, row, row+1, gtk.FILL, gtk.FILL,
                 xpadding=5, ypadding=5)
    return b

def questiondlg(window, question, subtext=None):
    """Display a question dialog and return True/False."""
    dlg = gtk.MessageDialog(window, gtk.DIALOG_MODAL,
                            gtk.MESSAGE_QUESTION, gtk.BUTTONS_YES_NO,
                            question)
    if subtext is not None:
        dlg.format_secondary_text(subtext)
    ret = False
    response = dlg.run()
    if response == gtk.RESPONSE_YES:
        ret = True
    dlg.destroy()
    return ret    

def now_button_clicked_cb(button, entry=None):
    """Copy the 'now' time of day into the supplied entry."""
    if entry is not None:
        entry.set_text(tod.tod('now').timestr())

def edit_times_dlg(window, st=None, ft=None):
    """Display times edit dialog and return updated start and end times."""
    b = gtk.Builder()
    b.add_from_file(os.path.join(scbdo.UI_PATH, 'edit_times.ui'))
    dlg = b.get_object('timing')
    dlg.set_transient_for(window)

    se = b.get_object('timing_start_entry')
    se.modify_font(pango.FontDescription("monospace"))
    if st is not None:
        se.set_text(st)
    b.get_object('timing_start_now').connect('clicked',
                  now_button_clicked_cb, se)

    fe = b.get_object('timing_finish_entry')
    fe.modify_font(pango.FontDescription("monospace"))
    if ft is not None:
        fe.set_text(ft)
    b.get_object('timing_finish_now').connect('clicked',
                  now_button_clicked_cb, fe)
    ret = dlg.run()
    st = se.get_text().strip()
    ft = fe.get_text().strip()
    dlg.destroy()
    return (ret, st, ft)

