
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

"""Rider name database helper object.

This module provides a simple object helper for manipulating the
rider namebank database. Methods are provided for retrieving rows
by license no and for searching by name.

namebank objects are intended to be used in a 'with' context eg:

  with namebank() as n:
     matches = n.search('first', 'last')

"""

import os
import shelve

import scbdo
from scbdo import strops


class namebank(object):
    """Namebank storage and search module.

    The namebank object maintains a persistent storage of rider rows
    with the following structure:

      KEY -- String: CA license 'no' or rider ID
      VAL -- Array: [ID, FIRST, LAST, CLUB, CAT, REFID, ABBR, STATE]

    Searching by name uses an internal index to facilitate speedy
    return of matching riders.

    Internally two python shelve objects are used to map search keys
    to lists of rider info (for the namebank) or rider ids (for the
    name index).

    """
    def __init__(self):
        """Constructor."""
        self.__open = False
        self.__nb = None
        self.__ind = None

    def open(self):
        """(Re)Open the namebank database files."""
        self.close()
        self.__nb = shelve.open(os.path.join(scbdo.DATA_PATH, 'namebank'))
        self.__ind = shelve.open(os.path.join(scbdo.DATA_PATH, 'nameindx'))
        self.__open = True

    def close(self):
        """Close the namebank database files."""
        if self.__nb is not None:
            self.__nb.close()
            self.__nb = None
        if self.__ind is not None:
            self.__ind.close()
            self.__ind = None
        self.__open = False

    def search(self, first='', last=''):
        """Return a set of matching rider ids from the namebank."""

        # reformat search strings
        fs = strops.search_name(first)
        ls = strops.search_name(last)

        # Build candidate id set
        cset = set()
        if fs[0:4] in self.__ind:
            cset = cset.union(self.__ind[fs[0:4]])
        if ls[0:4] in self.__ind:
            cset = cset.union(self.__ind[ls[0:4]])

        # filter candidates further on full search string
        fset = set()
        if len(first) > 0:
            for r in cset:
                fn = self.__nb[r][1]
                if strops.search_name(fn).find(fs) == 0:
                    fset.add(r)	# mark r in first name set
        else:
            fset = cset		# 'empty' first matches all
        lset = set()
        if len(last) > 0:
            for r in cset:
                ln = self.__nb[r][2]
                if strops.search_name(ln).find(ls) == 0:
                    lset.add(r)	# mark r in last name set
        else:
            lset = cset

        # return intersection of fset and lset
        return(fset.intersection(lset))

    def __len__(self):
        """Called to implement the built-in function len()."""
        return len(self.__nb)

    def __getitem__(self, key):
        """Called to implement evaluation of self[key]."""
        return self.__nb[key]

    def __contains__(self, key):
        """Called to implement membership test operators."""
        return key in self.__nb

    def __enter__(self):
        """Enter the runtime context related to this object."""
        if not self.__open:
            self.open()
        return self

    def __exit__(self, exc_type, exc_value, tb):
        """Exit the runtime context related to this object."""
        self.close()
