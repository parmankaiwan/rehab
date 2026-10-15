from typing import Literal,Optional
from pydantic import BaseModel,Field,model_validator
class ChannelConfig(BaseModel):
 internal_id:str=Field(pattern=r"^channel_[1-4]$");display_name:str=Field(min_length=1,max_length=40);muscle_label:Optional[str]=Field(default=None,max_length=64);body_side:Optional[Literal["LEFT","RIGHT","UNKNOWN","N/A"]]=None;electrode_configuration:Optional[str]=Field(default=None,max_length=120);placement_notes:Optional[str]=Field(default=None,max_length=500);skin_prep_notes:Optional[str]=Field(default=None,max_length=500);sensor_type:Optional[str]=Field(default=None,max_length=80);electrode_spacing_mm:Optional[float]=Field(default=None,gt=0,le=200);electrode_orientation:Optional[str]=Field(default=None,max_length=120);placement_landmark_notes:Optional[str]=Field(default=None,max_length=500);reference_electrode_location:Optional[str]=Field(default=None,max_length=200);sensor_attachment_notes:Optional[str]=Field(default=None,max_length=500);electrode_protocol_id:Optional[str]=Field(default=None,max_length=100)
class ConnectRequest(BaseModel):
 transport_type:Literal["USB_SERIAL","MOCK"]="USB_SERIAL";mock_scenario:Literal["CLEAN_EMG_LIKE","POWERLINE_50HZ","POWERLINE_60HZ","FLATLINE","CLIPPING","PERFECT_CLOCK","JITTER","SEQUENCE_GAPS","DUPLICATES","CLOCK_DRIFT","BURST_DELIVERY","10_BIT_NORMAL","12_BIT_NORMAL","SIGNED_16_BIT","OUT_OF_RANGE","LOW_DYNAMIC_RANGE","STABLE","VARIABLE","DRIFT"]="CLEAN_EMG_LIKE";serial_port:Optional[str]=Field(default=None,max_length=100);baud_rate:int=Field(default=115200,ge=1200,le=3000000);protocol:Literal["VALUE_ONLY","TIMESTAMP_VALUE","CSV_CHANNELS","TIMESTAMP_CSV_CHANNELS","SEQUENCE_TIMESTAMP_CSV"]="CSV_CHANNELS";expected_sample_rate_hz:float=Field(default=1000,gt=0,le=10000);channels:list[ChannelConfig]=Field(min_length=1,max_length=4);adc_bits:Optional[int]=Field(default=None,ge=1,le=32)
 @model_validator(mode="after")
 def unique(self):
  if len({x.internal_id for x in self.channels})!=len(self.channels):raise ValueError("Channel IDs must be unique")
  if self.transport_type=="USB_SERIAL" and not self.serial_port:raise ValueError("Serial port is required")
  return self
class RecordingRequest(BaseModel):
 rehab_type:str;subject_id:str=Field(pattern=r"^[A-Za-z0-9_-]+$");research_label:str;duration_seconds:float=Field(gt=0,le=3600);countdown_seconds:int=Field(default=3,ge=0,le=10);manual_stop:bool=False;affected_side:Literal["LEFT","RIGHT","UNKNOWN","N/A"]="UNKNOWN";session_id:Optional[str]=None;study_id:Optional[str]=None;collection_id:Optional[str]=None;protocol_id:Optional[str]=None;protocol_version:Optional[int]=Field(default=None,ge=1);protocol_snapshot:Optional[dict]=None;trial_id:Optional[str]=None;trial_number:int=Field(default=1,ge=1);attempt_number:int=Field(default=1,ge=1);sync_group_id:Optional[str]=None;sync_status:str="NOT_CONFIGURED";preflight_snapshot:Optional[dict]=None;notes:str=Field(default="",max_length=2000);hardware_profile_id:Optional[str]=None;hardware_profile_version:Optional[int]=Field(default=None,ge=1);channel_map_snapshot:Optional[dict]=None;electrode_metadata:Optional[dict]=None;placement_notes:Optional[str]=None;consent_recorded:bool=False;sync_event_id:Optional[str]=None;baseline_id:Optional[str]=None;baseline_group_id:Optional[str]=None;validation_recording:bool=False;validation_run_id:Optional[str]=None
 @model_validator(mode="after")
 def consent(self):
  if not self.consent_recorded:raise ValueError("Documented research recording consent is required")
  return self
