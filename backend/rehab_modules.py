from __future__ import annotations
import json,re
from dataclasses import dataclass
from pathlib import Path
from typing import Any
SAFE_SLUG=re.compile(r"^[a-z][a-z0-9_]{1,63}$")
def options(values):return tuple((str(x["id"]),str(x.get("display_name",x["id"]))) if isinstance(x,dict) else (str(x),str(x).replace("_"," ").title()) for x in values)
@dataclass(frozen=True)
class RehabModule:
 id:str;slug:str;name:str;description:str;enabled:bool;display_order:int;labels:tuple[str,...];label_options:tuple[tuple[str,str],...];emg_labels:tuple[str,...];emg_label_options:tuple[tuple[str,str],...]
 def as_dict(self)->dict[str,Any]:return {"id":self.id,"slug":self.slug,"name":self.name,"display_name":self.name,"description":self.description,"enabled":self.enabled,"display_order":self.display_order,"labels":list(self.labels),"label_options":[{"id":x,"display_name":y} for x,y in self.label_options],"emg_labels":list(self.emg_labels),"emg_label_options":[{"id":x,"display_name":y} for x,y in self.emg_label_options],"model_scope":self.id}
class RehabModuleRegistry:
 def __init__(self,path:Path):
  data=json.loads(path.read_text(encoding="utf-8"));items=data.get("modules",[]);modules=[]
  for index,x in enumerate(items):
   cv=options(x["labels"]);emg=options(x.get("emg_labels",x["labels"]))
   modules.append(RehabModule(str(x["id"]),str(x["slug"]),str(x.get("display_name",x.get("name",x["id"]))),str(x["description"]),bool(x.get("enabled",True)),int(x.get("display_order",index+1)),tuple(a for a,_ in cv),cv,tuple(a for a,_ in emg),emg))
  self.modules=tuple(sorted(modules,key=lambda m:m.display_order));ids=[x.id for x in self.modules];slugs=[x.slug for x in self.modules];orders=[x.display_order for x in self.modules]
  if not self.modules or len(ids)!=len(set(ids)) or len(slugs)!=len(set(slugs)) or len(orders)!=len(set(orders)):raise ValueError("Rehab module IDs, slugs, and display order must be unique")
  if any(not SAFE_SLUG.fullmatch(x.slug) or not x.id.replace("_","").isalnum() or x.id!=x.id.upper() or not x.labels or not x.emg_labels or len(x.labels)!=len(set(x.labels)) or len(x.emg_labels)!=len(set(x.emg_labels)) for x in self.modules):raise ValueError("Unsafe or invalid rehab module configuration")
 def by_id(self,value:str)->RehabModule:
  module=next((x for x in self.modules if x.id==value),None)
  if not module:raise ValueError("Unknown rehab type")
  return module
 def by_slug(self,value:str)->RehabModule:
  if not SAFE_SLUG.fullmatch(value):raise ValueError("Unknown rehab module")
  module=next((x for x in self.modules if x.slug==value),None)
  if not module:raise ValueError("Unknown rehab module")
  return module
 def validate_label(self,rehab_type:str,label:str,require_enabled:bool=True)->RehabModule:
  module=self.by_id(rehab_type)
  if require_enabled and not module.enabled:raise ValueError("Rehab module is archived")
  if label not in module.labels:raise ValueError("Research label does not belong to selected rehab type")
  return module
 def validate_emg_label(self,rehab_type:str,label:str,require_enabled:bool=True)->RehabModule:
  module=self.by_id(rehab_type)
  if require_enabled and not module.enabled:raise ValueError("Rehab module is archived")
  if label not in module.emg_labels:raise ValueError("EMG research label does not belong to selected rehab type")
  return module