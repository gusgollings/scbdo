// DISC SCB Protocol : UNT4 + DHI Overlay
// Date: 2009-05-11
//
// Simplified DHI protocol interface for use with 
// DISC scoreboard in competition.
[PROTOCOL]
name=DISC SCB Protocol
header=<SOH>
comport=SOCKET
terminator=<EOT>
settings=2004

// **************
// Section: UNT4
// **************

[MSG]
name=Clear All Lines
//position:0   1    2    3
message=<SOH><STX><ERP><EOT>
compare=0,3
//s-field=:position,length,dbeID, dbeSubId, buffOffset, indexA W, .... indexD Weight,filling char,string
s-field=0,32,IGSCBDO,0,0,0,0,0,0, , 
s-field=0,32,IGSCBDO,1,0,0,0,0,0, , 
s-field=0,32,IGSCBDO,2,0,0,0,0,0, , 
s-field=0,32,IGSCBDO,3,0,0,0,0,0, , 
s-field=0,32,IGSCBDO,4,0,0,0,0,0, , 
s-field=0,32,IGSCBDO,5,0,0,0,0,0, , 
s-field=0,32,IGSCBDO,6,0,0,0,0,0, , 
s-field=0,32,IGSCBDO,7,0,0,0,0,0, , 
s-field=0,32,IGSCBDO,8,0,0,0,0,0, , 
s-field=0,32,IGSCBDO,9,0,0,0,0,0, , 
s-field=0,32,IGSCBDO,10,0,0,0,0,0, , 
s-field=0,32,IGSCBDO,11,0,0,0,0,0, , 
s-field=0,32,IGSCBDO,12,0,0,0,0,0, , 
s-field=0,32,IGSCBDO,13,0,0,0,0,0, , 
s-field=0,32,IGSCBDO,14,0,0,0,0,0, , 
s-field=0,32,IGSCBDO,15,0,0,0,0,0, , 
s-field=0,32,IGSCBDO,16,0,0,0,0,0, , 
s-field=0,32,IGSCBDO,17,0,0,0,0,0, , 
s-field=0,32,IGSCBDO,18,0,0,0,0,0, , 
s-field=0,32,IGSCBDO,19,0,0,0,0,0, , 
action=1
skipothers

[MSG]
name=Erase to End of Line
//pos     0    1    2  3456  7    8
message=<SOH><STX><DLE>xxyy<ERL><EOT>
compare=0,3,7,1
index=5,2,0,0,3,2,0,0
//s-field=:position,length,dbeID, dbeSubId, buffOffset, indexA W, .... indexD Weight,filling char,string
s-field=0,32,IGSCBDO,0,0,1,0,1,0, , 
action=2
skipothers

[MSG]
name=Positioned Text
//pos     0    1    2  3456...
message=<SOH><STX><DLE>0001WR 50.99    CR 51.07        0.2 <EOT>
compare=0,3
index=5,2,0,0,3,2,0,0
//p-field=:position,length,dbeID, dbeSubId, buffOffset, indexA W, .... indexD Weight
p-field=7,32,IGSCBDO,0,0,1,0,1,0
action=3
skipothers


// *****************************
// Section: DHI Overlay Control
// *****************************

[MSG]
name=OVERLAY OFF
//pos     0  12345678901  2
message=<SOH>OVERLAY OFF<EOT>
compare=0,11
action=10000
skipothers

[MSG]
name=OVERLAY ON
//pos     0  1234567890  1
message=<SOH>OVERLAY ON<EOT>
compare=0,11
action=10001
skipothers

[MSG]
name=OVERLAY Select
//pos     0  1234567890  1
message=<SOH>OVERLAY xx<EOT>
compare=0,8
index=9,2,0,0,0,0,0,0
action=10002,1
skipothers
