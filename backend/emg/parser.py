from __future__ import annotations
import math
from typing import Optional

def parse_serial_line(line:str,protocol:str,channel_count:int)->Optional[tuple[Optional[int],Optional[float],list[float]]]:
 text=line.strip()
 if not text:return None
 try:parts=[x.strip() for x in text.split(",")]
 except Exception:return None
 try:
  if protocol=="VALUE_ONLY" and channel_count==1 and len(parts)==1:result=None,None,[float(parts[0])]
  elif protocol=="TIMESTAMP_VALUE" and channel_count==1 and len(parts)==2:result=None,float(parts[0]),[float(parts[1])]
  elif protocol=="CSV_CHANNELS" and len(parts)==channel_count:result=None,None,[float(x) for x in parts]
  elif protocol=="TIMESTAMP_CSV_CHANNELS" and len(parts)==channel_count+1:result=None,float(parts[0]),[float(x) for x in parts[1:]]
  elif protocol=="SEQUENCE_TIMESTAMP_CSV" and len(parts)==channel_count+2:result=int(parts[0]),float(parts[1]),[float(x) for x in parts[2:]]
  else:return None
  _,timestamp,values=result
  if (timestamp is not None and not math.isfinite(timestamp)) or not all(math.isfinite(value) for value in values):return None
  return result
 except (ValueError,OverflowError):return None
 return None
