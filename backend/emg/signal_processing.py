from __future__ import annotations

import hashlib
import json
import math
from collections import deque
from typing import Literal

import numpy as np
from pydantic import BaseModel, ConfigDict, Field, model_validator
from scipy.signal import butter, iirnotch, sosfilt, tf2sos

PROCESSING_PIPELINE_VERSION = "3.0.0"


class EmgProcessingConfig(BaseModel):
    model_config = ConfigDict(allow_inf_nan=False)
    enabled: bool = False
    processing_sample_rate_hz: float = Field(default=1000, gt=0, le=20_000)
    sample_rate_source: Literal["DEVICE_CONFIGURED", "DEVICE_TIMESTAMP_ESTIMATED", "HOST_RATE_ESTIMATED"] = "DEVICE_CONFIGURED"
    dc_removal_enabled: bool = True
    bandpass_enabled: bool = True
    bandpass_low_hz: float = Field(default=20, gt=0)
    bandpass_high_hz: float = Field(default=450, gt=0)
    bandpass_order: int = Field(default=4, ge=1, le=10)
    notch_enabled: bool = False
    notch_frequency_hz: float = Field(default=50, gt=0)
    notch_q: float = Field(default=30, gt=0)
    rectification_enabled: bool = True
    rms_enabled: bool = True
    rms_window_ms: float = Field(default=100, gt=0, le=5000)
    envelope_enabled: bool = False
    envelope_lowpass_hz: float = Field(default=5, gt=0)
    processing_version: str = PROCESSING_PIPELINE_VERSION

    @model_validator(mode="after")
    def validate_dsp(self):
        nyquist = self.processing_sample_rate_hz / 2
        if self.bandpass_enabled:
            if self.bandpass_low_hz >= self.bandpass_high_hz:
                raise ValueError("Low cutoff must be below high cutoff.")
            if self.bandpass_high_hz >= nyquist:
                raise ValueError("High cutoff must be below Nyquist frequency.")
        if self.notch_enabled and self.notch_frequency_hz >= nyquist:
            raise ValueError("Notch frequency must be below Nyquist frequency.")
        if self.envelope_enabled and self.envelope_lowpass_hz >= nyquist:
            raise ValueError("Envelope cutoff must be below Nyquist frequency.")
        return self

    @property
    def hash(self) -> str:
        payload=json.dumps(self.model_dump(),sort_keys=True,separators=(",",":"))
        return hashlib.sha256(payload.encode()).hexdigest()


