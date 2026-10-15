from __future__ import annotations
import csv,hashlib,json,os,platform,random,shutil,sqlite3,sys,traceback
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime,timezone
from pathlib import Path
from typing import Literal
import joblib,numpy as np,sklearn
from fastapi import APIRouter,Depends,HTTPException,Query
from fastapi.responses import FileResponse
from pydantic import BaseModel,ConfigDict,Field
from sklearn.ensemble import RandomForestClassifier
from sklearn.impute import SimpleImputer
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import accuracy_score,balanced_accuracy_score,classification_report,confusion_matrix,f1_score,precision_score,recall_score
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler
from .dataset_config import dataset_settings
from .master_dataset_api import require_master,vault
from .supabase_vault import SupabaseVaultError,SupabaseVaultMirror

ML_DATA_ROOT=Path(os.getenv("FLEXMAP_ML_DATA_ROOT",Path(__file__).resolve().parent.parent/"data"/"ml")).resolve();ML_DATA_ROOT.mkdir(parents=True,exist_ok=True)
DB_PATH=dataset_settings().database_path
router=APIRouter(prefix="/api/master/ml",tags=["Master Machine Learning"],dependencies=[Depends(require_master)])
supabase_vault=SupabaseVaultMirror()
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
def unified_recording(recording_id):
 if recording_id.startswith("REC-"):
  item=vault.get(recording_id)
  if not item:return None
  metadata=item.get("metadata",{})
  return {**item,"modality":"CV","research_label":item.get("label"),"is_mock":bool(metadata.get("is_mock",False)),"artifact_references":metadata.get("artifacts",{}),"schema_versions":{"dataset":item.get("dataset_schema_version"),"cv":metadata.get("software_version")}}
 if recording_id.startswith("EMG-"):
  item=emg_service().get(recording_id)
  if not item:return None
  metadata=item.get("metadata",{});manifest={};base=dataset_settings().root/item["relative_path"]
  if (base/"artifact_manifest.json").is_file():manifest=json.loads((base/"artifact_manifest.json").read_text(encoding="utf-8"))
  return {**item,"modality":"EMG","category":item.get("rehab_type"),"label":item.get("research_label"),"review_status":"APPROVED" if item.get("training_eligible") else "NOT_ELIGIBLE","artifact_references":manifest,"schema_versions":{"dataset":metadata.get("dataset_schema_version"),"emg":metadata.get("emg_schema_version")}}
 return None
def eligibility(item,allow_mock=False):
 if item.get("deleted_at") or item.get("review_status") in ("DELETED","TRASHED"):return False,"TRASHED"
 if item.get("excluded"):return False,"MANUALLY_EXCLUDED"
 if item.get("is_mock") and not allow_mock:return False,"MOCK_DATA"
 if not item.get("research_label"):return False,"MISSING_LABEL"
 if not item.get("subject_id"):return False,"MISSING_SUBJECT"
 if item.get("technical_quality")=="INVALID":return False,"INTEGRITY_INVALID"
 if not item.get("training_eligible"):return False,"NOT_TRAINING_ELIGIBLE"
 base=(dataset_settings().root/item["relative_path"]).resolve();required="measurements.json" if item["modality"]=="CV" else "emg_raw.csv"
 if not base.is_relative_to(dataset_settings().root.resolve()) or not (base/required).is_file():return False,f"MISSING_{required.upper().replace('.','_')}"
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
 return [item for item in items if item]

def require_supabase_vault():
 status=supabase_vault.public_status()
 if not status["configured"]:raise HTTPException(503,"Supabase vault is not configured")
 if not status["enabled"]:raise HTTPException(409,"Supabase vault sync is disabled")

@router.get("/supabase/status")
def supabase_status(check:bool=False):return supabase_vault.check_connection() if check else supabase_vault.public_status()

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
 items=[unified_recording(x["recording_id"]) for x in vault.list(rehab_type=rehab_type,label=label,subject=subject_id,session_id=session_id)]
 for module in emg_service().registry.modules:
  if rehab_type and module.id!=rehab_type:continue
  items.extend(unified_recording(x["recording_id"]) for x in emg_service().list(module.slug,label))
 result=[public_record(x) for x in items if x and (not modality or x["modality"]==modality)]
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
 return {"recording_id":item["recording_id"],"subject_id":item.get("subject_id"),"session_id":item.get("session_id"),"trial_id":item.get("trial_id") or metadata.get("trial_id"),"collection_id":item.get("collection_id") or metadata.get("collection_id"),"rehab_type":item.get("rehab_type") or item.get("category"),"modality":item["modality"],"research_label":item.get("research_label"),"affected_side":item.get("affected_side"),"protocol_id":item.get("protocol_id") or metadata.get("protocol_id"),"protocol_version":item.get("protocol_version") or metadata.get("protocol_version"),"review_status":item.get("review_status"),"technical_quality":item.get("technical_quality"),"training_eligible":bool(item.get("training_eligible")),"is_mock":bool(item.get("is_mock")),"artifact_references":item.get("artifact_references",{}),"schema_versions":item.get("schema_versions",{})}
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
 with connect() as db:return [rowdict(x) for x in db.execute("SELECT * FROM ml_dataset_versions ORDER BY created_at DESC")]
