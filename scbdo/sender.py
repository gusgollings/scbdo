
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

"""SCBDO/DHI sender class.

This module provides a thread object which collects, queues
and dispatches all messages intended for the scoreboard to
the DHI. A calling application should use the sender methods
for all low-level scb drawing.

SCB messages are stored in a Queue object and written out to
the DHI using blocking I/O.

"""

import threading
import Queue
import logging
import socket

from scbdo import unt4
from scbdo import strops

# dispatch thread queue commands
TCMDS = ('EXIT', 'PORT', 'MSG')

class scbport(object):
    """Scoreboard communication port object."""
    def __init__(self, addr, protocol):
        """Constructor.

        Parameters:

          addr -- socket style 2-tuple (host, port)
          protocol -- one of socket.SOCK_STREAM or socket.SOCK_DGRAM

        """
        self.__s = socket.socket(socket.AF_INET, protocol)
        self.__s.connect(addr)
        if protocol is socket.SOCK_STREAM:
            # set the TCP 'no delay' option
            self.__s.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
        else:	# assume Datagram (UDP)
            # set all scb packets to look like 'EF' VoIP packets
            self.__s.setsockopt(socket.IPPROTO_IP, socket.IP_TOS, 0xB8)
        self.send = self.__s.send  # local cache the send() method
        self.running = True

    def sendall(self, buf):
        """Send all of buf to port."""
        msglen = len(buf)
        sent = 0
        while sent < msglen:
            out = self.send(buf[sent:])
            if out == 0:
                raise socket.error("DHI command socket broken")
            sent += out
        pass

    def close(self):
        """Shutdown socket object."""
        self.running = False
        try:
            self.__s.shutdown(socket.SHUT_RDWR)
        except:
            pass	# error here should not leak out

def mkport(port):
    """Create a new scbport socket object.

    port is a string specifying the DHI address as follows:

        [PROTOCOL:]ADDRESS[:PORT]

    Where:

        PROTOCOL :: TCP or UDP	(optional)
        ADDRESS :: hostname or IP address
        PORT :: port name or number (optional)

    The default protocol is UDP and the default port 5060.

    """
    nprot = socket.SOCK_DGRAM	# default is UDP
    naddr = 'localhost'		# default is localhost
    nport = 5060		# default is 'sip' scbport
    if port == 'SCBDO':
        nprot = socket.SOCK_STREAM
        naddr = 'scb.disc'
        nport = 2004
    elif port == 'DEBUG':
        pass
    else:
        vels = ['UDP', 'localhost', 'sip']
        aels = port.translate(strops.PRINT_TRANS).strip().split(':')
        if len(aels) == 3:
            vels[0] = aels[0].upper()
            vels[1] = aels[1]
            vels[2] = aels[2]
        elif len(aels) == 2:
            if aels[0].upper() in ['TCP', 'UDP']:
                # assume PROT:ADDR
                vels[0] = aels[0].upper()
                vels[1] = aels[1]
            else:
                vels[1] = aels[0]
                vels[2] = aels[1]
        elif len(aels) == 1:
            vels[1] = aels[0]
        else:
            raise socket.error('Invalid port specification string')

        # 'import' the vels...
        if vels[0] == 'TCP':
            nprot = socket.SOCK_STREAM
        elif vels[0] == 'UDP':
            nprot = socket.SOCK_DGRAM
        else:
            raise socket.error('Invalid protocol specified.')
        naddr = vels[1]
        if vels[2].isdigit():
            nport = int(vels[2])
        else:
            nport = socket.getservbyname(vels[2])
    
    ## split port string into [PROTOCOL:]ADDR[:PORT]
    return scbport((naddr, nport), nprot)

