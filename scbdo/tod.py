
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

"""Time of Day (ToD) functions and abstract class.

This module defines the tod class and some utility functions.

ToD records are used to establish net times

Time of Day quantities are stored as a positive decimal number of
seconds in the range [0, 86400). The overflow value '24:00:00'
(equivalent to 86400 seconds) is forbidden and its presence
flags a programming error or an error in the attached timing device.
All time of day and net time values must be less than 24hrs.

'rounding' is by truncation toward zero. If a negative value is
specified by manually setting the timeval attribute, the resulting
timestring may not be what is expected. Arithmetic will still be
exact, however a negative result may not display as expected.

A time of day object includes:

   - timeval : decimal tod in seconds (eg 1.2345, 4506.9023, etc)
   - index   : 4 character identifier string (eg '1' to '9999')
   - chan    : 3 character channel string from source (eg 'C0', 'C2M', etc)
   - refid   : string reference id, used for RFID tag events (eg '75ae7f')

Supported ToD String Patterns:

   [[HH:]MM:]SS[.dcmz]		Canonical
   [[HH-]MM-]SS[.dcmz]		Keypad
   [[HHh]MM:]SS[.dcmz]		Result

Arithmetic operations on ToD types:

The only supported arithmetic operations on ToD objects are
subtraction and addition. Subtraction obtains a net time from
two time of day values, while addition obtains a time of day
from a time of day and a net time. These conventions are assumed
and have the following peculiarities:

Given two tod objects a and b, the statement:

   c = a - b

Creates a "net time" c such that:

   c.timeval == (a.timeval - b.timeval) if a.timeval >= b.timeval
OR
   c.timeval == (86400 - b.timeval + a.timeval) if a.timeval < b.timeval

'c' is a new tod object, whose timeval is the exact number of
seconds between tod 'b' and tod 'a'. 'b' is always
assumed to have happened before 'a', and so if the value of
'a.timeval' is less than the value of 'b.timeval', overflow
is assumed.

Given a tod object a and a "net time" b, the statement:

   c = a + b

Creates a new tod c such that:

   c.timeval == (a.timeval + b.timeval) % 86400

'c' is a new tod object, whose timeval is exactly the number of
seconds in net time 'b' after tod 'a'.

In both cases, the index chan and refid are set on 'c' as follows:

   index = ''
   chan = 'NET'
   refid = ''

Normalised tod strings are printed as on the Timy receipt:

  'NNNN CCC HH:MM:SS.dcmz REFID'

Where 'NNNN' is the index, 'CCC' is the chan and the time is
printed, space padded, according to the requested precision.

"""

import decimal		# ToD internal representation
import re		# used to scan ToD string: HH:MM:SS.dcmz 
import time

QUANT_5PLACES = decimal.Decimal('0.00001') # does not work with Timy printer
QUANT_4PLACES = decimal.Decimal('0.0001')
QUANT_3PLACES = decimal.Decimal('0.001')
QUANT_2PLACES = decimal.Decimal('0.01')
QUANT_1PLACE = decimal.Decimal('0.1')
QUANT_0PLACES = decimal.Decimal('1')
QUANT = [QUANT_0PLACES, QUANT_1PLACE, QUANT_2PLACES,
         QUANT_3PLACES, QUANT_4PLACES, QUANT_5PLACES]
QUANT_FW = [2, 4, 5, 6, 7, 8]
QUANT_TWID = [8, 10, 11, 12, 13, 14]
QUANT_PAD = ['     ', '   ', '  ', ' ', '', '']
TOD_RE=re.compile(r'^(?:(?:(\d{1,2})[h:-])?(\d{1,2})[:-])?(\d{1,2}(?:\.\d+)?)$')


def str2tod(timeval=''):
    """Return tod for given string without fail."""
    ret = None
    if timeval is not None and timeval != '':
        try:
            ret = tod(timeval)
        except:
            pass
    return ret