class BaselineRequest(BaseModel):
 rehab_type:str;subject_id:str=Field(pattern=r"^[A-Za-z0-9_-]+$");duration_seconds:float=Field(default=5,ge=1,le=60);session_id:Optional[str]=None;collection_id:Optional[str]=None;protocol_id:Optional[str]=None;protocol_version:Optional[int]=Field(default=None,ge=1);baseline_group_id:Optional[str]=None;baseline_number:Optional[int]=Field(default=None,ge=1);hardware_profile_id:Optional[str]=None;hardware_profile_version:Optional[int]=Field(default=None,ge=1);channel_map_snapshot:Optional[dict]=None;notes:str=Field(default="",max_length=1000)
class RecordingMarkerRequest(BaseModel):
 event_type:Literal["MOVEMENT_STARTED","TARGET_REACHED","MOVEMENT_ENDED","SENSOR_ISSUE","CUSTOM"];notes:str=Field(default="",max_length=500)
class HardwareProfileRequest(BaseModel):
 display_name:str=Field(min_length=1,max_length=120);manufacturer:Optional[str]=None;device_model:Optional[str]=None;microcontroller:Optional[str]=None;transport_type:Literal["USB_SERIAL","MOCK","OTHER"]="USB_SERIAL";serial_baud_rate:Optional[int]=Field(default=None,ge=1200,le=3000000);protocol:Optional[str]=None;channel_count:int=Field(ge=1,le=4);expected_sample_rate_hz:float=Field(gt=0,le=10000);device_timestamp_supported:bool=False;device_timestamp_unit:Optional[Literal["NANOSECONDS","MICROSECONDS","MILLISECONDS","SECONDS","SAMPLE_TICKS","UNKNOWN"]]=None;device_sequence_supported:bool=False;device_sequence_modulus:Optional[int]=Field(default=None,gt=1);adc_bits:Optional[int]=Field(default=None,ge=1,le=32);adc_min_count:Optional[float]=None;adc_max_count:Optional[float]=None;adc_reference_voltage_v:Optional[float]=Field(default=None,gt=0);adc_zero_code:Optional[float]=None;analog_frontend_gain:Optional[float]=Field(default=None,gt=0);analog_frontend_offset_v:Optional[float]=None;sensor_output_type:Optional[str]=None;raw_representation:Literal["ADC_COUNTS_UNSIGNED","ADC_COUNTS_SIGNED","MILLIVOLTS","MICROVOLTS","CUSTOM"]="CUSTOM";electrode_type:Optional[str]=None;mains_frequency_hz:Optional[Literal[50,60]]=None;usb_vid:Optional[str]=None;usb_pid:Optional[str]=None;device_serial_number:Optional[str]=None;hardware_description:Optional[str]=None;notes:Optional[str]=None;is_mock:bool=False

class QualityProfileRequest(BaseModel):
 hardware_profile_id:str;quality_profile_id:Optional[str]=None;settings:dict;source_rationale:str=Field(min_length=1,max_length=1000);status:Literal["DEVELOPMENT","VALIDATED_FOR_HARDWARE_TESTING","ARCHIVED"]="DEVELOPMENT"

class ValidationRequest(BaseModel):
 hardware_profile_id:str;notes:str=Field(default="",max_length=2000)

class BaselineRepeatabilityRequest(BaseModel):
 hardware_profile_id:str;baseline_ids:list[str]=Field(min_length=2,max_length=10)
