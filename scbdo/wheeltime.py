
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

"""Times-7 Wheeltime helper.

This module provides a thread object which interfaces with the
Times-7 Wheeltime RFID system. Once connected, the thread will
collect RFID events from the wheeltime and deliver them to a calling
thread via a response queue.

A calling thread creates a wheeltime thread and then polls for 
new RFIDs with the wheeltime.response() method.

TCP/IP communicaton with an attached wheeltime unit is handled
by blocking I/O in a sub thread.

"""

import threading
import Queue
import logging
import decimal
import socket
import time

from scbdo import tod

# System defaults
#WHEELIP = 'localhost'		# Testing address
WHEELIP = '192.168.95.32'	# CSV wheeltime IP
#WHEELIP = '10.19.1.103'		# Old Times-7 wheeltime IP addr
WHEELRAWPORT = 10000		# Port for raw tag stream
WHEELFSPORT = 10200		# Port for FS/LS filtered stream
WHEELCMDPORT = 9999		# Wheeltime command port

# thread queue commands -> private to timy thread
TCMDS = ('RFID', 'EXIT', 'ADDR', 'MSG')

# Logging defaults
RFID_LOG_LEVEL = 16	# lower so not in status and on-screen logger.
logging.addLevelName(RFID_LOG_LEVEL, 'RFID')

adder = lambda sum, ch: sum + ord(ch)

def ipico_lrc(ipxstr='', el=34):
    """Return the so-called 'LRC' character sum from IPX module."""
    return reduce(adder, ipxstr[2:el], 0) & 0xff

def sendall(s, buf):
    """Send all of buf to socket s."""
    msglen = len(buf)
    sent = 0
    while sent < msglen:
        out = s.send(buf[sent:])
        if out == 0:
            raise socket.error("Wheeltime command socket broken")
        sent += out
        
class wtio(threading.Thread):
    """Wheeltime I/O Helper Thread.

    wtio provides a simple helper object thread class to
    perform blocking reads from an inet socket and deliver
    parsed Time of Day event objects back to a wheeltime
    thread object through the command queue.

    """
    def __init__(self, addr=None, cqueue=None, log=None):
        """Construct wheeltime I/O thread.

        Named parameters:

          addr -- tcp address or hostname of Wheeltime unit
          cqueue -- wheeltime thread command queue object
          log -- wheeltime thread log object

        """
        threading.Thread.__init__(self)
        self.daemon = True	# daemon so doesn't hold up main proc
        self.cqueue = cqueue
        self.log = log
        self.addr = addr
        self.rdbuf = ''
        self.running = False

    def close(self):
        """Signal thread for termination."""
        self.running = False

    def readline(self, s=None):
        """Return newline delimited lines from socket.

        This function works on an input buffer, returning one complete
        line per call or None if one is not yet fully received.

        """
        ret = None
        idx = self.rdbuf.find('\n')
        if idx < 0:
            inb = s.recv(2048)
            if inb == '':
                self.log.info('Wheeltime I/O connection broken')
                self.close()
            else:
                self.rdbuf += inb
            idx = self.rdbuf.find('\n')
        if idx >= 0:
            ret = self.rdbuf[0:idx+1]
            self.rdbuf = self.rdbuf[idx+1:]
        return ret

    def procmsg(self, msg):
        """Read IPX wheeltime event and insert as tod into command queue."""
        s = msg.strip()
        if (len(s) == 36 or len(s) == 38) and s[1] == 'a':
            sum = ipico_lrc(s)
            lrc = int(s[34:36], 16)
            if sum == lrc:
                #tagid=s[4:16]	## NOTE: Using 'shortform' tag ids
                if s[4:10] == '058001':	# match id prefix
                    tagid=(s[10:16]).lower()
                    timestr = '{0}:{1}:{2}.{3:02}'.format(s[26:28], s[28:30],
                                   s[30:32], int(s[32:34], 16))
                    self.cqueue.put_nowait(('RFID',
                          tod.tod(timestr, 'RFID', '', tagid)))
                else:
                    self.log.warn('Spurious tag id: ' + s[4:10] + ' :: ' 
                                    + s[10:16])
            else:
                self.log.warn('Incorrect char sum message skipped: ' 
                               + hex(sum) + ' != ' + hex(lrc))
        elif len(s) == 30 and s[0:8] == 'ab010a2c':
            sum = ipico_lrc(s, 28)
            lrc = int(s[28:30], 16)
            if sum == lrc:
                timestr = '{0}:{1}:{2}.{3:02}'.format(s[16:18], s[18:20],
                               s[20:22], int(s[22:24], 16))
                self.cqueue.put_nowait(('RFID',
                      tod.tod(timestr, 'RFID', '', 'trig')))
                #self.log.debug('TRIG MSG: ' + repr(s))
            else:
                self.log.warn('Incorrect char sum message skipped: ' 
                               + hex(sum) + ' != ' + hex(lrc))
        else:
            self.log.debug('Non RFID message: ' + repr(msg))

    def run(self):
        """Called via threading.Thread.start()."""
        self.running = True
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            s.settimeout(10)	# longer timeout is ok now
            s.connect((self.addr, WHEELFSPORT))
            while self.running:
                try:
                    m = self.readline(s)
                    if m is not None:
                        self.procmsg(m)
                except socket.timeout:
                    pass
            s.shutdown(socket.SHUT_RDWR)
            s.close()
        except Exception as e:
            self.running = False
            self.log.error('WTIO Exception: ' + repr(e))
            #raise		# No need to except here - thread dies.

