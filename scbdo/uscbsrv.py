
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

"""uSCBsrv/IRC server class.

This module provides a thread object which maintains a persistent
uSCBsrv server connection to the configured irc server. Announce
messages are broadcast to the announcer.

Live announce messages are stored in a Queue object and written out
to the irc server using blocking I/O.

TODO: IRC connect and error handling is VERY messy - some more
      thought is required to cleanly handle all init and error
      conditions to avoid spurious reconnects and hang states

"""

import threading
import Queue
import logging
import socket
import random
import time

from scbdo import unt4
from scbdo import tod
from scbdo import strops

# Global Defaults
USCBSRV_HOST=''		# default is "not present"
USCBSRV_PORT=6667
USCBSRV_CHANNEL='#announce'
USCBSRV_SRVNICK='uSCBsrv'

# dispatch thread queue commands
TCMDS = ('EXIT', 'PORT', 'MSG')


def parse_portstr(portstr=''):
    """Read a port string and split into defaults."""
    port = USCBSRV_PORT
    host = ''
    nick = USCBSRV_SRVNICK

    # strip off nickname
    ar = portstr.rsplit('@', 1)
    if len(ar) == 2:
        nick = ar[0][0:9]	# limit nick to 9 char
        portstr = ar[1]
    else:
        portstr = ar[0]

    # read host:port
    ar = portstr.split(':')
    if len(ar) > 1:
        host = ar[0]
        if ar[1].isdigit():
            port = int(ar[1])
    else:
        host = ar[0]

    return (host, port, nick)

class uscbsrv(threading.Thread):
    """uSCBsrv server thread.

       methods are grouped as follows:

	- scbdo methods called by gtk main thread for 
	  manipulating the live announce stream, includes
          old-style DHI postxt and setline methods

	- uSCBsrv protocol methods called by uSCBsrv client
          communications - todo

	- irc protocol methods called by the lower level irclib


       If irclib is not present, this module reverts to a disconnected
       'black hole' sender.

    """

    ### SCBdo - GTK main thread methods

    def clrall(self):
        """Clear the live announce screen."""
        self.sendmsg(unt4.GENERAL_CLEARING)

    def clrline(self, line):
        """Clear the specified line in DHI database."""
        self.sendmsg(unt4.unt4(xx=0,yy=int(line),erl=True))

    def set_title(self, line):
        """Update the announcer's title line."""
        self.sendmsg(unt4.unt4(header='title',text=line))

    def set_time(self, tstr):
        """Update the announcer's time."""
        self.sendmsg(unt4.unt4(header='time',text=tstr))

    def set_start(self, stod):
        """Update the announcer's relative start time."""
        self.sendmsg(unt4.unt4(header='start',text=stod.rawtime()))

    def add_rider(self, rvec):
        """Send a rider vector to the announcer."""
        self.sendmsg(unt4.unt4(header='rider',text=chr(unt4.US).join(rvec)))

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

    def sendmsg(self, unt4msg=None):
        """Pack and send a unt4 message to the live announce stream."""
        self.queue.put_nowait(('MSG', unt4msg.pack()))

    def write(self, msg=None):
        """Send the provided raw text msg to the live announce stream."""
        self.queue.put_nowait(('MSG', msg))

    def exit(self, msg=None):
        """Request thread termination."""
        self.running = False
        self.queue.put_nowait(('EXIT', msg))

    def wait(self):             # NOTE: Do not call from cmd thread
        """Suspend calling thread until cqueue is empty."""
        self.queue.join()

    ### uSCBsrv protocol methods

    # TODO

    ### IRC protocol methods

    def irc_event_cb(self, c, e):
        """Debug method to collect all IRC events."""
        self.log.debug(str(e.eventtype()) + ' :: '
                         + str(e.source()) + '->' + str(e.target()) + ' :: '
                         + '/'.join(map(str, e.arguments())))

    def channel_join_cb(self, c, e):
        """Register channel join."""
        su = self.il.nm_to_n(e.source()).lower()
        tg = e.target().lower()
        if su == self.srvnick.lower() and tg == self.channel:
            self.chanstatus = True
            self.connect_pending = False # flags queue processing ok
            self.log.debug('Joined channel ' + str(e.target()))
            self.dumbcnt = 0

    def channel_part_cb(self, c, e):
        """Register channel part."""
        tg = e.target().lower()
        if (len(e.arguments()) > 0 and tg == self.channel
            and e.arguments()[0].lower() == self.srvnick.lower()):
            self.chanstatus = False
            self.log.debug('Left channel ' + str(e.target()))

    def privmsg_cb(self, c, e):
        """Handle private message."""
