from __future__ import annotations
from enum import Enum
from typing import Literal,Optional
from pydantic import BaseModel,Field,field_validator,model_validator
class RecordingState(str,Enum):
 IDLE="IDLE";CONFIGURED="CONFIGURED";COUNTDOWN="COUNTDOWN";RECORDING="RECORDING";FINALIZING="FINALIZING";REVIEW="REVIEW";SAVING="SAVING";SAVED="SAVED";DISCARDED="DISCARDED";ERROR="ERROR"
class RecordingConfiguration(BaseModel):
 rehab_type:str=Field(min_length=1,max_length=64);rehab_slug:Optional[str]=Field(default=None,max_length=64);subject_id:str=Field(min_length=1,max_length=64,pattern=r"^[A-Za-z0-9_-]+$");category:str=Field(min_length=1,max_length=64);label:str=Field(min_length=1,max_length=96);duration_seconds:float=Field(gt=0);countdown_seconds:Literal[3,5]=3;manual_stop:bool=False;affected_side:Optional[str]=Field(default=None,pattern=r"^(LEFT|RIGHT)$");view:str=Field(default="Front",max_length=40);notes:str=Field(default="",max_length=2000);session_id:Optional[str]=Field(default=None,max_length=80);exercise_id:Optional[str]=Field(default=None,max_length=80);study_id:Optional[str]=Field(default=None,max_length=80);collection_id:Optional[str]=Field(default=None,max_length=80);protocol_id:Optional[str]=Field(default=None,max_length=80);protocol_version:Optional[int]=Field(default=None,ge=1);protocol_snapshot:Optional[dict]=None;trial_id:Optional[str]=Field(default=None,max_length=100);trial_number:int=Field(default=1,ge=1);attempt_number:int=Field(default=1,ge=1);sync_group_id:Optional[str]=Field(default=None,max_length=100);sync_status:str="NOT_CONFIGURED";preflight_snapshot:Optional[dict]=None;store_raw_video:bool=True;store_annotated_video:bool=True;store_preview_image:bool=True;consent_recorded:bool=False;label_source:str="MASTER_MANUAL"
 @field_validator("subject_id","category","label","view",mode="before")
 @classmethod
 def strip_text(cls,value):return value.strip() if isinstance(value,str) else value
 @model_validator(mode="after")
 def consent(self):
  if not self.consent_recorded:raise ValueError("Documented research recording consent is required")
  return self
class RecordingStatus(BaseModel):
 state:RecordingState;recording_id:Optional[str]=None;elapsed_seconds:float=0;remaining_seconds:float=0;countdown_seconds:int=3;countdown_remaining:int=0;recording_start_timestamp_ns:Optional[int]=None;frame_count:int=0;pose_result_count:int=0;error:Optional[str]=None;review:Optional[dict]=None
class DatasetUpdate(BaseModel):
 category:Optional[str]=None;label:Optional[str]=None;notes:Optional[str]=Field(default=None,max_length=2000)
 @model_validator(mode="after")
 def not_empty(self):
  if self.category is None and self.label is None and self.notes is None:raise ValueError("No update supplied")
  return self
class RehabAssignment(BaseModel):
 rehab_type:str;label:str;confirm:bool=False
class ExclusionUpdate(BaseModel):
 excluded:bool;reason:Optional[str]=Field(default=None,max_length=500)
 @model_validator(mode="after")
 def reason_required(self):
  if self.excluded and not self.reason:raise ValueError("Exclusion reason is required")
  return self
class BatchConfiguration(BaseModel):recordings:int=Field(default=1,ge=1,le=100);rest_seconds:float=Field(default=3,ge=0,le=300);review_each:bool=True
