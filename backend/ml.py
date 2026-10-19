from __future__ import annotations
import csv,hashlib,json,os,platform,random,shutil,sqlite3,sys,traceback
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime,timezone
from pathlib import Path
from typing import Literal
import joblib,numpy as np,sklearn
from fastapi import APIRouter,Depends,HTTPException,Query
from fastapi.responses import FileResponse,Response
from pydantic import BaseModel,ConfigDict,Field
from sklearn.ensemble import RandomForestClassifier
from sklearn.impute import SimpleImputer
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import accuracy_score,balanced_accuracy_score,classification_report,confusion_matrix,f1_score,precision_score,recall_score
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler
from .dataset_config import dataset_settings
from .master_dataset_api import browser_collections,require_master,vault
from .supabase_vault import SupabaseVaultError,SupabaseVaultMirror
from .emg.cloud_vault import EmgCloudVault
from .ml_cloud import MlCloudRepository
from .ml_features import CV_FEATURES_V2,EMG_FEATURES_V2,extract_cv_features,extract_emg_features,parse_pose_observations

ML_DATA_ROOT=Path(os.getenv("FLEXMAP_ML_DATA_ROOT",Path(__file__).resolve().parent.parent/"data"/"ml")).resolve();ML_DATA_ROOT.mkdir(parents=True,exist_ok=True)
DB_PATH=dataset_settings().database_path
router=APIRouter(prefix="/api/master/ml",tags=["Master Machine Learning"],dependencies=[Depends(require_master)])
supabase_vault=SupabaseVaultMirror()
cloud_emg_vault=EmgCloudVault()
ml_cloud=MlCloudRepository()
def utcnow():return datetime.now(timezone.utc).isoformat()
def canonical(value):return json.dumps(value,sort_keys=True,separators=(",",":"),ensure_ascii=False).encode()
def connect():
 db=sqlite3.connect(DB_PATH,timeout=20,check_same_thread=False);db.row_factory=sqlite3.Row;return db
def initialize():
 with connect() as db:db.executescript("""
 CREATE TABLE IF NOT EXISTS ml_dataset_versions(dataset_version_id TEXT PRIMARY KEY,name TEXT NOT NULL,status TEXT NOT NULL,rehab_type TEXT NOT NULL,modality TEXT NOT NULL,recording_ids_json TEXT NOT NULL,source_query_json TEXT NOT NULL,label_distribution_json TEXT NOT NULL,subject_distribution_json TEXT NOT NULL,quality_distribution_json TEXT NOT NULL,health_json TEXT NOT NULL,manifest_sha256 TEXT,created_at TEXT NOT NULL,created_by TEXT NOT NULL,mock_included INTEGER NOT NULL DEFAULT 0);
 CREATE TABLE IF NOT EXISTS ml_feature_pipelines(feature_pipeline_id TEXT PRIMARY KEY,name TEXT NOT NULL,modality TEXT NOT NULL,version TEXT NOT NULL,config_json TEXT NOT NULL,source_fields_json TEXT NOT NULL,created_at TEXT NOT NULL,code_version TEXT NOT NULL);
 CREATE TABLE IF NOT EXISTS ml_splits(split_id TEXT PRIMARY KEY,dataset_version_id TEXT NOT NULL,strategy TEXT NOT NULL,seed INTEGER NOT NULL,config_json TEXT NOT NULL,assignments_json TEXT NOT NULL,leakage_json TEXT NOT NULL,created_at TEXT NOT NULL);
 CREATE TABLE IF NOT EXISTS ml_training_runs(training_run_id TEXT PRIMARY KEY,dataset_version_id TEXT NOT NULL,manifest_sha256 TEXT NOT NULL,feature_pipeline_id TEXT NOT NULL,split_id TEXT NOT NULL,task TEXT NOT NULL,model_type TEXT NOT NULL,model_config_json TEXT NOT NULL,status TEXT NOT NULL,stage TEXT NOT NULL,progress REAL NOT NULL,created_at TEXT NOT NULL,started_at TEXT,completed_at TEXT,error TEXT,evaluation_scope TEXT NOT NULL,metrics_json TEXT,feature_importance_json TEXT,artifact_dir TEXT NOT NULL,cancel_requested INTEGER NOT NULL DEFAULT 0);
 CREATE TABLE IF NOT EXISTS ml_model_registry(model_id TEXT PRIMARY KEY,version INTEGER NOT NULL,training_run_id TEXT NOT NULL,dataset_version_id TEXT NOT NULL,manifest_sha256 TEXT NOT NULL,split_id TEXT NOT NULL,feature_pipeline_id TEXT NOT NULL,task TEXT NOT NULL,model_type TEXT NOT NULL,status TEXT NOT NULL,created_at TEXT NOT NULL,notes TEXT NOT NULL);""")
 with connect() as db:
  db.execute("UPDATE ml_training_runs SET status='FAILED',stage='INTERRUPTED',completed_at=?,error=COALESCE(error,'Backend restarted before training completed') WHERE status='RUNNING'",(utcnow(),))
initialize()

class DatasetFromVault(BaseModel):
 recording_ids:list[str]=Field(min_length=1,max_length=10000);name:str=Field(min_length=2,max_length=100);source_query:dict=Field(default_factory=dict);allow_mock:bool=False
class SplitRequest(BaseModel):
 dataset_version_id:str;strategy:Literal["SUBJECT_GROUPED_HOLDOUT","GROUP_K_FOLD"]="SUBJECT_GROUPED_HOLDOUT";train_ratio:float=Field(default=.70,gt=0,lt=1);validation_ratio:float=Field(default=.15,ge=0,lt=1);test_ratio:float=Field(default=.15,gt=0,lt=1);seed:int=42;folds:int=Field(default=5,ge=2,le=20);development_only:bool=False
class RunRequest(BaseModel):
 model_config=ConfigDict(populate_by_name=True)
 dataset_version_id:str;split_id:str;task:Literal["RESEARCH_LABEL_CLASSIFICATION"]="RESEARCH_LABEL_CLASSIFICATION";feature_pipeline_id:str;model_type:Literal["LOGISTIC_REGRESSION","RANDOM_FOREST"];hyperparameters:dict=Field(default_factory=dict,alias="model_config");warnings_acknowledged:bool=False
class RegisterRequest(BaseModel):
 training_run_id:str;status:Literal["EXPERIMENTAL","VALIDATED"]="EXPERIMENTAL";notes:str=Field(default="",max_length=2000)
def rowdict(row):
 if not row:return None
 result=dict(row)
 for key in tuple(result):
  if key.endswith("_json"):result[key[:-5]]=json.loads(result.pop(key) or "null")
 for key in ("mock_included","cancel_requested"):
  if key in result:result[key]=bool(result[key])
 return result