####
        su = self.il.nm_to_n(e.source()).lower()
        self.log.info('Received private message from ' + su + ' :: '
                        + ''.join(e.arguments()))

    ### uSCBsrv internals

    def __init__(self, linelen=32):
        """Constructor."""
        threading.Thread.__init__(self) 
        self.running = False
        self._curpace = 0.1
        self.il = None

        try:
            import irclib
            self.ih = irclib.IRC()
            self.il = irclib
        except ImportError:
            self.ih = fakeirc()
        self.ic = self.ih.server()

        self.np = tod.tod('now')+tod.tod('30')	# self ping timeeout

        self.name = 'uSCBsrv'
        self.rdbuf = ''
        self.wrbuf = ''
        self.chanstatus = False
        self.host = USCBSRV_HOST
        self.port = USCBSRV_PORT
        self.channel = USCBSRV_CHANNEL
        self.srvnick = USCBSRV_SRVNICK
        self.doreconnect = False
        self.connect_pending = False
        self.dumbcnt = 0

        self.curov = None
        self.linelen = linelen

        self.queue = Queue.Queue()
        self.log = logging.getLogger('scbdo.uscbsrv')
        self.log.setLevel(logging.DEBUG)

    def set_portstr(self, portstr='', channel='#announce'):
        """Set irc connection by a port string."""
        (host, port, nick) = parse_portstr(portstr)
        self.set_port(host, port, channel, nick)

    def set_port(self, host=None, port=None, channel=None,
                       srvnick=None, reconnect=False):
        """Request change in irc connection."""
        if host is not None and host != self.host:
            self.host = host
            if self.host == '' and self.ic.is_connected():
                self.ic.disconnect()
            else:
                reconnect = True
        if port is not None and port != self.port:
            self.port = port
            reconnect = True
        if channel is not None and channel != self.channel:
            self.channel = channel
            reconnect = True
        if srvnick is not None:
            self.srvnick = srvnick
            #self.srvnick = srvnick.lower()
            reconnect = True
        if reconnect:
            try:
                while True:
                    self.queue.get_nowait()
                    self.queue.task_done()
            except Queue.Empty:
                pass 
            self.queue.put_nowait(('PORT', ''))

    def connected(self):
        """Return true if connected and in channel."""
        return self.ic.is_connected() and self.chanstatus

    def _reconnect(self):
        if not self.connect_pending:
            self.connect_pending = True
            self.ic.connect(self.host, self.port, self.srvnick)
            self.ic.oper('SCBdo', 'ogfPOHYkaw')
            self.ic.join(self.channel)
            self.ic.mode(self.channel, '+tn')
            self.ic.topic(self.channel, 'uSCBsrv Live Result Feed')

    def _pacing(self, delay=None):
        """Adjust internal pacing delay."""
        if delay is None:
            self._curpace += 0.1
            if self._curpace > 1.5:
                self._curpace = 1.5
        else:
            self._curpace = delay
        return self._curpace

    def run(self):
        """Called via threading.Thread.start()."""
        self.running = True
        self.log.debug('Starting')
        self.ic.add_global_handler('privmsg', self.privmsg_cb, -10)
        self.ic.add_global_handler('join', self.channel_join_cb, -10)
        self.ic.add_global_handler('part', self.channel_part_cb, -10)
        self.ic.add_global_handler('kick', self.channel_part_cb, -10)
        ##self.ic.add_global_handler('all_events', self.irc_event_cb, 0)
        while self.running:
            try:
                self.ih.process_once(0)
                if self.host != '':
                    # irc process phase
                    if not self.connected() or self.doreconnect:
                        self.doreconnect = False
                        if not self.connect_pending:
                            self.chanstatus = False
                            self._reconnect()    

                    # keepalive ping
                    now = tod.tod('now')
                    if now > self.np:
                        self.ic.ctcp('PING', self.srvnick,
                                     str(int(time.time())))
                        self.np = now + tod.tod('60')
                else:
                    time.sleep(5)

                # queue process phase - queue empty exception breaks loop
                while True:
                    m = self.queue.get_nowait()
                    self.queue.task_done()
                    if m[0] == 'MSG' and self.host != '':
                        ## TODO : split message > 450 ?
                        self.ic.privmsg(self.channel, unt4.encode(m[1]))
                    elif m[0] == 'EXIT':
                        self.log.debug('Request to close : ' + str(m[1]))
                        self.running = False
                    elif m[0] == 'PORT':
                        if not self.connect_pending:
                            self.doreconnect = True
                    self._pacing(0.0)

            except Queue.Empty:
                time.sleep(self._pacing())	# pacing
            except Exception as e:
                self.log.error('Exception: ' + str(type(e)) + str(e))
                self.connect_pending = False
                self.dumbcnt += 1
                if self.dumbcnt > 2:
                    self.host = ''
                    self.log.debug('Not connected.')
                time.sleep(2.0)
        self.ic.close()
        self.log.info('Exiting')

