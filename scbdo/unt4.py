
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

"""UNT4 Protocol Wrapper.

Pack and unpack UNT4 protocol messages for Omega Galactica DHI.

Note: Normal program code will not use this library directly
      except to access the pre-defined overlay messages. All
      scoreboard communication should go via the sender or
      scbwin classes.

Needs work:

  - pack() method should validate parameters for set
  - input strings should be scanned _once_ only, not twice
  - is I/O buffer part of this module?
    or does it belong in caller?

"""

# mode 1 constants
SOH = 0x01
STX = 0x02
EOT = 0x04
HOME= 0x08
CR  = 0x0d
LF  = 0x0a
ERL = 0x0b
ERP = 0x0c
DLE = 0x10
DC2 = 0x12
DC3 = 0x13
DC4 = 0x14
FS = 0x1c
GS = 0x1d
RS = 0x1e
US = 0x1f


ENCMAP = {
   chr(SOH):'<O>',
   chr(STX):'<T>',
   chr(EOT):'<E>',
   chr(HOME):'<H>',
   chr(CR):'<R>',
   chr(LF):'<A>',
   chr(ERL):'<L>',
   chr(ERP):'<P>',
   chr(DLE):'<D>',
   chr(DC2):'<2>',
   chr(DC3):'<3>',
   chr(DC4):'<4>',
   chr(FS):'<F>',
   chr(GS):'<G>',
   chr(RS):'<R>',
   chr(US):'<U>'}
  
# Encoding for text -> use 1 byte for compatibility
CHAR_ENCODE = 'latin_1'

def encode(unt4buf=''):
    """Encode the unt4 buffer for use with IRC."""
    for key in ENCMAP:
        unt4buf = unt4buf.replace(key, ENCMAP[key])
    return unt4buf

def decode(ircbuf=''):
    """Decode the irc buffer to unt4msg pack."""
    ircbuf = ircbuf.replace('<00>','')
    for key in ENCMAP:
        ircbuf = ircbuf.replace(ENCMAP[key], key)
    return ircbuf

class unt4buf(object):
    """UNT4 input buffer object.

    Extract complete UNT4 packets from the specified port object
    and return as string. None is returned at end of file or
    stream closure.

    """
    def __init__(self, port=None):
        """Constructor."""
        self.port = port
        self.buf = ''
        #self.buf = b''		# Python3
        self.bpos = 0
        self.pack = ''
        #self.pack = b''	# Python3
        self.state = None

    def fetch(self):
        """Return next complete UNT4 packet or None at EOF."""
        if self.state is EOT:
            self.state = None
            self.pack = ''
            #self.pack = b''	# Python3
        while True:
            if self.bpos >= len(self.buf):
                # does this need to be recv ?
                self.buf = self.port.read(1024)
                self.bpos = 0
                if len(self.buf) is 0:
                    break	# no more input -> indicates EOF

            npos = self.buf.find(chr(SOH), self.bpos)
            #npos = self.buf.find(bytes([SOH]), self.bpos)
            fpos = self.buf.find(chr(EOT), self.bpos)
            #fpos = self.buf.find(bytes([EOT]), self.bpos)
            if npos < 0:     ## <SOH> not found in buf
                if self.state == SOH:
                    if fpos < 0:
                        self.pack += self.buf[self.bpos:]
                        self.bpos = len(self.buf)  # save all bytes in buf
                    else:
                        self.state = EOT
                        self.pack += self.buf[self.bpos:fpos+1]
                        self.bpos = fpos + 1  # save bytes to <EOT>
                        break		      # finish packet and break out
                else:
                    self.bpos = len(self.buf) # discard to end of buf
            elif fpos < 0:   ## <SOH> found, <EOT> not found in buf
                self.state = SOH   # flip mode identifier
                self.pack = chr(SOH)
                #self.pack = bytes([SOH])
                self.bpos = npos + 1  # advance to packet data
            else:            ## <SOH> and <EOT> found in buf
                if npos > fpos and self.state == SOH:
                    self.state = EOT
                    self.pack += self.buf[self.bpos:fpos+1]
                    self.bpos = fpos + 1  # save bytes to <EOT>
                    break		      # finish packet and break out
                else:
                    self.state = SOH   # flip mode identifier
                    self.pack = chr(SOH)
                    #self.pack = bytes([SOH])
                    self.bpos = npos + 1  # advance to packet data
        if self.state is EOT:
            return self.pack
        return None

