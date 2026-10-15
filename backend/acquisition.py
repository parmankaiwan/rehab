from __future__ import annotations

import csv, json, shutil, threading, uuid
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal, Optional
from fastapi import APIRouter, Depends, Header, HTTPException
from pydantic import BaseModel, Field, model_validator
from .dataset_config import dataset_settings
from .dataset_models import RecordingConfiguration, RecordingState
from .master_dataset_api import require_master, recorder, vault
from .posture_stream import store as posture_store
from .video_store import raw_video_store, video_store
from .emg.api import service as emg_service
from .emg.schemas import BaselineRequest as EmgBaselineRequest, RecordingMarkerRequest as EmgMarkerRequest, RecordingRequest as EmgRecordingRequest

def utcnow(): return datetime.now(timezone.utc).isoformat()
ID = Field(pattern=r"^[A-Za-z0-9_-]+$", min_length=1, max_length=80)

class StudyCreate(BaseModel):
 study_id:str=ID;name:str=Field(min_length=1,max_length=160);description:str=Field(default="",max_length=2000);status:Literal["DRAFT","ACTIVE","COMPLETED","ARCHIVED"]="ACTIVE";allowed_rehab_modules:list[str]=Field(default_factory=list);notes:str=Field(default="",max_length=2000)
class SubjectCreate(BaseModel):
 subject_id:str=ID;affected_side:Optional[Literal["LEFT","RIGHT","UNKNOWN","N/A"]]=None;cohort_label:Optional[str]=Field(default=None,max_length=80);notes:str=Field(default="",max_length=2000)
class TrialPlanItem(BaseModel):
 label:str=Field(min_length=1,max_length=96);count:int=Field(ge=1,le=100);duration_seconds:float=Field(gt=0,le=3600);duration_mode:Literal["FIXED","MANUAL_STOP"]="FIXED";rest_after_seconds:float=Field(default=0,ge=0,le=600);instructions:str=Field(default="",max_length=500)
class ProtocolCreate(BaseModel):
 protocol_id:str=ID;display_name:str=Field(min_length=1,max_length=160);description:str=Field(default="",max_length=2000);rehab_type:str=Field(min_length=1,max_length=64);modality:Literal["CV","EMG","PAIRED"];allowed_labels:list[str]=Field(min_length=1);trial_plan:list[TrialPlanItem]=Field(min_length=1);countdown_seconds:int=Field(default=3,ge=0,le=10);required_sensors:list[str]=Field(default_factory=list);optional_sensors:list[str]=Field(default_factory=list);required_metadata:list[str]=Field(default_factory=lambda:["subject_id","session_id","affected_side"]);technical_quality_policy:dict=Field(default_factory=dict);instructions:str=Field(default="",max_length=3000);status:Literal["DRAFT","ACTIVE","ARCHIVED"]="ACTIVE";keep_failed_attempts:bool=True;required_emg_channels:Optional[int]=Field(default=None,ge=1,le=4);required_hardware_profile_id:Optional[str]=None;recommended_channel_map:list[dict]=Field(default_factory=list);baseline_required:bool=False;baseline_count:int=Field(default=1,ge=0,le=10);baseline_duration_seconds:float=Field(default=5,ge=1,le=60);quality_policy:dict=Field(default_factory=dict)
 @model_validator(mode="after")
 def valid_plan(self):
  missing=sorted({x.label for x in self.trial_plan}-set(self.allowed_labels))
  if missing:raise ValueError(f"Trial labels not allowed: {', '.join(missing)}")
  if self.modality in {"CV","PAIRED"} and self.countdown_seconds not in {3,5}:raise ValueError("CV countdown_seconds must be 3 or 5")
  return self
class CollectionCreate(BaseModel):
 study_id:Optional[str]=None;subject_id:str=ID;session_id:str=ID;protocol_id:str=ID;protocol_version:Optional[int]=Field(default=None,ge=1);affected_side:Literal["LEFT","RIGHT","UNKNOWN","N/A"]="UNKNOWN";consent_recorded:bool=False;hardware_profile_id:Optional[str]=None;hardware_profile_version:Optional[int]=Field(default=None,ge=1);channel_map:list[dict]=Field(default_factory=list);electrode_metadata:dict=Field(default_factory=dict);controller_id:Optional[str]=Field(default=None,max_length=100);notes:str=Field(default="",max_length=2000)
 @model_validator(mode="after")
 def consent(self):
  if not self.consent_recorded:raise ValueError("Documented research recording consent is required")
  return self
class TrialStart(BaseModel):modality:Optional[Literal["CV","EMG"]]=None;override_warnings:bool=False;controller_id:Optional[str]=Field(default=None,max_length=100)
class TrialDecision(BaseModel):recording_id:Optional[str]=None;notes:str=Field(default="",max_length=1000)
class RetryRequest(BaseModel):retain_failed_attempt:bool=True;reason:str=Field(default="Technical retry",min_length=1,max_length=500)
class SkipRequest(BaseModel):reason:str=Field(min_length=1,max_length=500)
class MarkerCreate(BaseModel):event_type:Literal["MOVEMENT_STARTED","TARGET_REACHED","MOVEMENT_ENDED","TRACKING_ISSUE","SENSOR_ISSUE","CUSTOM"];relative_timestamp_ms:Optional[float]=Field(default=None,ge=0);recording_id:Optional[str]=None;notes:str=Field(default="",max_length=500)
class BaselineAction(BaseModel):notes:str=Field(default="",max_length=1000)

