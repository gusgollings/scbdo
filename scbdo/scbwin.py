
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

"""Abstract and specific classes for scoreboard 'windows'.

This module provides a number of animated scoreboard window
objects for the display of lists, times and transitions.

A scoreboard window is a stateful information block that
may or may not be animated. All types of windows have the following
interface:

 reset()	reset state to start (calls redraw)
 pause()	toggle paused state, returns next val
 redraw()	redraw fixed screen elements
 update()	advance animation by one 'frame', caller is
		expected to repeatedly call update at ~20Hz

Specific scb-wins will have additional methods for setting internal
and incidental info.

Typical usage is something like:

    w = scbwintype(scb, typedata...)
    w.initstuff(typedata)
    w.reset()
    loop:
        w.update()

Shared properties for all scbwins:

	scb	A sender thread handle

Per-class init func should not draw onto screen, only redraw()
or first call to update() will emit anything to scb surface.

"""

import sender
import unt4
import time		# for time.strftime() :(

import scbdo
from scbdo import strops

PAGE_INIT=10		# count before table starts displaying
PAGE_DELAY=70		# def tenths of sec to hold each page of table
PAGE_ROWOFT=11		# first DHI row for table data
SP_PAGE_ROWOFT=6	# first DHI row for table data
DATE_FMT=('%a %d/%m/%y'
          + ' ' * (scbdo.SCB_LINELEN - 22)
          + '%H:%M:%S')

class scbwin(object):
    """Base class for all scoreboard windows.

    Classes inheriting from scbwin are required to override the
    update() and redraw() methods.

    """
    def __init__(self, scb=None):
        """Base class constructor."""
        self.paused = False
        self.scb = scb
        self.count = 0
        if type(self.scb) is not sender.sender:
            raise TypeError('scb param must be a sender type')

    def reset(self):
        """Reset scbwin to initial state."""
        self.count = 0
        self.redraw()
        self.paused = False

    def pause(self, set=None):
        """Update the pause property.

        If param 'set' is not provided toggle the current pause state,
        otherwise update pause to equal 'set'.

        """
        if set is not None:
           self.paused = bool(set)
        else:
           self.paused = not self.paused
        return self.paused

    def redraw(self):
        """Virtual redraw method."""
        pass

    def update(self):
        """Virtual update method."""
        self.count += 1

class scbclock(scbwin):
    """Event clock window.

    Display event lines under a date and time string. Eg:

      012345678901234567890123
       Sat 02/02/10__12:12:12		'__' expands with W
      ------------------------
           CENTERED LINE 1
           CENTERED LINE 2
           CENTERED LINE 3

    """
    def __init__(self, scb=None, line1='', line2='', line3=''):
        scbwin.__init__(self, scb)
        self.line1 = line1
        self.line2 = line2
        self.line3 = line3
        self.header = time.strftime(DATE_FMT)
        self.tovr = unt4.OVERLAY_4LINE
        if self.line3 == '':
            if self.line2 == '':
                if self.line1 == '':
                    self.tovr = unt4.OVERLAY_1LINE
                else:
                    self.tovr = unt4.OVERLAY_2LINE
            else:
                self.tovr = unt4.OVERLAY_3LINE
    def redraw(self):
        self.scb.setline(0, self.header)
        for i in range(1,4):
            self.scb.clrline(i)
        self.scb.setoverlay(self.tovr)
    def update(self):
        """Animate the clock window.

        After an initial pause, animate the title lines onto
        the scorebord with approx 0.1s delay between lines.

        Date and time in the header are autmomatically updated
        from the system time.

        """
        if not self.paused:
            if self.count == 14:
                self.scb.setline(1,self.line1)
            if self.count == 16:
                self.scb.setline(2,self.line2)
            if self.count == 18:
                self.scb.setline(3,self.line3)
            if self.count % 2 == 0:
                next = time.strftime(DATE_FMT)
                if next != self.header:
                    self.scb.setline(0, next)
                    self.header = next
            self.count += 1

