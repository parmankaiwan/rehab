"""TEST DEVICE protocol V2. Does not open serial ports or post to acquisition."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Literal

import numpy as np
from pydantic import BaseModel, Field, model_validator


class ChannelIdentity(BaseModel):
    channel_id: str = Field(pattern=r"^channel_[1-4]$")
    adc_bits: int = Field(12,ge=2,le=24)
    voltage_reference: float = Field(3.3,gt=0,le=10)
    gain: float = Field(1,gt=0)
    offset: float = 0
    physical_coordinate_mm: float | None = None
    normalized_coordinate: float | None = Field(None,ge=-1,le=1)
    units: Literal["ADC_COUNTS","VOLTS","ENVELOPE_UNITS"] = "ADC_COUNTS"


class TestDeviceConfig(BaseModel):
    source_type: Literal["TEST_DEVICE"] = "TEST_DEVICE"
    protocol_version: Literal["FLEXMAP_EMG_V2"] = "FLEXMAP_EMG_V2"
    device_id: str = Field("TEST-DEVICE",pattern=r"^TEST-[A-Za-z0-9_-]+$")
    firmware_version: str = "SIMULATOR-2.0"
    channels: list[ChannelIdentity] = Field(min_length=1,max_length=4)
    sample_rate_hz: int = Field(1000,ge=10,le=4000)
    samples: int = Field(200,ge=20,le=10000)
    seed: int = 42
    fault: Literal["NONE","DROPPED","OUT_OF_ORDER","DUPLICATE","CHANNEL_MISMATCH","TIMESTAMP_DRIFT","TIMING_JITTER","SATURATION","INVALID_NUMERIC","DISCONNECT"] = "NONE"

    @model_validator(mode="after")
    def unique_channels(self):
        if len({c.channel_id for c in self.channels})!=len(self.channels):raise ValueError("Channel IDs must be unique")
        return self


def generate_packets(config):
    rng=np.random.default_rng(config.seed);packets=[];n=len(config.channels)
    for i in range(config.samples):
        stamp=round(i*1e6/config.sample_rate_hz)
        if config.fault=="TIMESTAMP_DRIFT":stamp=round(stamp*1.02)
        if config.fault=="TIMING_JITTER":stamp=max(0,stamp+int(rng.normal(0,60)))
        values=[round(2048+200*np.sin(2*np.pi*(40+j*10)*i/config.sample_rate_hz)) for j in range(n)]
        row={"protocol_version":config.protocol_version,"source_type":"TEST_DEVICE","device_id":config.device_id,"firmware_version":config.firmware_version,"sequence":i,"timestamp_us":stamp,"channel_ids":[c.channel_id for c in config.channels],"values":values,"missing":[False]*n,"clock":"SHARED_SAMPLE_COUNTER","interchannel_skew_us":None}
        if i==config.samples//2:
            if config.fault=="DROPPED":continue
            if config.fault=="CHANNEL_MISMATCH":row["values"]=values[:-1]
            if config.fault=="SATURATION":row["values"]=[2**c.adc_bits-1 for c in config.channels]
            if config.fault=="INVALID_NUMERIC":row["values"]=["NaN"]*n
            if config.fault=="DISCONNECT":
                packets.append(json.dumps({"event":"DISCONNECTED","source_type":"TEST_DEVICE"}));packets.append(json.dumps({"event":"RECONNECTED","source_type":"TEST_DEVICE"}));continue
            if config.fault=="DUPLICATE":packets.append(json.dumps(row))
        packets.append(json.dumps(row))
    if config.fault=="OUT_OF_ORDER":packets[5],packets[6]=packets[6],packets[5]
    return packets


def parse_packet(line,config):
    try:
        row=json.loads(line)
        if row.get("event") in {"DISCONNECTED","RECONNECTED"}:
            if row.get("source_type")!="TEST_DEVICE":raise ValueError("Simulator source mismatch")
            return row
        for key,value in (("protocol_version","FLEXMAP_EMG_V2"),("source_type","TEST_DEVICE"),("device_id",config.device_id)):
            if row.get(key)!=value:raise ValueError(f"Invalid {key}")
        ids=[c.channel_id for c in config.channels]
        if row["channel_ids"]!=ids or len(row["values"])!=len(ids) or len(row["missing"])!=len(ids):raise ValueError("Channel mismatch")
        if not isinstance(row["sequence"],int) or row["sequence"]<0 or not isinstance(row["timestamp_us"],int) or row["timestamp_us"]<0:raise ValueError("Invalid sequence/timestamp")
        if any(not isinstance(m,bool) for m in row["missing"]):raise ValueError("Invalid missing indicator")
        if any(not missing and (not isinstance(v,(int,float)) or not np.isfinite(v)) for v,missing in zip(row["values"],row["missing"])):raise ValueError("Invalid numeric value")
        return row
    except (KeyError,TypeError,json.JSONDecodeError) as exc:raise ValueError("Malformed V2 packet") from exc


def test_stream(config,folder:Path | None=None):
    lines=generate_packets(config);accepted=[];invalid=duplicates=out_of_order=events=clipped=0;last=-1
    for line in lines:
        try:row=parse_packet(line,config)
        except ValueError:invalid+=1;continue
        if "event" in row:events+=1;continue
        if row["sequence"]==last:duplicates+=1;continue
        if row["sequence"]<last:out_of_order+=1;continue
        last=row["sequence"];accepted.append(row)
        clipped+=sum(v<=0 or v>=2**c.adc_bits-1 for v,c in zip(row["values"],config.channels))
    stamps=np.asarray([r["timestamp_us"] for r in accepted]);sequence=np.asarray([r["sequence"] for r in accepted]);delta=np.diff(stamps)
    expected=1e6/config.sample_rate_hz;timing_residual=delta-np.diff(sequence)*expected
    effective=(len(accepted)-1)*1e6/(stamps[-1]-stamps[0]) if len(accepted)>1 else None
    missing=int(np.maximum(np.diff(sequence)-1,0).sum()) if len(sequence)>1 else 0
    waveform={c.channel_id:[None if row["missing"][j] else row["values"][j] for row in accepted] for j,c in enumerate(config.channels)}
    report={"source_type":"TEST_DEVICE","physical_hardware":"NOT TESTED — PHYSICAL HARDWARE REQUIRED","configuration":config.model_dump(),"valid_samples":len(accepted),"invalid_packets":invalid,"duplicate_packets":duplicates,"out_of_order_packets":out_of_order,"sequence_gaps":missing,"disconnect_events":events,"clipped_values":clipped,"effective_delivered_rate_hz":effective,"clock_rate_hz":float((sequence[-1]-sequence[0])*1e6/(stamps[-1]-stamps[0])) if len(sequence)>1 else None,"timing_residual_jitter_us":float(np.std(timing_residual)) if len(delta) else None,"interchannel_skew_us":None,"synchronization_quality":"SIMULATED_SHARED_CLOCK; physical simultaneity unverified","waveform":waveform,"timestamp_us":stamps.tolist(),"calibration":"CONFIGURATION_ONLY; physical calibration NOT TESTED"}
    if folder:
        folder.mkdir(parents=True,exist_ok=True);path=folder/"test_device_recording.json";path.write_text(json.dumps({"metadata":config.model_dump(),"samples":accepted}),encoding="utf-8");raw=path.read_bytes();restored=json.loads(raw)
        report["recording_integrity"]={"sha256":hashlib.sha256(raw).hexdigest(),"samples_retrieved":len(restored["samples"]),"metadata_matches":restored["metadata"]==config.model_dump(),"recording_namespace":"RESEARCH_TEST_DEVICE_ONLY"}
        (folder/"test_device_report.json").write_text(json.dumps(report),encoding="utf-8")
    return report