def emg_service():
 from .emg.api import service
 return service
def _cloud_cv(recording_id):
 try:item=browser_collections.get_sample(recording_id,include_trashed=True)
 except (SupabaseVaultError,FileNotFoundError):return None
 if not item:return None
 metadata=item.get("metadata") or {};label=item.get("reviewed_label") or item.get("label_at_capture")
 return {**item,"recording_id":item["sample_id"],"modality":"CV","research_label":label,"label":label,"subject_id":item.get("subject_id"),"rehab_type":metadata.get("rehabilitation_module_id") or metadata.get("rehab_type") or item.get("dataset_id"),"is_mock":bool(metadata.get("is_mock") or metadata.get("synthetic")),"deleted_at":item.get("trashed_at"),"artifact_references":item.get("artifact_manifest") or [],"schema_versions":{"dataset":metadata.get("schema_version"),"cv":metadata.get("software_version")},"source_backend":"SUPABASE_CV"}
def _cloud_emg(recording_id):
 try:item=cloud_emg_vault.get_recording(recording_id)
 except (SupabaseVaultError,FileNotFoundError):return None
 metadata=item.get("metadata") or {}
 return {**item,"modality":"EMG","subject_id":item.get("subject_id") or item.get("subject_code"),"category":item.get("rehab_type") or item.get("dataset_id"),"deleted_at":item.get("trashed_at"),"is_mock":bool(item.get("is_mock") or metadata.get("is_mock") or metadata.get("synthetic")),"artifact_references":item.get("artifacts") or [],"schema_versions":{"dataset":metadata.get("dataset_schema_version"),"emg":metadata.get("emg_schema_version")},"source_backend":"SUPABASE_EMG"}
def unified_recording(recording_id):
 if recording_id.startswith("SMP-"):return _cloud_cv(recording_id)
 if recording_id.startswith("REC-"):
  item=vault.get(recording_id)
  if not item:return None
  metadata=item.get("metadata",{})
  return {**item,"modality":"CV","research_label":item.get("label"),"is_mock":bool(metadata.get("is_mock",False)),"artifact_references":metadata.get("artifacts",{}),"schema_versions":{"dataset":item.get("dataset_schema_version"),"cv":metadata.get("software_version")}}
 if recording_id.startswith("EMG-"):
  item=emg_service().get(recording_id)
  if not item:return _cloud_emg(recording_id)
  metadata=item.get("metadata",{});manifest={};base=dataset_settings().root/item["relative_path"]
  if (base/"artifact_manifest.json").is_file():manifest=json.loads((base/"artifact_manifest.json").read_text(encoding="utf-8"))
  return {**item,"modality":"EMG","category":item.get("rehab_type"),"label":item.get("research_label"),"review_status":"APPROVED" if item.get("training_eligible") else "NOT_ELIGIBLE","artifact_references":manifest,"schema_versions":{"dataset":metadata.get("dataset_schema_version"),"emg":metadata.get("emg_schema_version")}}
 return None
def _artifact_entry(item,name):
 refs=item.get("artifact_references") or []
 if isinstance(refs,dict):
  direct=refs.get(name)
  if isinstance(direct,dict):return {"name":name,**direct}
  for key,value in refs.items():
   if Path(str(key)).name==name and isinstance(value,dict):return {"name":name,**value}
 else:
  for entry in refs:
   candidate=entry.get("name") or Path(str(entry.get("object_path") or "")).name
   if candidate==name:return entry
 return None
def artifact_bytes(item,name):
 source=item.get("source_backend")
 if source=="SUPABASE_CV":content,status,_=browser_collections.artifact(item["recording_id"],name)
 elif source=="SUPABASE_EMG":
  entry=_artifact_entry(item,name)
  if not entry:raise FileNotFoundError(name)
  content,status,_=cloud_emg_vault.read_artifact(item["recording_id"],str(entry["artifact_id"]))
 else:
  content=(recording_path(item)/name).read_bytes();status=200
 if status not in (200,206):raise RuntimeError(f"Artifact read failed ({status})")
 expected=(_artifact_entry(item,name) or {}).get("sha256")
 actual=hashlib.sha256(content).hexdigest()
 if expected and len(str(expected))==64 and expected!=actual:raise RuntimeError(f"Artifact checksum mismatch: {name}")
 return content
def artifact_hashes(item):
 required=("pose_observations.jsonl","pose_observations.json") if item["modality"]=="CV" and item.get("source_backend")=="SUPABASE_CV" else (("measurements.json",) if item["modality"]=="CV" else ("emg_raw.csv",))
 hashes={}
 for name in required:
  try:content=artifact_bytes(item,name)
  except FileNotFoundError:continue
  hashes[name]=hashlib.sha256(content).hexdigest()
 if not hashes:raise FileNotFoundError(required[0])
 return hashes
def eligibility(item,allow_mock=False):
 if item.get("deleted_at") or item.get("review_status") in ("DELETED","TRASHED"):return False,"TRASHED"
 if item.get("excluded"):return False,"MANUALLY_EXCLUDED"
 if item.get("is_mock") and not allow_mock:return False,"MOCK_DATA"
 if not item.get("research_label"):return False,"MISSING_LABEL"
 if not item.get("subject_id"):return False,"MISSING_SUBJECT"
 if str(item.get("technical_quality") or "").upper() in ("INVALID","FAILED","UNUSABLE"):return False,"INTEGRITY_INVALID"
 if item.get("source_backend") and item.get("persistence_status")!="STORED":return False,"SOURCE_NOT_STORED"
 if item.get("review_status")!="APPROVED":return False,"REVIEW_NOT_APPROVED"
 if not item.get("training_eligible"):return False,"NOT_TRAINING_ELIGIBLE"
 try:artifact_hashes(item)
 except (FileNotFoundError,RuntimeError,SupabaseVaultError) as exc:return False,f"ARTIFACT_NOT_VERIFIED: {exc}"
 return True,"ELIGIBLE"
def public_record(item):
 allowed,reason=eligibility(item);metadata=item.get("metadata",{})
 return {"recording_id":item["recording_id"],"subject_id":item.get("subject_id"),"session_id":item.get("session_id"),"study_id":item.get("study_id") or metadata.get("study_id"),"collection_id":item.get("collection_id") or metadata.get("collection_id"),"protocol_id":item.get("protocol_id") or metadata.get("protocol_id"),"rehab_type":item.get("rehab_type") or item.get("category"),"modality":item["modality"],"research_label":item.get("research_label"),"affected_side":item.get("affected_side"),"review_status":item.get("review_status"),"technical_quality":item.get("technical_quality"),"training_eligible":allowed,"eligibility_reason":reason,"is_mock":bool(item.get("is_mock")),"created_at":item.get("created_at")}

