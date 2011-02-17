SCBdo :: DISC Cycle racing support applications.


OVERVIEW
--------

Tools to support electronic timing, data handling and scoreboard
output at cycle races:

 - roadrace  : Mass start road race, IRTT and participation ride
               with RFID tags (supports Times7 wheeltime).

 - road_announce : Announcer terminal/scoreboard app for road races.

 - trackmeet : Timing, scoreboard and data handling for track events, use
               with Alge Timy and Omega galactica.

 - track_announce : Announcer terminal/scoreboard app for track meets.

 - ucihour   : UCI Hour record attempt timing and scoreboard for use 
               with Alge Timy and Omega galactica.


PRE-REQUISITES
--------------

Compulsory libraries:

	- python >= 2.6 < 3.0
	- gtk+/glib/cairo/pango >= 2.0
	- pygtk >= 2.0

Optional libraries:

	- gnome (for documentation browser)
	- pyserial (required for Alge timy support)
	- irclib (required for uSCBsrv/announcer comms)

Notes:

	- Standard Linux install (Debian or Ubuntu) meets all requirements.
	- for installation on windows please see below.


INSTALLATION
------------

Linux:

	- unpack distribution
	- run:  python ./setup.py install

Windows:

On windows (XP, Vista etc) the pre-requisites are quite difficult
to install. The following process works for XP, and should work
for other flavours.

Step 1: Install Python 2.6

 - Download and install Python 2.6. SCBdo is written with Python 3
   in mind, so it WILL NOT WORK with python2.5. Unfortunately it will
   also not yet work with python3 - since most of the libraries required
   do not exist for python3.

   Python installer for windows (version 2.6.5):

     http://python.org/ftp/python/2.6.5/python-2.6.5.msi

Step 2: Install GTK Runtime "bundle"

SCBdo uses the gtk+ user interface library, which is not a native
part of the Microsoft Windows family of operating systems. gtk++
has a number of complicated inter-dependancies, so the most reliable
way to install it is as follows:

 - Download the 2.20 "gtk+-bundle":

     http://ftp.gnome.org/pub/gnome/binaries/win32/gtk+/2.20/gtk+-bundle_2.20.0-20100406_win32.zip

 - Extract the whole lot to C:\gtk

 - Edit your PATH to include C:\gtk\bin

	[XP/2000]
	- Right-click "My Computer" and select "properties"
	- Select "Advanced" tab
	- Under "System Variables" select PATH and add:

		;C:\gtk\bin

	  To the end of the existing value

	[Vista (untested)]
	- Windows Key -> "Computer" -> "Properties"
	- Select "Advanced system settings"
	- Select "Environment Variables"
	- Select PATH and add as above.

  - Check GTK is installed correctly:

	- open a command terminal
	- type:

		gtk-demo

	- check that the GTK+ demo application runs.

  - Download and install the pygtk libraries:

	http://ftp.gnome.org/pub/GNOME/binaries/win32/pygobject/2.20/pygobject-2.20.0.win32-py2.6.exe
	http://ftp.gnome.org/pub/GNOME/binaries/win32/pycairo/1.8/pycairo-1.8.6.win32-py2.6.exe
	http://ftp.gnome.org/pub/GNOME/binaries/win32/pygtk/2.16/pygtk-2.16.0.win32-py2.6.exe

  - Run the scbdo windows installer.