class ChannelProcessor:
    def __init__(self, config: EmgProcessingConfig):
        self.config=config;fs=config.processing_sample_rate_hz
        self.main_sos=None;self.main_zi=None;self.notch_sos=None;self.notch_zi=None;self.envelope_sos=None;self.envelope_zi=None
        if config.bandpass_enabled:
            self.main_sos=butter(config.bandpass_order,[config.bandpass_low_hz,config.bandpass_high_hz],btype="bandpass",fs=fs,output="sos")
        elif config.dc_removal_enabled:
            self.main_sos=butter(2,0.5,btype="highpass",fs=fs,output="sos")
        if self.main_sos is not None:self.main_zi=np.zeros((len(self.main_sos),2))
        if config.notch_enabled:
            b,a=iirnotch(config.notch_frequency_hz,config.notch_q,fs);self.notch_sos=tf2sos(b,a);self.notch_zi=np.zeros((len(self.notch_sos),2))
        if config.envelope_enabled:
            self.envelope_sos=butter(2,config.envelope_lowpass_hz,btype="lowpass",fs=fs,output="sos");self.envelope_zi=np.zeros((len(self.envelope_sos),2))
        self.rms_window=max(1,round(fs*config.rms_window_ms/1000));self.squares=deque(maxlen=self.rms_window);self.square_sum=0.0

    def process_batch(self, raws: list[float]) -> list[dict[str,float|None]]:
        array=np.asarray(raws,dtype=float);filtered=array.copy()
        if not np.isfinite(array).all():raise ValueError("EMG processing requires finite raw samples")
        if self.main_sos is not None:filtered,self.main_zi=sosfilt(self.main_sos,filtered,zi=self.main_zi)
        if self.notch_sos is not None:filtered,self.notch_zi=sosfilt(self.notch_sos,filtered,zi=self.notch_zi)
        rectified=np.abs(filtered);rms=[]
        for value in filtered:
            square=float(value*value)
            if len(self.squares)==self.squares.maxlen:self.square_sum-=self.squares[0]
            self.squares.append(square);self.square_sum+=square;rms.append(math.sqrt(self.square_sum/len(self.squares)))
        envelopes=[None]*len(array)
        if self.envelope_sos is not None:
            values,self.envelope_zi=sosfilt(self.envelope_sos,rectified,zi=self.envelope_zi);envelopes=[float(x) for x in values]
        return [{"raw":float(raw),"filtered":float(filt),"rectified":float(rect),"rms":float(rms_value),"envelope":env} for raw,filt,rect,rms_value,env in zip(array,filtered,rectified,rms,envelopes)]
    def process(self, raw: float) -> dict[str,float|None]:
        if not math.isfinite(raw):raise ValueError("EMG processing requires finite raw samples")
        filtered=float(raw)
        if self.main_sos is not None:
            y,self.main_zi=sosfilt(self.main_sos,[filtered],zi=self.main_zi);filtered=float(y[0])
        if self.notch_sos is not None:
            y,self.notch_zi=sosfilt(self.notch_sos,[filtered],zi=self.notch_zi);filtered=float(y[0])
        rectified=abs(filtered)
        square=filtered*filtered
        if len(self.squares)==self.squares.maxlen:self.square_sum-=self.squares[0]
        self.squares.append(square);self.square_sum+=square
        rms=math.sqrt(self.square_sum/len(self.squares))
        envelope=None
        if self.envelope_sos is not None:
            y,self.envelope_zi=sosfilt(self.envelope_sos,[rectified],zi=self.envelope_zi);envelope=float(y[0])
        return {"raw":float(raw),"filtered":filtered,"rectified":rectified,"rms":rms,"envelope":envelope}


class EmgProcessingPipeline:
    def __init__(self,config:EmgProcessingConfig|None=None):
        self.config=config or EmgProcessingConfig();self.processors:dict[str,ChannelProcessor]={};self.error: str|None=None;self.processed_display_drop_count=0
    def apply(self,config:EmgProcessingConfig):self.config=config;self.reset()
    def reset(self):self.processors={};self.error=None
    def process(self,sample:dict)->dict|None:
        if not self.config.enabled:return None
        try:
            channels={}
            for key,raw in sample["channels"].items():
                if key not in self.processors:self.processors[key]=ChannelProcessor(self.config)
                channels[key]=self.processors[key].process(float(raw))
            return {"sequence_id":sample["sequence_id"],"host_timestamp_ns":sample["host_timestamp_ns"],"channels":channels,"processing_version":self.config.processing_version,"config_hash":self.config.hash}
        except Exception as exc:
            self.error=f"PROCESSING DISABLED: {exc}";self.config=self.config.model_copy(update={"enabled":False});self.reset();self.error=f"PROCESSING DISABLED: {exc}";return None

    def process_batch(self,samples:list[dict])->list[dict]:
        if not self.config.enabled or not samples:return []
        try:
            keys=list(samples[0]["channels"]);by_channel={}
            for key in keys:
                if key not in self.processors:self.processors[key]=ChannelProcessor(self.config)
                by_channel[key]=self.processors[key].process_batch([float(sample["channels"][key]) for sample in samples])
            return [{"sequence_id":sample["sequence_id"],"host_timestamp_ns":sample["host_timestamp_ns"],"channels":{key:by_channel[key][index] for key in keys},"processing_version":self.config.processing_version,"config_hash":self.config.hash} for index,sample in enumerate(samples)]
        except Exception as exc:
            self.error=f"PROCESSING DISABLED: {exc}";self.config=self.config.model_copy(update={"enabled":False});self.processors={};return []
    def process_rows(self,rows:list[dict])->list[dict]:
        self.reset();result=[]
        for start in range(0,len(rows),256):result.extend(self.process_batch(rows[start:start+256]))
        return result