# UNT4 Packet class
class unt4(object):
    """UNT4 Packet Class."""
    def __init__(self, unt4str=None, 
                   prefix=None, header='', 
                   erp=False, erl=False, 
                   xx=None, yy=None, text=''):
        """Constructor.

        Parameters:

          unt4str -- packed unt4 string, overrides other params
          prefix -- prefix byte <DC2>, <DC3>, etc
          header -- header string eg 'R_F$'
          erp -- true for general clearing <ERP>
          erl -- true for <ERL>
          xx -- packet's column offset 0-99
          yy -- packet's row offset 0-99
          text -- packet content string

        """
        self.prefix = prefix    # <DC2>, <DC3>, etc
        self.header = header    # ident text string eg 'R_F$'
        self.erp = erp          # true for general clearing <ERP>
        self.erl = erl          # true for <ERL>
        self.xx = xx            # input column 0-99
        self.yy = yy            # input row 0-99
        self.text = text        # text string
        if unt4str is not None:
            self.unpack(unt4str)

    def unpack(self, unt4str=''):
        """Unpack the UNT4 string into this object."""
        if len(unt4str) > 2 and unt4str[0] is chr(SOH) \
                            and unt4str[-1] is chr(EOT):
            self.prefix = None
            newhead = ''
            newtext = ''
            self.erl = False
            self.erp = False
            head = True		# All text before STX is considered header
            stx = False
            dle = False
            dlebuf = ''
            i = 1
            packlen = len(unt4str) - 1
            while i < packlen:
                och = ord(unt4str[i])
                if och == STX:
                    stx = True
                    head = False
                elif och == DLE and stx:
                    dle = True
                elif dle:
                    dlebuf += unt4str[i]
                    if len(dlebuf) == 4:
                        dle = False
                elif head:
                    if och in (DC2, DC3, DC4):
                        self.prefix = och   # assume pfx before head text
                    else:
                        newhead += unt4str[i]
                elif stx:
                    if och == ERL:
                        self.erl = True
                    elif och == ERP:
                        self.erp = True
                    else:
                        newtext += unt4str[i]
                i += 1
            if len(dlebuf) == 4:
                self.xx = int(dlebuf[:2])
                self.yy = int(dlebuf[2:])
            self.header = newhead
            self.text = newtext

    def pack(self):
        """Return UNT4 string packet."""
        head = ''
        text = ''
        if self.erp:	# overrides any other message content
            text = chr(STX) + chr(ERP)
        else:
            head = self.header
            if self.prefix is not None:
                head = chr(self.prefix) + head
            if self.xx is not None and self.yy is not None:
                text += chr(DLE) + '{0:02d}{1:02d}'.format(self.xx, self.yy)
            text += self.text
            if self.erl:
                text += chr(ERL)
            if len(text) > 0:
                text = chr(STX) + text
        return chr(SOH) + head + text + chr(EOT)
	## DANGER - Deliberately damage packets for testing.
        ##msg = chr(SOH) + head + text + chr(EOT)
        ##if random.randint(0,10) == 0:
            ##pervert = chr(random.randint(0,255))
            ##pervert_idx = random.randint(0,len(msg)-1)
            ##msg = msg[0:pervert_idx] + pervert + msg[pervert_idx+1:]
        ##return msg
 
# 'Constant' messages
GENERAL_CLEARING = unt4(erp=True)
OVERLAY_ON = unt4(header='OVERLAY ON')
OVERLAY_OFF = unt4(header='OVERLAY OFF')
OVERLAY_1LINE = unt4(header='OVERLAY 00')
OVERLAY_2LINE = unt4(header='OVERLAY 01')
OVERLAY_3LINE = unt4(header='OVERLAY 02')
OVERLAY_4LINE = unt4(header='OVERLAY 03')
OVERLAY_R1P4 = unt4(header='OVERLAY 04')
OVERLAY_R2P2 = unt4(header='OVERLAY 05')
OVERLAY_R2P3 = unt4(header='OVERLAY 06')
OVERLAY_R2P4 = unt4(header='OVERLAY 07')
OVERLAY_T1P4 = unt4(header='OVERLAY 08')
OVERLAY_T1P5 = unt4(header='OVERLAY 09')
OVERLAY_24X5 = unt4(header='OVERLAY 10')
OVERLAY_24X6 = unt4(header='OVERLAY 11')
OVERLAY_CLOCK = unt4(header='OVERLAY 12')
OVERLAY_IMAGE = unt4(header='OVERLAY 13')
OVERLAY_BLANK = unt4(header='OVERLAY 14')

# Todo: Tests