def recording_path(item):
 base=(dataset_settings().root/item["relative_path"]).resolve();root=dataset_settings().root.resolve()
 if not base.is_relative_to(root):raise ValueError("Unsafe Dataset Vault path")
 return base

def all_vault_recordings():
 items=[unified_recording(x["recording_id"]) for x in vault.list()]
 for module in emg_service().registry.modules:items.extend(unified_recording(x["recording_id"]) for x in emg_service().list(module.slug,""))
 if browser_collections.config.configured:
  try:
   for dataset in browser_collections.list_datasets():
    detail=browser_collections.get_dataset(dataset["dataset_id"]) or {}
    items.extend(_cloud_cv(x["sample_id"]) for x in detail.get("samples",[]))
  except SupabaseVaultError:pass
 if cloud_emg_vault.config.configured:
  try:items.extend(_cloud_emg(x["recording_id"]) for x in cloud_emg_vault.list_recordings())
  except SupabaseVaultError:pass
 deduplicated={item["recording_id"]:item for item in items if item}
 return list(deduplicated.values())

def require_supabase_vault():
 status=supabase_vault.public_status()
 if not status["configured"]:raise HTTPException(503,"Supabase vault is not configured")
 if not status["enabled"]:raise HTTPException(409,"Supabase vault sync is disabled")

@router.get("/supabase/status")
def supabase_status(check:bool=False):return supabase_vault.check_connection() if check else supabase_vault.public_status()
@router.get("/durable-storage/status")
def durable_storage_status():return ml_cloud.public_status()

@router.post("/supabase/sync")
def sync_supabase_vault():
 require_supabase_vault();items=all_vault_recordings()
 return supabase_vault.sync_many((item,recording_path(item)) for item in items)

@router.post("/supabase/sync/{recording_id}")
def sync_supabase_recording(recording_id:str):
 require_supabase_vault();item=unified_recording(recording_id)
 if not item:raise HTTPException(404,"Recording not found")
 try:return supabase_vault.sync_recording(item,recording_path(item))
 except SupabaseVaultError as exc:raise HTTPException(502,str(exc)) from exc

@router.get("/vault-recordings")
def vault_recordings(rehab_type:str="",modality:str="",label:str="",subject_id:str="",session_id:str="",eligible:bool=False):
 items=all_vault_recordings()
 result=[public_record(x) for x in items if (not modality or x["modality"]==modality) and (not rehab_type or (x.get("rehab_type") or x.get("category"))==rehab_type) and (not label or x.get("research_label")==label) and (not subject_id or x.get("subject_id")==subject_id) and (not session_id or x.get("session_id")==session_id)]
 if eligible:result=[x for x in result if x["training_eligible"]]
 return sorted(result,key=lambda x:x.get("created_at") or "",reverse=True)

@router.delete("/vault-recordings/{recording_id}")
def delete_vault_recording(recording_id:str,confirm:str=Query(...)):
 if confirm!=recording_id:raise HTTPException(422,"Confirmation must match the recording ID")
 item=unified_recording(recording_id)
 if not item:raise HTTPException(404,"Recording not found")
 with connect() as db:
  frozen=db.execute("SELECT dataset_version_id,recording_ids_json FROM ml_dataset_versions WHERE status='FROZEN'").fetchall()
 for row in frozen:
  if recording_id in json.loads(row["recording_ids_json"] or "[]"):raise HTTPException(409,f"Recording is referenced by frozen dataset {row['dataset_version_id']}")
 try:
  if item["modality"]=="CV":vault.delete(recording_id)
  else:emg_service().delete_saved(recording_id)
  try:supabase_vault.mark_deleted(recording_id)
  except SupabaseVaultError:pass
  return {"success":True,"recording_id":recording_id}
 except FileNotFoundError as exc:raise HTTPException(404,"Recording not found") from exc
 except ValueError as exc:raise HTTPException(422,str(exc)) from exc
def summarize(items,allow_mock):
 labels=Counter(x["research_label"] for x in items);subjects=Counter(x["subject_id"] for x in items);quality=Counter(x.get("technical_quality") or "UNKNOWN" for x in items);errors=[];warnings=[]
 if len({x["modality"] for x in items})!=1:errors.append("MULTIPLE_MODALITIES_SELECTED")
 if len({x.get("rehab_type") or x.get("category") for x in items})!=1:errors.append("MULTIPLE_REHAB_TYPES_SELECTED")
 if len(labels)<2:errors.append("AT_LEAST_TWO_TARGET_CLASSES_REQUIRED")
 for item in items:
  ok,reason=eligibility(item,allow_mock)
  if not ok:errors.append(f"{item['recording_id']}: {reason}")
 if any(x.get("is_mock") for x in items):warnings.append("MOCK_DATA_INCLUDED")
 if subjects and max(subjects.values())/len(items)>.5:warnings.append("ONE_SUBJECT_DOMINATES_RECORDINGS")
 if len(subjects)<3:warnings.append("LOW_SUBJECT_COUNT")
 state="NOT_READY" if errors else "READY_WITH_WARNINGS" if warnings else "READY"
 return dict(labels),dict(subjects),dict(quality),{"state":state,"errors":sorted(set(errors)),"warnings":warnings}
def manifest_row(item):
 metadata=item.get("metadata",{})
 return {"recording_id":item["recording_id"],"subject_id":item.get("subject_id"),"session_id":item.get("session_id"),"trial_id":item.get("trial_id") or metadata.get("trial_id"),"collection_id":item.get("collection_id") or metadata.get("collection_id"),"related_trial_group":item.get("collection_id") or metadata.get("collection_id") or item.get("trial_id") or metadata.get("trial_id") or item["recording_id"],"rehab_type":item.get("rehab_type") or item.get("category"),"modality":item["modality"],"research_label":item.get("research_label"),"affected_side":item.get("affected_side"),"protocol_id":item.get("protocol_id") or metadata.get("protocol_id"),"protocol_version":item.get("protocol_version") or metadata.get("protocol_version"),"review_status":item.get("review_status"),"technical_quality":item.get("technical_quality"),"training_eligible":bool(item.get("training_eligible")),"is_mock":bool(item.get("is_mock")),"source_backend":item.get("source_backend","LOCAL"),"artifact_hashes":artifact_hashes(item),"artifact_references":item.get("artifact_references",{}),"schema_versions":item.get("schema_versions",{})}
