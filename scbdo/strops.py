
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

"""Basic string filtering, truncation and padding."""

import re
import scbdo

PLACELIST_TRANS = '\
        \
        \
        \
        \
        \
     -  \
01234567\
89      \
 ABCDEFG\
HIJKLMNO\
PQRSTUVW\
XYZ     \
 abcdefg\
hijklmno\
pqrstuvw\
xyz     \
        \
        \
        \
        \
        \
        \
        \
        \
        \
        \
        \
        \
        \
        \
        \
        '
"""Bib translation table for place listings."""

PLACESERLIST_TRANS = '\
        \
        \
        \
        \
        \
     -. \
01234567\
89      \
 ABCDEFG\
HIJKLMNO\
PQRSTUVW\
XYZ     \
 abcdefg\
hijklmno\
pqrstuvw\
xyz     \
        \
        \
        \
        \
        \
        \
        \
        \
        \
        \
        \
        \
        \
        \
        \
        '
"""Bib translation table for place listings with bib.ser strings."""

BIBLIST_TRANS = '\
        \
        \
        \
        \
        \
        \
01234567\
89      \
 ABCDEFG\
HIJKLMNO\
PQRSTUVW\
XYZ     \
 abcdefg\
hijklmno\
pqrstuvw\
xyz     \
        \
        \
        \
        \
        \
        \
        \
        \
        \
        \
        \
        \
        \
        \
        \
        '
"""Bib translation table for parsing bib lists."""

BIBSERLIST_TRANS = '\
        \
        \
        \
        \
        \
      . \
01234567\
89      \
 ABCDEFG\
HIJKLMNO\
PQRSTUVW\
XYZ     \
 abcdefg\
hijklmno\
pqrstuvw\
xyz     \
        \
        \
        \
        \
        \
        \
        \
        \
        \
        \
        \
        \
        \
        \
        \
        '
"""Bib.ser translation table for parsing bib.ser lists."""

PRINT_TRANS = '\
        \
        \
        \
        \
 !"#$%&\'\
()*+,-./\
01234567\
89:;<=>?\
@ABCDEFG\
HIJKLMNO\
PQRSTUVW\
XYZ[\\]^_\
`abcdefg\
hijklmno\
pqrstuvw\
xyz{|}~ \
        \
        \
        \
        \
        \
        \
        \
        \
        \
        \
        \
        \
        \
        \
        \
        '
"""Basic printing ASCII character table."""

def fitname(first, last, width, trunc=False):
    """Return a 'nicely' truncated name field for display.

    Attempts to modify name to fit in width as follows:

    1: 'First Lastone-Lasttwo'    - simple concat
    2: 'First Lasttwo'            - ditch hypenated name
    3: 'F. Lasttwo'               - abbrev first name
    4: 'F Lasttwo'                - get 1 xtra char omit period
    5: 'F. Lasttwo'               - give up and return name for truncation

    If optional param trunc is set and field would be longer than
    width, truncate and replace the last 3 chars with elipsis '...'

    """
    ret = ''
    fstr = str(first).strip()
    lstr = str(last).strip().upper()
    trystr = (fstr + ' ' + lstr).strip()
    if len(trystr) > width:
        lstr = lstr.split('-')[-1].strip()
        trystr = fstr + ' ' + lstr
        if len(trystr) > width:
            if len(fstr) > 0:
                trystr = fstr[0] + '. ' + lstr
            else:
                trystr = lstr
            if len(trystr) == width + 1 and len(fstr) > 0:  # opportunistic
                trystr = fstr[0] + ' ' + lstr
    if trunc:
        ret = trystr[0:width]
        if width > 6:
            if len(trystr) > width:
                ret = trystr[0:(width - 3)] + '...'
    else:
        ret = trystr
    return ret

def num2ord(place):
    """Return ordinal for the given place."""
    omap = { '1' : 'st',
             '2' : 'nd',
             '3' : 'rd',
             '11' : 'th',
             '12' : 'th',
             '13' : 'th' }
    if place in omap:
        return place + omap[place]
    elif len(place) > 1 and place[-1] in omap:
        return place + omap[place[-1]]
    elif place.isdigit():
        return place + 'th'
    else:
        return place

def truncpad(srcline, length, align='l'):
    """Return srcline truncated and padded to length, aligned as requested."""
    ret = srcline
    if length > 6:
        if len(srcline) > length:
            ret = srcline[0:(length - 3)] + '...'
        else:
            ret = srcline
    else:
        ret = srcline[0:length]
    if align == 'l':
        ret = ret.ljust(length)
    elif align == 'r':
        ret = ret.rjust(length)
    else:
        ret = ret.center(length)
    return ret

