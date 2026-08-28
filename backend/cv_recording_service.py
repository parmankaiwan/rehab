from __future__ import annotations
import csv,json,platform,shutil,sys,threading,time
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
  self.settings=settings;self.vault=vault;self.raw_store=raw_store;self.annotated_store=annotated_store;self.posture_store=posture_store;self._lock=threading.RLock();self._state=RecordingState.IDLE;self._recording_id=None;self._configuration=None;self._started_monotonic=None;self._countdown_started=None;self._frame_count=self._pose_count=0;self._error=None;self._review=None;self._cancel=threading.Event();self._thread=None
 def start(self,configuration:RecordingConfiguration)->RecordingStatus:
  module=self.vault.registry.validate_label(configuration.rehab_type,configuration.label)
  configuration.rehab_slug=module.slug;configuration.category=module.id
  if configuration.duration_seconds>self.settings.max_recording_seconds:raise ValueError("Duration exceeds safety limit")
  if not self.annotated_store.is_fresh():raise RuntimeError("CV ENGINE NOT AVAILABLE")
  if shutil.disk_usage(self.settings.root).free<self.settings.minimum_free_bytes:raise RuntimeError("INSUFFICIENT STORAGE")
  with self._lock:
   if self._state in (RecordingState.COUNTDOWN,RecordingState.RECORDING,RecordingState.FINALIZING,RecordingState.SAVING):raise RuntimeError("A recording is already active")
   self._recording_id=self.vault.new_recording_id();configuration.session_id=configuration.session_id or self.vault.next_session_id();configuration.trial_number=self.vault.next_trial(configuration.subject_id,configuration.session_id,configuration.category,configuration.label);self._configuration=configuration;self._state=RecordingState.CONFIGURED;self._error=None;self._review=None;self._frame_count=self._pose_count=0;self._cancel.clear();self._thread=threading.Thread(target=self._run,name="flexmap-dataset-recorder",daemon=True);self._thread.start()
  return self.status()
 def cancel(self):
  with self._lock:
   if self._state not in (RecordingState.CONFIGURED,RecordingState.COUNTDOWN,RecordingState.RECORDING):raise RuntimeError("No active recording")
   self._cancel.set()
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
   elapsed=max(0,time.monotonic()-self._started_monotonic) if self._started_monotonic and self._state in (RecordingState.RECORDING,RecordingState.FINALIZING,RecordingState.REVIEW) else 0;duration=self._configuration.duration_seconds if self._configuration else 0;countdown=max(0,self.settings.countdown_seconds-int(time.monotonic()-self._countdown_started)) if self._state==RecordingState.COUNTDOWN and self._countdown_started else 0
   return RecordingStatus(state=self._state,recording_id=self._recording_id,elapsed_seconds=min(elapsed,duration),remaining_seconds=max(0,duration-elapsed),countdown_remaining=countdown,frame_count=self._frame_count,pose_result_count=self._pose_count,error=self._error,review=self._review)
 def review_path(self,recording_id,filename):
  allowed={"video.mp4","annotated_video.mp4","preview.jpg","metadata.json","quality_report.json","landmarks.json","landmarks.csv","measurements.json","events.json"}
  if recording_id!=self._recording_id or filename not in allowed:raise FileNotFoundError(filename)
  path=self.vault.temp_path(recording_id)/filename
  if not path.is_file():raise FileNotFoundError(filename)
  return path
 def _set_state(self,state):
  with self._lock:self._state=state
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
   self._set_state(RecordingState.COUNTDOWN);self._countdown_started=time.monotonic()
   if self._cancel.wait(self.settings.countdown_seconds):self._set_state(RecordingState.DISCARDED);return
   temp.mkdir(parents=True,exist_ok=False);raw_sub=self.raw_store.subscribe(self.settings.recording_frame_queue_max);ann_sub=self.annotated_store.subscribe(self.settings.recording_frame_queue_max);self._started_monotonic=time.monotonic();self._set_state(RecordingState.RECORDING)
   frames=[];measurements=[];preview=[];events=[{"event":"RECORDING_STARTED","timestamp_ms":0}];last_snapshot=-1.0;raw_count=ann_count=0;width=height=0;last_quality=None
   while time.monotonic()-self._started_monotonic<config.duration_seconds and not self._cancel.is_set():
    for packet in raw_sub.drain():
     if config.store_raw_video:
      if raw_writer is None:raw_writer,image,width,height=self._open_writer(temp/"video.mp4",packet,self.settings.video_codec,self.settings.target_video_fps)
      else:image=cv2.imdecode(np.frombuffer(packet.jpeg,dtype=np.uint8),cv2.IMREAD_COLOR)
      if image is not None:raw_writer.write(image);raw_count+=1
    for packet in ann_sub.drain():
     if config.store_annotated_video:
      if ann_writer is None:ann_writer,image,width,height=self._open_writer(temp/"annotated_video.mp4",packet,self.settings.video_codec,self.settings.target_video_fps)
      else:image=cv2.imdecode(np.frombuffer(packet.jpeg,dtype=np.uint8),cv2.IMREAD_COLOR)
      if image is not None:ann_writer.write(image);ann_count+=1
     preview.append((time.monotonic()-self._started_monotonic,packet.jpeg))
    snapshot=self.posture_store.latest()
    if snapshot and snapshot.timestamp!=last_snapshot:
     relative=round((time.monotonic()-self._started_monotonic)*1000);quality=snapshot.tracking_quality if snapshot.tracking_quality in ("GOOD","POOR","LOST") else "LOST";landmarks={name:point.model_dump(mode="json") for name,point in snapshot.landmarks.items()};frame_id=snapshot.capture_frame_id or (ann_count or raw_count);frames.append({"frame_id":frame_id,"capture_timestamp_ns":snapshot.capture_timestamp_ns,"timestamp_ms":relative,"source_timestamp":snapshot.timestamp,"tracking_quality":quality,"landmarks":landmarks});sample={"frame_id":frame_id,"timestamp_ms":relative,"tracking_quality":quality,"overall_posture_state":snapshot.overall_state.value,"ready":snapshot.ready}
     for key,component in snapshot.components.items():
      if component.value is not None:sample[key.lower()]={"value":component.value,"units":component.units,"state":component.state.value}
     measurements.append(sample);self._pose_count+=1;last_snapshot=snapshot.timestamp
     if last_quality and quality!=last_quality and (quality=="LOST" or last_quality=="LOST"):events.append({"event":"TRACKING_LOST" if quality=="LOST" else "TRACKING_RECOVERED","timestamp_ms":relative})
     last_quality=quality
    self._frame_count=max(raw_count,ann_count);time.sleep(.003)
   for writer in (raw_writer,ann_writer):
    if writer:writer.release()
   raw_writer=ann_writer=None;dropped=max(raw_sub.dropped,ann_sub.dropped);self.raw_store.unsubscribe(raw_sub);self.annotated_store.unsubscribe(ann_sub);raw_sub=ann_sub=None
   self._set_state(RecordingState.FINALIZING)
   if self._cancel.is_set():self.vault.discard_temp(rid);self._set_state(RecordingState.DISCARDED);return
   actual=time.monotonic()-self._started_monotonic;events.append({"event":"RECORDING_ENDED","timestamp_ms":round(actual*1000)})
   self._finalize(temp,rid,config,frames,measurements,events,preview,width,height,actual,raw_count,ann_count,dropped)
   self._set_state(RecordingState.REVIEW)
  except Exception as exc:
   for writer in (raw_writer,ann_writer):
    if writer:writer.release()
   if raw_sub:self.raw_store.unsubscribe(raw_sub)
   if ann_sub:self.annotated_store.unsubscribe(ann_sub)
   with self._lock:self._state=RecordingState.ERROR;self._error=str(exc)
 def _finalize(self,temp,rid,config,frames,measurements,events,preview,width,height,actual,raw_count,ann_count,dropped):
  (temp/"landmarks.json").write_text(json.dumps({"dataset_schema_version":"2.0","recording_id":rid,"frames":frames},indent=2),encoding="utf-8");self._write_landmark_csv(temp/"landmarks.csv",rid,frames);(temp/"measurements.json").write_text(json.dumps({"dataset_schema_version":"2.0","recording_id":rid,"samples":measurements},indent=2),encoding="utf-8");(temp/"events.json").write_text(json.dumps({"dataset_schema_version":"2.0","recording_id":rid,"events":events},indent=2),encoding="utf-8")
  if config.store_preview_image and preview:(temp/"preview.jpg").write_bytes(min(preview,key=lambda x:abs(x[0]-actual/2))[1])
  raw_valid=self._valid_video(temp/"video.mp4",config.store_raw_video);ann_valid=self._valid_video(temp/"annotated_video.mp4",config.store_annotated_video);quality=build_quality_report(rid,frames,actual,raw_count,ann_count,dropped,raw_valid,ann_valid);(temp/"quality_report.json").write_text(json.dumps(quality,indent=2),encoding="utf-8")
  metadata={**config.model_dump(),"dataset_schema_version":"2.0","recording_id":rid,"created_at_utc":datetime.now(timezone.utc).isoformat(),"created_at":datetime.now(timezone.utc).isoformat(),"duration_requested_seconds":config.duration_seconds,"duration_actual_seconds":actual,"frame_count":max(raw_count,ann_count),"raw_frame_count":raw_count,"annotated_frame_count":ann_count,"pose_result_count":len(frames),"measurement_sample_count":len(measurements),"frame_width":width,"frame_height":height,"actual_recorded_fps":max(raw_count,ann_count)/actual if actual else 0,"pose_result_rate_hz":len(frames)/actual if actual else 0,"raw_video_stored":config.store_raw_video,"annotated_video_stored":config.store_annotated_video,"raw_video_source":"existing_cv_camera_pre_annotation","annotated_video_source":"existing_cv_post_annotation","camera_owner":"existing_cv_engine","raw_video_mirrored":False,"display_preview_mirrored":False,"preview_source":"annotated","research_label":config.label,"label_source":"MASTER_MANUAL","technical_quality":quality["overall_technical_quality"],"tracking_good_ratio":quality["tracking_good_ratio"],"tracking_poor_ratio":quality["tracking_poor_ratio"],"tracking_lost_ratio":quality["tracking_lost_ratio"],"review_status":"REVIEW","approved":False,"training_eligible":False,"excluded":False,"software_version":"2.0","opencv_version":cv2.__version__,"python_version":sys.version.split()[0],"operating_system":platform.platform(),"pose_model_filename":"pose_landmarker.task"}
  (temp/"metadata.json").write_text(json.dumps(metadata,indent=2),encoding="utf-8");metadata["artifacts"]=artifact_manifest(temp);(temp/"metadata.json").write_text(json.dumps(metadata,indent=2),encoding="utf-8");errors=validate_sample_integrity(temp,metadata);quality["integrity_errors"]=errors;quality["overall_technical_quality"]="INVALID" if errors else quality["overall_technical_quality"];(temp/"quality_report.json").write_text(json.dumps(quality,indent=2),encoding="utf-8");metadata["technical_quality"]=quality["overall_technical_quality"];metadata["artifacts"]=artifact_manifest(temp);(temp/"metadata.json").write_text(json.dumps(metadata,indent=2),encoding="utf-8")
  self._review={"recording_id":rid,"duration_seconds":actual,"frame_count":max(raw_count,ann_count),"raw_frame_count":raw_count,"annotated_frame_count":ann_count,"pose_result_count":len(frames),"tracking_good_ratio":quality["tracking_good_ratio"],"technical_quality":quality["overall_technical_quality"],"quality_report":quality,"has_raw_video":config.store_raw_video,"has_annotated_video":config.store_annotated_video,"integrity_errors":errors}
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