class scbtt(scbwin):
    """Pursuit/ITT/Teams Timer window.

    Display a pursuit/time trial timer window with two names
    and two time values. Time values are copied onto the overlay
    within the update() method. No time calculations are conducted,
    this class only displays the strings provided.

    Example:

        012345678901234567890123
              Prefix Info
        ------------------------
        12 Blackburn Team 1
        >>>>>>>>(1) hh:mm:ss.dcm 
        10 Blackburn Team 2
        >>>>>>>>(3) hh:mm:ss.dcm 

    """
    def __init__(self, scb=None, header='',line1='', line2=''):
        scbwin.__init__(self, scb)
        self.header = header
        self.line1 = line1
        self.line2 = line2
        self.curt1 = ''
        self.nextt1 = ''
        self.curr1 = ''
        self.nextr1 = ''
        self.curt2 = ''
        self.nextt2 = ''
        self.curr2 = ''
        self.nextr2 = ''

    def redraw(self):
        self.scb.setline(4, self.header)
        self.scb.setline(6, self.line1)
        self.scb.setline(8, self.line2)
        self.scb.clrline(7)
        self.scb.clrline(9)
        self.curt1 = ''
        self.nextt1 = ''
        self.curr1 = ''
        self.nextr1 = ''
        self.curt2 = ''
        self.nextt2 = ''
        self.curr2 = ''
        self.nextr2 = ''
        self.scb.setoverlay(unt4.OVERLAY_R1P4)

    def sett1(self, timestr=''):
        """Set the next front straight time string."""
        self.nextt1 = timestr

    def sett2(self, timestr=''):
        """Set the next back straight time string."""
        self.nextt2 = timestr

    def setr1(self, rank=''):
        """Set the next front straight rank string."""
        self.nextr1 = rank

    def setr2(self, rank=''):
        """Set the next back straight rank string."""
        self.nextr2 = rank

    def update(self):
        """If any time or ranks change, copy new value onto overlay."""
        if not self.paused:
            if self.curr1 != self.nextr1:
                self.scb.setline(7,
                      strops.truncpad(self.nextr1, scbdo.SCB_LINELEN - 13,
                                      'r') + ' ' + self.nextt1)
                self.curr1 = self.nextr1
                self.curt1 = self.nextt1
            elif self.curt1 != self.nextt1:
                self.scb.postxt(7, scbdo.SCB_LINELEN - 12, self.nextt1)
                self.curt1 = self.nextt1
            if self.curr2 != self.nextr2:
                self.scb.setline(9,
                      strops.truncpad(self.nextr2, scbdo.SCB_LINELEN - 13,
                                      'r') + ' ' + self.nextt2)
                self.curr2 = self.nextr2
                self.curt2 = self.nextt2
            elif self.curt2 != self.nextt2:
                self.scb.postxt(9, scbdo.SCB_LINELEN - 12, self.nextt2)
                self.curt2 = self.nextt2
            self.count += 1

class scbtimer(scbwin):
    """Sprint timer window with avg speed.

    Copy provided time strings into pre-determined fields
    on the overlay. No time calcs are performed - this module
    only works on strings.

    Example:

        012345678901234567890123
          Blahface Point Score
          intermediate sprint
        ------------------------
              200m: hh:mm:ss.000
               Avg:  xx.yyy km/h

    """
    def __init__(self, scb=None, line1='', line2='',
                 timepfx='', avgpfx='Avg:'):
        scbwin.__init__(self, scb)
        self.line1 = line1
        self.line2 = line2
        self.timepfx = timepfx
        self.avgpfx = avgpfx
        self.curtime = ''
        self.nexttime = ''
        self.curavg = ''
        self.nextavg = ''

    def redraw(self):
        self.scb.setline(4, self.line1)
        self.scb.setline(5, self.line2)
        self.scb.setline(6, strops.truncpad(self.timepfx, 
                             scbdo.SCB_LINELEN - 13, 'r'))
        self.scb.clrline(7)
        self.curtime = ''
        self.nexttime = ''
        self.curavg = ''
        self.nextavg = ''
        self.scb.setoverlay(unt4.OVERLAY_R2P2)

    def settime(self, timestr=''):
        """Set the next time speed string."""
        self.nexttime = timestr

    def setavg(self, avgstr=''):
        """Set the next average speed string."""
        self.nextavg = avgstr

    def update(self):
        """If time or avg change, copy new value onto overlay."""
        if not self.paused:
            if self.curtime != self.nexttime:
                self.scb.postxt(6, scbdo.SCB_LINELEN - 12,
                                  self.nexttime)
                self.curtime = self.nexttime
            if self.curavg != self.nextavg:
                self.scb.setline(7,
                      strops.truncpad(self.avgpfx, scbdo.SCB_LINELEN - 13,
                                       'r') + ' ' + self.nextavg)
                self.curavg = self.nextavg
            self.count += 1