def next_id(prefix,table,column):
 with connect() as db:count=db.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]+1
 return f"{prefix}-{datetime.now(timezone.utc):%Y%m%d}-{count:05d}"

@router.post("/datasets/from-vault")
def dataset_from_vault(request:DatasetFromVault):
 if len(set(request.recording_ids))!=len(request.recording_ids):raise HTTPException(422,"Duplicate recording IDs are not allowed")
 items=[unified_recording(x) for x in request.recording_ids];missing=[rid for rid,item in zip(request.recording_ids,items) if not item]
 if missing:raise HTTPException(422,f"Recordings do not resolve: {', '.join(missing)}")
 labels,subjects,quality,health=summarize(items,request.allow_mock)
 if health["state"]=="NOT_READY":raise HTTPException(422,{"message":"Dataset is not ready","health":health})
 dataset_id=next_id("DATASET","ml_dataset_versions","dataset_version_id");modality=items[0]["modality"];rehab=items[0].get("rehab_type") or items[0].get("category")
 with connect() as db:db.execute("INSERT INTO ml_dataset_versions VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",(dataset_id,request.name,"DRAFT",rehab,modality,json.dumps(request.recording_ids),json.dumps(request.source_query),json.dumps(labels),json.dumps(subjects),json.dumps(quality),json.dumps(health),None,utcnow(),"MASTER",int(any(x.get("is_mock") for x in items))))
 return get_dataset(dataset_id)
@router.get("/datasets")
def datasets():
 with connect() as db:local=[rowdict(x) for x in db.execute("SELECT * FROM ml_dataset_versions ORDER BY created_at DESC")]
 remote=[cloud_dataset(x) for x in ml_cloud.list("flexmap_ml_dataset_versions")];return sorted({x["dataset_version_id"]:x for x in remote+local}.values(),key=lambda x:x["created_at"],reverse=True)
def cloud_dataset(item):
 distributions=item.get("distributions") or {}
 return {"dataset_version_id":item["dataset_version_id"],"name":item["name"],"status":item["status"],"rehab_type":item["rehab_type"],"modality":item["modality"],"recording_ids":item.get("recording_ids") or [],"source_query":item.get("source_query") or {},"label_distribution":distributions.get("labels") or {},"subject_distribution":distributions.get("subjects") or {},"quality_distribution":distributions.get("quality") or {},"health":item.get("health") or {},"manifest_sha256":item.get("manifest_sha256"),"created_at":item["created_at"],"created_by":item.get("created_by","MASTER"),"mock_included":bool(item.get("mock_included")),"manifest":item.get("manifest")}
@router.get("/datasets/{dataset_id}")
def get_dataset(dataset_id:str):
 with connect() as db:item=rowdict(db.execute("SELECT * FROM ml_dataset_versions WHERE dataset_version_id=?",(dataset_id,)).fetchone())
 if not item:
  remote=ml_cloud.get("flexmap_ml_dataset_versions","dataset_version_id",dataset_id)
  if remote:
   item=cloud_dataset(remote);manifest=item.pop("manifest",None)
   if manifest:
    base=ML_DATA_ROOT/"datasets"/dataset_id;base.mkdir(parents=True,exist_ok=True);(base/"dataset_manifest.json").write_text(json.dumps(manifest,indent=2),encoding="utf-8")
 if not item:raise HTTPException(404,"Dataset Version not found")
 return item
@router.post("/datasets/{dataset_id}/freeze")
def freeze_dataset(dataset_id:str):
 item=get_dataset(dataset_id)
 if item["status"]=="FROZEN":return item
 records=[unified_recording(x) for x in item["recording_ids"]]
 if any(x is None for x in records):raise HTTPException(409,"A source recording no longer resolves")
 _,_,_,health=summarize(records,item["mock_included"])
 if health["state"]=="NOT_READY":raise HTTPException(422,health)
 manifest=[manifest_row(x) for x in records];digest=hashlib.sha256(canonical(manifest)).hexdigest();base=ML_DATA_ROOT/"datasets"/dataset_id;base.mkdir(parents=True,exist_ok=False)
 (base/"dataset_manifest.json").write_text(json.dumps(manifest,indent=2),encoding="utf-8")
 fields=[x for x in manifest[0] if x not in ("artifact_references","schema_versions")]
 with (base/"dataset_manifest.csv").open("w",newline="",encoding="utf-8") as handle:
  writer=csv.DictWriter(handle,fieldnames=fields);writer.writeheader();writer.writerows({k:row.get(k) for k in fields} for row in manifest)
 (base/"provenance.json").write_text(json.dumps({**item,"manifest_sha256":digest,"frozen_at":utcnow()},indent=2),encoding="utf-8")
 with connect() as db:db.execute("UPDATE ml_dataset_versions SET status='FROZEN',manifest_sha256=?,health_json=? WHERE dataset_version_id=?",(digest,json.dumps(health),dataset_id))
 frozen=get_dataset(dataset_id)
 ml_cloud.upsert("flexmap_ml_dataset_versions","dataset_version_id",{"dataset_version_id":dataset_id,"name":frozen["name"],"modality":frozen["modality"],"rehab_type":frozen["rehab_type"],"status":"FROZEN","manifest_sha256":digest,"recording_ids":frozen["recording_ids"],"source_query":frozen["source_query"],"distributions":{"labels":frozen["label_distribution"],"subjects":frozen["subject_distribution"],"quality":frozen["quality_distribution"]},"health":health,"manifest":manifest,"mock_included":frozen["mock_included"],"created_by":frozen["created_by"],"created_at":frozen["created_at"],"frozen_at":utcnow()})
 return frozen

def assignments_for(subjects,request):
 unique=sorted(set(subjects));rng=random.Random(request.seed);rng.shuffle(unique)
 if request.strategy=="GROUP_K_FOLD":
  if len(unique)<request.folds:raise HTTPException(422,"Insufficient subjects for requested Group K-Fold")
  return {subject:f"FOLD_{index%request.folds+1}" for index,subject in enumerate(unique)},"RESEARCH"
 if abs(request.train_ratio+request.validation_ratio+request.test_ratio-1)>.001:raise HTTPException(422,"Split ratios must total 1.0")
 if len(unique)<3 and not request.development_only:raise HTTPException(422,"INSUFFICIENT SUBJECTS FOR SUBJECT-GROUPED HOLDOUT")
 if len(unique)<3:return {subject:"TRAIN" for subject in unique},"DEVELOPMENT_ONLY"
 test_n=max(1,round(len(unique)*request.test_ratio));val_n=max(1,round(len(unique)*request.validation_ratio));train_n=len(unique)-test_n-val_n
 if train_n<1:raise HTTPException(422,"Insufficient subjects for train, validation, and test groups")
 return {subject:("TEST" if i<test_n else "VALIDATION" if i<test_n+val_n else "TRAIN") for i,subject in enumerate(unique)},"RESEARCH"