class AcquisitionStore:
 def __init__(self,root:Path|None=None):
  self.root=root or dataset_settings().root;self.path=self.root/"research_acquisition.json";self.report_dir=self.root/"collection_reports";self.lock=threading.RLock();self._recover()
 @staticmethod
 def empty():return {"schema_version":"1.0","studies":[],"subjects":[],"protocols":[],"collections":[],"audit":[]}
 def _read(self):
  try:data=json.loads(self.path.read_text(encoding="utf-8")) if self.path.exists() else self.empty()
  except (OSError,ValueError):data=self.empty()
  for key,value in self.empty().items():data.setdefault(key,value)
  return data
 def _write(self,data):
  self.path.parent.mkdir(parents=True,exist_ok=True);temp=self.path.with_suffix(".tmp");temp.write_text(json.dumps(data,indent=2),encoding="utf-8");temp.replace(self.path)
 def _audit(self,data,action,cid=None,tid=None,details=None):
  data["audit"].append({"event_id":f"AUD-{uuid.uuid4().hex[:12].upper()}","action":action,"timestamp":utcnow(),"collection_id":cid,"trial_id":tid,"created_by":"MASTER","details":details or {}});data["audit"]=data["audit"][-10000:]
 @staticmethod
 def _find(rows,key,value):return next((x for x in rows if x[key]==value),None)
 def _recover(self):
  with self.lock:
   data=self._read();changed=False
   for collection in data["collections"]:
    for trial in collection["trials"]:
     if trial["state"] in {"COUNTDOWN","RECORDING","FINALIZING"}:
      trial.update(state="RETRY_REQUIRED",interrupted_at=utcnow(),quality_result="INVALID");trial.setdefault("quality_warnings",[]).append("Backend restarted during an unfinished trial");collection["status"]="INCOMPLETE";self._audit(data,"TRIAL_INTERRUPTED",collection["collection_id"],trial["trial_id"],{"reason":"BACKEND_RESTART"});changed=True
   if changed:self._write(data)
 def list(self,key):
  with self.lock:return list(reversed(self._read()[key]))
 def create_study(self,p):
  with self.lock:
   data=self._read()
   if self._find(data["studies"],"study_id",p.study_id):raise ValueError("Study ID already exists")
   item={**p.model_dump(),"created_at":utcnow(),"protocol_ids":[]};data["studies"].append(item);self._write(data);return item
 def create_subject(self,p):
  with self.lock:
   data=self._read()
   if self._find(data["subjects"],"subject_id",p.subject_id):raise ValueError("Subject ID already exists")
   item={**p.model_dump(),"created_at":utcnow()};data["subjects"].append(item);self._write(data);return item
 def protocol(self,data,pid,version=None):
  rows=[x for x in data["protocols"] if x["protocol_id"]==pid and (version is None or x["protocol_version"]==version)]
  return max(rows,key=lambda x:x["protocol_version"]) if rows else None
 def create_protocol(self,p):
  vault.registry.by_id(p.rehab_type)
  for label in p.allowed_labels:
   if p.modality in {"CV","PAIRED"}:vault.registry.validate_label(p.rehab_type,label)
   if p.modality=="EMG":vault.registry.validate_emg_label(p.rehab_type,label)
  with self.lock:
   data=self._read();version=max([x["protocol_version"] for x in data["protocols"] if x["protocol_id"]==p.protocol_id] or [0])+1;item={**p.model_dump(),"protocol_version":version,"created_at":utcnow(),"immutable":True,"used_by_collections":0};data["protocols"].append(item);self._write(data);return item
 def create_collection(self,p):
  with self.lock:
   data=self._read();protocol=self.protocol(data,p.protocol_id,p.protocol_version)
   if not protocol:raise KeyError("Protocol not found")
   if protocol["status"]!="ACTIVE":raise ValueError("Protocol is not active")
   if not self._find(data["subjects"],"subject_id",p.subject_id):raise KeyError("Subject not found")
   if p.study_id and not self._find(data["studies"],"study_id",p.study_id):raise KeyError("Study not found")
   cid=f"COL-{datetime.now(timezone.utc):%Y%m%d}-{uuid.uuid4().hex[:8].upper()}";trials=[];number=0
   hardware_snapshot=None
   if protocol["modality"] in {"EMG","PAIRED"}:
    profile_id=p.hardware_profile_id or protocol.get("required_hardware_profile_id")
    if profile_id:
     hardware_snapshot=emg_service.hardware.snapshot(profile_id,p.hardware_profile_version)
    elif protocol.get("required_hardware_profile_id"):
     raise ValueError("The protocol requires an EMG hardware profile")
   channel_map=p.channel_map or protocol.get("recommended_channel_map") or ([x.model_dump() for x in emg_service.config.channels] if emg_service.config else [])
   required_channels=protocol.get("required_emg_channels")
   if protocol["modality"] in {"EMG","PAIRED"} and required_channels and len(channel_map)!=required_channels:raise ValueError(f"Protocol requires {required_channels} configured EMG channels")
   for step in protocol["trial_plan"]:
    for index in range(1,step["count"]+1):
     number+=1;trials.append({"trial_id":f"TRIAL-{cid[4:]}-{number:03d}","trial_number":number,"label_index":index,"label_count":step["count"],"research_label":step["label"],"duration_seconds":step["duration_seconds"],"duration_mode":step.get("duration_mode","FIXED"),"countdown_seconds":protocol.get("countdown_seconds",3),"countdown_remaining":0,"rest_after_seconds":step.get("rest_after_seconds",0),"instructions":step.get("instructions",""),"state":"PLANNED","attempt_number":1,"attempts":[],"recording_ids":{"CV":None,"EMG":None},"active_modality":None,"sync_group_id":None,"sync_status":"NOT_CONFIGURED","quality_result":None,"quality_warnings":[],"quality_reports":{},"preflight_snapshot":None,"markers":[]})
   baseline_count=protocol.get("baseline_count",1) if protocol.get("baseline_required") else 0
   baselines=[{"baseline_number":i+1,"state":"PLANNED","attempt_number":1,"baseline_id":None,"attempts":[]} for i in range(baseline_count)]
   item={**p.model_dump(),"collection_id":cid,"rehab_type":protocol["rehab_type"],"modality":protocol["modality"],"protocol_version":protocol["protocol_version"],"protocol_snapshot":protocol,"hardware_profile_snapshot":hardware_snapshot,"hardware_profile_id":hardware_snapshot.get("hardware_profile_id") if hardware_snapshot else p.hardware_profile_id,"hardware_profile_version":hardware_snapshot.get("profile_version") if hardware_snapshot else p.hardware_profile_version,"channel_map_snapshot":channel_map,"electrode_metadata_snapshot":p.electrode_metadata,"processing_snapshot":emg_service.processing_status() if protocol["modality"] in {"EMG","PAIRED"} else None,"baseline_group_id":f"BASEGRP-{uuid.uuid4().hex[:10].upper()}","baselines":baselines,"controller_id":p.controller_id,"status":"PLANNED","created_at":utcnow(),"started_at":None,"ended_at":None,"paused_at":None,"current_trial_id":trials[0]["trial_id"],"trials":trials,"revision":1};data["collections"].append(item);protocol["used_by_collections"]+=1;self._audit(data,"COLLECTION_CREATED",cid,details={"protocol_id":protocol["protocol_id"],"protocol_version":protocol["protocol_version"],"hardware_profile_id":item.get("hardware_profile_id"),"baseline_group_id":item["baseline_group_id"]});self._write(data);self.write_manifests(item);return item
 def preflight(self,collection):
  protocol=collection["protocol_snapshot"];modality=protocol["modality"];root=dataset_settings().root;free=shutil.disk_usage(root).free;checks=[]
  def add(name,state,message,measured=None):checks.append({"name":name,"state":state,"message":message,"measured":measured})
  writable=root.exists() and root.is_dir();add("Storage writer","PASS" if writable else "BLOCKED","Dataset root is available" if writable else "Dataset root is unavailable");add("Disk space","PASS" if free>=dataset_settings().minimum_free_bytes else "BLOCKED",f"{free/1073741824:.1f} GB available",free)
  if modality in {"CV","PAIRED"}:
   snapshot=posture_store.latest();camera=raw_video_store.is_fresh();engine=video_store.is_fresh();tracking=bool(snapshot and snapshot.connected)
   add("Camera","PASS" if camera else "BLOCKED","Fresh raw camera frames" if camera else "No fresh camera frames")
   add("CV engine","PASS" if engine else "BLOCKED","Fresh annotated frames" if engine else "CV engine is not publishing frames")
   add("Pose tracking","PASS" if tracking else ("WARNING" if engine else "BLOCKED"),f"Tracking {snapshot.tracking_quality}" if snapshot else "No fresh pose result")
   cvstate=recorder.status().state;add("CV recorder","BLOCKED" if cvstate in {RecordingState.COUNTDOWN,RecordingState.RECORDING,RecordingState.FINALIZING,RecordingState.SAVING} else "PASS",f"Recorder {cvstate.value}")
  if modality in {"EMG","PAIRED"}:
   emg=emg_service.status();streaming=emg.get("connection_state")=="STREAMING";age=emg.get("latest_data_age_ms");rate=emg.get("received_rate_hz") or 0;required=protocol.get("required_emg_channels")
   add("EMG board","PASS" if streaming else "BLOCKED","EMG stream connected" if streaming else "EMG board is not streaming")
   fresh=streaming and rate>0 and (age is None or age<2000);add("EMG samples","PASS" if fresh else "BLOCKED",f"{rate:.1f} Hz; age {age if age is not None else 'unknown'} ms",rate)
   channel_ok=required is None or emg.get("channel_count")==required;add("EMG channels","PASS" if channel_ok else "BLOCKED",f"{emg.get('channel_count',0)} configured; {required or 'protocol default'} required")
   locked=collection.get("channel_map_snapshot") or [];current=[x.model_dump() for x in emg_service.config.channels] if emg_service.config else []
   channel_fields=("internal_id","display_name","muscle_label","body_side","electrode_configuration","electrode_spacing_mm","reference_electrode_location")
   channel_match=bool(locked) and len(locked)==len(current) and all(all(expected.get(field)==actual.get(field) for field in channel_fields) for expected,actual in zip(locked,current))
   add("Channel map","PASS" if channel_match else "BLOCKED",f"{len(locked)} locked channels; {len(current)} live channels" if channel_match else "Live channel identity or electrode configuration differs from the locked collection snapshot")
   hardware=collection.get("hardware_profile_snapshot");required_profile=protocol.get("required_hardware_profile_id")
   hardware_ok=bool(hardware) if required_profile else True
   add("Hardware profile","PASS" if hardware_ok else "BLOCKED",hardware.get("display_name","Locked profile") if hardware else ("Optional profile not selected" if not required_profile else "Required hardware profile is missing"))
   if hardware:
    validation_history=emg_service.hardware.validation_history(hardware["hardware_profile_id"])
    matching_validation=next((item for item in validation_history if item.get("hardware_profile_version")==hardware.get("profile_version") and item.get("final_technical_status") in {"PASS","PASS_WITH_WARNINGS"}),None)
    add("Hardware validation","PASS" if matching_validation else "WARNING",f"Current profile v{hardware.get('profile_version')} validated by {matching_validation.get('validation_run_id')}" if matching_validation else "Current hardware profile version has no completed technical validation")
   baseline_required=bool(protocol.get("baseline_required"));accepted=sum(x.get("state")=="ACCEPTED" for x in collection.get("baselines",[]));needed=protocol.get("baseline_count",1) if baseline_required else 0
   add("Baseline","PASS" if accepted>=needed else "BLOCKED",f"{accepted} accepted; {needed} required")
   signal=emg_service.signal_quality_report();warnings=signal.get("warnings",[])
   add("Signal quality","WARNING" if warnings else "PASS","; ".join(warnings[:3]) if warnings else "No descriptive signal warnings",signal)
   estate=emg.get("recording_state");add("EMG recorder","BLOCKED" if estate in {"COUNTDOWN","RECORDING","FINALIZING"} else "PASS",f"Recorder {estate}")
  overall="BLOCKED" if any(x["state"]=="BLOCKED" for x in checks) else "WARNING" if any(x["state"]=="WARNING" for x in checks) else "PASS"
  return {"overall":overall,"checked_at":utcnow(),"checks":checks,"free_storage_bytes":free}
 def _sync(self,data,collection):
  trial=next((x for x in collection["trials"] if x["trial_id"]==collection.get("current_trial_id")),None);changed=False
  if trial and trial["state"] in {"COUNTDOWN","RECORDING","FINALIZING"}:
   modality=trial.get("active_modality");sensor=recorder.status().model_dump(mode="json") if modality=="CV" else emg_service.recording_status();state=str(sensor.get("state"));mapped={"CONFIGURED":"COUNTDOWN","COUNTDOWN":"COUNTDOWN","RECORDING":"RECORDING","FINALIZING":"FINALIZING","REVIEW":"REVIEW","ERROR":"RETRY_REQUIRED","DISCARDED":"DISCARDED"}.get(state)
   trial["elapsed_seconds"]=sensor.get("elapsed_seconds",0)
   if trial.get("countdown_remaining")!=sensor.get("countdown_remaining",0):trial["countdown_remaining"]=sensor.get("countdown_remaining",0);changed=True
   if sensor.get("recording_start_timestamp_ns") and trial.get("recording_start_timestamp_ns")!=sensor.get("recording_start_timestamp_ns"):
    trial["recording_start_timestamp_ns"]=sensor.get("recording_start_timestamp_ns");trial["recording_started_at"]=utcnow();trial["started_at"]=trial["recording_started_at"];self._audit(data,"RECORDING_STARTED",collection["collection_id"],trial["trial_id"],{"recording_start_timestamp_ns":trial["recording_start_timestamp_ns"],"countdown_seconds":trial.get("countdown_seconds",3)});changed=True
   if mapped and mapped!=trial["state"]:trial["state"]=mapped;changed=True
   if mapped=="RETRY_REQUIRED" and sensor.get("error")=="TRACKING_LOST":trial["quality_warnings"]=["Tracking was lost during countdown. Countdown reset to the full duration."];self._audit(data,"COUNTDOWN_CANCELLED",collection["collection_id"],trial["trial_id"],{"reason":"TRACKING_LOST"})
   rid=sensor.get("recording_id")
   if rid and modality:trial["recording_ids"][modality]=rid
   if mapped=="REVIEW":
    review=sensor.get("review") or {};metadata=review.get("metadata",{});trial["quality_result"]=metadata.get("technical_quality") or review.get("technical_quality") or review.get("quality_report",{}).get("overall_technical_quality") or "GOOD_WITH_WARNINGS";trial["quality_warnings"]=list(dict.fromkeys(review.get("quality_report",{}).get("warnings",[])+review.get("signal_quality_report",{}).get("warnings",[])+review.get("integrity_errors",[])));trial["quality_reports"]={key:review.get(key) for key in ("quality_report","acquisition_quality_report","signal_quality_report","integrity_report") if review.get(key)}
    if metadata.get("interrupted"):
     trial.update(state="RETRY_REQUIRED",interrupted_at=utcnow(),quality_result="INVALID");collection["status"]="INCOMPLETE";self._audit(data,"TRIAL_INTERRUPTED",collection["collection_id"],trial["trial_id"],{"reason":metadata.get("interruption_reason","DEVICE_INTERRUPTION")})
  if changed:collection["revision"]+=1;self._write(data)
  return collection
 def get(self,cid):
  with self.lock:
   data=self._read();item=self._find(data["collections"],"collection_id",cid);return self._sync(data,item) if item else None
 def baseline(self,cid,action,body=None):
  with self.lock:
   data=self._read();collection=self._find(data["collections"],"collection_id",cid)
   if not collection:raise KeyError("Collection not found")
   slots=collection.get("baselines",[]);slot=next((x for x in slots if x["state"] in {"PLANNED","RETRY_REQUIRED"}),None)
   if action=="start":
    if not slot:raise ValueError("No baseline slot is ready")
    if emg_service.baseline_status().get("state") in {"COUNTDOWN","RECORDING"}:raise RuntimeError("A baseline is already active")
    req=EmgBaselineRequest(rehab_type=collection["rehab_type"],subject_id=collection["subject_id"],session_id=collection["session_id"],collection_id=cid,protocol_id=collection["protocol_id"],protocol_version=collection["protocol_version"],baseline_group_id=collection["baseline_group_id"],baseline_number=slot["baseline_number"],duration_seconds=collection["protocol_snapshot"].get("baseline_duration_seconds",5),hardware_profile_id=collection.get("hardware_profile_id"),hardware_profile_version=collection.get("hardware_profile_version"),channel_map_snapshot={"channels":collection.get("channel_map_snapshot",[])},notes=body.notes if body else "")
    slot["state"]="RECORDING";self._audit(data,"BASELINE_STARTED",cid,details={"baseline_number":slot["baseline_number"],"attempt_number":slot["attempt_number"]});result=emg_service.start_baseline(req)
   elif action=="accept":
    result=emg_service.baseline_status();baseline=result.get("baseline")
    slot=next((x for x in slots if x["state"]=="RECORDING"),None)
    if result.get("state")!="COMPLETE" or not baseline or not slot:raise RuntimeError("Baseline is not ready for review")
    slot.update(state="ACCEPTED",baseline_id=baseline["baseline_id"],accepted_at=utcnow());slot["attempts"].append({"attempt_number":slot["attempt_number"],"baseline_id":baseline["baseline_id"],"outcome":"ACCEPTED","timestamp":utcnow()});self._audit(data,"BASELINE_ACCEPTED",cid,details={"baseline_id":baseline["baseline_id"]})
   elif action=="retry":
    result=emg_service.baseline_status();slot=next((x for x in slots if x["state"] in {"RECORDING","RETRY_REQUIRED"}),None)
    if not slot:raise ValueError("No baseline is available to retry")
    baseline=result.get("baseline");slot["attempts"].append({"attempt_number":slot["attempt_number"],"baseline_id":baseline.get("baseline_id") if baseline else None,"outcome":"RETRY_REQUIRED","timestamp":utcnow(),"notes":body.notes if body else ""});slot.update(state="PLANNED",attempt_number=slot["attempt_number"]+1,baseline_id=None);self._audit(data,"BASELINE_RETRIED",cid,details={"baseline_number":slot["baseline_number"]})
   else:raise ValueError("Unknown baseline action")
   collection["revision"]+=1;self._write(data);self.write_manifests(collection);return {"collection":collection,"baseline_status":result}
 def mutate(self,cid,action,body=None,tid=None):
  with self.lock:
   data=self._read();collection=self._find(data["collections"],"collection_id",cid)
   if not collection:raise KeyError("Collection not found")
   trial=next((x for x in collection["trials"] if x["trial_id"]==tid),None) if tid else None;now=utcnow()
   if action=="start_collection":
    if collection["status"] not in {"PLANNED","INCOMPLETE","PAUSED"}:raise ValueError("Collection cannot be started from its current state")
    collection.update(status="ACTIVE",started_at=collection["started_at"] or now,paused_at=None);self._audit(data,"COLLECTION_STARTED",cid)
   elif action=="pause":
    if any(x["state"] in {"COUNTDOWN","RECORDING","FINALIZING"} for x in collection["trials"]):raise ValueError("Finish or cancel the active recording before pausing")
    collection.update(status="PAUSED",paused_at=now);self._audit(data,"COLLECTION_PAUSED",cid)
   elif action=="resume":collection.update(status="ACTIVE",paused_at=None);self._audit(data,"COLLECTION_RESUMED",cid)
   elif not trial:raise KeyError("Trial not found")
   elif action=="start_trial":
    if collection["status"]!="ACTIVE":raise ValueError("Collection must be active")
    if trial["state"] not in {"PLANNED","READY","RETRY_REQUIRED"}:raise ValueError("Trial cannot be started")
    if collection.get("controller_id") and body.controller_id!=collection["controller_id"]:raise RuntimeError("This collection is controlled by another browser tab")
    pre=self.preflight(collection)
    if pre["overall"]=="BLOCKED":raise RuntimeError("Preflight is blocked")
    if pre["overall"]=="WARNING" and not body.override_warnings:raise RuntimeError("Explicit warning override is required")
    modality=body.modality or ("CV" if collection["modality"] in {"CV","PAIRED"} else "EMG")
    if collection["modality"]!="PAIRED" and modality!=collection["modality"]:raise ValueError("Modality does not match protocol")
    trial.update(preflight_snapshot=pre,active_modality=modality,state="COUNTDOWN",countdown_remaining=trial.get("countdown_seconds",3),countdown_started_at=now,started_at=None,recording_start_timestamp_ns=None)
    common=dict(rehab_type=collection["rehab_type"],subject_id=collection["subject_id"],duration_seconds=trial["duration_seconds"],session_id=collection["session_id"],study_id=collection.get("study_id"),collection_id=cid,protocol_id=collection["protocol_id"],protocol_version=collection["protocol_version"],protocol_snapshot=collection["protocol_snapshot"],trial_id=tid,trial_number=trial["trial_number"],attempt_number=trial["attempt_number"],sync_status="NOT_CONFIGURED",preflight_snapshot=pre,consent_recorded=True)
    if modality=="CV":
     result=recorder.start(RecordingConfiguration(**common,category=collection["rehab_type"],label=trial["research_label"],countdown_seconds=trial.get("countdown_seconds",3),manual_stop=trial.get("duration_mode")=="MANUAL_STOP",affected_side=collection["affected_side"] if collection["affected_side"] in {"LEFT","RIGHT"} else None));trial["recording_ids"]["CV"]=result.recording_id
    else:
     baseline_id=next((x.get("baseline_id") for x in collection.get("baselines",[]) if x.get("state")=="ACCEPTED"),None)
     result=emg_service.start_recording(EmgRecordingRequest(**common,research_label=trial["research_label"],affected_side=collection["affected_side"],countdown_seconds=collection["protocol_snapshot"].get("countdown_seconds",3),manual_stop=trial.get("duration_mode")=="MANUAL_STOP",hardware_profile_id=collection.get("hardware_profile_id"),hardware_profile_version=collection.get("hardware_profile_version"),channel_map_snapshot={"channels":collection.get("channel_map_snapshot",[])},electrode_metadata=collection.get("electrode_metadata_snapshot",{}),baseline_id=baseline_id,baseline_group_id=collection.get("baseline_group_id")));trial["recording_ids"]["EMG"]=result.get("recording_id")
    self._audit(data,"COUNTDOWN_STARTED",cid,tid,{"attempt_number":trial["attempt_number"],"modality":modality,"countdown_seconds":trial.get("countdown_seconds",3),"preflight":pre})
   elif action=="cancel_countdown":
    if trial["state"]!="COUNTDOWN" or trial.get("active_modality")!="CV":raise ValueError("No CV countdown is active")
    recorder.cancel();trial.update(state="READY",active_modality=None,countdown_remaining=trial.get("countdown_seconds",3),countdown_started_at=None,started_at=None,recording_start_timestamp_ns=None);trial["recording_ids"]["CV"]=None;self._audit(data,"COUNTDOWN_CANCELLED",cid,tid,{"reason":"MANUAL_CANCEL"})
   elif action=="stop_trial":
    if trial["state"]!="RECORDING" or trial.get("duration_mode")!="MANUAL_STOP":raise ValueError("Only an active manual-stop recording can be stopped")
    recorder.stop() if trial.get("active_modality")=="CV" else emg_service.stop_recording();trial["state"]="FINALIZING";self._audit(data,"TRIAL_STOP_REQUESTED",cid,tid)
   elif action in {"approve","approve_warning"}:
    if trial["state"]!="REVIEW":raise ValueError("Trial is not ready for review")
    modality=trial["active_modality"];rid=body.recording_id or trial["recording_ids"].get(modality)
    if not rid:raise ValueError("Recording ID is unavailable")
    final_state="APPROVED_WITH_WARNINGS" if action=="approve_warning" else "APPROVED"
    recorder.save(rid) if modality=="CV" else emg_service.save(rid,final_state,None,body.notes);trial["state"]=final_state;trial["ended_at"]=now;trial["review_notes"]=body.notes;trial["attempts"].append({"attempt_number":trial["attempt_number"],"recording_id":rid,"modality":modality,"outcome":trial["state"],"timestamp":now});self._audit(data,"TRIAL_APPROVED_WITH_WARNING" if action=="approve_warning" else "TRIAL_APPROVED",cid,tid,{"recording_id":rid})
   elif action=="retry":
    if trial["state"] not in {"REVIEW","RETRY_REQUIRED","DISCARDED"}:raise ValueError("Trial is not retryable")
    modality=trial.get("active_modality");rid=trial["recording_ids"].get(modality) if modality else None
    if trial["state"]=="REVIEW" and rid:
     if body.retain_failed_attempt and modality=="EMG":emg_service.save(rid,"RETRY_REQUIRED",False,body.reason)
     elif not body.retain_failed_attempt:(recorder.discard(rid) if modality=="CV" else emg_service.discard(rid))
    trial["attempts"].append({"attempt_number":trial["attempt_number"],"recording_id":rid if body.retain_failed_attempt else None,"modality":modality,"outcome":"RETRY_REQUIRED","reason":body.reason,"timestamp":now});trial.update(attempt_number=trial["attempt_number"]+1,state="READY",quality_result=None,quality_warnings=[],active_modality=None);self._audit(data,"TRIAL_RETRIED",cid,tid,{"attempt_number":trial["attempt_number"],"reason":body.reason})
   elif action=="discard":
    modality=trial.get("active_modality");rid=body.recording_id or (trial["recording_ids"].get(modality) if modality else None)
    if rid and trial["state"]=="REVIEW":(recorder.discard(rid) if modality=="CV" else emg_service.discard(rid))
    trial.update(state="DISCARDED",ended_at=now);self._audit(data,"TRIAL_DISCARDED",cid,tid,{"recording_id":rid,"notes":body.notes})
   elif action=="skip":
    if trial["state"] in {"COUNTDOWN","RECORDING","FINALIZING"}:raise ValueError("An active trial cannot be skipped")
    trial.update(state="SKIPPED",skip_reason=body.reason,ended_at=now);self._audit(data,"TRIAL_SKIPPED",cid,tid,{"reason":body.reason})
   elif action=="marker":
    if trial.get("active_modality")=="EMG":
     server_marker=emg_service.add_recording_marker(body.event_type,body.notes);relative=server_marker["relative_timestamp_ms"];event_id=server_marker["event_id"]
    else:relative=body.relative_timestamp_ms;event_id=f"MARK-{uuid.uuid4().hex[:12].upper()}"
    marker={"event_id":event_id,"trial_id":tid,"recording_id":body.recording_id or trial.get("recording_ids",{}).get(trial.get("active_modality")),"relative_timestamp_ms":relative,"event_type":body.event_type,"created_by":"MASTER","created_at":now,"notes":body.notes};trial["markers"].append(marker);self._audit(data,"TRIAL_MARKER_ADDED",cid,tid,marker)
   terminal={"APPROVED","APPROVED_WITH_WARNINGS","SKIPPED"}
   if collection["trials"] and all(x["state"] in terminal for x in collection["trials"]):collection.update(status="COMPLETE",ended_at=now);self._audit(data,"COLLECTION_COMPLETED",cid)
   next_trial=next((x for x in collection["trials"] if x["state"] in {"PLANNED","READY","RETRY_REQUIRED"}),None);collection["current_trial_id"]=next_trial["trial_id"] if next_trial else (tid or collection.get("current_trial_id"));collection["revision"]+=1;self._write(data);self.write_manifests(collection)
   if collection["status"]=="COMPLETE":self.write_report(collection)
   return collection
 def write_manifests(self,c):
  folder=self.report_dir/c["collection_id"];folder.mkdir(parents=True,exist_ok=True)
  manifest={key:value for key,value in c.items() if key not in {"trials"}}
  manifest["schema_version"]="1.0";manifest["generated_at"]=utcnow();manifest["trial_summary"]=[{"trial_id":x["trial_id"],"trial_number":x["trial_number"],"label":x["research_label"],"state":x["state"],"attempt_number":x["attempt_number"],"recording_ids":x["recording_ids"],"quality_result":x.get("quality_result")} for x in c["trials"]]
  (folder/"collection_manifest.json").write_text(json.dumps(manifest,indent=2),encoding="utf-8")
  with (folder/"trial_manifest.csv").open("w",newline="",encoding="utf-8") as handle:
   fields=["trial_id","trial_number","research_label","duration_seconds","duration_mode","attempt_number","state","cv_recording_id","emg_recording_id","quality_result"]
   writer=csv.DictWriter(handle,fieldnames=fields);writer.writeheader()
   for x in c["trials"]:writer.writerow({"trial_id":x["trial_id"],"trial_number":x["trial_number"],"research_label":x["research_label"],"duration_seconds":x["duration_seconds"],"duration_mode":x.get("duration_mode","FIXED"),"attempt_number":x["attempt_number"],"state":x["state"],"cv_recording_id":x["recording_ids"].get("CV"),"emg_recording_id":x["recording_ids"].get("EMG"),"quality_result":x.get("quality_result")})
 def write_report(self,c):
  counts=Counter(x["state"] for x in c["trials"]);planned=len(c["trials"]);report={"collection_id":c["collection_id"],"generated_at":utcnow(),"planned_trials":planned,"attempted":sum(bool(x["attempts"] or x.get("started_at")) for x in c["trials"]),"approved":counts["APPROVED"],"approved_with_warnings":counts["APPROVED_WITH_WARNINGS"],"discarded":counts["DISCARDED"],"skipped":counts["SKIPPED"],"missing":sum(x["state"] not in {"APPROVED","APPROVED_WITH_WARNINGS","SKIPPED"} for x in c["trials"]),"interruptions":sum(bool(x.get("interrupted_at")) for x in c["trials"]),"sensor_warnings":[w for x in c["trials"] for w in x.get("quality_warnings",[])],"baseline_accepted":sum(x.get("state")=="ACCEPTED" for x in c.get("baselines",[])),"coverage_completeness":(counts["APPROVED"]+counts["APPROVED_WITH_WARNINGS"]+counts["SKIPPED"])/planned if planned else 0};folder=self.report_dir/c["collection_id"];folder.mkdir(parents=True,exist_ok=True);(folder/"collection_quality_report.json").write_text(json.dumps(report,indent=2),encoding="utf-8");self.write_manifests(c)
 def coverage(self,include_mock=False):
  with self.lock:collections=self._read()["collections"]
  cells=defaultdict(lambda:{"recordings":0,"unique_subjects":set(),"approved_trials":0,"planned_trials":0})
  for c in collections:
   if not include_mock and (c.get("hardware_profile_snapshot") or {}).get("is_mock"):continue
   for t in c["trials"]:
    for modality in (["CV","EMG"] if c["modality"]=="PAIRED" else [c["modality"]]):
     key=(c["subject_id"],c["rehab_type"],modality,t["research_label"],f"{c['protocol_id']}_V{c['protocol_version']}");cell=cells[key];cell["planned_trials"]+=1;rid=t["recording_ids"].get(modality)
     if rid and t["state"] in {"APPROVED","APPROVED_WITH_WARNINGS"}:cell["recordings"]+=1;cell["approved_trials"]+=1;cell["unique_subjects"].add(c["subject_id"])
  rows=[]
  for key,value in cells.items():rows.append({"subject_id":key[0],"rehab_type":key[1],"modality":key[2],"label":key[3],"protocol":key[4],"recordings":value["recordings"],"unique_subjects":len(value["unique_subjects"]),"approved_trials":value["approved_trials"],"planned_trials":value["planned_trials"],"missing_trials":max(0,value["planned_trials"]-value["approved_trials"])})
  protocols=Counter(f"{c['protocol_id']}_V{c['protocol_version']}" for c in collections);hardware=Counter(c.get("hardware_profile_id") or "UNSPECIFIED" for c in collections if c["modality"] in {"EMG","PAIRED"});baseline={"required":sum(bool(c.get("protocol_snapshot",{}).get("baseline_required")) for c in collections),"complete":sum(bool(c.get("baselines")) and all(x.get("state")=="ACCEPTED" for x in c.get("baselines",[])) for c in collections)}
  return {"include_mock":include_mock,"rows":rows,"recordings":sum(x["recordings"] for x in rows),"unique_subjects":len({x["subject_id"] for x in rows if x["recordings"]}),"dimensions":["subject_id","rehab_type","modality","label","protocol","hardware_profile","baseline"],"protocol_distribution":dict(protocols),"hardware_distribution":dict(hardware),"baseline_coverage":baseline,"ml_readiness":{"eligible_recordings":sum(x["recordings"] for x in rows),"unique_subjects":len({x["subject_id"] for x in rows if x["recordings"]}),"mock_excluded":not include_mock}}