@router.get("/datasets/{dataset_id}")
def get_dataset(dataset_id:str):
 with connect() as db:item=rowdict(db.execute("SELECT * FROM ml_dataset_versions WHERE dataset_version_id=?",(dataset_id,)).fetchone())
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
 return get_dataset(dataset_id)

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
 records=json.loads(manifest_path.read_text(encoding="utf-8"));subject_map,scope=assignments_for([x["subject_id"] for x in records],request)
 assignments=[{"recording_id":x["recording_id"],"subject_id":x["subject_id"],"split":subject_map[x["subject_id"]]} for x in records];overlaps={};groups={x["split"] for x in assignments}
 for left in groups:
  for right in groups:
   if left<right:
    overlap=sorted({x["subject_id"] for x in assignments if x["split"]==left}&{x["subject_id"] for x in assignments if x["split"]==right})
    if overlap:overlaps[f"{left}:{right}"]=overlap
 duplicate_ids=[x for x,count in Counter(a["recording_id"] for a in assignments).items() if count>1];leakage={"subject_overlap":overlaps,"recording_overlap":[],"duplicate_ids":duplicate_ids,"passed":not overlaps and not duplicate_ids}
 if not leakage["passed"]:raise HTTPException(422,"Split leakage detected")
 split_id=next_id("SPLIT","ml_splits","split_id");base=ML_DATA_ROOT/"splits"/split_id;base.mkdir(parents=True)
 with (base/"split_manifest.csv").open("w",newline="",encoding="utf-8") as handle:
  writer=csv.DictWriter(handle,fieldnames=["recording_id","subject_id","split"]);writer.writeheader();writer.writerows(assignments)
 config={**request.model_dump(),"evaluation_scope":scope}
 with connect() as db:db.execute("INSERT INTO ml_splits VALUES(?,?,?,?,?,?,?,?)",(split_id,request.dataset_version_id,request.strategy,request.seed,json.dumps(config),json.dumps(assignments),json.dumps(leakage),utcnow()))
 return get_split(split_id)
@router.get("/splits/{split_id}")
def get_split(split_id:str):
 with connect() as db:item=rowdict(db.execute("SELECT * FROM ml_splits WHERE split_id=?",(split_id,)).fetchone())
 if not item:raise HTTPException(404,"Split not found")
 return item

CV_FEATURES=["duration_seconds","frame_count","pose_result_count","tracking_good_ratio","tracking_poor_ratio","tracking_lost_ratio","pose_result_rate_hz","actual_recorded_fps","ready_ratio"]
EMG_FEATURES=["raw_mean","raw_std","raw_min","raw_max","raw_peak_to_peak","rms_mean","valid_ratio","measured_sample_rate_hz","channel_count","sample_count"]
def ensure_pipelines():
 definitions=[("FP-CV-KINEMATICS-V1","CV Kinematics V1","CV","1.0",CV_FEATURES),("FP-EMG-DESCRIPTIVE-V1","EMG Descriptive Features V1","EMG","1.0",EMG_FEATURES)]
 with connect() as db:
  for pid,name,modality,version,fields in definitions:db.execute("INSERT OR IGNORE INTO ml_feature_pipelines VALUES(?,?,?,?,?,?,?,?)",(pid,name,modality,version,json.dumps({"aggregation":"recording"}),json.dumps(fields),utcnow(),"flexmap-ml-1"))