@router.post("/splits")
def create_split(request:SplitRequest):
 dataset=get_dataset(request.dataset_version_id)
 if dataset["status"]!="FROZEN":raise HTTPException(409,"Dataset Version must be frozen")
 manifest_path=ML_DATA_ROOT/"datasets"/dataset["dataset_version_id"]/"dataset_manifest.json"
 records=json.loads(manifest_path.read_text(encoding="utf-8"))
 # Connected components keep both a subject and any explicitly related trial
 # group in one partition, even when malformed imports reuse a trial group.
 parent=list(range(len(records)))
 def find(index):
  while parent[index]!=index:parent[index]=parent[parent[index]];index=parent[index]
  return index
 def union(left,right):
  left,right=find(left),find(right)
  if left!=right:parent[right]=left
 seen={}
 for index,row in enumerate(records):
  for key in (("subject",row["subject_id"]),("related",row.get("related_trial_group") or row["recording_id"])):
   if key in seen:union(index,seen[key])
   else:seen[key]=index
 units=[f"GROUP-{find(index)}" for index in range(len(records))];unit_map,scope=assignments_for(units,request)
 assignments=[{"recording_id":x["recording_id"],"subject_id":x["subject_id"],"related_trial_group":x.get("related_trial_group") or x["recording_id"],"split":unit_map[units[index]]} for index,x in enumerate(records)];overlaps={};groups={x["split"] for x in assignments}
 for left in groups:
  for right in groups:
   if left<right:
    overlap=sorted({x["subject_id"] for x in assignments if x["split"]==left}&{x["subject_id"] for x in assignments if x["split"]==right})
    if overlap:overlaps[f"{left}:{right}"]=overlap
 related_overlap={}
 for left in groups:
  for right in groups:
   if left<right:
    overlap=sorted({x["related_trial_group"] for x in assignments if x["split"]==left}&{x["related_trial_group"] for x in assignments if x["split"]==right})
    if overlap:related_overlap[f"{left}:{right}"]=overlap
 duplicate_ids=[x for x,count in Counter(a["recording_id"] for a in assignments).items() if count>1];leakage={"subject_overlap":overlaps,"related_trial_overlap":related_overlap,"recording_overlap":[],"duplicate_ids":duplicate_ids,"passed":not overlaps and not related_overlap and not duplicate_ids}
 if not leakage["passed"]:raise HTTPException(422,"Split leakage detected")
 split_id=next_id("SPLIT","ml_splits","split_id");base=ML_DATA_ROOT/"splits"/split_id;base.mkdir(parents=True)
 with (base/"split_manifest.csv").open("w",newline="",encoding="utf-8") as handle:
  writer=csv.DictWriter(handle,fieldnames=["recording_id","subject_id","related_trial_group","split"]);writer.writeheader();writer.writerows(assignments)
 config={**request.model_dump(),"evaluation_scope":scope}
 with connect() as db:db.execute("INSERT INTO ml_splits VALUES(?,?,?,?,?,?,?,?)",(split_id,request.dataset_version_id,request.strategy,request.seed,json.dumps(config),json.dumps(assignments),json.dumps(leakage),utcnow()))
 created=get_split(split_id);ml_cloud.upsert("flexmap_ml_splits","split_id",{"split_id":split_id,"dataset_version_id":request.dataset_version_id,"strategy":request.strategy,"seed":request.seed,"configuration":config,"assignments":assignments,"leakage_report":leakage,"created_at":created["created_at"]});return created
@router.get("/splits/{split_id}")
def get_split(split_id:str):
 with connect() as db:item=rowdict(db.execute("SELECT * FROM ml_splits WHERE split_id=?",(split_id,)).fetchone())
 if not item:
  remote=ml_cloud.get("flexmap_ml_splits","split_id",split_id)
  if remote:item={"split_id":remote["split_id"],"dataset_version_id":remote["dataset_version_id"],"strategy":remote["strategy"],"seed":remote["seed"],"config":remote.get("configuration") or {},"assignments":remote.get("assignments") or [],"leakage":remote.get("leakage_report") or {},"created_at":remote["created_at"]}
 if not item:raise HTTPException(404,"Split not found")
 return item

CV_FEATURES=["duration_seconds","frame_count","pose_result_count","tracking_good_ratio","tracking_poor_ratio","tracking_lost_ratio","pose_result_rate_hz","actual_recorded_fps","ready_ratio"]
EMG_FEATURES=["raw_mean","raw_std","raw_min","raw_max","raw_peak_to_peak","rms_mean","valid_ratio","measured_sample_rate_hz","channel_count","sample_count"]
def ensure_pipelines():
 definitions=[
  ("FP-CV-KINEMATICS-V1","CV Kinematics V1","CV","1.0",CV_FEATURES,{"aggregation":"recording","legacy":True}),
  ("FP-EMG-DESCRIPTIVE-V1","EMG Descriptive Features V1","EMG","1.0",EMG_FEATURES,{"aggregation":"recording","legacy":True}),
  ("FP-CV-POSE-KINEMATICS-V2","CV Pose Kinematics V2","CV","2.0",CV_FEATURES_V2,{"coordinate_frame":"MediaPipe normalized image coordinates; x right, y down, z relative and not metric","angle_definition":"2D shoulder-elbow-wrist included angle","visibility_threshold":0.5,"limitations":["camera-plane estimate","perspective and occlusion sensitive","not a clinical measurement"]}),
  ("FP-EMG-SIGNAL-V2","EMG Signal Features V2","EMG","2.0",EMG_FEATURES_V2,{"baseline_correction":"per-channel mean removal","filtering":"none; avoids undocumented cutoff assumptions","frequency_features":"only with positive sampling rate, >=32 samples, and non-constant signal","channels":"features computed per channel, then descriptive aggregation; raw channels are never concatenated","limitations":["amplitude is not muscle strength","not a clinical outcome"]}),
 ]
 with connect() as db:
  for pid,name,modality,version,fields,config in definitions:db.execute("INSERT OR IGNORE INTO ml_feature_pipelines VALUES(?,?,?,?,?,?,?,?)",(pid,name,modality,version,json.dumps(config),json.dumps(fields),utcnow(),"flexmap-ml-2"))
 for pid,name,modality,version,fields,config in definitions:ml_cloud.upsert("flexmap_ml_feature_pipelines","feature_pipeline_id",{"feature_pipeline_id":pid,"name":name,"modality":modality,"version":version,"configuration":config,"source_fields":fields,"code_version":"flexmap-ml-2","created_at":utcnow()})
