from __future__ import annotations
import json, threading
from datetime import datetime, timezone
from pydantic import BaseModel, Field
from fastapi import APIRouter, Depends, HTTPException
from .dataset_config import dataset_settings
from .master_dataset_api import require_master, vault
from .emg.api import service as emg_service
class SessionCreate(BaseModel):
 subject_id:str=Field(pattern=r"^[A-Za-z0-9_-]+$",min_length=1,max_length=64);rehab_type:str;affected_side:str=Field(pattern=r"^(LEFT|RIGHT|UNKNOWN|N/A)$");study_id:str|None=Field(default=None,max_length=80);protocol_id:str|None=Field(default=None,max_length=80);protocol_version:int|None=Field(default=None,ge=1);notes:str=Field(default="",max_length=2000)
class SessionUpdate(BaseModel):
 status:str|None=Field(default=None,pattern=r"^(PLANNED|ACTIVE|PAUSED|COMPLETE|ABORTED|ARCHIVED)$");notes:str|None=Field(default=None,max_length=2000)
class SessionStore:
 def __init__(self):self.path=dataset_settings().root/"research_sessions.json";self.lock=threading.RLock()
 def _read(self):
  try:return json.loads(self.path.read_text(encoding="utf-8")) if self.path.exists() else []
  except (ValueError,OSError):return []
 def _write(self,rows):
  self.path.parent.mkdir(parents=True,exist_ok=True);temp=self.path.with_suffix(".tmp");temp.write_text(json.dumps(rows,indent=2),encoding="utf-8");temp.replace(self.path)
 def _hydrate(self,item):
  cv_rows=vault.list(session_id=item["session_id"]);emg_rows=[]
  for module in vault.registry.modules:emg_rows.extend(r for r in emg_service.list(module.slug) if r.get("session_id")==item["session_id"])
  cv=[r["recording_id"] for r in cv_rows];emg=[r["recording_id"] for r in emg_rows]
  events=[{"type":"SESSION_CREATED","timestamp":item["created_at"],"label":"Session created"}]
  events.extend({"type":"CV_RECORDING","timestamp":r.get("created_at"),"label":f'CV recording {r["recording_id"]}',"recording_id":r["recording_id"]} for r in cv_rows if r.get("created_at"))
  events.extend({"type":"EMG_RECORDING","timestamp":r.get("created_at"),"label":f'EMG recording {r["recording_id"]}',"recording_id":r["recording_id"]} for r in emg_rows if r.get("created_at"))
  if item.get("ended_at"):events.append({"type":"SESSION_COMPLETE","timestamp":item["ended_at"],"label":"Session completed"})
  events.sort(key=lambda event:event["timestamp"] or "")
  return {**item,"cv_recording_ids":cv,"emg_recording_ids":emg,"trial_count":len(cv)+len(emg),"synchronization":"NOT_CONFIGURED","activity":events}
 def list(self):
  with self.lock:return [self._hydrate(row) for row in reversed(self._read())]
 def get(self,sid):return next((row for row in self.list() if row["session_id"]==sid),None)
 def create(self,payload):
  vault.registry.by_id(payload.rehab_type)
  with self.lock:
   rows=self._read();today=datetime.now(timezone.utc).strftime("%Y%m%d");seq=max([int(r["session_id"].rsplit("-",1)[-1]) for r in rows if r["session_id"].startswith(f"SESSION-{today}-")] or [0])+1;now=datetime.now(timezone.utc).isoformat();item={"session_id":f"SESSION-{today}-{seq:03d}",**payload.model_dump(),"created_at":now,"started_at":None,"ended_at":None,"status":"PLANNED"};rows.append(item);self._write(rows);return self._hydrate(item)
 def update(self,sid,payload):
  with self.lock:
   rows=self._read();item=next((r for r in rows if r["session_id"]==sid),None)
   if not item:raise KeyError(sid)
   changes=payload.model_dump(exclude_none=True);item.update(changes);now=datetime.now(timezone.utc).isoformat()
   if changes.get("status")=="ACTIVE" and not item.get("started_at"):item["started_at"]=now
   if changes.get("status")=="COMPLETE":item["ended_at"]=now
   self._write(rows);return self._hydrate(item)
store=SessionStore();router=APIRouter(prefix="/api/master/sessions",tags=["Research Sessions"],dependencies=[Depends(require_master)])
@router.get("")
def list_sessions():return store.list()
@router.post("")
def create_session(payload:SessionCreate):
 try:return store.create(payload)
 except ValueError as exc:raise HTTPException(422,str(exc)) from exc
@router.get("/{session_id}")
def get_session(session_id:str):
 item=store.get(session_id)
 if not item:raise HTTPException(404,"Session not found")
 return item
@router.patch("/{session_id}")
def update_session(session_id:str,payload:SessionUpdate):
 try:return store.update(session_id,payload)
 except KeyError as exc:raise HTTPException(404,"Session not found") from exc
