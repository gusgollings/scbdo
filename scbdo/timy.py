
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

"""Alge Timy I/O helper.

This module provides a thread object which interfaces with an
Alge Timy connected via a serial connection. Methods are provided
to read timing events as tod objects and to write commands to
the Timy. 

A calling thread creates a timy thread and then polls for events
with the timy.response() method.

Timing events are delivered to the response queue if the timing channel
is armed. The channel is then de-armed automatically unless the armlock
has been set by the calling thread.

For example:

	Calling thread		Cmd Thread		Timy
						<-	C0 1:23.4567
				C0 not armed
	response is None
	arm(3)		->
				C3 armed
						<-	C3 1:24.4551
				C3 queued
	C3 1:24.4551	<-
				C3 dearmed
						<-	C3 1:24.4901
				C3 not armed
	response is None

When a calling thread sets the arming lock with timy.armlock(True),
a channel remains armed until explicitly dearmed by a calling thread.

Notes:

	- ALL timing impulses correctly read from an attached
	  Timy will be logged by the command thread with the log
	  label 'TIMER', even when the channel is not armed.

	- It is assumed that messages are received over the serial
	  connection in the same order as they are measured by
	  the Timy. This means that for any two tod messages read by
          a calling thread, say m1 and m2, the time measured by the
          Timy between the messages will be m2 - m1.

		m1 = timy.response()
                m2 = timy.response()
                net = m2 - m1

          This assumption has not yet been verified :/

"""

import threading
import Queue
import serial
import logging
import decimal

from scbdo import strops
from scbdo import tod

# System default timy serial port
TIMYPORT = '/dev/ttyUSB0'
MAINPORT = '/dev/ttyUSB0'
BACKUPPORT = '/dev/ttyUSB1'

# TIMY serial baudrate
TIMY_BAUD = 9600	# Note: Timy cannot keep up with faster baud

# thread queue commands -> private to timy thread
TCMDS = ('EXIT', 'PORT', 'MSG', 'ARM', 'DEARM', 'TRIG', 'SYNC')

# timing channels at DISC
CHAN_START = 0
CHAN_FINISH = 1
CHAN_PA = 2
CHAN_PB = 3
CHAN_AUX = 4
CHAN_100 = 5

TIMER_LOG_LEVEL = 25
logging.addLevelName(TIMER_LOG_LEVEL, 'TIMER')

adder = lambda sum, ch: sum + ord(ch)

def timy_checksum(msg):
    """Return the character sum for the Timy message string."""
    return reduce(adder, msg, 0) & 0xff

def timy_getsum(chkstr):
    """Convert Timy 'checksum' string to an integer."""
    return ((((ord(chkstr[0]) - 0x30) << 4) & 0xf0)
            | ((ord(chkstr[1]) - 0x30) & 0x0f))