acquisition=AcquisitionStore();router=APIRouter(prefix="/api/master",dependencies=[Depends(require_master)],tags=["Research Acquisition"])
def fail(exc):
 if isinstance(exc,KeyError):raise HTTPException(404,str(exc).strip("'")) from exc
 if isinstance(exc,RuntimeError):raise HTTPException(409,str(exc)) from exc
 raise HTTPException(422,str(exc)) from exc
def perform(cid,name,body=None,tid=None):
 try:return acquisition.mutate(cid,name,body,tid)
 except (ValueError,KeyError,RuntimeError) as exc:fail(exc)
@router.get("/studies")
def studies():return acquisition.list("studies")
@router.post("/studies")
def study_create(p:StudyCreate):
 try:return acquisition.create_study(p)
 except (ValueError,KeyError) as exc:fail(exc)
@router.get("/subjects")
def subjects():return acquisition.list("subjects")
@router.post("/subjects")
def subject_create(p:SubjectCreate):
 try:return acquisition.create_subject(p)
 except (ValueError,KeyError) as exc:fail(exc)
@router.get("/collection-protocols")
def protocols():return acquisition.list("protocols")
@router.post("/collection-protocols")
def protocol_create(p:ProtocolCreate):
 try:return acquisition.create_protocol(p)
 except (ValueError,KeyError) as exc:fail(exc)
