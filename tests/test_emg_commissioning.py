import json
import time
from collections import deque
from types import SimpleNamespace
from unittest.mock import patch

from backend.emg import commissioning as module
from backend.emg.commissioning import EmgHardwareValidationStore, ValidationRunCreate, ValidationTestRequest
from backend.emg.hardware_profiles import HardwareProfileStore


class Channel:
    internal_id="channel_1";display_name="Biceps";muscle_label="BICEPS";body_side="RIGHT"
    def model_dump(self):return {"internal_id":self.internal_id,"display_name":self.display_name,"muscle_label":self.muscle_label,"body_side":self.body_side}


def sample(i):return {"sequence_id":i,"host_timestamp_ns":i*1_000_000,"device_timestamp":i,"device_sequence_id":i,"channels":{"channel_1":2048+i%17},"valid":True}


class FakeService:
    def __init__(self,root):
        self.hardware=HardwareProfileStore(root);self.profile=self.hardware.create({"display_name":"ESP32 Real","transport_type":"USB_SERIAL","serial_baud_rate":115200,"protocol":"CSV_CHANNELS","channel_count":1,"expected_sample_rate_hz":1000,"device_timestamp_supported":True,"device_timestamp_unit":"MILLISECONDS","device_sequence_supported":True,"adc_bits":12,"adc_min_count":0,"adc_max_count":4095,"raw_representation":"ADC_COUNTS_UNSIGNED","is_mock":False});self.samples=deque((sample(i) for i in range(1,201)),maxlen=60000);self.processed_samples=deque(maxlen=10000);self.processing_queue=SimpleNamespace(maxsize=5000);self.sequence=200;self.invalid=2;self.config=SimpleNamespace(channels=[Channel()]);self.selected_device={"port":"COM9","description":"CP210x","manufacturer":"Silicon Labs","vid":"10C4","pid":"EA60","serial_number":"ABC","hwid":"USB VID:PID=10C4:EA60"};self.recording_id=None;self.processing=SimpleNamespace(config=SimpleNamespace())
    def status(self):return {"connection_state":"STREAMING","serial_port":"COM9","baud_rate":115200,"protocol":"CSV_CHANNELS","channel_count":1,"received_rate_hz":998,"valid_samples":self.sequence,"invalid_packets":self.invalid,"recorder_drops":0,"is_mock":False,"device":self.selected_device,"processing":{"processed_display_drop_count":0,"processing_queue_depth":2,"processing_queue_capacity":5000}}
    def serial_diagnostics(self):return {"bytes_received":12000,"valid_packets":200,"invalid_packets":2,"first_valid_packet_latency_ms":180}
    def baseline_repeatability_report(self,pid,ids):return {"hardware_profile_id":pid,"baseline_ids":ids,"channels":{"channel_1":{"coefficient_of_variation":.02,"warnings":[]}},"warnings":[]}
    def get_baseline(self,bid):return {"baseline_id":bid,"summary":{"channel_1":{"raw_mean":2048,"rms_mean":12}}}


def prepared(tmp_path):
    service=FakeService(tmp_path);store=EmgHardwareValidationStore(tmp_path,service)
    with patch.object(module,"scan_serial_devices",return_value=[{**service.selected_device,"is_usb":True}]):
        run=store.create(ValidationRunCreate(hardware_profile_id=service.profile["hardware_profile_id"],selected_port="COM9"))
    return service,store,run


def pass_steps(store,run_id,*test_ids):
    run=store._read(run_id)
    for test_id in test_ids:run["tests"][test_id]["state"]="PASS"
    store._write(run)


def test_validation_run_persists_identity_and_state(tmp_path):
    service,store,run=prepared(tmp_path);assert run["status"]=="RUNNING";assert run["real_hardware"] is True;assert run["hardware_profile_version"]==1;assert run["tests"]["usb_detection"]["state"]=="NOT_RUN";assert store.get(run["validation_run_id"])["validation_run_id"]==run["validation_run_id"]