class sender(threading.Thread):
    """Galactica DHI sender thread.

    sender provides a helper object thread class to aid
    delivery of UNT4 message packets into an Omega Galactica
    DHI scoreboard 'database'. The class also provides basic
    text drawing primitives, overlay control and clearing.

    Scoreboard DHI database is assumed to comprise 20 rows
    (lines) of 32 latin_1 characters (columns). Mapping of
    database rows to overlay screens is outlined in the attached
    SCBdo DISC DHI documentation.

    """

    def clrall(self):
        """Clear all lines in DHI database."""
        self.sendmsg(unt4.GENERAL_CLEARING)

    def clrline(self, line):
        """Clear the specified line in DHI database."""
        self.sendmsg(unt4.unt4(xx=0,yy=int(line),erl=True))

    def setline(self, line, msg):
        """Set the specified DHI database line to msg."""
        msg = msg[0:self.linelen].ljust(self.linelen)
        msg = msg + ' ' * (self.linelen - len(msg))
        self.sendmsg(unt4.unt4(xx=0,yy=int(line),text=msg))

    def linefill(self, line, char='_'):
        """Use char to fill the specified line."""
        msg = char * self.linelen
        self.sendmsg(unt4.unt4(xx=0,yy=int(line),text=msg))

    def postxt(self, line, oft, msg):
        """Position msg at oft on line in DHI database."""
        assert oft >= 0, 'Offset should be >= 0'
        if oft < self.linelen:
            msg = msg[0:(self.linelen-oft)]
            self.sendmsg(unt4.unt4(xx=int(oft),yy=int(line),text=msg))

    def setoverlay(self, newov):
        """Request overlay newov to be displayed on the scoreboard."""
        if self.curov != newov:
            self.sendmsg(newov)
            self.curov = newov

    def __init__(self, port=None, linelen=32):
        """Constructor."""
        threading.Thread.__init__(self) 
        self.name = 'sender'
        self.port = None
        self.linelen = int(linelen)
        self.ignore = False
        self.curov = None
        self.queue = Queue.Queue()
        self.log = logging.getLogger('scbdo.sender')
        self.log.setLevel(logging.DEBUG)
        self.running = False
        if port is not None:
            self.setport(port)

    def sendmsg(self, unt4msg=None):
        """Pack and send a unt4 message to the DHI."""
        self.queue.put_nowait(('MSG', unt4msg.pack()))

    def write(self, msg=None):
        """Send the provided msg to the DHI."""
        self.queue.put_nowait(('MSG', msg))

    def exit(self, msg=None):
        """Request thread termination."""
        self.running = False
        self.queue.put_nowait(('EXIT', msg))

    def wait(self):             # NOTE: Do not call from cmd thread
        """Suspend calling thread until cqueue is empty."""
        self.queue.join()

    def setport(self, port=None):
        """Dump command queue content and (re)open DHI port.

        Specify hostname and port for TCP connection as follows:

            tcp:hostname:2004

        Or use system defaults:

		SCBDO -- TCP:scb.disc:2004
		DEBUG -- UDP:localhost:5060

        """
        try:
            while True:
                self.queue.get_nowait()
                self.queue.task_done()
        except Queue.Empty:
            pass 
        self.queue.put_nowait(('PORT', port))

    def set_ignore(self, ignval=False):
        """Set or clear the ignore flag.

        While the ignore flag is set commands will be read, but
        no packets will be sent to the DHI.

        """
        self.ignore = bool(ignval)

    def connected(self):
        """Return true if SCB connected."""
        return self.port is not None and self.port.running

    def run(self):
        """Called via threading.Thread.start()."""
        self.running = True
        self.log.debug('Starting')
        while self.running:
            m = self.queue.get()
            self.queue.task_done()
            try:
                if m[0] == 'MSG' and not self.ignore and self.port:
                    self.port.sendall(m[1])
                elif m[0] == 'EXIT':
                    self.log.debug('Request to close : ' + str(m[1]))
                    self.running = False
                elif m[0] == 'PORT':
                    if self.port is not None:
                        self.port.close()
                        self.port = None
                    if m[1] is not None and m[1] != '' and m[1] != 'NULL':
                        self.log.debug('Re-Connect port: ' + str(m[1]))
                        self.port = mkport(m[1])
                        self.curov = None
                    else:
                        self.log.debug('Not connected.')

            except IOError as e:
                self.log.error('IO Error: ' + str(type(e)) + str(e))
                if self.port is not None:
                    self.port.close()
                self.port = None
            except Exception as e:
                self.log.error('Exception: ' + str(type(e)) + str(e))
        if self.port is not None:
            self.port.close()
        self.log.info('Exiting')

if __name__ == "__main__":
    """Simple 'Hello World' example with logging."""
    h = logging.StreamHandler()
    h.setLevel(logging.DEBUG)
    s = sender('DEBUG')
    s.log.addHandler(h)
    s.clrall()				# queue commands
    s.setline(0, 'Hello World')
    s.setoverlay(unt4.OVERLAY_1LINE)
    s.start()				# start thread
    s.wait()				# wait for all cmds to be proc'd
    if s.connected():
        print('- sender still connected.')
    else:
        print('- sender not connected.')
    s.exit('hello done.')		# signal thread to end
    s.join()				# wait for thread to terminate