@router.get("/collections")
def collections():return acquisition.list("collections")
@router.post("/collections")
def collection_create(p:CollectionCreate):
 try:return acquisition.create_collection(p)
 except (ValueError,KeyError) as exc:fail(exc)
@router.get("/collections/{cid}")
def collection_get(cid:str):
 item=acquisition.get(cid)
 if not item:raise HTTPException(404,"Collection not found")
 return item
@router.get("/collections/{cid}/preflight")
def collection_preflight(cid:str):
 item=acquisition.get(cid)
 if not item:raise HTTPException(404,"Collection not found")
 return acquisition.preflight(item)
@router.get("/collections/{cid}/trials")
def trial_list(cid:str):return collection_get(cid)["trials"]
@router.post("/collections/{cid}/start")
def collection_start(cid:str):return perform(cid,"start_collection")
@router.post("/collections/{cid}/pause")
def collection_pause(cid:str):return perform(cid,"pause")
@router.post("/collections/{cid}/resume")
def collection_resume(cid:str):return perform(cid,"resume")
@router.get("/collections/{cid}/baseline")
def collection_baseline(cid:str):
 item=collection_get(cid);return {"collection":item,"baseline_status":emg_service.baseline_status()}
@router.post("/collections/{cid}/baseline/start")
def collection_baseline_start(cid:str,p:BaselineAction):
 try:return acquisition.baseline(cid,"start",p)
 except (ValueError,KeyError,RuntimeError) as exc:fail(exc)
