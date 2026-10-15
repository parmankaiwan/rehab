from __future__ import annotations
import csv,hashlib,json,math,platform,shutil,sys,threading,time
from datetime import datetime,timezone
from pathlib import Path
from typing import Any,Optional
import cv2,numpy as np
from .dataset_config import DatasetSettings
from .dataset_models import RecordingConfiguration,RecordingState,RecordingStatus
from .dataset_quality import artifact_manifest,build_quality_report,validate_sample_integrity
from .dataset_vault import DatasetVault

class CvRecordingService:
 """Consumes ordered subscriptions from the existing CV owner; never opens camera or runs inference."""
 def __init__(self,settings:DatasetSettings,vault:DatasetVault,raw_store,annotated_store,posture_store)->None:
  self.settings=settings;self.vault=vault;self.raw_store=raw_store;self.annotated_store=annotated_store;self.posture_store=posture_store;self._lock=threading.RLock();self._state=RecordingState.IDLE;self._recording_id=None;self._configuration=None;self._started_monotonic=None;self._recording_start_timestamp_ns=None;self._countdown_started=None;self._frame_count=self._pose_count=0;self._error=None;self._review=None;self._cancel=threading.Event();self._stop=threading.Event();self._thread=None
 def start(self,configuration:RecordingConfiguration)->RecordingStatus:
  module=self.vault.registry.validate_label(configuration.rehab_type,configuration.label)
  configuration.rehab_slug=module.slug;configuration.category=module.id
  if configuration.duration_seconds>self.settings.max_recording_seconds:raise ValueError("Duration exceeds safety limit")
  if not self.annotated_store.is_fresh():raise RuntimeError("CV ENGINE NOT AVAILABLE")
  if shutil.disk_usage(self.settings.root).free<self.settings.minimum_free_bytes:raise RuntimeError("INSUFFICIENT STORAGE")
  with self._lock:
   if self._state in (RecordingState.COUNTDOWN,RecordingState.RECORDING,RecordingState.FINALIZING,RecordingState.SAVING):raise RuntimeError("A recording is already active")
   self._recording_id=self.vault.new_recording_id();configuration.session_id=configuration.session_id or self.vault.next_session_id()
   if not configuration.trial_id:configuration.trial_number=self.vault.next_trial(configuration.subject_id,configuration.session_id,configuration.category,configuration.label)
   self._configuration=configuration;self._state=RecordingState.CONFIGURED;self._error=None;self._review=None;self._frame_count=self._pose_count=0;self._started_monotonic=None;self._recording_start_timestamp_ns=None;self._cancel.clear();self._stop.clear();self._thread=threading.Thread(target=self._run,name="flexmap-dataset-recorder",daemon=True);self._thread.start()
  return self.status()
 def cancel(self):
  with self._lock:
   if self._state not in (RecordingState.CONFIGURED,RecordingState.COUNTDOWN,RecordingState.RECORDING):raise RuntimeError("No active recording")
   self._cancel.set()
  return self.status()
 def stop(self):
  with self._lock:
   if self._state!=RecordingState.RECORDING or not self._configuration or not self._configuration.manual_stop:raise RuntimeError("No manual-stop CV recording is active")
   self._stop.set()
  return self.status()
 def save(self,recording_id):
  with self._lock:
   if self._state!=RecordingState.REVIEW or recording_id!=self._recording_id:raise RuntimeError("Recording is not ready")
   self._state=RecordingState.SAVING
  try:
   result=self.vault.save_temp(recording_id);self._set_state(RecordingState.SAVED);return result
  except Exception as exc:
   with self._lock:self._state=RecordingState.ERROR;self._error=str(exc)
   raise
 def discard(self,recording_id):
  if recording_id!=self._recording_id:raise RuntimeError("Recording unavailable")
  self.vault.discard_temp(recording_id);self._set_state(RecordingState.DISCARDED)
 def status(self):
  with self._lock:
   elapsed=max(0,time.monotonic()-self._started_monotonic) if self._started_monotonic and self._state in (RecordingState.RECORDING,RecordingState.FINALIZING,RecordingState.REVIEW) else 0;duration=self._configuration.duration_seconds if self._configuration else 0;selected=self._configuration.countdown_seconds if self._configuration else self.settings.countdown_seconds;countdown=max(0,math.ceil(selected-(time.monotonic()-self._countdown_started))) if self._state==RecordingState.COUNTDOWN and self._countdown_started else 0
   return RecordingStatus(state=self._state,recording_id=self._recording_id,elapsed_seconds=min(elapsed,duration),remaining_seconds=max(0,duration-elapsed),countdown_seconds=selected,countdown_remaining=countdown,recording_start_timestamp_ns=self._recording_start_timestamp_ns,frame_count=self._frame_count,pose_result_count=self._pose_count,error=self._error,review=self._review)
 def review_path(self,recording_id,filename):
  allowed={"video.mp4","annotated_video.mp4","preview.jpg","metadata.json","quality_report.json","integrity_report.json","artifact_manifest.json","frame_index.csv","pose_landmarks.json","pose_landmarks.csv","landmarks.json","landmarks.csv","tracking.csv","measurement_quality.csv","kinematics.csv","readiness.csv","posture_components.csv","exercise_state.csv","calibration.json","rep_events.json","compensation_events.json","session_summary.json","measurements.json","events.json"}
  if recording_id!=self._recording_id or filename not in allowed:raise FileNotFoundError(filename)
  path=self.vault.temp_path(recording_id)/filename
  if not path.is_file():raise FileNotFoundError(filename)
  return path
 def _set_state(self,state):
  with self._lock:self._state=state
 def _tracking_usable(self):
  snapshot=self.posture_store.latest()
  return bool(self.raw_store.is_fresh() and self.annotated_store.is_fresh() and snapshot and snapshot.connected and snapshot.tracking_quality!="LOST")
 def _wait_for_countdown(self,seconds):
  self._countdown_started=time.monotonic();deadline=self._countdown_started+seconds
  while time.monotonic()<deadline:
   if self._cancel.is_set():return "CANCELLED"
   if not self._tracking_usable():return "TRACKING_LOST"
   self._cancel.wait(min(.05,max(0,deadline-time.monotonic())))
  return "CANCELLED" if self._cancel.is_set() else ("READY" if self._tracking_usable() else "TRACKING_LOST")
 @staticmethod
 def _open_writer(path,packet,codec,fps):
  image=cv2.imdecode(np.frombuffer(packet.jpeg,dtype=np.uint8),cv2.IMREAD_COLOR)
  if image is None:raise RuntimeError("Frame decode failed")
  height,width=image.shape[:2];writer=cv2.VideoWriter(str(path),cv2.VideoWriter_fourcc(*codec),fps,(width,height))
  if not writer.isOpened():raise RuntimeError("Video writer could not be opened")
  return writer,image,width,height
 @staticmethod
 def _valid_video(path:Path,expected:bool)->bool:
  if not expected:return True
  return (not expected) or (path.is_file() and path.stat().st_size > 0)
 def _run(self):
  rid,config=self._recording_id,self._configuration
  if not rid or not config:return
  temp=self.vault.temp_path(rid);raw_sub=ann_sub=None;raw_writer=ann_writer=None
  try:
   self._set_state(RecordingState.COUNTDOWN);countdown_result=self._wait_for_countdown(config.countdown_seconds)
   if countdown_result=="CANCELLED":self._set_state(RecordingState.DISCARDED);return
   if countdown_result=="TRACKING_LOST":
    with self._lock:self._state=RecordingState.ERROR;self._error="TRACKING_LOST"
    return
   temp.mkdir(parents=True,exist_ok=False);self._started_monotonic=time.monotonic();self._recording_start_timestamp_ns=time.time_ns();self._set_state(RecordingState.RECORDING);raw_sub=self.raw_store.subscribe(self.settings.recording_frame_queue_max);ann_sub=self.annotated_store.subscribe(self.settings.recording_frame_queue_max)
   frames=[];frame_index=[];measurements=[];preview=[];events=[{"event":"RECORDING_STARTED","timestamp_ms":0}];last_snapshot=-1.0;raw_count=ann_count=0;width=height=0;last_quality=None
   while time.monotonic()-self._started_monotonic<config.duration_seconds and not self._cancel.is_set() and not self._stop.is_set():
    for packet in raw_sub.drain():
     frame_row={"recording_id":rid,"capture_frame_id":packet.sequence,"capture_timestamp_ns":packet.capture_timestamp_ns,"relative_time_ms":round((packet.received_monotonic-self._started_monotonic)*1000,3),"wall_time_utc":datetime.fromtimestamp(packet.source_timestamp,tz=timezone.utc).isoformat() if packet.source_timestamp else None,"raw_video_frame_index":None,"annotated_video_frame_index":None,"pose_result_available":False,"pose_result_id":None,"tracking_state":None,"recording_state":"RECORDING"};frame_index.append(frame_row)
     if config.store_raw_video:
      if raw_writer is None:raw_writer,image,width,height=self._open_writer(temp/"video.mp4",packet,self.settings.video_codec,self.settings.target_video_fps)
      else:image=cv2.imdecode(np.frombuffer(packet.jpeg,dtype=np.uint8),cv2.IMREAD_COLOR)
      if image is not None:
       raw_writer.write(image);raw_count+=1
       frame_row["raw_video_frame_index"]=raw_count-1
    for packet in ann_sub.drain():
     if config.store_annotated_video:
      if ann_writer is None:ann_writer,image,width,height=self._open_writer(temp/"annotated_video.mp4",packet,self.settings.video_codec,self.settings.target_video_fps)
      else:image=cv2.imdecode(np.frombuffer(packet.jpeg,dtype=np.uint8),cv2.IMREAD_COLOR)
      if image is not None:
       ann_writer.write(image);ann_count+=1
       match=next((row for row in reversed(frame_index) if row["capture_frame_id"]==packet.sequence),None)
       if match:match["annotated_video_frame_index"]=ann_count-1
     preview.append((time.monotonic()-self._started_monotonic,packet.jpeg))
    snapshot=self.posture_store.latest()
    if snapshot and snapshot.timestamp!=last_snapshot:
     relative=round((time.monotonic()-self._started_monotonic)*1000);quality=snapshot.tracking_quality if snapshot.tracking_quality in ("GOOD","POOR","LOST") else "LOST";landmarks={name:point.model_dump(mode="json") for name,point in snapshot.landmarks.items()};frame_id=snapshot.capture_frame_id or (ann_count or raw_count);frames.append({"frame_id":frame_id,"capture_timestamp_ns":snapshot.capture_timestamp_ns,"timestamp_ms":relative,"source_timestamp":snapshot.timestamp,"tracking_quality":quality,"landmarks":landmarks});sample={"frame_id":frame_id,"timestamp_ms":relative,"tracking_quality":quality,"overall_posture_state":snapshot.overall_state.value,"ready":snapshot.ready}
     sample["ready_progress"]=snapshot.ready_progress;sample["ready_stage"]=snapshot.ready_stage;sample["feedback"]=list(snapshot.feedback);sample["exercise_snapshot"]=snapshot.exercise_snapshot
     for key,component in snapshot.components.items():
      if component.value is not None:sample[key.lower()]={"value":component.value,"units":component.units,"state":component.state.value}
     measurements.append(sample);self._pose_count+=1;last_snapshot=snapshot.timestamp
     match=next((row for row in reversed(frame_index) if row["capture_frame_id"]==frame_id),None)
     if match:match.update(pose_result_available=True,pose_result_id=self._pose_count,tracking_state=quality)
     if last_quality and quality!=last_quality and (quality=="LOST" or last_quality=="LOST"):events.append({"event":"TRACKING_LOST" if quality=="LOST" else "TRACKING_RECOVERED","timestamp_ms":relative})
     last_quality=quality
    self._frame_count=max(raw_count,ann_count);time.sleep(.003)
   for writer in (raw_writer,ann_writer):
    if writer:writer.release()
   raw_writer=ann_writer=None;dropped=max(raw_sub.dropped,ann_sub.dropped);self.raw_store.unsubscribe(raw_sub);self.annotated_store.unsubscribe(ann_sub);raw_sub=ann_sub=None
   self._set_state(RecordingState.FINALIZING)
   if self._cancel.is_set():self.vault.discard_temp(rid);self._set_state(RecordingState.DISCARDED);return
   actual=time.monotonic()-self._started_monotonic;events.append({"event":"RECORDING_ENDED","timestamp_ms":round(actual*1000)})
   self._finalize(temp,rid,config,frames,frame_index,measurements,events,preview,width,height,actual,raw_count,ann_count,dropped)
   self._set_state(RecordingState.REVIEW)
  except Exception as exc:
   for writer in (raw_writer,ann_writer):
    if writer:writer.release()
   if raw_sub:self.raw_store.unsubscribe(raw_sub)
   if ann_sub:self.annotated_store.unsubscribe(ann_sub)
   with self._lock:self._state=RecordingState.ERROR;self._error=str(exc)
 def _finalize(self,temp,rid,config,frames,frame_index,measurements,events,preview,width,height,actual,raw_count,ann_count,dropped):
  valid_frame_ids={row["capture_frame_id"] for row in frame_index};paired=[(frame,sample) for frame,sample in zip(frames,measurements) if frame["frame_id"] in valid_frame_ids];frames=[pair[0] for pair in paired];measurements=[pair[1] for pair in paired]
  (temp/"landmarks.json").write_text(json.dumps({"dataset_schema_version":"2.0","recording_id":rid,"frames":frames},indent=2),encoding="utf-8");self._write_landmark_csv(temp/"landmarks.csv",rid,frames);(temp/"measurements.json").write_text(json.dumps({"dataset_schema_version":"2.0","recording_id":rid,"samples":measurements},indent=2),encoding="utf-8");(temp/"events.json").write_text(json.dumps({"dataset_schema_version":"2.0","recording_id":rid,"events":events},indent=2),encoding="utf-8")
  self._write_structured_artifacts(temp,rid,config,frames,frame_index,measurements,events,actual,raw_count,ann_count,dropped)
  if config.store_preview_image and preview:(temp/"preview.jpg").write_bytes(min(preview,key=lambda x:abs(x[0]-actual/2))[1])
  raw_valid=self._valid_video(temp/"video.mp4",config.store_raw_video);ann_valid=self._valid_video(temp/"annotated_video.mp4",config.store_annotated_video);quality=build_quality_report(rid,frames,actual,raw_count,ann_count,dropped,raw_valid,ann_valid);(temp/"quality_report.json").write_text(json.dumps(quality,indent=2),encoding="utf-8")
  metadata={**config.model_dump(),"dataset_schema_version":"2.0","recording_id":rid,"recording_start_timestamp_ns":self._recording_start_timestamp_ns,"created_at_utc":datetime.now(timezone.utc).isoformat(),"created_at":datetime.now(timezone.utc).isoformat(),"duration_requested_seconds":config.duration_seconds,"duration_actual_seconds":actual,"frame_count":max(raw_count,ann_count),"raw_frame_count":raw_count,"annotated_frame_count":ann_count,"pose_result_count":len(frames),"measurement_sample_count":len(measurements),"frame_width":width,"frame_height":height,"actual_recorded_fps":max(raw_count,ann_count)/actual if actual else 0,"pose_result_rate_hz":len(frames)/actual if actual else 0,"raw_video_stored":config.store_raw_video,"annotated_video_stored":config.store_annotated_video,"raw_video_source":"existing_cv_camera_pre_annotation","annotated_video_source":"existing_cv_post_annotation","camera_owner":"existing_cv_engine","raw_video_mirrored":False,"display_preview_mirrored":False,"preview_source":"annotated","research_label":config.label,"label_source":"MASTER_MANUAL","technical_quality":quality["overall_technical_quality"],"tracking_good_ratio":quality["tracking_good_ratio"],"tracking_poor_ratio":quality["tracking_poor_ratio"],"tracking_lost_ratio":quality["tracking_lost_ratio"],"review_status":"REVIEW","approved":False,"training_eligible":False,"excluded":False,"software_version":"2.0","opencv_version":cv2.__version__,"python_version":sys.version.split()[0],"operating_system":platform.platform(),"pose_model_filename":"pose_landmarker.task"}
  (temp/"metadata.json").write_text(json.dumps(metadata,indent=2),encoding="utf-8");errors=validate_sample_integrity(temp,metadata);quality["integrity_errors"]=errors;quality["overall_technical_quality"]="INVALID" if errors else quality["overall_technical_quality"];(temp/"quality_report.json").write_text(json.dumps(quality,indent=2),encoding="utf-8");metadata["technical_quality"]=quality["overall_technical_quality"];metadata["artifacts"]=self._final_manifest(temp)["artifacts"];(temp/"metadata.json").write_text(json.dumps(metadata,indent=2),encoding="utf-8");(temp/"artifact_manifest.json").write_text(json.dumps(self._final_manifest(temp),indent=2),encoding="utf-8");integrity=self._integrity_report(temp,rid,frame_index,frames,config);(temp/"integrity_report.json").write_text(json.dumps(integrity,indent=2),encoding="utf-8");(temp/"artifact_manifest.json").write_text(json.dumps(self._final_manifest(temp),indent=2),encoding="utf-8")
  self._review={"recording_id":rid,"duration_seconds":actual,"frame_count":max(raw_count,ann_count),"raw_frame_count":raw_count,"annotated_frame_count":ann_count,"pose_result_count":len(frames),"tracking_good_ratio":quality["tracking_good_ratio"],"technical_quality":quality["overall_technical_quality"],"quality_report":quality,"has_raw_video":config.store_raw_video,"has_annotated_video":config.store_annotated_video,"integrity_errors":errors}
  pipeline=next((sample.get("exercise_snapshot") for sample in measurements if sample.get("exercise_snapshot")),{});metadata.update(dataset_schema_version="3.0",cv_pipeline_version=pipeline.get("cv_pipeline_version","UNKNOWN"),cv_performance_profile=pipeline.get("performance_profile","UNKNOWN"),cv_quality_profile_id=pipeline.get("quality_profile_id","UNKNOWN"));(temp/"metadata.json").write_text(json.dumps(metadata,indent=2),encoding="utf-8");(temp/"artifact_manifest.json").write_text(json.dumps(self._final_manifest(temp),indent=2),encoding="utf-8")
 @staticmethod
 def _csv(path,fields,rows):
  with path.open("w",newline="",encoding="utf-8") as handle:
   writer=csv.DictWriter(handle,fieldnames=fields,extrasaction="ignore");writer.writeheader();writer.writerows(rows)
 def _write_structured_artifacts(self,temp,rid,config,frames,frame_index,measurements,events,actual,raw_count,ann_count,dropped):
  frame_fields=["recording_id","capture_frame_id","capture_timestamp_ns","relative_time_ms","wall_time_utc","raw_video_frame_index","annotated_video_frame_index","pose_result_available","pose_result_id","tracking_state","recording_state"]
  self._csv(temp/"frame_index.csv",frame_fields,frame_index)
  long_landmarks=[]
  for pose_id,frame in enumerate(frames,1):
   frame["pose_result_id"]=pose_id
   for name,point in frame["landmarks"].items():
    side="LEFT" if name.startswith("LEFT") else "RIGHT" if name.startswith("RIGHT") else "MIDLINE"
    long_landmarks.append({"recording_id":rid,"pose_result_id":pose_id,"capture_frame_id":frame["frame_id"],"pose_timestamp_ns":frame.get("capture_timestamp_ns"),"relative_time_ms":frame["timestamp_ms"],"landmark_index":None,"landmark_name":name,"side":side,"region":"UPPER_BODY","x_normalized":point.get("x"),"y_normalized":point.get("y"),"z_model":point.get("z"),"visibility":point.get("visibility"),"presence":point.get("presence"),"valid":point.get("valid",True)})
  landmark_fields=["recording_id","pose_result_id","capture_frame_id","pose_timestamp_ns","relative_time_ms","landmark_index","landmark_name","side","region","x_normalized","y_normalized","z_model","visibility","presence","valid"]
  self._csv(temp/"pose_landmarks.csv",landmark_fields,long_landmarks);(temp/"pose_landmarks.json").write_text(json.dumps({"schema_version":"3.0","recording_id":rid,"pose_results":frames},indent=2),encoding="utf-8")
  tracking=[];quality_rows=[];kinematics=[];readiness=[];components=[];exercise=[]
  for pose_id,(frame,sample) in enumerate(zip(frames,measurements),1):
   base={"recording_id":rid,"capture_frame_id":frame["frame_id"],"timestamp_ns":frame.get("capture_timestamp_ns"),"relative_time_ms":frame["timestamp_ms"]}
   valid=sum(bool(p.get("valid",True)) for p in frame["landmarks"].values())
   tracking.append({**base,"pose_result_id":pose_id,"overall_tracking_state":frame["tracking_quality"],"required_landmarks_valid":valid>=8,"valid_landmark_count":valid,"stale":False,"tracking_reason_code":None})
   kine={**base}
   for name,value in sample.items():
    if isinstance(value,dict) and isinstance(value.get("value"),(int,float)):kine[name]=value["value"];quality_rows.append({**base,"metric_name":name.upper(),"quality_state":value.get("state","UNKNOWN"),"measurement_confidence":value.get("confidence"),"reason_code":None,"age_ms":None})
   ex=sample.get("exercise_snapshot") or {}
   for source,target in (("affected_elbow_angle","affected_elbow_angle_deg"),("raw_angle_deg","raw_elbow_angle_deg"),("smoothed_angle_deg","smoothed_elbow_angle_deg"),("extension_progress","extension_progress")):
    if ex.get(source) is not None:kine[target]=ex[source]
   kinematics.append(kine);readiness.append({**base,"ready":sample.get("ready"),"ready_progress":sample.get("ready_progress"),"ready_stage":sample.get("ready_stage"),"overall_state":sample.get("overall_posture_state"),"primary_feedback":(sample.get("feedback") or [None])[0],"secondary_feedback":(sample.get("feedback") or [None,None])[1] if len(sample.get("feedback") or [])>1 else None,"baseline_id":ex.get("calibration_id")})
   for name,value in sample.items():
    if isinstance(value,dict) and "state" in value:components.append({**base,"component_name":name.upper(),"state":value.get("state"),"raw_value":value.get("value"),"normalized_value":None,"reason_code":None})
   if ex:exercise.append({**base,**ex})
  self._csv(temp/"tracking.csv",["recording_id","pose_result_id","capture_frame_id","timestamp_ns","relative_time_ms","overall_tracking_state","required_landmarks_valid","valid_landmark_count","stale","tracking_reason_code"],tracking)
  self._csv(temp/"measurement_quality.csv",["recording_id","capture_frame_id","timestamp_ns","relative_time_ms","metric_name","quality_state","measurement_confidence","reason_code","age_ms"],quality_rows)
  kine_fields=["recording_id","capture_frame_id","timestamp_ns","relative_time_ms"]+sorted({key for row in kinematics for key in row if key not in {"recording_id","capture_frame_id","timestamp_ns","relative_time_ms"}});self._csv(temp/"kinematics.csv",kine_fields,kinematics)
  self._csv(temp/"readiness.csv",["recording_id","capture_frame_id","timestamp_ns","relative_time_ms","ready","ready_progress","ready_stage","overall_state","primary_feedback","secondary_feedback","baseline_id"],readiness)
  self._csv(temp/"posture_components.csv",["recording_id","capture_frame_id","timestamp_ns","relative_time_ms","component_name","state","raw_value","normalized_value","reason_code"],components)
  if exercise:
   ex_fields=["recording_id","capture_frame_id","timestamp_ns","relative_time_ms"]+sorted({key for row in exercise for key in row if key not in {"recording_id","capture_frame_id","timestamp_ns","relative_time_ms"}});self._csv(temp/"exercise_state.csv",ex_fields,exercise)
  reps=[];compensations=[];calibration=None
  for row in exercise:
   if row.get("rep_event"):reps.append(row["rep_event"])
   if row.get("compensation_events"):compensations.extend(row["compensation_events"])
   if row.get("calibration"):calibration=row["calibration"]
  (temp/"rep_events.json").write_text(json.dumps({"schema_version":"3.0","recording_id":rid,"events":reps,"authoritative":bool(reps)},indent=2),encoding="utf-8");(temp/"compensation_events.json").write_text(json.dumps({"schema_version":"3.0","recording_id":rid,"analysis_available":bool(exercise),"events":compensations},indent=2),encoding="utf-8")
  if calibration:(temp/"calibration.json").write_text(json.dumps({"schema_version":"3.0","recording_id":rid,**calibration},indent=2),encoding="utf-8")
  summary={"schema_version":"3.0","recording_id":rid,"session_id":config.session_id,"exercise_id":config.exercise_id,"duration_ms":round(actual*1000),"capture_frame_count":max(raw_count,ann_count),"pose_result_count":len(frames),"tracking_good_ratio":sum(f["tracking_quality"]=="GOOD" for f in frames)/max(1,len(frames)),"tracking_poor_ratio":sum(f["tracking_quality"]=="POOR" for f in frames)/max(1,len(frames)),"tracking_lost_ratio":sum(f["tracking_quality"]=="LOST" for f in frames)/max(1,len(frames)),"completed_rep_count":max((r.get("rep_count",0) for r in exercise),default=None),"compensation_event_counts":{},"warnings":["RECORDING_QUEUE_DROPS"] if dropped else []};(temp/"session_summary.json").write_text(json.dumps(summary,indent=2),encoding="utf-8")
 @staticmethod
 def _final_manifest(temp):
  artifacts={}
  for path in sorted(temp.iterdir()):
   if path.is_file() and path.name!="artifact_manifest.json":artifacts[path.name]={"path":path.name,"sha256":hashlib.sha256(path.read_bytes()).hexdigest(),"size_bytes":path.stat().st_size,"layer":"RAW" if path.name=="video.mp4" else "DERIVED" if path.name not in {"metadata.json","events.json","integrity_report.json"} else "METADATA"}
  return {"schema_version":"3.0","artifacts":artifacts}
 @staticmethod
 def _integrity_report(temp,rid,frame_index,frames,config):
  frame_ids=[row["capture_frame_id"] for row in frame_index];pose_ids=[frame["frame_id"] for frame in frames];errors=[]
  if any(b<=a for a,b in zip(frame_ids,frame_ids[1:])):errors.append("FRAME_IDS_NOT_MONOTONIC")
  if any(pid not in set(frame_ids) for pid in pose_ids):errors.append("ORPHAN_POSE_FRAME_REFERENCE")
  required=["metadata.json","frame_index.csv","artifact_manifest.json","quality_report.json"]+(["video.mp4"] if config.store_raw_video else [])
  missing=[name for name in required if not (temp/name).is_file()]
  errors.extend("MISSING_"+name.upper().replace(".","_") for name in missing)
  return {"schema_version":"3.0","recording_id":rid,"status":"PASS" if not errors else "FAIL","errors":errors,"checks":{"frame_ids_monotonic":"FRAME_IDS_NOT_MONOTONIC" not in errors,"pose_frame_references_valid":"ORPHAN_POSE_FRAME_REFERENCE" not in errors,"required_artifacts_present":not missing},"legacy":False}
 @staticmethod
 def _write_landmark_csv(path,rid,frames):
  names=sorted({name for frame in frames for name in frame["landmarks"]});fields=["recording_id","frame_id","capture_timestamp_ns","timestamp_ms","tracking_quality"]+[f"{name.lower()}_{part}" for name in names for part in ("x","y","z","visibility","presence","valid")]
  with path.open("w",newline="",encoding="utf-8") as handle:
   writer=csv.DictWriter(handle,fieldnames=fields);writer.writeheader()
   for frame in frames:
    row={key:frame.get(key) for key in fields[:5]}
    for name in names:
     point=frame["landmarks"].get(name,{})
     for part in ("x","y","z","visibility","presence","valid"):row[f"{name.lower()}_{part}"]=point.get(part)
    writer.writerow(row)