def dec2str(dectod=None, places=4, zeros=False):
    """Return formatted string for given tod decimal value.

    Convert the decimal number dectod to a time string with the
    supplied number of decimal places. 

    Note: negative timevals match case one or three depending on
          value of zeros flag, and are truncated toward zero.
          Oversized timevals will grow in width

          optional argument 'zeros' will use leading zero chars. eg:

             '00h00:01.2345'   zeros=True
                    '1.2345'   zeros=False

    """
    strtod = None

    assert places >= 0 and places <= 5, 'places not in range [0, 5]'
    
    if dectod is not None: 		# conditional here?
        if zeros or dectod >= 3600:	# NOTE: equal compares fine w/decimal
            fmt = '{0}h{1:02}:{2:0{3}}' 	# 'HHhMM:SS.dcmz'
            if zeros:
                fmt = '{0:02}:{1:02}:{2:0{3}}'	# '00h00:0S.dcmz'
            strtod = fmt.format(int(dectod)//3600,
                (int(dectod)%3600)//60,
                dectod.quantize(QUANT[places],
                rounding=decimal.ROUND_FLOOR)%60,
                QUANT_FW[places])
        elif dectod >= 60:	# MM:SS.dcmz
            strtod = '{0}:{1:0{2}}'.format(int(dectod)//60,
                dectod.quantize(QUANT[places],
                rounding=decimal.ROUND_FLOOR)%60,
                QUANT_FW[places])
        else: 			# SS.dcmz or -SSSSS.dcmz
            strtod = '{0}'.format(dectod.quantize(QUANT[places],
                rounding=decimal.ROUND_FLOOR))
    return strtod

def str2dec(timestr=''):
    """Return decimal for given string.

    Convert the time of day value represented by the string supplied
    to a decimal number of seconds.

    Attempts to match against the common patterns:

    HHhMM:SS.dcmz		Result style
    HH:MM:SS.dcmz		Canonical
    HH-MM-SS.dcmz		Keypad

    In optional groups as follows:

    [[HH:]MM:]SS[.dcmz]

    NOTE: Now truncates all incoming times to 4 places to avoid
          inconsistencies.

    """
    dectod=None
    timestr=timestr.strip()
    if timestr == 'now':
        ltoft = time.localtime().tm_isdst * 3600	# DST Hack
        dectod = decimal.Decimal(str(
                    (time.time() - (time.timezone - ltoft)) % 86400))
                    # !!ERROR!! 2038, UTC etc -> check def Unix time
    else:
        m = TOD_RE.match(timestr)
        if m is not None:
            dectod = decimal.Decimal(m.group(3))
            dectod += decimal.Decimal(m.group(2) or 0) * 60
            dectod += decimal.Decimal(m.group(1) or 0) * 3600
        else:
            # last attempt - try and handle as other decimal constructor
            dectod = decimal.Decimal(timestr)
    return dectod.quantize(QUANT[4], rounding=decimal.ROUND_FLOOR)

