from __future__ import annotations
import asyncio,os
from fastapi import APIRouter,Depends,Header,HTTPException,WebSocket,WebSocketDisconnect
from fastapi.responses import FileResponse
from .schemas import BaselineRepeatabilityRequest,BaselineRequest,ConnectRequest,HardwareProfileRequest,QualityProfileRequest,RecordingRequest,ValidationRequest
from .signal_processing import EmgProcessingConfig
from .service import EmgService
from ..dataset_config import dataset_settings
from ..master_dataset_api import require_master
service=EmgService(dataset_settings());router=APIRouter(prefix="/api/master/emg",tags=["Master EMG"],dependencies=[Depends(require_master)]);ws_router=APIRouter()
@router.get("/devices")
def devices():return service.devices()
@router.get("/status")
def status():return service.status()
@router.post("/connect")
def connect(req:ConnectRequest):
 try:return service.connect(req)
 except RuntimeError as exc:raise HTTPException(409,str(exc)) from exc
@router.post("/disconnect")
def disconnect():return service.disconnect()
@router.get("/rehab-modules")
def modules():return [{**x.as_dict(),"emg_stats":service.stats(x.slug)} for x in service.registry.modules]
@router.get("/rehab/{slug}/stats")
def stats(slug:str):
 try:return service.stats(slug)
 except ValueError as exc:raise HTTPException(404,str(exc)) from exc
@router.get("/rehab/{slug}/recordings")
def recordings(slug:str,label:str="",mock:str="",hardware_profile_id:str="",hardware_version:int|None=None,channel_count:int|None=None,processing_version:str="",quality_profile_id:str=""):
 try:return service.list(slug,label,mock,hardware_profile_id,hardware_version,channel_count,processing_version,quality_profile_id)
 except ValueError as exc:raise HTTPException(404,str(exc)) from exc
@router.post("/recordings/start")
def start(req:RecordingRequest):
 try:return service.start_recording(req)
 except ValueError as exc:raise HTTPException(422,str(exc)) from exc
 except RuntimeError as exc:raise HTTPException(409,str(exc)) from exc
@router.get("/recordings/status")
def recording_status():return service.recording_status()
@router.post("/recordings/cancel")
def cancel():return service.cancel()
@router.post("/recordings/{rid}/save")
def save(rid:str):
 try:return service.save(rid)
 except (RuntimeError,ValueError) as exc:raise HTTPException(409,str(exc)) from exc
@router.delete("/recordings/{rid}/review")
def discard(rid:str):
 try:return service.discard(rid)
 except RuntimeError as exc:raise HTTPException(409,str(exc)) from exc
@router.get("/recordings/{rid}")
def detail(rid:str):
 x=service.get(rid)
 if not x:raise HTTPException(404,"EMG recording not found")
 return x
@router.get("/recordings/{rid}/files/{name}")
def artifact(rid:str,name:str):
 try:return FileResponse(service.file(rid,name),filename=name)
 except FileNotFoundError as exc:raise HTTPException(404,"File not found") from exc