# A rider intro screen
#
# Line 1: 'header' displays immediately
# Line 2: number/hcap/'teaser' displays after 10th delay
# Line 3: Name/info types out char by char after 2-10th delay
# Line 4: (optional) types out after further 2-10th delay
#
# Pauses at completion of draw
class scbintro(scbwin):
    """Rider intro screen.

        Line 1: 'header' displays immediately
        Line 2: number/hcap/'teaser' displays after 10th delay
        Line 3: Name/info types out char by char after 2-10th delay
        Line 4: (optional) types out after further 2-10th delay
    
    """
    def redraw(self):
        self.scb.setline(0, self.header)
        for i in range(1,4):
            self.scb.clrline(i)
        self.scb.setoverlay(self.tovr)

    def update(self):
        if not self.paused:
            msgstart = PAGE_INIT + 6
            msgend = msgstart + 25
            if self.count == PAGE_INIT:	# draw prompt at ~+0.5s
                self.scb.setline(1,self.prompt)
            elif self.count >= msgstart and self.count < msgend:
                oft = self.count-msgstart
                if len(self.info) > oft:
                    self.scb.postxt(2, oft, self.info[oft])
            elif self.count == msgend:
                self.scb.setline(2, self.info)
                self.paused = True
            self.count += 1

    def setinfo(self, prompt='', info='', xtra=''):
        """Update overlay info."""
        self.prompt = str(prompt)[0:32]
        self.info = str(info)[0:32]
        self.xtra = str(xtra)[0:32]

    def __init__(self, scb=None, head='', lines=3):
        scbwin.__init__(self, scb)
        self.header = head
        self.lines = 3
        self.prompt = ''
        self.info = ''
        self.xtra = ''
        self.tovr = unt4.OVERLAY_3LINE
        if lines != 3:
            self.lines = 4
            self.tovr = unt4.OVERLAY_4LINE