@router.post("/collections/{cid}/baseline/accept")
def collection_baseline_accept(cid:str):
 try:return acquisition.baseline(cid,"accept")
 except (ValueError,KeyError,RuntimeError) as exc:fail(exc)
@router.post("/collections/{cid}/baseline/retry")
def collection_baseline_retry(cid:str,p:BaselineAction):
 try:return acquisition.baseline(cid,"retry",p)
 except (ValueError,KeyError,RuntimeError) as exc:fail(exc)
@router.post("/collections/{cid}/trials/{tid}/start")
def trial_start(cid:str,tid:str,p:TrialStart,x_flexmap_controller_id:Optional[str]=Header(default=None)):
 p.controller_id=x_flexmap_controller_id or p.controller_id
 return perform(cid,"start_trial",p,tid)
@router.post("/collections/{cid}/trials/{tid}/stop")
def trial_stop(cid:str,tid:str):return perform(cid,"stop_trial",tid=tid)
@router.post("/collections/{cid}/trials/{tid}/cancel-countdown")
def trial_cancel_countdown(cid:str,tid:str):return perform(cid,"cancel_countdown",tid=tid)
@router.post("/collections/{cid}/trials/{tid}/approve")
def trial_approve(cid:str,tid:str,p:TrialDecision):return perform(cid,"approve",p,tid)
@router.post("/collections/{cid}/trials/{tid}/approve-with-warning")
def trial_approve_warning(cid:str,tid:str,p:TrialDecision):return perform(cid,"approve_warning",p,tid)
@router.post("/collections/{cid}/trials/{tid}/retry")
def trial_retry(cid:str,tid:str,p:RetryRequest):return perform(cid,"retry",p,tid)
@router.post("/collections/{cid}/trials/{tid}/discard")
def trial_discard(cid:str,tid:str,p:TrialDecision):return perform(cid,"discard",p,tid)
@router.post("/collections/{cid}/trials/{tid}/skip")
def trial_skip(cid:str,tid:str,p:SkipRequest):return perform(cid,"skip",p,tid)
@router.post("/collections/{cid}/trials/{tid}/markers")
def trial_marker(cid:str,tid:str,p:MarkerCreate):return perform(cid,"marker",p,tid)
@router.get("/collection-coverage")
def coverage(include_mock:bool=False):return acquisition.coverage(include_mock)