ensure_pipelines()
@router.get("/feature-pipelines")
def feature_pipelines():
 with connect() as db:local=[rowdict(x) for x in db.execute("SELECT * FROM ml_feature_pipelines ORDER BY modality,name")]
 remote=[{"feature_pipeline_id":x["feature_pipeline_id"],"name":x["name"],"modality":x["modality"],"version":x["version"],"config":x.get("configuration") or {},"source_fields":x.get("source_fields") or [],"created_at":x["created_at"],"code_version":x["code_version"]} for x in ml_cloud.list("flexmap_ml_feature_pipelines","modality.asc,name.asc")]
 return list({x["feature_pipeline_id"]:x for x in remote+local}.values())

def cv_features(item):
 base=dataset_settings().root/item["relative_path"];meta=item.get("metadata",{});measurements=json.loads((base/"measurements.json").read_text(encoding="utf-8"));samples=measurements.get("samples",[])
 return {"duration_seconds":item.get("duration_seconds"),"frame_count":item.get("frame_count"),"pose_result_count":item.get("pose_result_count"),"tracking_good_ratio":item.get("tracking_good_ratio"),"tracking_poor_ratio":item.get("tracking_poor_ratio"),"tracking_lost_ratio":item.get("tracking_lost_ratio"),"pose_result_rate_hz":meta.get("pose_result_rate_hz"),"actual_recorded_fps":meta.get("actual_recorded_fps"),"ready_ratio":sum(bool(x.get("ready")) for x in samples)/len(samples) if samples else 0.0}
def emg_features(item):
 base=dataset_settings().root/item["relative_path"];values=[];valid=0;total=0
 with (base/"emg_raw.csv").open(encoding="utf-8") as handle:
  for row in csv.DictReader(handle):
   total+=1;valid+=str(row.get("valid","")).lower() in ("true","1")
   for key,value in row.items():
    if key.startswith("channel_"):
     try:values.append(float(value))
     except (ValueError,TypeError):pass
 if not values:raise RuntimeError(f"No numeric EMG samples in {item['recording_id']}")
 array=np.asarray(values,dtype=float)
 return {"raw_mean":float(np.mean(array)),"raw_std":float(np.std(array)),"raw_min":float(np.min(array)),"raw_max":float(np.max(array)),"raw_peak_to_peak":float(np.ptp(array)),"rms_mean":float(np.sqrt(np.mean(np.square(array)))),"valid_ratio":valid/total if total else 0.0,"measured_sample_rate_hz":item.get("measured_sample_rate_hz"),"channel_count":item.get("channel_count"),"sample_count":item.get("sample_count")}
def cv_features_v2(item):
 name="pose_observations.jsonl" if _artifact_entry(item,"pose_observations.jsonl") else "pose_observations.json"
 if item.get("source_backend")!="SUPABASE_CV" and not (recording_path(item)/name).is_file():name="measurements.json"
 return extract_cv_features(parse_pose_observations(artifact_bytes(item,name)))
def emg_features_v2(item):
 rate=item.get("measured_sample_rate_hz") or item.get("sample_rate_hz") or (item.get("metadata") or {}).get("sample_rate_hz")
 return extract_emg_features(artifact_bytes(item,"emg_raw.csv"),sample_rate_hz=float(rate) if rate else None)
def extract_features(item,pipeline_id):
 if pipeline_id=="FP-CV-POSE-KINEMATICS-V2":return cv_features_v2(item),CV_FEATURES_V2
 if pipeline_id=="FP-EMG-SIGNAL-V2":return emg_features_v2(item),EMG_FEATURES_V2
 return (cv_features(item),CV_FEATURES) if item["modality"]=="CV" else (emg_features(item),EMG_FEATURES)
def set_run(run_id,**values):
 if not values:return
 columns=",".join(f"{key}=?" for key in values)
 with connect() as db:db.execute(f"UPDATE ml_training_runs SET {columns} WHERE training_run_id=?",(*values.values(),run_id))
def persist_run_cloud(run_id,base):
 if not ml_cloud.enabled:return
 try:
  manifest=ml_cloud.upload_artifacts(run_id,base);ml_cloud.persist_run(get_run(run_id),manifest)
 except SupabaseVaultError as exc:
  (base/"cloud_persistence_error.log").write_text(str(exc),encoding="utf-8")
def evaluation_metrics(truth,pred,labels):
 return {"accuracy":accuracy_score(truth,pred),"balanced_accuracy":balanced_accuracy_score(truth,pred),"precision_macro":precision_score(truth,pred,average="macro",zero_division=0),"recall_macro":recall_score(truth,pred,average="macro",zero_division=0),"f1_macro":f1_score(truth,pred,average="macro",zero_division=0),"per_class":classification_report(truth,pred,labels=labels,output_dict=True,zero_division=0),"confusion_matrix":{"labels":labels,"values":confusion_matrix(truth,pred,labels=labels).tolist()},"evaluation_samples":len(truth)}