def test_usb_and_serial_require_real_detection_and_valid_packets(tmp_path,monkeypatch):
    service,store,run=prepared(tmp_path);monkeypatch.setattr(module,"scan_serial_devices",lambda include_non_usb=False:[{**service.selected_device,"is_usb":True}]);rid=run["validation_run_id"];run=store.start_test(rid,"usb_detection",ValidationTestRequest());assert run["tests"]["usb_detection"]["state"]=="PASS";run=store.start_test(rid,"serial_connection",ValidationTestRequest());assert run["tests"]["serial_connection"]["state"]=="PASS";assert run["tests"]["serial_connection"]["metrics"]["valid_packets"]==200


def test_stream_statistics_and_channel_report_are_saved(tmp_path):
    service,store,run=prepared(tmp_path);rid=run["validation_run_id"];pass_steps(store,rid,"usb_detection","serial_connection");run=store.start_test(rid,"stream",ValidationTestRequest(duration_seconds=1));data=store._read(rid);data["tests"]["stream"]["runtime"]["start_monotonic_ns"]=time.monotonic_ns()-2_000_000_000;data["tests"]["stream"]["runtime"]["start_sequence"]=0;data["tests"]["stream"]["runtime"]["start_valid_samples"]=0;store._write(data);run=store.get(rid);assert run["tests"]["stream"]["state"] in {"PASS","WARNING"};assert run["tests"]["stream"]["metrics"]["median_interval_ms"]==1;run=store.start_test(rid,"channels",ValidationTestRequest());assert run["tests"]["channels"]["metrics"]["channels"]["channel_1"]["display_name"]=="Biceps";assert (store._folder(rid)/"stream_test.json").is_file()


def test_three_baselines_repeatability_and_profile_mismatch(tmp_path):
    service,store,run=prepared(tmp_path);rid=run["validation_run_id"];pass_steps(store,rid,"usb_detection","serial_connection","stream","channels");run=store.start_test(rid,"baseline",ValidationTestRequest(baseline_ids=["B1","B2","B3"]));assert run["tests"]["baseline"]["state"]=="PASS";assert run["tests"]["baseline"]["metrics"]["repeatability"]["channels"]["channel_1"]["coefficient_of_variation"]==.02;service.hardware.version(service.profile["hardware_profile_id"],{**service.profile,"expected_sample_rate_hz":500});match=store.profile_validation(service.profile["hardware_profile_id"]);assert match["configuration_matches"] is False;assert "DIFFERS" in match["warning"]


def test_interruption_reconnect_retry_and_final_report(tmp_path):
    service,store,run=prepared(tmp_path);rid=run["validation_run_id"];pass_steps(store,rid,"review");store.start_test(rid,"interruption",ValidationTestRequest());original=service.status;service.status=lambda:{**original(),"connection_state":"DISCONNECTED"};run=store.get(rid);assert run["tests"]["interruption"]["state"]=="PASS";store.start_test(rid,"reconnect",ValidationTestRequest());service.status=original;run=store.get(rid);assert run["tests"]["reconnect"]["state"]=="PASS";run=store.start_test(rid,"retry",ValidationTestRequest(prior_recording_id="EMG-1",recording_id="EMG-2"));assert run["tests"]["retry"]["state"]=="PASS";run=store.complete(rid);assert run["status"]=="INCOMPLETE";report=json.loads((store._folder(rid)/"final_report.json").read_text());assert report["final_technical_status"]=="INCOMPLETE";assert report["scope_statement"].startswith("THIS IS TECHNICAL");assert store.list(service.profile["hardware_profile_id"])[0]["validation_run_id"]==rid


def test_run_creation_rejects_missing_or_non_usb_hardware(tmp_path,monkeypatch):
    service=FakeService(tmp_path);store=EmgHardwareValidationStore(tmp_path,service)
    monkeypatch.setattr(module,"scan_serial_devices",lambda:[])
    try:store.create(ValidationRunCreate(hardware_profile_id=service.profile["hardware_profile_id"],selected_port="COM3"))
    except ValueError as error:assert "HARDWARE NOT DETECTED" in str(error)
    else:raise AssertionError("A Bluetooth or missing port must not start commissioning")


def test_later_step_is_locked_until_prerequisite_passes(tmp_path):
    _,store,run=prepared(tmp_path)
    try:store.start_test(run["validation_run_id"],"stream",ValidationTestRequest())
    except ValueError as error:assert "serial_connection" in str(error)
    else:raise AssertionError("Stream test must be locked")