@router.get("/recordings/{rid}/waveform")
def waveform(rid:str,max_points:int=2000):
 x=service.get(rid)
 if not x:raise HTTPException(404,"EMG recording not found")
 import csv
 with service.file(rid,'emg_raw.csv').open(encoding='utf-8') as f:rows=list(csv.DictReader(f))
 stride=max(1,len(rows)//max(1,min(max_points,5000)));return {"recording_id":rid,"raw_units":"ADC_COUNTS","samples":rows[::stride][:5000]}
@router.get("/processing/config")
def processing_config():return service.processing_config()
@router.put("/processing/config")
def processing_update(config:EmgProcessingConfig):return service.apply_processing_config(config)
@router.post("/processing/reset")
def processing_reset():return service.reset_processing()
@router.put("/processing/display")
def processing_display(signals:list[str]):
 try:return service.select_display_signals(signals)
 except ValueError as exc:raise HTTPException(422,str(exc)) from exc
@router.get("/signal-quality")
def signal_quality():return service.signal_quality_report()
@router.post("/baseline/start")
def baseline_start(req:BaselineRequest):
 try:return service.start_baseline(req)
 except (RuntimeError,ValueError) as exc:raise HTTPException(409,str(exc)) from exc
@router.post("/baseline/stop")
def baseline_stop():return service.baseline_status()
@router.get("/baseline/status")
def baseline_status():return service.baseline_status()
@router.get("/baselines")
def baselines():return service.list_baselines()
@router.get("/baselines/{bid}")
def baseline(bid:str):
 value=service.get_baseline(bid)
 if not value:raise HTTPException(404,"Baseline not found")
 return value
@router.post("/recordings/{rid}/reprocess")
def reprocess(rid:str,config:EmgProcessingConfig,preferred_for_review:bool=False):
 try:return service.reprocess(rid,config,preferred_for_review)
 except FileNotFoundError as exc:raise HTTPException(404,"EMG recording not found") from exc
 except RuntimeError as exc:raise HTTPException(409,str(exc)) from exc
@router.get("/recordings/{rid}/processing-runs")
def processing_runs(rid:str):return service.processing_runs(rid)
@router.get("/recordings/{rid}/processing-runs/{proc_id}/waveform")
def processing_waveform(rid:str,proc_id:str,max_points:int=2000):
 value=service.processing_waveform(rid,proc_id,max_points)
 if not value:raise HTTPException(404,"Processing run not found")
 return value
@router.get("/recordings/{rid}/signal-quality")
def recording_signal_quality(rid:str):
 runs=service.processing_runs(rid)
 if not runs:return {"status":"NOT_YET_GENERATED","message":"RAW RECORDING — Processing not yet generated"}
 return runs[0]
@router.get("/hardware-profiles")
def hardware_profiles(include_archived:bool=False):return service.hardware_profiles(include_archived)
@router.post("/hardware-profiles")
def hardware_profile_create(req:HardwareProfileRequest):
 try:return service.create_hardware_profile(req.model_dump())
 except ValueError as exc:raise HTTPException(409,str(exc)) from exc
@router.get("/hardware-profiles/{profile_id}")
def hardware_profile(profile_id:str):
 value=service.hardware_profile(profile_id)
 if not value:raise HTTPException(404,"Hardware profile not found")
 return value
@router.post("/hardware-profiles/{profile_id}/versions")
def hardware_profile_version(profile_id:str,req:HardwareProfileRequest):
 try:return service.version_hardware_profile(profile_id,req.model_dump())
 except KeyError as exc:raise HTTPException(404,"Hardware profile not found") from exc
@router.post("/hardware-profiles/{profile_id}/archive")
def hardware_profile_archive(profile_id:str):
 try:return service.archive_hardware_profile(profile_id)
 except KeyError as exc:raise HTTPException(404,"Hardware profile not found") from exc
@router.get("/hardware-profiles/{profile_id}/validations")
def validation_history(profile_id:str):return service.hardware_history(profile_id)
@router.get("/hardware-profiles/{profile_id}/validations/{run_id}/download")
def validation_download(profile_id:str,run_id:str):
 try:return FileResponse(service.hardware.validation_report_path(profile_id,run_id),filename="hardware_validation_report.json")
 except FileNotFoundError as exc:raise HTTPException(404,"Validation report not found") from exc
@router.post("/quality-profiles")
def quality_profile(req:QualityProfileRequest):return service.create_quality_profile(req.model_dump())
@router.post("/validation/timing")
def validate_timing(req:ValidationRequest):
 try:return service.validate_timing(req.hardware_profile_id)
 except KeyError as exc:raise HTTPException(404,"Hardware profile not found") from exc
@router.post("/validation/adc")
def validate_adc(req:ValidationRequest):
 try:return service.validate_adc(req.hardware_profile_id)
 except KeyError as exc:raise HTTPException(404,"Hardware profile not found") from exc
@router.post("/validation/channels")
def validate_channels(req:ValidationRequest):
 try:return service.validate_channels(req.hardware_profile_id)
 except KeyError as exc:raise HTTPException(404,"Hardware profile not found") from exc
@router.post("/validation/powerline")
def validate_powerline(req:ValidationRequest):
 try:return service.validate_powerline(req.hardware_profile_id)
 except KeyError as exc:raise HTTPException(404,"Hardware profile not found") from exc
@router.post("/validation/filter-response")
def validate_filter(req:ValidationRequest):
 try:return service.validate_filter(req.hardware_profile_id)
 except KeyError as exc:raise HTTPException(404,"Hardware profile not found") from exc
@router.get("/validation/host-latency")
def validate_latency():return service.validate_latency()
@router.post("/validation/quick-check")
def validate_quick(req:ValidationRequest):
 try:return service.quick_signal_check(req.hardware_profile_id)
 except KeyError as exc:raise HTTPException(404,"Hardware profile not found") from exc
@router.post("/validation/baseline-repeatability")
def validate_baseline(req:BaselineRepeatabilityRequest):
 try:return service.baseline_repeatability_report(req.hardware_profile_id,req.baseline_ids)
 except KeyError as exc:raise HTTPException(404,"Hardware profile or baseline not found") from exc
@router.post("/validation/report")
def validation_report(req:ValidationRequest):
 try:return service.generate_hardware_report(req.hardware_profile_id,req.notes)
 except KeyError as exc:raise HTTPException(404,"Hardware profile not found") from exc
@router.post("/recordings/{rid}/hardware-profile/{profile_id}")
def assign_hardware(rid:str,profile_id:str):
 try:return service.assign_hardware_profile(rid,profile_id)
 except (KeyError,FileNotFoundError) as exc:raise HTTPException(404,"Recording or profile not found") from exc
@router.post("/ws-ticket")
def ticket():return {"ticket":service.issue_ticket(),"expires_seconds":60}
@ws_router.websocket("/ws/emg")
async def emg_socket(ws:WebSocket,ticket:str=""):
 if not service.consume_ticket(ticket):await ws.close(code=4403);return
 await ws.accept();after=0
 try:
  while True:
   batch=service.batch(after);after=batch['latest_sequence_id']
   if batch['samples']:await ws.send_json(batch)
   await ws.send_json(service.status());await asyncio.sleep(.04)
 except (WebSocketDisconnect,RuntimeError):pass