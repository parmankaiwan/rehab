from __future__ import annotations
import hashlib,json,os
from datetime import datetime,timezone
from pathlib import Path
import cv2
open_saved_video = cv2.VideoCapture
class VideoPreviewService:
 def __init__(self,settings,vault):self.settings,self.vault=settings,vault
 def folder(self,rid):
  item=self.vault.get(rid)
  if not item:raise FileNotFoundError(rid)
  path=(self.settings.root/item["relative_path"]).resolve()
  if not path.is_relative_to(self.settings.root.resolve()):raise ValueError("Unsafe recording path")
  return path
 def paths(self,rid,variant):
  if variant not in ("raw","annotated"):raise ValueError("Invalid video variant")
  folder=self.folder(rid);return folder/("video.mp4" if variant=="raw" else "annotated_video.mp4"),folder/f"{variant}_web.webm"
 def hash(self,path):
  d=hashlib.sha256()
  with path.open("rb") as h:
   for block in iter(lambda:h.read(1048576),b""):d.update(block)
  return d.hexdigest()
 def inspect(self,path):
  if not path.is_file():return {"exists":False,"file":path.name}
  c=open_saved_video(str(path))
  try:
   code=int(c.get(cv2.CAP_PROP_FOURCC));fps=float(c.get(cv2.CAP_PROP_FPS));frames=int(c.get(cv2.CAP_PROP_FRAME_COUNT));result={"exists":True,"file":path.name,"size_bytes":path.stat().st_size,"sha256":self.hash(path),"readable":c.isOpened(),"codec":"".join(chr((code>>(8*i))&255) for i in range(4)).strip(chr(0)),"width":int(c.get(cv2.CAP_PROP_FRAME_WIDTH)),"height":int(c.get(cv2.CAP_PROP_FRAME_HEIGHT)),"fps":fps,"frame_count":frames,"duration_seconds":frames/fps if fps else None};ok,_=c.read();result["first_frame_readable"]=ok;return result
  finally:c.release()
 def status(self,rid):
  folder=self.folder(rid);mp=folder/"video_preview_metadata.json";meta=json.loads(mp.read_text("utf-8")) if mp.is_file() else {"variants":{}};out={"recording_id":rid,"poster_exists":(folder/"preview.jpg").is_file()}
  for variant in ("raw","annotated"):
   source,preview=self.paths(rid,variant);si,pi=self.inspect(source),self.inspect(preview);ready=pi.get("readable") and meta.get("variants",{}).get(variant,{}).get("source_sha256")==si.get("sha256");compatible=si.get("codec","").lower() in ("avc1","h264","vp80","vp90");out[variant]={**si,"browser_compatible":compatible,"preview_status":"READY" if ready else ("NOT_REQUIRED" if compatible else "MISSING"),"preview":pi if ready else None,"playback_source":"preview" if ready else "original"}
  return out
 def generate(self,rid,variant):
  source,preview=self.paths(rid,variant);si=self.inspect(source)
  if not si.get("first_frame_readable"):raise ValueError("Video file could not be decoded")
  if self.status(rid)[variant]["preview_status"]=="READY":return self.status(rid)[variant]
  before=si["sha256"];temp=preview.with_suffix(".tmp.webm");c=open_saved_video(str(source));w=cv2.VideoWriter(str(temp),cv2.VideoWriter_fourcc(*"VP80"),si["fps"],(si["width"],si["height"]))
  try:
   if not w.isOpened():raise RuntimeError("VP8 WebM encoder is unavailable")
   while True:
    ok,frame=c.read()
    if not ok:break
    w.write(frame)
  finally:c.release();w.release()
  pi=self.inspect(temp)
  if not pi.get("readable") or pi.get("frame_count")!=si["frame_count"]:temp.unlink(missing_ok=True);raise RuntimeError("Preview validation failed")
  if self.hash(source)!=before:temp.unlink(missing_ok=True);raise RuntimeError("Canonical source changed")
  os.replace(temp,preview);mp=source.parent/"video_preview_metadata.json";meta=json.loads(mp.read_text("utf-8")) if mp.is_file() else {"schema_version":"1.0","variants":{}}
  meta["variants"][variant]={"source_file":source.name,"source_sha256":before,"preview_file":preview.name,"preview_sha256":self.hash(preview),"source_codec":si["codec"],"preview_codec":"VP8","source_width":si["width"],"source_height":si["height"],"source_fps":si["fps"],"created_at":datetime.now(timezone.utc).isoformat(),"tool":"OpenCV VideoWriter","tool_version":cv2.__version__};mp.write_text(json.dumps(meta,indent=2),"utf-8");return self.status(rid)[variant]