class tod(object):
    """A class for representing time of day and RFID events."""
    def __init__(self, timeval=0, index='', chan='', refid=''):
        """Construct tod object.

        Keyword arguments:
        timeval -- time value to be represented (string/int/decimal/tod)
        index -- tod index identifier string
        chan -- channel string
        refed -- a reference identifier string

        """

        self.index = str(index)[0:4]
        self.chan = str(chan)[0:3]
        self.refid = refid
        if type(timeval) is str:
            self.timeval = str2dec(timeval)
        elif type(timeval) is tod:
            self.timeval = timeval.timeval
        else:
            self.timeval = decimal.Decimal(timeval)
        assert self.timeval >= 0 and self.timeval < 86400, 'timeval not in range [0, 86400)'

    def __str__(self):
        """Return a normalised tod string."""
        return self.refstr()

    def __repr__(self):
        """Return object representation string."""
        return "tod('{0}', '{1}', '{2}', '{3}')".format(str(self.timeval),
            str(self.index), str(self.chan), str(self.refid))

    def refstr(self, places=4):
        """Return 'normalised' string form.

        'NNNN CCC HHhMM:SS.dcmz REFID'
        to the specified number of decimal places in the set
        [0, 1, 2, 3, 4, 5]

        """
        return '{0: >4} {1: <3} {2} {3}'.format(self.index, self.chan,
                self.timestr(places), self.refid)

    def truncate(self, places=4):
        """Return a new ToD object with a truncated time value."""
        return tod(timeval=self.timeval.quantize(QUANT[places],
                rounding=decimal.ROUND_FLOOR), index='', chan='ToD', refid='')

    def as_hours(self, places=0):
        """Return the tod value in hours, truncated to the desired places."""
        return (self.timeval / 3600).quantize(QUANT[places],
                                            rounding=decimal.ROUND_FLOOR)

    def as_seconds(self, places=0):
        """Return the tod value in seconds, truncated to the desired places."""
        return self.timeval.quantize(QUANT[places],
                                     rounding=decimal.ROUND_FLOOR)

    def as_minutes(self, places=0):
        """Return the tod value in minutes, truncated to the desired places."""
        return (self.timeval / 60).quantize(QUANT[places],
                                            rounding=decimal.ROUND_FLOOR)

    def timestr(self, places=4, zeros=False):
        """Return time string component of the tod, whitespace padded."""
        return '{0: >{1}}{2}'.format(dec2str(self.timeval, places, zeros),
            QUANT_TWID[places], QUANT_PAD[places])

    def rawtime(self, places=4, zeros=False):
        """Return time string component of the tod, without padding."""
        return dec2str(self.timeval, places, zeros)

    def speedstr(self, dist=200):
        """Return an average speed estimate for the provided distance."""
        if self.timeval == 0:
            return '---.--- km/h'
        return '{0:7.3f} km/h'.format(3.6 * float(dist) / float(self.timeval))

    def copy(self):
        """Return a copy of the supplied tod."""
        return tod(self.timeval, self.index, self.chan, self.refid)

    def __lt__(self, other):
        if type(other) is tod:
            return self.timeval < other.timeval
        else:
            return self.timeval < other

    def __le__(self, other):
        if type(other) is tod:
            return self.timeval <= other.timeval
        else:
            return self.timeval <= other

    def __eq__(self, other):
        if type(other) is tod:
            return self.timeval == other.timeval
        else:
            return self.timeval == other

    def __ne__(self, other):
        if type(other) is tod:
            return self.timeval != other.timeval
        else:
            return self.timeval != other

    def __gt__(self, other):
        if type(other) is tod:
            return self.timeval > other.timeval
        else:
            return self.timeval > other

    def __ge__(self, other):
        if type(other) is tod:
            return self.timeval >= other.timeval
        else:
            return self.timeval >= other

    def __sub__(self, other):
        """Compute time of day subtraction and return a NET tod object.

        NOTE: 'other' always happens _before_ self, so a smaller value
              for self implies rollover of the clock. This mods all net
              times by 24Hrs.

        """
        if type(other) is tod:
            oft = None
            if self.timeval >= other.timeval:
                oft = self.timeval - other.timeval
            else:
                oft = 86400 - other.timeval + self.timeval
            return tod(timeval=oft, index='', chan='NET', refid='')
        else:
            raise TypeError('Cannot subtract {0} from tod.'.format(
                                str(type(other).__name__)))

    def __add__(self, other):
        """Compute time of day addition and return a new tod object.

        NOTE: 'other' is assumed to be a NET time interval. The returned
              tod will have a timeval mod 86400.

        """
        if type(other) is tod:
            oft = (self.timeval + other.timeval) % 86400
            return tod(timeval=oft, index='', chan='ToD', refid='')
        else:
            raise TypeError('Cannot add {0} to tod.'.format(
                                str(type(other).__name__)))


# ToD 'constants'
ZERO = tod()
MAX = tod('23h59:59.9999')