class fakeirc(object):
    """Relacement dummy class for when irclib is not present."""
    def server(self):
        return self

    def process_once(self, delay=None):
        pass

    def is_connected(self):
        return False

    def disconnect(self):
        pass

    def connect(self, host=None, port=None, nick=None, data=None):
        """Fake an IOError to effectively shut down object."""
        raise IOError('IRC library not present.')

    def close(self, data=None):
        pass

    def oper(self, user=None, pword=None, data=None):
        pass

    def join(self, chan=None, data=None):
        pass

    def mode(self, chan=None, mode=None, data=None):
        pass

    def topic(self, chan=None, topic=None, data=None):
        pass

    def add_global_handler(self, sig=None, cb=None, arg=None, data=None):
        pass

    def ctcp(self, cmd=None, nick=None, ts=None, data=None):
        pass

    def privmsg(self, chan=None, msg=None, data=None):
        pass
    
if __name__ == '__main__':
    h = logging.StreamHandler()
    h.setLevel(logging.DEBUG)
    ann = uscbsrv()
    ann.log.addHandler(h)
    ann.start()
    count = 0
    while not ann.connected():
        print ('waiting for connect...')
        time.sleep(1)
    try:
        ann.clrall()
        ann.set_title('uSCBsrv library test.')
        ann.set_split(tod.tod('now'))
        ann.add_rider(['1.','2','Three FOUR (Five)', 'SIX', '43:01.64'])
        ann.add_rider([])
        ann.add_rider(['1.','2','Three FOUR (Five)', 'SIX', '43:03.64'])
        ann.add_rider(['1.','2','Three FOUR (Five)', 'SIX', '43:04.64'])
        ann.add_rider(['6.','2','Three FOUR (Five)', 'SIX', ''])
        ann.add_rider(['7.','2','Three FOUR (Five)', 'SIX', ''])
        ann.add_rider(['1.','2','Three FOUR (Five)', 'SIX', '43:05.64'])
        ann.add_rider(['1.','2','Three FOUR (Five)', 'SIX', '43:07.64'])
        while True:
           time.sleep(1)
           ann.set_split(tod.tod('now'))
           count += 1
           if count == 40:
               ann.set_port(host='')
           if count == 80:
               ann.set_port(host='192.168.95.16')
    except:
        ann.clrall()
        ann.wait()
        ann.exit()
        ann.join()
        raise
    
    ann.clrall()
    ann.wait()
    ann.exit()
    ann.join()