def search_name(namestr):
    return namestr.translate(BIBLIST_TRANS).strip().lower()

def resname_bib(bib, first, last, club):
    """Return rider name formatted for results with bib (champs/live)."""
    ret = bib + ' ' + fitname(first, last, 64)
    if club is not None and club != '':
        ret += ' (' + club + ')'
    return ret

def resname(first, last, club):
    """Return rider name formatted for results."""
    ret = fitname(first, last, 64)
    if club is not None and club != '':
        ret += ' (' + club + ')'
    return ret

def listname(first, last=None, club=None):
    """Return a rider name summary field for non-edit lists."""
    ret = fitname(first, last, 32)
    if club:
        ret += ' (' + club + ')'
    return ret

def reformat_bibserlist(bibserstr):
    """Filter and return a bib.ser start list."""
    return ' '.join(bibserstr.translate(BIBSERLIST_TRANS).split())

def reformat_bibserplacelist(placestr):
    """Filter and return a canonically formatted bib.ser place list."""
    if placestr.find('-') < 0:		# This is the 'normal' case!
        return reformat_bibserlist(placestr)
    # otherwise, do the hard substitutions...
    # TODO: allow the '=' token to indicate RFPLACES ok 
    placestr = placestr.translate(PLACESERLIST_TRANS).strip()
    placestr = re.sub(r'\s*\-\s*', r'-', placestr)	# remove surrounds
    placestr = re.sub(r'\-+', r'-', placestr)		# combine dupes
    return ' '.join(placestr.strip('-').split())

def reformat_biblist(bibstr):
    """Filter and return a canonically formatted start list."""
    return ' '.join(bibstr.translate(BIBLIST_TRANS).split())

def reformat_placelist(placestr):
    """Filter and return a canonically formatted place list."""
    if placestr.find('-') < 0:		# This is the 'normal' case!
        return reformat_biblist(placestr)
    # otherwise, do the hard substitutions...
    placestr = placestr.translate(PLACELIST_TRANS).strip()
    placestr = re.sub(r'\s*\-\s*', r'-', placestr)	# remove surrounds
    placestr = re.sub(r'\-+', r'-', placestr)		# combine dupes
    return ' '.join(placestr.strip('-').split())

def confopt_bool(confstr):
    """Check and return a boolean option from config."""
    if confstr.lower() in ['yes', 'true', '1']:
        return True
    else:
        return False

def confopt_float(confstr, default=None):
    """Check and return a floating point number."""
    ret = default
    try:
        ret = float(confstr)
    except ValueError:
        pass
    return ret

def confopt_distunits(confstr):
    """Check and return a valid unit from metres or laps."""
    if confstr.lower() == 'laps':
        return 'laps'
    else:
        return 'metres' 

def confopt_posint(confstr, default=None):
    """Check and return a valid positive integer."""
    ret = default
    if confstr.isdigit():
        ret = int(confstr)
    return ret

def confopt_dist(confstr, default=None):
    """Check and return a valid distance unit."""
    ret = default
    if confstr.isdigit():
        ret = int(confstr)
    return ret

def confopt_chan(confstr, default=None):
    """Check and return a valid timing channel id."""
    ret = default
    if confstr.isdigit() and len(confstr) == 1:
        ival = int(confstr)
        if ival >= 0 and ival <= 7:
            ret = ival
    return ival

def confopt_pair(confstr, value, default=None):
    """Return value or the default."""
    ret = default
    if confstr.lower() == value.lower():
        ret = value
    return ret

def confopt_list(confstr, list=[], default=None):
    """Return an element from list or default."""
    ret = default
    for elem in list:
        if confstr.lower() == elem.lower():
            ret = elem
            break
    return ret

def bibstr2bibser(bibstr=''):
    """Split a bib.series string and return bib and series."""
    a = bibstr.strip().split('.')
    ret_bib = ''
    ret_ser = ''
    if len(a) > 0:
        ret_bib = a[0]
    if len(a) > 1:
        ret_ser = a[1]
    return (ret_bib, ret_ser)

def bibser2bibstr(bib='', ser=''):
    """Return a valid bib.series string."""
    ret = bib
    if ser != '':
        ret += '.' + ser
    return ret