# Fake times for special cases
FAKETIMES = {
 'catch':ZERO,
 'max':MAX.copy(),
 'caught':MAX.copy(),
 'abort':MAX.copy(),
 'dsq':MAX.copy(),
 'dnf':MAX.copy(),
 'dns':MAX.copy()}
extra = decimal.Decimal('0.00001')
cof = decimal.Decimal('0.00001')
for c in ['caught', 'abort', 'dsq', 'dnf', 'dns']:
    FAKETIMES[c].timeval += cof
    cof += extra

class todlist():
    """ToD list helper class for managing splits and ranks."""
    def __init__(self, lbl=''):
        self.__label = lbl
        self.__store = []

    def __iter__(self):
        return self.__store.__iter__()

    def __len__(self):
        return len(self.__store)

    def __getitem__(self, key):
        return self.__store[key]

    def rank(self, bib, series=''):
        """Return current 0-based rank for given bib."""
        ret = None
        i = 0
        last = None
        for lt in self.__store:
            if last is not None:
                if lt != last:
                    i += 1
            if lt.refid == bib and lt.index == series:
                ret = i
                break
            last = lt
        return ret

    def clear(self):
        self.__store = []

    def remove(self, bib, series=''):
        i = 0
        while i < len(self.__store):
            if self.__store[i].refid == bib and self.__store[i].index == series:
                del self.__store[i]
            else:
                i += 1

    def insert(self, t, bib=None, series=''):
        """Insert t into ordered list."""
        ret = None
        if t in FAKETIMES: # re-assign a coded 'finish'
            t = FAKETIMES[t]

        if type(t) is tod:
            if bib is None:
                bib = t.index
            rt = tod(timeval=t.timeval, chan=self.__label,
                       refid=bib, index=series)
            last = None
            i = 0
            found = False
            for lt in self.__store:
                if rt < lt:
                    self.__store.insert(i, rt)
                    found = True
                    break
                i += 1
            if not found:
                self.__store.append(rt)
           
if __name__ == "__main__":
    srcs = ['1:23:45.6789', '1:23-45.6789', '1-23-45.6789',
            '1:23:45',      '1:23-45',      '1-23-45',
               '3:45.6789',    '3-45.6789',
               '3:45',         '3-45',
                 '45.6789',        '5.6',
                 '45',
            1.4, float('1.4'), decimal.Decimal('1.4'), '1.4',
            10123, float('10123'), decimal.Decimal('10123'), '10123',
            10123.456, float('10123.456'),
            decimal.Decimal('10123.456'), '10123.456',
            '-10234', '87012', '0', '86400', '86399.9999',
            'inf', 'nan', 'zero', 'now', '-inf',
            tod(0, 'ZERO'), tod('now', 'NOW') ]
         
    print ('1: Check Source Formats')
    for src in srcs:
        try:
            print ('\t' + repr(src) + ' =>\t' + str(tod(src)) + '/' + str(str2tod(src)))
        except Exception as e:
            print ('\t' + repr(src) + ' =>\t' + str(e) + '/' + str(str2tod(src)))
    
    print ('2: ToD Subtraction')
    a = tod(0, '1', 'C0')
    print ('\t     a: '+ str(a))
    b = tod('12.1234', '2', 'C1')
    print ('\t     b: '+ str(b))
    print ('\t [b-a]: '+ str(b-a))
    print ('\t [b+a]: '+ str(b+a))
    print ('\t1/100s: '+ (b-a).refstr(2))
    print ('\t1/100s: '+ (b+a).refstr(2))
    print ('\t   NET: '+ (b-a).timestr(2))
    print ('\t   ToD: '+ (b+a).timestr(2))
    print ('\t [a-b]: '+ str(a-b))
    print ('\t [a+b]: '+ str(a+b))
    print ('\t1/100s: '+ (a-b).refstr(2))
    print ('\t1/100s: '+ (a+b).refstr(2))
    print ('3: Copy & Speedstr')
    c = b.copy()
    print ('\t     c: '+ str(c))
    print ('\t   avg: '+ (b-a).speedstr())

