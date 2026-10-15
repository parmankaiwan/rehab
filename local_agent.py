"""Persistent Windows hardware agent for the hosted FlexMap application."""
from __future__ import annotations
import http.client,json,os,subprocess,threading,time,urllib.parse
from collections import deque
from pathlib import Path
from backend.emg.device_scanner import scan_serial_devices
from backend.emg.serial_manager import SerialConnectionConfig,SerialManager

ROOT=Path(__file__).resolve().parent;CV_ROOT=ROOT.parent/"CV part"
def load_env():
 path=ROOT/".env.agent"
 if path.exists():
  for raw in path.read_text(encoding="utf-8").splitlines():
   line=raw.strip()
   if line and not line.startswith("#") and "=" in line:
    key,value=line.split("=",1);os.environ.setdefault(key.strip(),value.strip())

class EmgPublisher:
 def __init__(self):
  self.base=urllib.parse.urlsplit(os.environ["FLEXMAP_WEB_BACKEND"].rstrip("/"));self.token=os.environ["FLEXMAP_ENGINE_TOKEN"];self.samples=deque(maxlen=5000);self.lock=threading.Lock();self.device={};self.port="";self.manager=SerialManager(self.on_sample,self.on_state);self.last_error=""
 def on_sample(self,values,device_seq=None,device_ts=None,valid=True):
  with self.lock:self.samples.append({"values":values,"device_sequence_id":device_seq,"device_timestamp":device_ts,"valid":valid})
 def on_state(self,state,error):
  if error and error!=self.last_error:print(f"EMG {state}: {error}",flush=True);self.last_error=error
 def ensure_connected(self):
  if self.manager.status()["reader_alive"]:return
  devices=scan_serial_devices(include_non_usb=True);preferred=os.getenv("FLEXMAP_EMG_PORT","").strip()
  device=next((x for x in devices if x["port"].casefold()==preferred.casefold()),None) if preferred else next((x for x in devices if x.get("is_usb")),None)
  if not device:return
  self.device,self.port=device,device["port"]
  cfg=SerialConnectionConfig(port=self.port,baud_rate=int(os.getenv("FLEXMAP_EMG_BAUD","115200")),protocol=os.getenv("FLEXMAP_EMG_PROTOCOL","CSV_CHANNELS"),expected_channels=int(os.getenv("FLEXMAP_EMG_CHANNELS","1")))
  self.manager.connect(cfg,device);print(f"EMG CONNECTING: {self.port}",flush=True)
 def publish(self):
  with self.lock:rows=[self.samples.popleft() for _ in range(min(250,len(self.samples)))]
  if not rows:return
  payload=json.dumps({"source_port":self.port,"baud_rate":int(os.getenv("FLEXMAP_EMG_BAUD","115200")),"protocol":os.getenv("FLEXMAP_EMG_PROTOCOL","CSV_CHANNELS"),"expected_sample_rate_hz":float(os.getenv("FLEXMAP_EMG_RATE","1000")),"channel_count":int(os.getenv("FLEXMAP_EMG_CHANNELS","1")),"device":self.device,"samples":rows},separators=(",",":")).encode()
  cls=http.client.HTTPSConnection if self.base.scheme=="https" else http.client.HTTPConnection;connection=cls(self.base.hostname,self.base.port or (443 if self.base.scheme=="https" else 80),timeout=5)
  try:
   connection.request("POST",f"{self.base.path.rstrip('/')}/api/engine/emg/batch",payload,{"Content-Type":"application/json","X-FlexMap-Engine-Token":self.token});response=connection.getresponse();response.read()
   if response.status>=400:raise OSError(f"EMG backend returned {response.status}")
  except Exception:
   with self.lock:self.samples.extendleft(reversed(rows))
   raise
  finally:connection.close()

def launch_cv():
 if os.getenv("FLEXMAP_AUTOSTART_CV","true").lower()!="true":return None
 python=CV_ROOT/".venv"/"Scripts"/"python.exe";main=CV_ROOT/"main.py"
 if not python.exists() or not main.exists():print("CV runtime not found",flush=True);return None
 return subprocess.Popen([str(python),str(main)],cwd=str(CV_ROOT),env=os.environ.copy())
def main():
 load_env();os.environ.setdefault("FLEXMAP_WEB_BACKEND","https://flexmap-rehab-api-parmankaiwan.onrender.com")
 if not os.getenv("FLEXMAP_ENGINE_TOKEN"):raise SystemExit("FLEXMAP_ENGINE_TOKEN is missing from .env.agent")
 cv=launch_cv();emg=EmgPublisher()
 while True:
  try:
   if cv and cv.poll() is not None:time.sleep(3);cv=launch_cv()
   emg.ensure_connected();emg.publish()
  except Exception as exc:print(f"AGENT RETRYING: {exc}",flush=True);time.sleep(2)
  time.sleep(.04)
if __name__=="__main__":main()
