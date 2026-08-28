from __future__ import annotations
from typing import Optional

def parse_serial_line(line:str,protocol:str,channel_count:int)->Optional[tuple[Optional[int],Optional[float],list[float]]]:
 text=line.strip()
 if not text:return None
 try:parts=[x.strip() for x in text.split(",")]
 except Exception:return None
 try:
  if protocol=="VALUE_ONLY" and channel_count==1 and len(parts)==1:return None,None,[float(parts[0])]
  if protocol=="TIMESTAMP_VALUE" and channel_count==1 and len(parts)==2:return None,float(parts[0]),[float(parts[1])]
  if protocol=="CSV_CHANNELS" and len(parts)==channel_count:return None,None,[float(x) for x in parts]
  if protocol=="TIMESTAMP_CSV_CHANNELS" and len(parts)==channel_count+1:return None,float(parts[0]),[float(x) for x in parts[1:]]
  if protocol=="SEQUENCE_TIMESTAMP_CSV" and len(parts)==channel_count+2:return int(parts[0]),float(parts[1]),[float(x) for x in parts[2:]]
 except (ValueError,OverflowError):return None
 return None