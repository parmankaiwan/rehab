import json
import pytest
from types import SimpleNamespace
from backend import acquisition as acquisition_module
from backend.acquisition import AcquisitionStore, CollectionCreate, MarkerCreate, ProtocolCreate, RetryRequest, SkipRequest, StudyCreate, SubjectCreate, TrialStart
from backend.dataset_models import RecordingState, RecordingStatus

def protocol(**changes):
 data={"protocol_id":"REACHING_CV","display_name":"Reaching CV","rehab_type":"REACHING","modality":"CV","allowed_labels":["reach"],"trial_plan":[{"label":"reach","count":5,"duration_seconds":3}],"required_sensors":["CAMERA"]};data.update(changes);return ProtocolCreate(**data)

def prepared(tmp_path):
 store=AcquisitionStore(tmp_path);store.create_study(StudyCreate(study_id="PILOT",name="Pilot"));store.create_subject(SubjectCreate(subject_id="P001",affected_side="RIGHT"));store.create_protocol(protocol());collection=store.create_collection(CollectionCreate(study_id="PILOT",subject_id="P001",session_id="SESSION001",protocol_id="REACHING_CV",affected_side="RIGHT",consent_recorded=True));return store,collection

def test_protocol_versions_are_immutable(tmp_path):
 store,_=prepared(tmp_path);v2=store.create_protocol(protocol(display_name="Reaching CV revised"));rows=store.list("protocols");assert v2["protocol_version"]==2;assert rows[-1]["display_name"]=="Reaching CV";assert rows[-1]["protocol_version"]==1

def test_cv_protocol_allows_only_three_or_five_without_changing_emg_range():
 assert protocol(countdown_seconds=3).countdown_seconds==3;assert protocol(countdown_seconds=5).countdown_seconds==5
 with pytest.raises(ValueError,match="must be 3 or 5"):protocol(countdown_seconds=4)
 assert protocol(modality="EMG",countdown_seconds=4).countdown_seconds==4

def test_trial_plan_expands_and_skip_requires_reason(tmp_path):
 store,collection=prepared(tmp_path);assert len(collection["trials"])==5;assert len({x["trial_id"] for x in collection["trials"]})==5
 store.mutate(collection["collection_id"],"start_collection");first=collection["trials"][0];updated=store.mutate(collection["collection_id"],"skip",SkipRequest(reason="Participant requested stop"),first["trial_id"]);assert updated["trials"][0]["state"]=="SKIPPED";assert updated["current_trial_id"]==updated["trials"][1]["trial_id"]

def test_retry_preserves_trial_and_increments_attempt(tmp_path):
 store,collection=prepared(tmp_path);data=json.loads(store.path.read_text());trial=data["collections"][0]["trials"][0];trial["state"]="RETRY_REQUIRED";trial_id=trial["trial_id"];store._write(data);updated=store.mutate(collection["collection_id"],"retry",RetryRequest(reason="Tracking interruption"),trial_id);trial=updated["trials"][0];assert trial["trial_id"]==trial_id;assert trial["attempt_number"]==2;assert trial["attempts"][0]["reason"]=="Tracking interruption"

def test_restart_marks_active_trial_recovery_required(tmp_path):
 store,collection=prepared(tmp_path);data=json.loads(store.path.read_text());data["collections"][0]["status"]="ACTIVE";data["collections"][0]["trials"][0]["state"]="RECORDING";store._write(data);recovered=AcquisitionStore(tmp_path).get(collection["collection_id"]);assert recovered["status"]=="INCOMPLETE";assert recovered["trials"][0]["state"]=="RETRY_REQUIRED"

def test_coverage_keeps_subject_and_recording_counts_distinct(tmp_path):
 store,collection=prepared(tmp_path);data=json.loads(store.path.read_text());trial=data["collections"][0]["trials"][0];trial["state"]="APPROVED";trial["recording_ids"]["CV"]="REC-1";store._write(data);coverage=store.coverage();assert coverage["recordings"]==1;assert coverage["unique_subjects"]==1;assert coverage["rows"][0]["missing_trials"]==4

class FakeChannel:
 def model_dump(self):return {"internal_id":"channel_1","display_name":"Biceps","muscle_label":"BICEPS","body_side":"RIGHT"}
class FakeHardware:
 def snapshot(self,pid,version=None):return {"hardware_profile_id":pid,"profile_version":version or 2,"display_name":"ESP32 EMG","channel_count":1,"is_mock":False}