class logoanim(scbwin):
    """Animated 'logo' screen."""
    def redraw(self):
        pass
        #self.scb.setoverlay(unt4.OVERLAY_IMAGE)

    def update(self):
        if not self.paused:
            if self.count % self.delay == 0:
                 dbline = 18
                 overlay = unt4.OVERLAY_IMAGE
                 # Alternate overlay
                 if self.curpg == 0:
                     self.curpg = 1
                     dbline = 19
                     overlay = unt4.OVERLAY_BLANK
                 else:
                     self.curpg = 0

                 # Set image content
                 curidx = (self.count//self.delay) % len(self.llist)
                 if self.llist[curidx] == 'CLOCK':
                     overlay = unt4.OVERLAY_CLOCK
                 else:
                     self.scb.setline(dbline, self.llist[curidx]) # set img
                 
                 # select overlay
                 self.scb.setoverlay(overlay)
                 if len(self.llist) == 1:
                     self.paused = True
            self.count += 1

    def set_logos(self, logostr):
        self.llist = []
        for l in logostr.split():
            self.llist.append(l)
        if len(self.llist) == 0:
            self.llist.append('')	# ensure one entry
 
    def __init__(self, scb=None, logolist='', delay=100):
        scbwin.__init__(self, scb)
        self.curpg = 0
        self.llist = []
        self.delay = delay
        self.set_logos(logolist)

class scbtest(scbwin):
    """A "test pattern" that loops over all the overlays."""
    def redraw(self):
        for i in range(0,19):
            self.scb.setline(i, 'Line ' + str(i)) 

    def update(self):
        if not self.paused:
            if self.count % 40 == 0:
                 self.scb.setoverlay(self.ovrs[self.curov])
                 self.curov = (self.curov + 1) % 4
            self.count += 1

    def __init__(self, scb=None, head='', lines=3):
        scbwin.__init__(self, scb)
        self.ovrs = [unt4.OVERLAY_4LINE, unt4.OVERLAY_R2P4, unt4.OVERLAY_24X6,
                     unt4.OVERLAY_IMAGE]
        self.curov = 0


class scbintsprint(scbwin):
    """Intermediate sprint window - scrolling table, with 2 headers.

    Parameters coldesc and rows as per scbtable)

    """
    def loadrows(self, coldesc=None, rows=None):
        self.rows=[]
        if coldesc is not None and rows is not None:
            for row in rows:
                nr = ''
                oft = 0
                for col in coldesc:
                    if type(col) is str:
                        nr += col
                    else:
                        if len(row) > oft:	# space pad 'short' rows
                            nr += strops.truncpad(row[oft], col[0], col[1])
                        else:
                            nr += ' ' * col[0]
                        oft += 1
                   
                self.rows.append(nr[0:32])
        self.nrpages = len(self.rows)//self.pagesz + 1
        if self.nrpages > 1 and len(self.rows) % self.pagesz == 0:
            self.nrpages -= 1
        # avoid hanging residual by scooting 2nd last entry onto
        # last page with a 'dummy' row, or scoot single line down by one
        if len(self.rows) % self.pagesz == 1:
            self.rows.insert(len(self.rows) - 2, ' ')

    def redraw(self):
        self.scb.setline(4, self.line1)
        self.scb.setline(5, self.line2)
        for i in range(6,10):
            self.scb.clrline(i)
        self.scb.setoverlay(self.tovr)

    def update(self):
        if self.count%2 == 0 and self.count > PAGE_INIT: # wait ~1/2 sec
            lclk = (self.count - PAGE_INIT) // 2
	    cpage = (lclk//self.delay) % self.nrpages
            pclk = lclk%self.delay
            if pclk < self.pagesz + 1:
                if pclk != self.pagesz:
                    self.scb.clrline(SP_PAGE_ROWOFT + pclk)
                elif self.nrpages == 1:
                    self.count += 1
                    self.paused = True       # no animate on single page
                if pclk != 0:
                    roft = self.pagesz * cpage + pclk-1
                    if roft < len(self.rows):
                        self.scb.setline(SP_PAGE_ROWOFT + pclk-1,
                                         self.rows[roft])
        if not self.paused:
            self.count += 1

    def __init__(self, scb=None, line1='', line2='',
                 coldesc=None, rows=None, delay=PAGE_DELAY):
        scbwin.__init__(self, scb)
        self.pagesz = 4
        self.nrpages = 0
        self.delay = delay
        self.tovr = unt4.OVERLAY_R2P4

        # prepare header -> must be preformatted
        self.line1 = line1[0:25]
        self.line2 = line2[0:25]

        # load rows
        self.rows = []		# formatted rows
        self.loadrows(coldesc, rows)


class scbtable(scbwin):
    """A self-looping info table.

    Displays 'pages' of rows formatted to coldesc:
   
    Coldesc: set of column tuples, each containing a field width
             as integer and the string 'l' or 'r' for left
             or right space padded, or a string constant
   
	       [(fieldwidth, l|r)|'str' ...]
   
    Example:  [(3,'r'), ' ', '(20,'l')]
 		   Three columns:
			   1: 3 character str padded to right
			   2: constant string ' '
			   3: 20 character str padded to left

    ADDED: timepfx and timestr for appending a time field to results

    """
    def loadrows(self, coldesc=None, rows=None):
        self.rows=[]
        if coldesc is not None and rows is not None:
            for row in rows:
                nr = ''
                oft = 0
                for col in coldesc:
                    if type(col) is str:
                        nr += col
                    else:
                        if len(row) > oft:	# space pad 'short' rows
                            nr += strops.truncpad(row[oft], col[0], col[1])
                        else:
                            nr += ' ' * col[0]
                        oft += 1
                self.rows.append(nr)	# truncation in sender ok
        self.nrpages = len(self.rows)//self.pagesz + 1
        if self.nrpages > 1 and len(self.rows) % self.pagesz == 0:
            self.nrpages -= 1
        # avoid hanging residual by scooting 2nd last entry onto
        # last page with a 'dummy' row, or scoot single line down by one
        if len(self.rows) % self.pagesz == 1:
            self.rows.insert(len(self.rows) - 2, ' ')

        # if time field set and not a round number of rows, append
        # time line to last row of last page
        finalmod = len(self.rows) % self.pagesz
        if self.timestr is not None and finalmod != 0:
            padrows = (self.pagesz - 1) - finalmod
            while padrows > 0:
                self.rows.append(' ')
                padrows -= 1
            self.rows.append(strops.truncpad(self.timepfx,
                                  scbdo.SCB_LINELEN - 13, 'r')
                                      + ' ' + self.timestr[0:12])

    def redraw(self):
        self.scb.setline(10, self.header)
        for i in range(11,18):
            self.scb.clrline(i)
        self.scb.setoverlay(self.tovr)

    def update(self):
        if self.count%2 == 0 and self.count > PAGE_INIT: # wait ~1/2 sec
            lclk = (self.count - PAGE_INIT) // 2
	    cpage = (lclk//self.delay) % self.nrpages
            pclk = lclk%self.delay
            if pclk < self.pagesz + 1:
                if pclk != self.pagesz:
                    self.scb.clrline(PAGE_ROWOFT + pclk)
                elif self.nrpages == 1:
                    self.count += 1
                    self.paused = True       # no animate on single page
                if pclk != 0:
                    roft = self.pagesz * cpage + pclk-1
                    if roft < len(self.rows):
                        self.scb.setline(PAGE_ROWOFT + pclk-1,
                                         self.rows[roft])
        if not self.paused:
            self.count += 1

    def __init__(self, scb=None, head='',
                 coldesc=None, rows=None, pagesz=7,
                 timepfx='', timestr=None, delay=PAGE_DELAY):
        scbwin.__init__(self, scb)
        # set page size
        self.pagesz = 7
        self.nrpages = 0
        self.delay = delay
        self.timestr = timestr
        self.timepfx = timepfx
        self.tovr = unt4.OVERLAY_T1P5
        if pagesz == 5:
            self.pagesz = 5		# ignore any other size
            self.tovr = unt4.OVERLAY_T1P4

        # prepare header -> must be preformatted
        self.header = head[0:scbdo.SCB_LINELEN]

        # load rows
        self.rows = []		# formatted rows
        self.loadrows(coldesc, rows)

# TODO: Tests for all window types.
