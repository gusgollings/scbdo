
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

"""Preliminary print primitives for race reports."""

import pango
import gtk

def pixmap(cr, filename, x, y, w=None, h=None, align='l'):
    """Display a pixmap at x,y scaled to w x h and aligned l|c|r."""

    cr.save()
    pixbuf = gtk.gdk.pixbuf_new_from_file(filename)
    imgw=pixbuf.get_width()
    imgh=pixbuf.get_height()
    if w is not None:
        sf = float(w)/float(imgw)
    elif h is not None:
        sf = float(h)/float(imgh)
    if align == 'r':
        x -= int(sf * float(imgw))
    elif align == 'c':
        x -= int(0.5 * sf * float(imgw))
    #sbuf = pixbuf.scale_simple(int(sf * imgw),
                               #int(sf * imgh), gtk.gdk.INTERP_BILINEAR)
    cr.translate(x, y)
    cr.scale(sf, sf)
    img = cr.set_source_pixbuf(pixbuf,0,0)
    #img = cr.set_source_pixbuf(sbuf,0,0)
    cr.paint()

    cr.restore()

def text_cent(cr, cx, w, y, msg, desc=None):
    """Position msg with font desc at y centered on page of width w."""
    cr.save()
    layout = cx.create_pango_layout()
    if desc is not None:
        layout.set_font_description(pango.FontDescription(desc))
    layout.set_text(msg)
    (tw,th) = layout.get_pixel_size()
    tof = (w-tw) // 2
    cr.move_to(tof,y)
    cr.update_layout(layout)
    cr.show_layout(layout)
    cr.stroke()
    cr.restore()

def text_left(cr, cx, x, y, msg, desc=None):
    """Position msg with font desc at x,y left aligned."""
    cr.save()
    layout = cx.create_pango_layout()
    if desc is not None:
        layout.set_font_description(pango.FontDescription(desc))
    layout.set_text(msg)
    cr.move_to(x, y)
    cr.update_layout(layout)
    cr.show_layout(layout)
    cr.stroke()
    cr.restore()

def text_right(cr, cx, x, y, msg, desc=None):
    """Position msg with font desc at x,y right aligned."""
    cr.save()
    layout = cx.create_pango_layout()
    if desc is not None:
        layout.set_font_description(pango.FontDescription(desc))
    layout.set_text(msg)
    (tw,th) = layout.get_pixel_size()
    cr.move_to(x-tw, y)
    cr.update_layout(layout)
    cr.show_layout(layout)
    cr.stroke()
    cr.restore()

def hline(cr, w, y):
    """Draw a horizontal line of width w at y."""
    cr.save()
    cr.set_source_rgb(0.2, 0.2, 0.2);
    cr.set_line_width(1)
    cr.move_to(0,y)
    cr.line_to(w,y)
    cr.stroke()
    cr.restore()

def header(cr, cx, w, title, subtitle):
    """Draw the common header elements."""
    text_cent(cr, cx, w, 10, title, "sans bold 12")
    text_cent(cr, cx, w, 25, subtitle, "sans italic 11")
    hline(cr, w, 45)

def footer(cr, cx, w, h, lstr, rstr, ly=45):
    """Draw the common footer elements."""
    text_left(cr, cx, 0, h-5, lstr, "sans italic 9")
    text_right(cr, cx, w, h-5, rstr, "sans italic 9")
    hline(cr, w, h-ly)

def bodyblock(cr, cx, w, msg, head=False):
    """Position a block of body text in the middle of the page."""
    text_cent(cr, cx, w, 60, msg, "monospace 10")