class FakeEmg:
 def __init__(self):self.config=SimpleNamespace(channels=[FakeChannel()]);self.hardware=FakeHardware();self.state="IDLE";self.recording_id="EMG-1";self.markers=[];self.baseline_result={"state":"IDLE","baseline":None}
 def processing_status(self):return {"processing_version":"test","config_hash":"abc"}
 def status(self):return {"connection_state":"STREAMING","latest_data_age_ms":10,"received_rate_hz":1000,"channel_count":1,"recording_state":self.state}
 def signal_quality_report(self):return {"warnings":[],"channels":{"channel_1":{"sample_count":1000}}}
 def start_recording(self,req):self.request=req;self.state="RECORDING";return {"recording_id":self.recording_id}
 def recording_status(self):return {"state":self.state,"recording_id":self.recording_id,"review":None}
 def add_recording_marker(self,event_type,notes=""):marker={"event_id":"MARK-SERVER","relative_timestamp_ms":123.5,"event":event_type};self.markers.append(marker);return marker
 def stop_recording(self):self.state="FINALIZING";return self.recording_status()
 def baseline_status(self):return self.baseline_result
 def start_baseline(self,req):self.baseline_request=req;self.baseline_result={"state":"COMPLETE","baseline":{"baseline_id":"BASE-1"}};return self.baseline_result

def test_emg_collection_locks_snapshots_and_writes_manifests(tmp_path,monkeypatch):
 fake=FakeEmg();monkeypatch.setattr(acquisition_module,"emg_service",fake);store=AcquisitionStore(tmp_path);store.create_subject(SubjectCreate(subject_id="P002",affected_side="RIGHT"));store.create_protocol(protocol(protocol_id="REACHING_EMG",display_name="Reaching EMG",modality="EMG",allowed_labels=["forward_reach"],trial_plan=[{"label":"forward_reach","count":1,"duration_seconds":3}],required_sensors=["EMG_BOARD"],required_emg_channels=1,required_hardware_profile_id="HWP-ESP32",recommended_channel_map=[FakeChannel().model_dump()],baseline_required=False))
 collection=store.create_collection(CollectionCreate(subject_id="P002",session_id="SESSION002",protocol_id="REACHING_EMG",affected_side="RIGHT",consent_recorded=True,hardware_profile_id="HWP-ESP32",hardware_profile_version=2,channel_map=[FakeChannel().model_dump()],controller_id="TAB-1"))
 assert collection["hardware_profile_snapshot"]["profile_version"]==2;assert collection["channel_map_snapshot"][0]["muscle_label"]=="BICEPS";folder=tmp_path/"collection_reports"/collection["collection_id"];assert (folder/"collection_manifest.json").is_file();assert (folder/"trial_manifest.csv").is_file()

def test_emg_manual_stop_and_marker_use_server_state(tmp_path,monkeypatch):
 fake=FakeEmg();monkeypatch.setattr(acquisition_module,"emg_service",fake);store=AcquisitionStore(tmp_path);store.create_subject(SubjectCreate(subject_id="P003",affected_side="RIGHT"));store.create_protocol(protocol(protocol_id="REACHING_EMG",display_name="Reaching EMG",modality="EMG",allowed_labels=["forward_reach"],required_sensors=["EMG_BOARD"],required_emg_channels=1,trial_plan=[{"label":"forward_reach","count":1,"duration_seconds":60,"duration_mode":"MANUAL_STOP"}]))
 collection=store.create_collection(CollectionCreate(subject_id="P003",session_id="SESSION003",protocol_id="REACHING_EMG",affected_side="RIGHT",consent_recorded=True,channel_map=[FakeChannel().model_dump()],controller_id="TAB-3"));cid=collection["collection_id"];tid=collection["trials"][0]["trial_id"];store.mutate(cid,"start_collection");
 with pytest.raises(RuntimeError,match="another browser tab"):store.mutate(cid,"start_trial",TrialStart(controller_id="TAB-OTHER"),tid)
 started=store.mutate(cid,"start_trial",TrialStart(controller_id="TAB-3"),tid);assert fake.request.manual_stop is True;started=store.get(cid);assert started["trials"][0]["state"]=="RECORDING"
 marked=store.mutate(cid,"marker",MarkerCreate(event_type="MOVEMENT_STARTED"),tid);assert marked["trials"][0]["markers"][0]["relative_timestamp_ms"]==123.5;stopped=store.mutate(cid,"stop_trial",tid=tid);assert stopped["trials"][0]["state"]=="FINALIZING"