class timy(threading.Thread):
    """Timy thread object class."""
    def __init__(self, port=None, name=None):
        """Construct timy thread object.

        Named parameters:

          port -- serial port number or device string
          name -- text identifier for use in log messages

        """
        threading.Thread.__init__(self) 
        nms = ['scbdo', 'timy']
        if name is not None:
            nms.append(str(name))
        self.name = '.'.join(nms)

        self.port = None
        self.armlocked = False
        self.arms = [False, False, False, False, False, False, False, False]
        self.error = False
        self.errstr = ''
        self.cqueue = Queue.Queue()	# command queue
        self.rqueue = Queue.Queue()	# response queue
        self.log = logging.getLogger(self.name)
        self.log.setLevel(logging.DEBUG)
        if port is not None:
            self.setport(port)

    def printline(self, msg=''):
        """Print msg to Timy printer, stripped and truncated."""
        lmsg = str(msg).translate(strops.PRINT_TRANS)[0:32]
        self.log.log(TIMER_LOG_LEVEL, lmsg)
        self.cqueue.put_nowait(('MSG', 'DTP' + lmsg + '\r'))

    def linefeed(self):
        """Advance Timy printer by one line."""
        self.cqueue.put_nowait(('MSG', 'PRILF\r'))

    def clrmem(self):
        """Clear memory in attached Timy."""
        self.cqueue.put_nowait(('MSG', 'CLR\r'))

    def printimp(self, doprint=True):
        """Enable or disable internal printing of timing impulses."""
        cmd = '1'
        if doprint:
            cmd = '0'
        self.cqueue.put_nowait(('MSG', 'PRIIGN' + cmd + '\r'))

    def write(self, msg=None):
        """Queue a raw command string to attached Timy."""
        self.cqueue.put_nowait(('MSG', str(msg).rstrip() + '\r'))

    def exit(self, msg=None):
        """Request thread termination."""
        self.running = False
        self.cqueue.put_nowait(('EXIT', msg)) # "Prod" command thread

    def setport(self, device=None):
        """Request (re)opening port as specified.

        Device may be a port number or a device identifier string.
        For information on port numbers or strings, see the
        documentation for serial.Serial().

        Call setport with no argument, None, or an empty string
        to close an open port or to run the timy thread with no
        external device.

        """
        self.cqueue.put_nowait(('PORT', device))

    def arm(self, channel):
        """Arm timing channel 0 - 8 for response through rqueue."""
        self.cqueue.put_nowait(('ARM', int(channel)))

    def dearm(self, channel=0):
        """De-arm timing channel 0 - 8 for response through rqueue."""
        self.cqueue.put_nowait(('DEARM', int(channel)))

    def armlock(self, lock=True):
        """Set or clear the arming lock."""
        self.armlocked = bool(lock)

    def sync(self):
        """Roughly synchronise Timy to PC clock."""
        self.cqueue.put_nowait(('SYNC', None))

    def sane(self):
        """Initialise Timy to 'sane' values.

        Values set by sane():

            TIMIYINIT		- initialise
            KL0			- keylock off
	    CHK1		- enable "checksum"
	    PRE4		- 10,000th sec precision
	    RR0			- Round by 'cut'
	    BE1			- Beep on
	    DTS00.02		- Start delay 0.02s
	    DTF00.02		- Finish & intermediate delay 0.02s
	    EMU0		- Running time off
	    PRIIGN1		- Don't print all impulses to receipt
	    PRILF		- Linefeed
	
        All commands are queued individually to the command thread
        so it is possible to use wait() to suspend the calling thread
        until the commands are sent:

            t.start()
	    t.sane()
	    t.wait()
    
        Note: "sane" here comes from use at track meets with the
              SCBdo program. It may not always make sense eg, to
              have all channel delays set to 2 hundredths of a
              second, or to have the internal impulse printing off
              by default.

        """
        for msg in ['TIMYINIT', 'NSF', 'KL0', 'CHK1', 'PRE4',
                    'RR0', 'BE1', 'DTS00.02', 'DTF00.02', 'EMU0',
                    'PRIIGN1', 'PRILF' ]:
            self.write(msg)

    def trig(self, channel=0, t=None):
        """Create a fake timing event.

        Parameters:

	    channel -- timing channel to 'fake'
	    t -- a tod object. If omitted, tod('now') is used

        Fake events are still subject to arming, but they are
        not sent to the attached Timy. While fake events are
        logged with a TIMER label, they will not appear on the
        Timy receipt unless printed explicitly.

        """
        if t is None:
            t = tod.tod('now')
        self.cqueue.put_nowait(('TRIG', int(channel), t))

    def response(self):
        """Check for a timing event in the response queue.

        Returns a tod object representing a timing event, or
        None if there are no tming events in the queue.

        """
        r = None
        try:
            r = self.rqueue.get_nowait()
            self.rqueue.task_done()
        except Queue.Empty:
            r = None
        return r

    def wait(self):
        """Suspend calling thread until the command queue is empty."""
        self.cqueue.join()

    def parse_impulse(self, msg):
        """Return tod object from timing msg or None."""
        ret = None
        msg = msg.rstrip()
        if len(msg) > 2:	# failsafe for [-2:] tsum slice
            tsum = timy_getsum(msg[-2:])
            csum = timy_checksum(msg[0:len(msg) - 2])
            if tsum == csum:
                e = msg.split()
                if len(e) == 4:
                    ret = tod.tod(timeval = e[2], index = e[0], chan = e[1])
                else:
                    self.log.error('Invalid message: ' + repr(msg))
            else:
                self.log.error('Corrupt message: ' + repr(msg))
                self.log.error('Checksum failed: 0x%02X != 0x%02X',
                               tsum, csum)
        else:
            self.log.warn('Short message: ' + repr(msg))
        return ret

    def procmsg(self, msg):
        """Process a raw message from the Timy.

        On reception of a timing channel message, the channel is
        compared against the list of armed channels. If the channel
        is armed, the tod object is inserted into the response queue.
        If the arm lock is not set, the channel is then de-armed.

        Other messages are ignored for now.

        Todo: Maintain a queue of commands sent and check non-timing
              responses against queued commands to help detect connection
	      errors. [low priority]

        """
        self.log.debug('Read msg = ' + repr(msg))
        if len(msg) > 5 and msg[0] == ' ' and msg[1:5].isdigit():
            st = self.parse_impulse(msg)
            if st is not None:
                self.log.log(TIMER_LOG_LEVEL, ' ' + str(st))
                if len(st.chan) > 1 and st.chan[0] == 'C':
                    channo = int(st.chan[1])
                    if self.arms[channo]:
                        self.rqueue.put_nowait(st)
                        self.log.debug('Queueing ToD: ' + str(st))
                        if not self.armlocked:
                            self.arms[channo] = False
                else:
                    self.log.warn('Got a non-channel impulse... Check program')
        elif msg[0:2].isdigit():
            pass			# EMU message
        else:
            pass			# other unknown message?

    def run(self):
        """Called via threading.Thread.start()."""
        running = True
        self.log.debug('Starting')
        while running:
            try:
                # Read phase
                if self.port is not None:
                    msg = self.port.readline(eol='\r')
                    if len(msg) > 0:
                        self.procmsg(msg)
                    m = self.cqueue.get_nowait()
                else:
                    # when no read port avail, block on read of command queue
                    m = self.cqueue.get()
                self.cqueue.task_done()
                
                # Write phase
                if type(m) is tuple and type(m[0]) is str and m[0] in TCMDS:
                    if m[0] == 'MSG' and not self.error:
                        self.log.debug('Sending rawmsg ' 
                              + str(m[1][0:12]).rstrip() + '...')
                        self.port.write(m[1].encode('latin_1'))
                    elif m[0] == 'ARM':
                        if type(m[1]) is int and m[1] < 8 and m[1] >= 0:
                            self.log.debug('Arming channel ' + str(m[1]))
                            self.arms[m[1]] = True;
                    elif m[0] == 'DEARM':
                        if type(m[1]) is int and m[1] < 8 and m[1] >= 0:
                            self.log.debug('De-Arming channel ' + str(m[1]))
                            self.arms[m[1]] = False;
                    elif m[0] == 'TRIG':
                        if type(m[1]) is int and m[1] < 8 and m[1] >= 0:
                            if type(m[2]) is tod.tod:
                                t = tod.tod(m[2].timeval, 'FAKE',
                                            'C' + str(m[1]) + 'i')
                                self.log.log(TIMER_LOG_LEVEL,' ' + str(t))
                                if self.arms[m[1]]:
                                    self.arms[m[1]] = False
                                    self.rqueue.put_nowait(t)
                    elif m[0] == 'SYNC' and not self.error:
                        self.log.debug('Rough synchronising to PC clock')
                        nowsec = tod.tod('now').timeval.quantize(
                         decimal.Decimal('1.'), rounding=decimal.ROUND_HALF_UP)
                        tstr = tod.tod(nowsec).rawtime(zeros=True)
                        sstr = 'SYNA' + tstr + '\r'
                        self.port.write(sstr.encode('latin_1'))
                        self.clrmem()
                        self.printline('PC SYNC : ' + tstr)
                    elif m[0] == 'EXIT':
                        self.log.debug('Request to close : ' + str(m[1]))
                        running = False	# This may already be set
                    elif m[0] == 'PORT':
                        if self.port is not None:
                            self.port.close()
                            self.port = None
                        if m[1] is not None and m[1] != '' and m[1] != 'NULL':
                            self.log.debug('Re-Connect port : ' + str(m[1]))
                            self.port = serial.Serial(m[1], TIMY_BAUD,
                                                      rtscts=1, timeout=0.2)
                            self.error = False
                        else:
                            self.log.debug('Not connected.')
                            self.error = True
                    else:
                        pass
                else:
                    self.log.warn('Unknown message: ' + repr(m))
            except Queue.Empty:
                pass
            except serial.SerialException as e:
                if self.port is not None:
                    self.port.close()
                    self.port = None
                self.errstr = "Serial port error."
                self.error = True
                self.log.error('Closed serial port: ' + str(type(e)) + str(e))
            except Exception as e:
                self.log.error('Exception: ' + str(type(e)) + str(e))
                self.errstr = str(e)
                self.error = True
        self.log.info('Exiting')

if __name__ == "__main__":
    import time
    t = timy(TIMYPORT)
    lh = logging.StreamHandler()
    lh.setLevel(logging.DEBUG)
    lh.setFormatter(logging.Formatter(
                      "%(asctime)s %(levelname)s:%(name)s: %(message)s"))
    t.log.addHandler(lh)
    try:
        t.start()
        t.sane()
        t.wait()
        t.clrmem()
        while True:
            t.trig(0)
            time.sleep(2)
    except:
        t.exit('Exception')
        raise
    t.exit('Timeout')
    t.join()
