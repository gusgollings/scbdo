
# SCBdo : DISC Track Racing Management Software
# Copyright (C) 2010,2011  Nathan Fraser
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

"""A collection of tools and applications for cycle racing events."""

import os
import gtk
import gobject
import logging
import sys

# 'check' python version
assert sys.version >= '2.6', "Missing pre-requisite: python >= 2.6"

VERSION = '1.3.0'
LIB_PATH = os.path.realpath(os.path.dirname(__file__))
UI_PATH = os.path.join(LIB_PATH, 'ui')
DB_PATH = os.path.join(LIB_PATH, 'data')
DATA_PATH = os.path.realpath(os.path.expanduser(
                             os.path.join('~', 'Documents', 'SCBdata')))
SCB_LINELEN = 24	# default scoreboard line length
SCB_LOGOFILE = os.path.join(UI_PATH, 'scbdo_icon.svg')

def init():
    """Shared SCBdo program initialisation."""
    print ("\n\
SCBdo(" + VERSION + ") Copyright (C) 2010,2011  Nathan Fraser\n\
This program comes with ABSOLUTELY NO WARRANTY.\n\
This is free software, and you are welcome to redistribute it\n\
under certain conditions.\n\n")

    # prepare for type 1 threads
    gobject.threads_init() 

    # fix the menubar accel mapping
    mset = gtk.settings_get_default()
    mset.set_string_property('gtk-menu-bar-accel', 'F24', 'override')

    # set the global default window icon
    try:
        gtk.window_set_default_icon_from_file(SCB_LOGOFILE)
    except:
        SCB_LOGOFILE = os.path.join(UI_PATH, 'scbdo_icon.png')
        gtk.window_set_default_icon_from_file(SCB_LOGOFILE)

    # Set global logging options
    logging._srcfile = None
    logging.logThreads = 0
    logging.logProcesses = 0

    # Check for data path and change working directory
    mk_data_path()
    os.chdir(DATA_PATH)

def mk_data_path():
    """Create shared data path if it does not exist."""
    if not os.path.exists(DATA_PATH):
        print ("SCBdo: Creating data directory " + repr(DATA_PATH))
        os.makedirs(DATA_PATH)

def help_docs(window):
    """Shell out to display help documents."""
    import platform
    if platform.system() == 'Windows':
        # shell out to explorer...
        pass
    else:
        import gnome
        props = {gnome.PARAM_APP_DATADIR:DB_PATH}
        prog = gnome.program_init('SCBdo', VERSION, properties=props)
        gnome.help_display('SCBdo')

def about_dlg(window):
    """Display SCBdo shared about dialog."""
    dlg = gtk.AboutDialog()
    dlg.set_transient_for(window)
    dlg.set_name('SCBdo')
    dlg.set_version(VERSION)
    dlg.set_copyright('Copyright (C) 2010,2011 Nathan Fraser')
    dlg.set_comments('Cycle race timing and data handling utilities')
    dlg.run()
    dlg.destroy()