ensure_pipelines()
@router.get("/feature-pipelines")
def feature_pipelines():
 with connect() as db:return [rowdict(x) for x in db.execute("SELECT * FROM ml_feature_pipelines ORDER BY modality,name")]

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
def set_run(run_id,**values):
 if not values:return
 columns=",".join(f"{key}=?" for key in values)
 with connect() as db:db.execute(f"UPDATE ml_training_runs SET {columns} WHERE training_run_id=?",(*values.values(),run_id))
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
  features=[cv_features(x) if dataset["modality"]=="CV" else emg_features(x) for x in records];names=CV_FEATURES if dataset["modality"]=="CV" else EMG_FEATURES;assignments={x["recording_id"]:x["split"] for x in split["assignments"]};rows=[]
  for item,feature in zip(records,features):rows.append({"recording_id":item["recording_id"],"subject_id":item["subject_id"],"research_label":item["research_label"],"split":assignments[item["recording_id"]],**feature})
  with (base/"feature_table.csv").open("w",newline="",encoding="utf-8") as handle:writer=csv.DictWriter(handle,fieldnames=list(rows[0]));writer.writeheader();writer.writerows(rows)
  stage("FITTING_PREPROCESSOR",.38);train_idx=np.asarray([i for i,x in enumerate(rows) if x["split"]=="TRAIN"] or list(range(len(rows))));X=np.asarray([[x.get(n) for n in names] for x in rows],dtype=float);y=np.asarray([x["research_label"] for x in rows]);config=run["model_config"]
  if len(set(y[train_idx]))<2:raise RuntimeError("Training group must contain at least two target classes")
  model=LogisticRegression(max_iter=int(config.get("max_iter",500)),random_state=int(config.get("random_state",42))) if run["model_type"]=="LOGISTIC_REGRESSION" else RandomForestClassifier(n_estimators=int(config.get("n_estimators",100)),max_depth=config.get("max_depth"),random_state=int(config.get("random_state",42)),n_jobs=max(1,min(2,(os.cpu_count() or 2)//2)))
  estimator=Pipeline([("imputer",SimpleImputer(strategy="median")),("scaler",StandardScaler() if run["model_type"]=="LOGISTIC_REGRESSION" else "passthrough"),("model",model)])
  stage("TRAINING_MODEL",.58);estimator.fit(X[train_idx],y[train_idx]);joblib.dump(estimator,base/"model.joblib")
  stage("EVALUATING",.76);evaluation_idx=np.asarray([i for i,x in enumerate(rows) if x["split"] in ("TEST","VALIDATION")])
  if not len(evaluation_idx):evaluation_idx=np.arange(len(rows))
  pred=estimator.predict(X[evaluation_idx]);truth=y[evaluation_idx];labels=sorted(set(y));proba=estimator.predict_proba(X[evaluation_idx]) if hasattr(estimator,"predict_proba") else None
  metrics={"accuracy":accuracy_score(truth,pred),"balanced_accuracy":balanced_accuracy_score(truth,pred),"precision_macro":precision_score(truth,pred,average="macro",zero_division=0),"recall_macro":recall_score(truth,pred,average="macro",zero_division=0),"f1_macro":f1_score(truth,pred,average="macro",zero_division=0),"per_class":classification_report(truth,pred,labels=labels,output_dict=True,zero_division=0),"confusion_matrix":{"labels":labels,"values":confusion_matrix(truth,pred,labels=labels).tolist()},"evaluation_samples":len(evaluation_idx)}
  prediction_rows=[]
  for position,index in enumerate(evaluation_idx):prediction_rows.append({"recording_id":rows[index]["recording_id"],"subject_id":rows[index]["subject_id"],"split":rows[index]["split"],"true_research_label":str(truth[position]),"predicted_label":str(pred[position]),"correct":bool(truth[position]==pred[position]),"confidence":float(max(proba[position])) if proba is not None else None})
  with (base/"predictions.csv").open("w",newline="",encoding="utf-8") as handle:writer=csv.DictWriter(handle,fieldnames=list(prediction_rows[0]));writer.writeheader();writer.writerows(prediction_rows)
  importance_model=estimator.named_steps["model"];raw=importance_model.feature_importances_ if hasattr(importance_model,"feature_importances_") else np.mean(np.abs(importance_model.coef_),axis=0);importance=sorted(({"feature":name,"importance":float(value)} for name,value in zip(names,raw)),key=lambda x:x["importance"],reverse=True)
  (base/"metrics.json").write_text(json.dumps(metrics,indent=2),encoding="utf-8");(base/"predictions.json").write_text(json.dumps(prediction_rows,indent=2),encoding="utf-8");stage("SAVING_ARTIFACTS",.94);set_run(run_id,status="COMPLETED",stage="COMPLETED",progress=1,completed_at=utcnow(),metrics_json=json.dumps(metrics),feature_importance_json=json.dumps(importance))
 except InterruptedError as exc:set_run(run_id,status="CANCELLED",stage="CANCELLED",completed_at=utcnow(),error=str(exc))
 except Exception as exc:
  base=Path(run["artifact_dir"]) if run else ML_DATA_ROOT/"runs"/run_id;base.mkdir(parents=True,exist_ok=True);(base/"error.log").write_text("".join(traceback.format_exception(exc)),encoding="utf-8");set_run(run_id,status="FAILED",stage="FAILED",completed_at=utcnow(),error=str(exc))

executor=ThreadPoolExecutor(max_workers=1,thread_name_prefix="flexmap-ml")
@router.post("/runs")
def create_run(request:RunRequest):
 dataset=get_dataset(request.dataset_version_id);split=get_split(request.split_id)
 if dataset["status"]!="FROZEN":raise HTTPException(409,"Dataset Version must be frozen")
 if split["dataset_version_id"]!=dataset["dataset_version_id"]:raise HTTPException(422,"Split does not belong to Dataset Version")
 with connect() as db:pipeline=rowdict(db.execute("SELECT * FROM ml_feature_pipelines WHERE feature_pipeline_id=?",(request.feature_pipeline_id,)).fetchone())
 if not pipeline or pipeline["modality"]!=dataset["modality"]:raise HTTPException(422,"Feature Pipeline is incompatible with dataset modality")
 if dataset["health"]["warnings"] and not request.warnings_acknowledged:raise HTTPException(422,"Dataset warnings must be acknowledged")
 run_id=next_id("RUN","ml_training_runs","training_run_id");base=ML_DATA_ROOT/"runs"/run_id;base.mkdir(parents=True);scope=split["config"].get("evaluation_scope","RESEARCH");config={**request.model_dump(by_alias=True),"software_versions":{"python":sys.version.split()[0],"sklearn":sklearn.__version__,"numpy":np.__version__,"platform":platform.platform()}}
 split_manifest=ML_DATA_ROOT/"splits"/split["split_id"]/"split_manifest.csv"
 if split_manifest.is_file():shutil.copy2(split_manifest,base/"split_manifest.csv")
 (base/"run_config.json").write_text(json.dumps(config,indent=2),encoding="utf-8")
 with connect() as db:db.execute("INSERT INTO ml_training_runs VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",(run_id,dataset["dataset_version_id"],dataset["manifest_sha256"],pipeline["feature_pipeline_id"],split["split_id"],request.task,request.model_type,json.dumps(request.hyperparameters),"QUEUED","QUEUED",0,utcnow(),None,None,None,scope,None,None,str(base),0))
 executor.submit(train,run_id);return get_run(run_id)
@router.get("/runs")
def runs():
 with connect() as db:return [rowdict(x) for x in db.execute("SELECT * FROM ml_training_runs ORDER BY created_at DESC")]
@router.get("/runs/{run_id}")
def get_run(run_id:str):
 with connect() as db:item=rowdict(db.execute("SELECT * FROM ml_training_runs WHERE training_run_id=?",(run_id,)).fetchone())
 if not item:raise HTTPException(404,"Training Run not found")
 predictions=Path(item["artifact_dir"])/"predictions.json";item["predictions"]=json.loads(predictions.read_text(encoding="utf-8")) if predictions.is_file() else []
 return item
@router.post("/runs/{run_id}/cancel")
def cancel_run(run_id:str):get_run(run_id);set_run(run_id,cancel_requested=1);return get_run(run_id)
@router.get("/runs/{run_id}/artifacts/{filename}")
def run_artifact(run_id:str,filename:str):
 run=get_run(run_id);base=Path(run["artifact_dir"]).resolve();path=(base/filename).resolve();allowed={"feature_table.csv","split_manifest.csv","model.joblib","metrics.json","predictions.csv","training_log.txt","run_config.json","error.log"}
 if filename not in allowed or path.parent!=base or not path.is_file():raise HTTPException(404,"Artifact not found")
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
 return get_model(model_id)
@router.get("/models")
def models():
 with connect() as db:return [rowdict(x) for x in db.execute("SELECT * FROM ml_model_registry ORDER BY created_at DESC")]
@router.get("/models/{model_id}")
def get_model(model_id:str):
 with connect() as db:item=rowdict(db.execute("SELECT * FROM ml_model_registry WHERE model_id=?",(model_id,)).fetchone())
 if not item:raise HTTPException(404,"Model not found")
 return item