def train(run_id):
 run=None
 try:
  with connect() as db:run=rowdict(db.execute("SELECT * FROM ml_training_runs WHERE training_run_id=?",(run_id,)).fetchone())
  dataset=get_dataset(run["dataset_version_id"]);split=get_split(run["split_id"]);base=Path(run["artifact_dir"]);log=[]
  def stage(name,progress):
   log.append(f"{utcnow()} {name}");(base/"training_log.txt").write_text("\n".join(log),encoding="utf-8");set_run(run_id,status="RUNNING",stage=name,progress=progress)
   with connect() as db:cancelled=db.execute("SELECT cancel_requested FROM ml_training_runs WHERE training_run_id=?",(run_id,)).fetchone()[0]
   if cancelled:raise InterruptedError("Run cancelled")
  set_run(run_id,status="RUNNING",started_at=utcnow());stage("VALIDATING_DATASET",.08)
  manifest_path=ML_DATA_ROOT/"datasets"/dataset["dataset_version_id"]/"dataset_manifest.json"
  frozen_manifest=json.loads(manifest_path.read_text(encoding="utf-8"))
  if hashlib.sha256(canonical(frozen_manifest)).hexdigest()!=dataset["manifest_sha256"]:raise RuntimeError("Frozen manifest hash validation failed")
  stage("EXTRACTING_FEATURES",.22);records=[]
  for frozen in frozen_manifest:
   source=unified_recording(frozen["recording_id"])
   if not source:raise RuntimeError(f"Source recording no longer resolves: {frozen['recording_id']}")
   records.append({**source,"subject_id":frozen["subject_id"],"research_label":frozen["research_label"]})
  extracted=[extract_features(x,run["feature_pipeline_id"]) for x in records];features=[item[0] for item in extracted];names=extracted[0][1];assignments={x["recording_id"]:x["split"] for x in split["assignments"]};rows=[]
  for item,feature in zip(records,features):rows.append({"recording_id":item["recording_id"],"subject_id":item["subject_id"],"research_label":item["research_label"],"split":assignments[item["recording_id"]],**feature})
  with (base/"feature_table.csv").open("w",newline="",encoding="utf-8") as handle:writer=csv.DictWriter(handle,fieldnames=list(rows[0]));writer.writeheader();writer.writerows(rows)
  stage("FITTING_PREPROCESSOR",.38);X=np.asarray([[x.get(n) for n in names] for x in rows],dtype=float);y=np.asarray([x["research_label"] for x in rows]);config=run["model_config"]
  if split["strategy"]=="GROUP_K_FOLD":
   train_idx=np.asarray([i for i,x in enumerate(rows) if x["split"] not in ("FOLD_1","FOLD_2")]);validation_idx=np.asarray([i for i,x in enumerate(rows) if x["split"]=="FOLD_2"]);test_idx=np.asarray([i for i,x in enumerate(rows) if x["split"]=="FOLD_1"])
  else:
   train_idx=np.asarray([i for i,x in enumerate(rows) if x["split"]=="TRAIN"]);validation_idx=np.asarray([i for i,x in enumerate(rows) if x["split"]=="VALIDATION"]);test_idx=np.asarray([i for i,x in enumerate(rows) if x["split"]=="TEST"])
  if run["evaluation_scope"]=="DEVELOPMENT_ONLY":train_idx=np.arange(len(rows));validation_idx=np.asarray([],dtype=int);test_idx=np.asarray([],dtype=int)
  if not len(train_idx):raise RuntimeError("Split contains no training records")
  if len(set(y[train_idx]))<2:raise RuntimeError("Training group must contain at least two target classes")
  model=LogisticRegression(max_iter=int(config.get("max_iter",500)),random_state=int(config.get("random_state",42))) if run["model_type"]=="LOGISTIC_REGRESSION" else RandomForestClassifier(n_estimators=int(config.get("n_estimators",100)),max_depth=config.get("max_depth"),random_state=int(config.get("random_state",42)),n_jobs=max(1,min(2,(os.cpu_count() or 2)//2)))
  estimator=Pipeline([("imputer",SimpleImputer(strategy="median")),("scaler",StandardScaler() if run["model_type"]=="LOGISTIC_REGRESSION" else "passthrough"),("model",model)])
  stage("TRAINING_MODEL",.58);estimator.fit(X[train_idx],y[train_idx]);joblib.dump(estimator,base/"model.joblib")
  stage("EVALUATING",.76);labels=sorted(set(y));metrics={"evaluation_scope":run["evaluation_scope"],"training_samples":len(train_idx),"validation":None,"test":None,"development_training":None};prediction_rows=[]
  partitions=[("validation",validation_idx),("test",test_idx)] if run["evaluation_scope"]!="DEVELOPMENT_ONLY" else [("development_training",train_idx)]
  for partition,indexes in partitions:
   if not len(indexes):continue
   pred=estimator.predict(X[indexes]);truth=y[indexes];proba=estimator.predict_proba(X[indexes]) if hasattr(estimator,"predict_proba") else None;metrics[partition]=evaluation_metrics(truth,pred,labels)
   for position,index in enumerate(indexes):prediction_rows.append({"recording_id":rows[index]["recording_id"],"subject_id":rows[index]["subject_id"],"split":partition.upper(),"true_research_label":str(truth[position]),"predicted_label":str(pred[position]),"correct":bool(truth[position]==pred[position]),"confidence":float(max(proba[position])) if proba is not None else None})
  primary=metrics.get("test") or metrics.get("validation") or metrics.get("development_training") or {}
  metrics.update({key:primary.get(key) for key in ("accuracy","balanced_accuracy","precision_macro","recall_macro","f1_macro","per_class","confusion_matrix","evaluation_samples")})
  with (base/"predictions.csv").open("w",newline="",encoding="utf-8") as handle:writer=csv.DictWriter(handle,fieldnames=list(prediction_rows[0]));writer.writeheader();writer.writerows(prediction_rows)
  importance_model=estimator.named_steps["model"];raw=importance_model.feature_importances_ if hasattr(importance_model,"feature_importances_") else np.mean(np.abs(importance_model.coef_),axis=0);importance=sorted(({"feature":name,"importance":float(value)} for name,value in zip(names,raw)),key=lambda x:x["importance"],reverse=True)
  (base/"metrics.json").write_text(json.dumps(metrics,indent=2),encoding="utf-8");(base/"predictions.json").write_text(json.dumps(prediction_rows,indent=2),encoding="utf-8");stage("SAVING_ARTIFACTS",.94)
  hashes={path.name:hashlib.sha256(path.read_bytes()).hexdigest() for path in base.iterdir() if path.is_file()};(base/"artifact_hashes.json").write_text(json.dumps(hashes,indent=2),encoding="utf-8")
  set_run(run_id,status="COMPLETED",stage="COMPLETED",progress=1,completed_at=utcnow(),metrics_json=json.dumps(metrics),feature_importance_json=json.dumps(importance))
  persist_run_cloud(run_id,base)
 except InterruptedError as exc:set_run(run_id,status="CANCELLED",stage="CANCELLED",completed_at=utcnow(),error=str(exc));persist_run_cloud(run_id,base)
 except Exception as exc:
  base=Path(run["artifact_dir"]) if run else ML_DATA_ROOT/"runs"/run_id;base.mkdir(parents=True,exist_ok=True);(base/"error.log").write_text("".join(traceback.format_exception(exc)),encoding="utf-8");set_run(run_id,status="FAILED",stage="FAILED",completed_at=utcnow(),error=str(exc));persist_run_cloud(run_id,base)

executor=ThreadPoolExecutor(max_workers=1,thread_name_prefix="flexmap-ml")
@router.post("/runs")
def create_run(request:RunRequest):
 dataset=get_dataset(request.dataset_version_id);split=get_split(request.split_id)
 if dataset["status"]!="FROZEN":raise HTTPException(409,"Dataset Version must be frozen")
 if split["dataset_version_id"]!=dataset["dataset_version_id"]:raise HTTPException(422,"Split does not belong to Dataset Version")
 with connect() as db:pipeline=rowdict(db.execute("SELECT * FROM ml_feature_pipelines WHERE feature_pipeline_id=?",(request.feature_pipeline_id,)).fetchone())
 if not pipeline or pipeline["modality"]!=dataset["modality"]:raise HTTPException(422,"Feature Pipeline is incompatible with dataset modality")
 if dataset["health"]["warnings"] and not request.warnings_acknowledged:raise HTTPException(422,"Dataset warnings must be acknowledged")
 run_id=next_id("RUN","ml_training_runs","training_run_id");base=ML_DATA_ROOT/"runs"/run_id;base.mkdir(parents=True);scope=split["config"].get("evaluation_scope","RESEARCH");config={**request.model_dump(by_alias=True),"random_seed":split["seed"],"dataset_manifest_sha256":dataset["manifest_sha256"],"split_configuration":split["config"],"software_versions":{"python":sys.version.split()[0],"sklearn":sklearn.__version__,"numpy":np.__version__,"platform":platform.platform()}}
 split_manifest=ML_DATA_ROOT/"splits"/split["split_id"]/"split_manifest.csv"
 if split_manifest.is_file():shutil.copy2(split_manifest,base/"split_manifest.csv")
 (base/"run_config.json").write_text(json.dumps(config,indent=2),encoding="utf-8")
 with connect() as db:db.execute("INSERT INTO ml_training_runs VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",(run_id,dataset["dataset_version_id"],dataset["manifest_sha256"],pipeline["feature_pipeline_id"],split["split_id"],request.task,request.model_type,json.dumps(request.hyperparameters),"QUEUED","QUEUED",0,utcnow(),None,None,None,scope,None,None,str(base),0))
 persist_run_cloud(run_id,base)
 executor.submit(train,run_id);return get_run(run_id)
@router.get("/runs")
def runs():
 with connect() as db:local=[rowdict(x) for x in db.execute("SELECT * FROM ml_training_runs ORDER BY created_at DESC")]
 remote=[cloud_run(x) for x in ml_cloud.list("flexmap_ml_training_runs")];return sorted({x["training_run_id"]:x for x in remote+local}.values(),key=lambda x:x["created_at"],reverse=True)
def cloud_run(item):
 return {"training_run_id":item["training_run_id"],"dataset_version_id":item["dataset_version_id"],"manifest_sha256":item["manifest_sha256"],"feature_pipeline_id":item["feature_pipeline_id"],"split_id":item["split_id"],"task":item["task"],"model_type":item["model_type"],"model_config":item.get("configuration") or {},"status":item["status"],"stage":item["stage"],"progress":1 if item["status"]=="COMPLETED" else 0,"created_at":item["created_at"],"started_at":item.get("started_at"),"completed_at":item.get("completed_at"),"error":item.get("error"),"evaluation_scope":item["evaluation_scope"],"metrics":item.get("metrics"),"feature_importance":item.get("feature_importance"),"artifact_dir":str(ML_DATA_ROOT/"runs"/item["training_run_id"]),"artifact_manifest":item.get("artifact_manifest") or [],"cancel_requested":False,"predictions":[]}
@router.get("/runs/{run_id}")
def get_run(run_id:str):
 with connect() as db:item=rowdict(db.execute("SELECT * FROM ml_training_runs WHERE training_run_id=?",(run_id,)).fetchone())
 if not item:
  remote=ml_cloud.get("flexmap_ml_training_runs","training_run_id",run_id)
  if remote:item=cloud_run(remote)
 if not item:raise HTTPException(404,"Training Run not found")
 predictions=Path(item["artifact_dir"])/"predictions.json";item["predictions"]=json.loads(predictions.read_text(encoding="utf-8")) if predictions.is_file() else []
 if not item["predictions"] and item.get("artifact_manifest"):
  artifact=next((x for x in item["artifact_manifest"] if x.get("name")=="predictions.json"),None)
  if artifact:item["predictions"]=json.loads(ml_cloud.download_artifact(artifact["object_path"],artifact["sha256"]))
 return item
@router.post("/runs/{run_id}/cancel")
def cancel_run(run_id:str):get_run(run_id);set_run(run_id,cancel_requested=1);return get_run(run_id)
@router.get("/runs/{run_id}/artifacts/{filename}")
def run_artifact(run_id:str,filename:str):
 run=get_run(run_id);base=Path(run["artifact_dir"]).resolve();path=(base/filename).resolve();allowed={"feature_table.csv","split_manifest.csv","model.joblib","metrics.json","predictions.csv","training_log.txt","run_config.json","artifact_hashes.json","error.log"}
 if filename not in allowed or path.parent!=base:raise HTTPException(404,"Artifact not found")
 if not path.is_file():
  artifact=next((x for x in run.get("artifact_manifest",[]) if x.get("name")==filename),None)
  if not artifact:raise HTTPException(404,"Artifact not found")
  content=ml_cloud.download_artifact(artifact["object_path"],artifact["sha256"])
  return Response(content,media_type="application/octet-stream",headers={"Content-Disposition":f'attachment; filename="{filename}"'})
 return FileResponse(path,filename=filename)
@router.post("/models/register")
def register_model(request:RegisterRequest):
 run=get_run(request.training_run_id)
 if run["status"]!="COMPLETED":raise HTTPException(409,"Only completed runs can be registered")
 with connect() as db:
  existing=db.execute("SELECT * FROM ml_model_registry WHERE training_run_id=?",(request.training_run_id,)).fetchone()
  if existing:return rowdict(existing)
  version=db.execute("SELECT COUNT(*) FROM ml_model_registry WHERE task=? AND model_type=?",(run["task"],run["model_type"])).fetchone()[0]+1;model_id=f"MODEL-{run['model_type']}-V{version:03d}"
  db.execute("INSERT INTO ml_model_registry VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",(model_id,version,run["training_run_id"],run["dataset_version_id"],run["manifest_sha256"],run["split_id"],run["feature_pipeline_id"],run["task"],run["model_type"],request.status,utcnow(),request.notes))
 model=get_model(model_id);ml_cloud.upsert("flexmap_ml_models","model_id",model);return model
@router.get("/models")
def models():
 with connect() as db:local=[rowdict(x) for x in db.execute("SELECT * FROM ml_model_registry ORDER BY created_at DESC")]
 remote=ml_cloud.list("flexmap_ml_models");return sorted({x["model_id"]:x for x in remote+local}.values(),key=lambda x:x["created_at"],reverse=True)
@router.get("/models/{model_id}")
def get_model(model_id:str):
 with connect() as db:item=rowdict(db.execute("SELECT * FROM ml_model_registry WHERE model_id=?",(model_id,)).fetchone())
 if not item:item=ml_cloud.get("flexmap_ml_models","model_id",model_id)
 if not item:raise HTTPException(404,"Model not found")
 return item