def test_required_baseline_is_linked_before_preflight_passes(tmp_path,monkeypatch):
 fake=FakeEmg();monkeypatch.setattr(acquisition_module,"emg_service",fake);store=AcquisitionStore(tmp_path);store.create_subject(SubjectCreate(subject_id="P004",affected_side="RIGHT"));store.create_protocol(protocol(protocol_id="BASELINE_EMG",display_name="Baseline EMG",modality="EMG",allowed_labels=["forward_reach"],trial_plan=[{"label":"forward_reach","count":1,"duration_seconds":3}],required_sensors=["EMG_BOARD"],required_emg_channels=1,baseline_required=True,baseline_count=1,baseline_duration_seconds=5));collection=store.create_collection(CollectionCreate(subject_id="P004",session_id="SESSION004",protocol_id="BASELINE_EMG",affected_side="RIGHT",consent_recorded=True,channel_map=[FakeChannel().model_dump()]));assert store.preflight(collection)["overall"]=="BLOCKED"
 started=store.baseline(collection["collection_id"],"start",acquisition_module.BaselineAction(notes="Resting"));assert fake.baseline_request.baseline_group_id==collection["baseline_group_id"];accepted=store.baseline(collection["collection_id"],"accept");assert accepted["collection"]["baselines"][0]["baseline_id"]=="BASE-1";assert store.preflight(accepted["collection"])["overall"]=="PASS"

class FakeCvRecorder:
 def __init__(self):self.state=RecordingState.IDLE;self.recording_id=None;self.configuration=None;self.cancelled=False;self.error=None
 def status(self):return RecordingStatus(state=self.state,recording_id=self.recording_id,countdown_seconds=self.configuration.countdown_seconds if self.configuration else 3,countdown_remaining=self.configuration.countdown_seconds if self.state==RecordingState.COUNTDOWN and self.configuration else 0,error=self.error)
 def start(self,configuration):self.configuration=configuration;self.recording_id="CV-COUNTDOWN-1";self.state=RecordingState.COUNTDOWN;return self.status()
 def cancel(self):self.cancelled=True;self.state=RecordingState.DISCARDED;return self.status()

def test_cv_protocol_countdown_persists_and_cancel_creates_no_trial_recording(tmp_path,monkeypatch):
 fake=FakeCvRecorder();monkeypatch.setattr(acquisition_module,"recorder",fake);store=AcquisitionStore(tmp_path);store.create_subject(SubjectCreate(subject_id="P005",affected_side="RIGHT"));store.create_protocol(protocol(countdown_seconds=5,trial_plan=[{"label":"reach","count":1,"duration_seconds":10}]))
 collection=store.create_collection(CollectionCreate(subject_id="P005",session_id="SESSION005",protocol_id="REACHING_CV",affected_side="RIGHT",consent_recorded=True));cid=collection["collection_id"];tid=collection["trials"][0]["trial_id"]
 assert collection["protocol_snapshot"]["countdown_seconds"]==5;assert collection["trials"][0]["countdown_seconds"]==5
 store.mutate(cid,"start_collection");monkeypatch.setattr(store,"preflight",lambda _:{"overall":"PASS","checks":[]})
 started=store.mutate(cid,"start_trial",TrialStart(),tid);assert started["trials"][0]["state"]=="COUNTDOWN";assert fake.configuration.countdown_seconds==5
 cancelled=store.mutate(cid,"cancel_countdown",tid=tid);assert fake.cancelled is True;assert cancelled["trials"][0]["state"]=="READY";assert cancelled["trials"][0]["recording_ids"]["CV"] is None

def test_tracking_loss_during_cv_countdown_requires_full_retry(tmp_path,monkeypatch):
 fake=FakeCvRecorder();monkeypatch.setattr(acquisition_module,"recorder",fake);store=AcquisitionStore(tmp_path);store.create_subject(SubjectCreate(subject_id="P006",affected_side="RIGHT"));store.create_protocol(protocol(countdown_seconds=5,trial_plan=[{"label":"reach","count":1,"duration_seconds":10}]))
 collection=store.create_collection(CollectionCreate(subject_id="P006",session_id="SESSION006",protocol_id="REACHING_CV",affected_side="RIGHT",consent_recorded=True));cid=collection["collection_id"];tid=collection["trials"][0]["trial_id"];store.mutate(cid,"start_collection");monkeypatch.setattr(store,"preflight",lambda _:{"overall":"PASS","checks":[]});store.mutate(cid,"start_trial",TrialStart(),tid)
 fake.state=RecordingState.ERROR;fake.error="TRACKING_LOST";updated=store.get(cid);trial=updated["trials"][0];assert trial["state"]=="RETRY_REQUIRED";assert trial["countdown_seconds"]==5;assert "Countdown reset" in trial["quality_warnings"][0]