class wheeltime(threading.Thread):
    """Wheeltime thread object class."""
    def __init__(self, addr=None, name=None):
        """Construct wheeltime thread object.

        Named parameters:
 
          addr -- ip address or hostname of wheeltime unit
          name -- text identifier for use in log messages

        """

        threading.Thread.__init__(self) 
        nms = ['scbdo', 'wheeltime']
        if name is not None:
            nms.append(str(name))
        self.name = '.'.join(nms)
        self.addr = None
        self.armed = False
        self.cqueue = Queue.Queue()	# command queue
        self.rqueue = Queue.Queue()	# response queue
        self.log = logging.getLogger(self.name)
        self.log.setLevel(logging.DEBUG)
        self.io = None
        self.running = False
        if addr is not None:
            self.setaddr(addr)

    def clrmem(self):
        """Clear wheeltime memory."""
        self.cqueue.put_nowait(('MSG', 'clear_history\n'))

    def write(self, msg=None):
        """Queue a raw command string."""
        self.cqueue.put_nowait(('MSG', str(msg).rstrip() + '\n'))

    def exit(self, msg=None):
        """Flag control thread termination."""
        self.running = False
        self.cqueue.put_nowait(('EXIT', msg))

    def setaddr(self, addr=None):
        """Request new wheeltime device address."""
        self.cqueue.put_nowait(('ADDR', addr))

    def arm(self):
        """Arm response queue."""
        self.log.debug('Arm response queue')
        self.armed = True

    def dearm(self):
        """De-arm response queue."""
        self.log.debug('De-arm response queue')
        self.armed = False

    def sync(self):
        """Rough synchronise wheeltime RTC to PC."""
        t = time.localtime()
        datestr = '{0}{1:02}{2:02}00{3:02}{4:02}{5:02}00'.format(
                     str(t[0])[2:], t[1], t[2], t[3], t[4], t[5])
        self.cqueue.put_nowait(('MSG', 'ab000701' + datestr + '\n'))

    def trig(self, refid=None):
        """Insert a fake rfid event into response queue."""
        t = tod.tod('now', 'FAKE')
        if refid is not None:
            t.refid = str(refid)
        self.cqueue.put_nowait(('RFID', t))

    def response(self):
        """Check for RFID events in response queue."""
        r = None
        try:
            r = self.rqueue.get_nowait()
            self.rqueue.task_done()
        except Queue.Empty:
            r = None
        return r

    def wait(self):		# NOTE: Do not call from cmd thread
        """Suspend calling thread until cqueue is empty."""
        self.cqueue.join()

    def command(self, command):		# NOTE: Lazy!
        """Connect to serv and dump a command."""
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.settimeout(0.5)
        s.connect((self.addr, WHEELCMDPORT))
        sendall(s, command.encode('latin_1'))
        s.shutdown(socket.SHUT_RDWR)
        s.close()

    def connected(self):
        """Return True if wheeltime unit connected."""
        return self.io and self.io.running

    def run(self):
        """Called via threading.Thread.start()."""
        self.running = True
        #self.log.debug('Starting')
        while self.running:
            try:
                # Read Phase
                m = self.cqueue.get()
                self.cqueue.task_done()
                
                # Write phase
                if m[0] == 'RFID':
                    assert type(m[1]) is tod.tod
                    self.log.log(RFID_LOG_LEVEL, ' ' + str(m[1]))
                    if self.armed:
                        self.rqueue.put_nowait(m[1])
                        #self.log.debug('Queueing RFID: ' + str(m[1]))
                elif m[0] == 'MSG':
                    if self.connected():
                        self.command(m[1])
                    else:
                        self.log.warn('Wheeltime not connected.')
                elif m[0] == 'EXIT':
                    self.running = False
                    self.log.debug('Request to close : ' + str(m[1]))
                elif m[0] == 'ADDR':
                    self.addr = None
                    if self.io is not None:
                        self.io.close()
                        self.io = None
                    if m[1] is not None and m[1] != '' and m[1] != 'NULL':
                        self.addr = m[1]
                        self.log.debug('Re-Connect wheeltime addr: ' + str(m[1]))
                        self.io = wtio(addr=self.addr, cqueue=self.cqueue,
                                       log=self.log)
                        self.io.start()
                    else:
                        self.log.info('Wheeltime not connected.')
                else:
                    self.log.warn('Unknown message: ' + repr(m))
            except Exception as e:
                self.log.error('Exception: ' + str(type(e)) + str(e))
        if self.io is not None:
            self.io.close()
        self.log.info('Exiting')

if __name__ == "__main__":
    w = wheeltime('localhost')
    lh = logging.StreamHandler()
    lh.setLevel(logging.DEBUG)
    lh.setFormatter(logging.Formatter(
                    "%(asctime)s %(levelname)s:%(name)s: %(message)s"))
    w.log.addHandler(lh)
    w.start()
    w.clrmem()
    w.sync()
    try:
        w.wait()
        w.arm()
        for r in ['fake01', 'fake02', 'fake03', 'fake04']:
            w.trig(r)
            time.sleep(5)
            # collect any events from response queue
            e = w.response()
            while e is not None:
                print ("RFID Event: " + str(e))
                e = w.response()
        w.dearm()
    except:
        w.exit('Exception')
        raise
    w.exit('Complete')
    w.join()
