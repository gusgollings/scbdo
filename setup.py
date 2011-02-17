
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

from distutils.core import setup

import sys
assert sys.version >= '2.6', "Missing pre-requisite: python >= 2.6"

try:
    import pygtk
    pygtk.require("2.0")
except:
    print("Missing pre-requisite: pygtk >= 2.0")
    raise

try:
    import gtk
except:
    print("Missing pre-requisite: gtk")
    raise

setup(name = 'scbdo',
      version = '1.3.0',
      description = 'Cycle race timing and data handling utilities',
      author = 'Nathan Fraser',
      author_email = 'ndf@undershorts.org',
      url = 'http://scbdo.sourceforge.net/',
      packages = ['scbdo'],
      package_dir={'scbdo': 'scbdo'},
      package_data={'scbdo': ['ui/*', 'data/gnome/help/SCBdo/C/SCBdo.xml']},
      scripts = ['bin/wheeltime_test', 'bin/update_namebank', 'bin/trackmeet', 'bin/roadrace', 'bin/sportif', 'bin/track_announce', 'bin/road_announce'],
      classifiers = ['Development Status :: 3 - Alpha',
              'Environment :: X11 Applications :: GTK',
              'Intended Audience :: Other Audience',
              'License :: OSI Approved :: GNU General Public License (GPL)',
              'Natural Language :: English',
              'Operating System :: OS Independent',
              'Programming Language :: Python :: 2.6',
              'Topic :: Other/Nonlisted Topic' ],
      license = 'GNU GPL Version 3',
)
