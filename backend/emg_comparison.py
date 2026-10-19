from __future__ import annotations

import csv
import hashlib
import io
import json
import random
import sqlite3
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal

import joblib
import numpy as np
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import Response
from pydantic import BaseModel, Field
from sklearn.ensemble import RandomForestClassifier
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import accuracy_score, balanced_accuracy_score, confusion_matrix, f1_score, precision_score, recall_score
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler
from sklearn.svm import SVC

from .dataset_config import dataset_settings
from .emg.cloud_vault import EmgCloudVault
from .emg_deep import predict_classifier, save_classifier, torch_status, train_classifier
from .emg_math import FUNCTIONS, gauss_legendre_rule, report_zip, simulate, slider_demo, spatial_function
from .master_dataset_api import require_master
from .ml_cloud import MlCloudRepository


router=APIRouter(prefix="/api/master/ml/emg-comparison",tags=["EMG Research Comparison"],dependencies=[Depends(require_master)])
DB_PATH=dataset_settings().database_path
ROOT=Path(__file__).resolve().parent.parent/"data"/"ml"/"emg-comparisons";ROOT.mkdir(parents=True,exist_ok=True)
executor=ThreadPoolExecutor(max_workers=1,thread_name_prefix="flexmap-emg-research")
ml_cloud=MlCloudRepository()
MIN_INDEPENDENT_SUBJECTS_FOR_INTERVALS=5

def now():return datetime.now(timezone.utc).isoformat()


def _real_vault_readiness():
 vault=EmgCloudVault()
 if not vault.config.configured:
  return {"configured":False,"state":"NOT_CONFIGURED","independent_subjects":0,"usable_classes":0,"simultaneous_channels":0,"classification_eligible":False,"spatial_gq_eligible":False,"reason":"Real EMG Vault is not configured"}
 try:rows=vault.list_recordings()
 except Exception:
  return {"configured":True,"state":"UNAVAILABLE","independent_subjects":None,"usable_classes":None,"simultaneous_channels":None,"classification_eligible":False,"spatial_gq_eligible":False,"reason":"Real EMG Vault readiness could not be verified"}
 usable=[row for row in rows if row.get("review_status")=="APPROVED" and row.get("training_eligible") and not row.get("excluded") and row.get("persistence_status")=="STORED"]
 subjects={str(row["subject_id"]) for row in usable if row.get("subject_id")};classes={str(row["research_label"]) for row in usable if row.get("research_label")};channels=max([int(row.get("channel_count") or 0) for row in usable] or [0])
 geometry_valid=bool(usable) and all(bool((row.get("channel_map_snapshot") or {}).get("geometry_validated")) for row in usable)
 classification_eligible=len(classes)>=2 and len(subjects)>=2
 spatial_eligible=channels>=3 and geometry_valid
 reasons=[]
 if len(classes)<2:reasons.append("fewer than two usable classes")
 if len(subjects)<2:reasons.append("fewer than two independent subjects")
 if channels<3:reasons.append("fewer than three simultaneous channels")
 if not geometry_valid:reasons.append("channel geometry is not validated")
 return {"configured":True,"state":"READY" if usable else "NO_USABLE_RECORDINGS","recordings":len(rows),"usable_recordings":len(usable),"independent_subjects":len(subjects),"usable_classes":len(classes),"simultaneous_channels":channels,"geometry_validated":geometry_valid,"classification_eligible":classification_eligible,"spatial_gq_eligible":spatial_eligible,"reason":"; ".join(reasons) or None}
def connect():db=sqlite3.connect(DB_PATH,timeout=20,check_same_thread=False);db.row_factory=sqlite3.Row;return db
def initialize():
 with connect() as db:
  db.execute("CREATE TABLE IF NOT EXISTS emg_comparison_experiments(experiment_id TEXT PRIMARY KEY,name TEXT NOT NULL,source_type TEXT NOT NULL,task TEXT NOT NULL,status TEXT NOT NULL,configuration_json TEXT NOT NULL,results_json TEXT,artifact_manifest_json TEXT NOT NULL,progress REAL NOT NULL,stage TEXT NOT NULL,error TEXT,created_at TEXT NOT NULL,completed_at TEXT)")
  db.execute("UPDATE emg_comparison_experiments SET status='FAILED',stage='INTERRUPTED',error=COALESCE(error,'Backend restarted before training completed'),completed_at=? WHERE status IN ('QUEUED','RUNNING')",(now(),))
  db.execute("UPDATE emg_comparison_experiments SET status='CANCELLED',stage='CANCELLED',completed_at=? WHERE status='CANCEL_REQUESTED'",(now(),))
initialize()

class DemoRequest(BaseModel):amplitudes:list[float]=Field(min_length=3,max_length=3)
class SimulationRequest(BaseModel):function:str="CENTRAL_PEAK";order:int=Field(default=3,ge=2,le=5);noise_std:float=Field(default=0,ge=0,le=1);position_error:float=Field(default=0,ge=0,le=.5);seed:int=42;frames:int=Field(default=120,ge=20,le=2000)
class ComparisonRequest(BaseModel):
 name:str=Field(default="EMG method comparison",min_length=2,max_length=120)
 source_type:Literal["SYNTHETIC_SIMULATION","REAL_EMG_VAULT","DENSE_REFERENCE"]="SYNTHETIC_SIMULATION"
 task:Literal["RESEARCH_LABEL_CLASSIFICATION","SPATIAL_INTEGRAL_ESTIMATION","DEVELOPMENT_ONLY_METHOD_DEMONSTRATION"]="RESEARCH_LABEL_CLASSIFICATION"
 dataset_version_id:str|None=None
 methods:list[Literal["ARITHMETIC_MEAN","GAUSSIAN_QUADRATURE","RAW_MULTICHANNEL","LEARNED_SPATIAL_WEIGHTS"]]=Field(default_factory=lambda:["ARITHMETIC_MEAN","GAUSSIAN_QUADRATURE"],min_length=1)
 models:list[Literal["LOGISTIC_REGRESSION","RANDOM_FOREST","SVM","MLP","CNN_1D","TCN","GRU","CNN_GRU","TRANSFORMER"]]=Field(default_factory=lambda:["LOGISTIC_REGRESSION","RANDOM_FOREST","MLP"],min_length=1)
 seed:int=42;simulation_function:str="CENTRAL_PEAK";subjects:int=Field(default=18,ge=3,le=200);epochs:int=Field(default=30,ge=1,le=500)

CATALOG=[
 ("LOGISTIC_REGRESSION","Classical baseline","Tabular mathematical features","LOW","Interpretable","Linear decision boundary",True),
 ("RANDOM_FOREST","Classical machine learning","Tabular mathematical features","LOW","Nonlinear feature interactions","Less directly interpretable",True),
 ("SVM","Classical machine learning","Scaled tabular features","MEDIUM","Strong small-data baseline","Can be slow on large datasets",True),
 ("MLP","Deep learning","Temporal EMG sequence","MEDIUM","Nonlinear learned representation","Overfits small datasets",False),
 ("CNN_1D","Deep learning","Temporal EMG sequence","MEDIUM","Learns local patterns","Requires PyTorch and adequate data",False),
 ("TCN","Deep learning","Temporal EMG sequence","MEDIUM","Longer temporal context","Requires PyTorch and adequate data",False),
 ("GRU","Deep learning","Temporal EMG sequence","MEDIUM","Sequential dynamics","Requires PyTorch and adequate data",False),
 ("CNN_GRU","Advanced deep learning","Temporal EMG sequence","HIGH","Local and sequential modeling","High overfitting risk",False),
 ("TRANSFORMER","Advanced experimental","Temporal EMG sequence","HIGH","Long-range attention","Not justified for small datasets",False),
]

@router.get("/catalog")
def catalog():
 torch=torch_status();items=[]
 for model,category,input_type,cost,advantage,limitation,builtin in CATALOG:
  available=builtin or (torch["available"] and model in {"MLP","CNN_1D","TCN","GRU","CNN_GRU"})
  reason = torch["reason"] if not torch["available"] else "Architecture is defined, but training remains blocked until an eligible temporal dataset and deep-learning worker are configured"
  items.append({"id":model,"name":model.replace("_"," "),"category":category,"input_representation":input_type,"estimated_cost":cost,"advantage":advantage,"limitation":limitation,"supported_task":"CLASSIFICATION","eligible":available,"ineligible_reason":None if available else (reason if model!="TRANSFORMER" else "Transformer is disabled until adequate independent data and compute are demonstrated")})
 return {"models":items,"torch":torch,"functions":FUNCTIONS,"methods":["ARITHMETIC_MEAN","GAUSSIAN_QUADRATURE","LEARNED_SPATIAL_WEIGHTS","RAW_MULTICHANNEL"],"hardware_limit":"Real spatial GQ requires at least 3 simultaneous, synchronized channels at validated positions. The commissioned FlexMap board currently has 1 channel.","durable_storage":ml_cloud.public_status()}

@router.post("/demo")
def demo(request:DemoRequest):return slider_demo(request.amplitudes)
@router.post("/simulation")
def simulation(request:SimulationRequest):return simulate(request.function,request.order,request.noise_std,request.position_error,request.seed,request.frames)

def _features(curve):
 curve=np.asarray(curve);return [float(np.mean(curve)),float(np.std(curve)),float(np.min(curve)),float(np.max(curve)),float(np.trapezoid(curve)/len(curve)),float(np.mean(np.abs(np.diff(curve))))]
def _fixture(config):
 rng=np.random.default_rng(config["seed"]);rule=gauss_legendre_rule(3);rows=[]
 spatial=spatial_function(config.get("simulation_function","CENTRAL_PEAK"),np.asarray(rule.nodes));spatial=spatial/np.mean(spatial)
 for subject in range(config["subjects"]):
  for label,base in (("REST",.25),("ACTIVATION",.75)):
   t=np.linspace(0,2*np.pi,128);temporal=base*(1+.22*np.sin(t+subject*.07));channels=np.maximum(spatial[:,None]*temporal+rng.normal(0,.04,(3,len(t))),0)
   rows.append({"subject":f"SYN-{subject:03d}","label":label,"channels":channels})
 subjects=list(range(config["subjects"]));random.Random(config["seed"]).shuffle(subjects);test=set(subjects[:max(1,round(len(subjects)*.2))]);validation=set(subjects[max(1,round(len(subjects)*.2)):max(2,round(len(subjects)*.4))])
 for row in rows:
  index=int(row["subject"].split("-")[1]);row["split"]="TEST" if index in test else "VALIDATION" if index in validation else "TRAIN"
 return rows
def _estimator(model,seed):
 if model=="LOGISTIC_REGRESSION":return Pipeline([("scale",StandardScaler()),("model",LogisticRegression(max_iter=500,random_state=seed))])
 if model=="RANDOM_FOREST":return RandomForestClassifier(n_estimators=120,random_state=seed,n_jobs=1)
 if model=="SVM":return Pipeline([("scale",StandardScaler()),("model",SVC(kernel="rbf",probability=True,random_state=seed))])
 raise ValueError(f"{model} requires the optional PyTorch worker and temporal dataset support")
def _representation(rows,method,seed):
 if method=="ARITHMETIC_MEAN":return np.asarray([_features(np.mean(x["channels"],axis=0)) for x in rows]),{"weights":[1/3]*3,"information_budget":"MATCHED_COLLAPSED_SIGNAL"}
 if method=="GAUSSIAN_QUADRATURE":
  weights=np.asarray(gauss_legendre_rule(3).average_weights);return np.asarray([_features(weights@x["channels"]) for x in rows]),{"weights":weights.tolist(),"information_budget":"MATCHED_COLLAPSED_SIGNAL"}
 if method=="RAW_MULTICHANNEL":return np.asarray([[value for channel in x["channels"] for value in _features(channel)] for x in rows]),{"weights":None,"information_budget":"EXPANDED_RAW_MULTICHANNEL_BASELINE"}
 if method=="LEARNED_SPATIAL_WEIGHTS":
  outer_train=[i for i,x in enumerate(rows) if x["split"]=="TRAIN"];subjects=sorted({rows[i]["subject"] for i in outer_train});inner_valid=set(subjects[::max(2,len(subjects)//3)])
  fit=np.asarray([i for i in outer_train if rows[i]["subject"] not in inner_valid]);valid=np.asarray([i for i in outer_train if rows[i]["subject"] in inner_valid]);labels=np.asarray([x["label"] for x in rows]);best_score=-1.0;best=np.asarray([1/3]*3)
  for first in range(11):
   for second in range(11-first):
    candidate=np.asarray([first,second,10-first-second],dtype=float)/10;X=np.asarray([_features(candidate@x["channels"]) for x in rows]);probe=_estimator("LOGISTIC_REGRESSION",seed);probe.fit(X[fit],labels[fit]);score=f1_score(labels[valid],probe.predict(X[valid]),average="macro",zero_division=0)
    if score>best_score:best_score=score;best=candidate
  return np.asarray([_features(best@x["channels"]) for x in rows]),{"weights":best.tolist(),"selection":"TRAINING_SUBJECTS_ONLY_INNER_HOLDOUT","inner_validation_macro_f1":float(best_score),"information_budget":"MATCHED_COLLAPSED_SIGNAL"}
 raise ValueError(f"Unsupported mathematical method: {method}")
def _bootstrap_f1(truth,pred,groups,seed,iterations=300):
 unique=sorted(set(groups.tolist()));rng=np.random.default_rng(seed);values=[]
 for _ in range(iterations):
  sampled=rng.choice(unique,size=len(unique),replace=True);indexes=np.concatenate([np.flatnonzero(groups==group) for group in sampled]);values.append(f1_score(truth[indexes],pred[indexes],average="macro",zero_division=0))
 return {"lower":float(np.percentile(values,2.5)),"upper":float(np.percentile(values,97.5)),"iterations":iterations,"unit":"SUBJECT"}
def _score(model,X,y,indexes,groups,seed):
 started=time.perf_counter();pred=model.predict(X[indexes]);elapsed=time.perf_counter()-started;truth=y[indexes];labels=sorted(set(y.tolist()))
 return _score_predictions(truth,pred,elapsed,groups[indexes],seed,labels)
def _score_predictions(truth,pred,elapsed,groups,seed,labels=None):
 labels=labels or sorted(set(truth.tolist()));independent_units=len(set(groups.tolist()));sufficient=independent_units>=MIN_INDEPENDENT_SUBJECTS_FOR_INTERVALS
 return {"macro_f1":float(f1_score(truth,pred,average="macro",zero_division=0)),"macro_f1_ci95":_bootstrap_f1(truth,pred,groups,seed) if sufficient else None,"balanced_accuracy":float(balanced_accuracy_score(truth,pred)),"accuracy":float(accuracy_score(truth,pred)),"precision_macro":float(precision_score(truth,pred,average="macro",zero_division=0)),"recall_macro":float(recall_score(truth,pred,average="macro",zero_division=0)),"confusion_matrix":{"labels":labels,"values":confusion_matrix(truth,pred,labels=labels).tolist()},"samples":len(truth),"independent_subjects":independent_units,"uncertainty_status":"SUBJECT_BOOTSTRAP_AVAILABLE" if sufficient else "INSUFFICIENT_INDEPENDENT_UNITS","inference_seconds":elapsed}
def _cancel_requested(experiment_id):
 with connect() as db:return db.execute("SELECT status FROM emg_comparison_experiments WHERE experiment_id=?",(experiment_id,)).fetchone()[0]=="CANCEL_REQUESTED"
def _temporal(rows,method,representation):
 if method=="RAW_MULTICHANNEL":return np.asarray([x["channels"] for x in rows],dtype=np.float32)
 weights=np.asarray(representation["weights"],dtype=np.float32);return np.asarray([(weights@x["channels"])[None,:] for x in rows],dtype=np.float32)
def _train(experiment_id):
 with connect() as db:row=db.execute("SELECT * FROM emg_comparison_experiments WHERE experiment_id=?",(experiment_id,)).fetchone();config=json.loads(row["configuration_json"]);db.execute("UPDATE emg_comparison_experiments SET status='RUNNING',stage='TRAINING',progress=.1 WHERE experiment_id=?",(experiment_id,))
 try:
  rows=_fixture(config);results=[];base=ROOT/experiment_id;base.mkdir(parents=True,exist_ok=True);total=len(config["methods"])*len(config["models"]);done=0
  for method in config["methods"]:
   with connect() as db:
    state=db.execute("SELECT status FROM emg_comparison_experiments WHERE experiment_id=?",(experiment_id,)).fetchone()[0]
   if state=="CANCEL_REQUESTED":
    with connect() as db:db.execute("UPDATE emg_comparison_experiments SET status='CANCELLED',stage='CANCELLED',completed_at=? WHERE experiment_id=?",(now(),experiment_id))
    return
   X,representation=_representation(rows,method,config["seed"]);y=np.asarray([x["label"] for x in rows]);groups=np.asarray([x["subject"] for x in rows]);train=np.asarray([i for i,x in enumerate(rows) if x["split"]=="TRAIN"]);validation=np.asarray([i for i,x in enumerate(rows) if x["split"]=="VALIDATION"]);test=np.asarray([i for i,x in enumerate(rows) if x["split"]=="TEST"])
   for architecture in config["models"]:
    if architecture in {"MLP","CNN_1D","TCN","GRU","CNN_GRU"}:
     temporal=_temporal(rows,method,representation);classes=sorted(set(y.tolist()));encoded=np.asarray([classes.index(value) for value in y])
     started=time.perf_counter();trained=train_classifier(architecture,temporal[train],encoded[train],temporal[validation],encoded[validation],epochs=config["epochs"],seed=config["seed"],cancel=lambda:_cancel_requested(experiment_id));training=time.perf_counter()-started;artifact=base/f"{method}-{architecture}.pt";save_classifier(artifact,trained["model"],architecture=architecture,channels=temporal.shape[1],samples=temporal.shape[2],classes=classes)
     validation_started=time.perf_counter();validation_indexes=predict_classifier(trained["model"],architecture,temporal[validation]);validation_elapsed=time.perf_counter()-validation_started;test_started=time.perf_counter();test_indexes=predict_classifier(trained["model"],architecture,temporal[test]);test_elapsed=time.perf_counter()-test_started
     validation_predictions=np.asarray([classes[i] for i in validation_indexes]);test_predictions=np.asarray([classes[i] for i in test_indexes]);validation_score=_score_predictions(y[validation],validation_predictions,validation_elapsed,groups[validation],config["seed"]);test_score=_score_predictions(y[test],test_predictions,test_elapsed,groups[test],config["seed"]+1);history=trained["history"];deep={"framework":"PYTORCH","device":trained["device"],"best_epoch":trained["best_epoch"],"early_stopped":trained["early_stopped"]}
    else:
     estimator=_estimator(architecture,config["seed"]);started=time.perf_counter();estimator.fit(X[train],y[train]);training=time.perf_counter()-started;artifact=base/f"{method}-{architecture}.joblib";joblib.dump(estimator,artifact);history=[];validation_predictions=estimator.predict(X[validation]);test_predictions=estimator.predict(X[test]);validation_score=_score(estimator,X,y,validation,groups,config["seed"]);test_score=_score(estimator,X,y,test,groups,config["seed"]+1);deep=None
    results.append({"model":architecture,"mathematical_method":method,"representation":representation,"deep_learning":deep,"dataset_version_id":"SYNTHETIC-SPATIAL-V1","independent_subjects":config["subjects"],"validation":validation_score,"test":test_score,"training_seconds":training,"model_size_bytes":artifact.stat().st_size,"training_history":history,"artifact_sha256":hashlib.sha256(artifact.read_bytes()).hexdigest(),"evaluation_scope":"DEVELOPMENT_ONLY","controlled_pair_key":architecture,"_validation_trace":{"truth":y[validation].tolist(),"predictions":validation_predictions.tolist(),"subjects":groups[validation].tolist()}})
    done+=1
    with connect() as db:db.execute("UPDATE emg_comparison_experiments SET progress=?,stage=? WHERE experiment_id=?",(.1+.8*done/total,f"TRAINING_{architecture}_{method}",experiment_id))
  comparisons=[]
  for architecture in config["models"]:
   pair={item["mathematical_method"]:item for item in results if item["model"]==architecture}
   if "ARITHMETIC_MEAN" in pair and "GAUSSIAN_QUADRATURE" in pair:
    mean,gq=pair["ARITHMETIC_MEAN"],pair["GAUSSIAN_QUADRATURE"];trace=mean["_validation_trace"];truth=np.asarray(trace["truth"]);groups_pair=np.asarray(trace["subjects"]);mean_pred=np.asarray(trace["predictions"]);gq_pred=np.asarray(gq["_validation_trace"]["predictions"]);unique=sorted(set(groups_pair.tolist()));rng=np.random.default_rng(config["seed"]);differences=[]
    sufficient=len(unique)>=MIN_INDEPENDENT_SUBJECTS_FOR_INTERVALS
    if sufficient:
     for _ in range(300):
      sampled=rng.choice(unique,size=len(unique),replace=True);indexes=np.concatenate([np.flatnonzero(groups_pair==group) for group in sampled]);differences.append(f1_score(truth[indexes],gq_pred[indexes],average="macro",zero_division=0)-f1_score(truth[indexes],mean_pred[indexes],average="macro",zero_division=0))
    interval={"lower":float(np.percentile(differences,2.5)),"upper":float(np.percentile(differences,97.5)),"iterations":300,"unit":"SUBJECT"} if sufficient else None
    comparisons.append({"model":architecture,"metric":"VALIDATION_MACRO_F1","gq_minus_mean":gq["validation"]["macro_f1"]-mean["validation"]["macro_f1"],"independent_subjects":len(unique),"paired_subject_bootstrap_ci95":interval,"uncertainty_status":"SUBJECT_BOOTSTRAP_AVAILABLE" if sufficient else "INSUFFICIENT_INDEPENDENT_UNITS","interpretation":"EXPLORATORY_SYNTHETIC_NOT_CLINICAL_SIGNIFICANCE"})
  for item in results:item.pop("_validation_trace",None)
  results.sort(key=lambda x:x["validation"]["macro_f1"],reverse=True);validation_subjects=min((item["validation"]["independent_subjects"] for item in results),default=0);ranking_eligible=validation_subjects>=MIN_INDEPENDENT_SUBJECTS_FOR_INTERVALS
  readiness={"status":"DEVELOPMENT_ONLY","display_message":"DEVELOPMENT ONLY — INSUFFICIENT REAL DATA","real_vault":_real_vault_readiness(),"synthetic_validation_subjects":validation_subjects,"minimum_subjects_for_exploratory_intervals":MIN_INDEPENDENT_SUBJECTS_FOR_INTERVALS,"ranking_eligible":ranking_eligible}
  ranking_statement="Synthetic validation ordering for development only" if ranking_eligible else "DEVELOPMENT ONLY — INSUFFICIENT REAL DATA; ordering is descriptive and must not be used for model selection"
  payload={"source_type":"SYNTHETIC_SIMULATION","evaluation_scope":"DEVELOPMENT_ONLY","data_readiness":readiness,"primary_ranking_metric":"validation_macro_f1","ranking_statement":ranking_statement,"statistical_comparisons":comparisons,"results":results,"best_validation":results[0] if results else None,"limitations":["Synthetic data only","DEVELOPMENT ONLY — INSUFFICIENT REAL DATA","No clinical generalization claim","Bootstrap intervals are omitted when fewer than five independent subjects are available in an evaluation partition","Held-out synthetic test was not used for model selection"]};(base/"results.json").write_text(json.dumps(payload,indent=2),encoding="utf-8");manifest=[{"name":p.name,"sha256":hashlib.sha256(p.read_bytes()).hexdigest(),"byte_size":p.stat().st_size} for p in base.iterdir() if p.is_file()]
  completed_at=now()
  with connect() as db:db.execute("UPDATE emg_comparison_experiments SET status='COMPLETED',stage='COMPLETED',progress=1,results_json=?,artifact_manifest_json=?,completed_at=? WHERE experiment_id=?",(json.dumps(payload),json.dumps(manifest),completed_at,experiment_id))
  if ml_cloud.enabled:
   item=get_experiment(experiment_id);cloud_manifest=ml_cloud.persist_comparison(item,base)
   with connect() as db:db.execute("UPDATE emg_comparison_experiments SET artifact_manifest_json=? WHERE experiment_id=?",(json.dumps(cloud_manifest),experiment_id))
 except Exception as exc:
  with connect() as db:db.execute("UPDATE emg_comparison_experiments SET status='FAILED',stage='FAILED',error=?,completed_at=? WHERE experiment_id=?",(str(exc),now(),experiment_id))

def _public(row):
 item=dict(row);item["configuration"]=json.loads(item.pop("configuration_json"));item["results"]=json.loads(item.pop("results_json")) if item.get("results_json") else None;item["artifact_manifest"]=json.loads(item.pop("artifact_manifest_json"));return item
@router.post("/experiments")
def create_experiment(request:ComparisonRequest):
 catalog_state={x["id"]:x for x in catalog()["models"]};blocked=[model for model in request.models if not catalog_state[model]["eligible"]]
 if blocked:raise HTTPException(422,{"message":"Selected models are not eligible","models":{x:catalog_state[x]["ineligible_reason"] for x in blocked}})
 if request.source_type!="SYNTHETIC_SIMULATION":raise HTTPException(422,"Real spatial comparison requires a compatible frozen dataset with at least three synchronized channels and validated geometry; the current one-channel hardware is not eligible")
 if request.task!="RESEARCH_LABEL_CLASSIFICATION":raise HTTPException(422,"This worker currently trains classification comparisons only. Use the Simulation Lab endpoint for integral-estimation experiments.")
 identifier=f"EMGCMP-{datetime.now(timezone.utc):%Y%m%d%H%M%S}-{random.randrange(1000,9999)}";config=request.model_dump()
 with connect() as db:db.execute("INSERT INTO emg_comparison_experiments VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)",(identifier,request.name,request.source_type,request.task,"QUEUED",json.dumps(config),None,"[]",0,"QUEUED",None,now(),None))
 executor.submit(_train,identifier);return get_experiment(identifier)
@router.get("/experiments")
def experiments():
 with connect() as db:return [_public(x) for x in db.execute("SELECT * FROM emg_comparison_experiments ORDER BY created_at DESC")]
@router.get("/experiments/{experiment_id}")
def get_experiment(experiment_id:str):
 with connect() as db:row=db.execute("SELECT * FROM emg_comparison_experiments WHERE experiment_id=?",(experiment_id,)).fetchone()
 if not row:raise HTTPException(404,"Experiment not found")
 return _public(row)
@router.post("/experiments/{experiment_id}/cancel")
def cancel_experiment(experiment_id:str):
 item=get_experiment(experiment_id)
 if item["status"] not in ("QUEUED","RUNNING"):raise HTTPException(409,"Only queued or running experiments can be cancelled")
 with connect() as db:db.execute("UPDATE emg_comparison_experiments SET status='CANCEL_REQUESTED',stage='CANCELLING' WHERE experiment_id=?",(experiment_id,))
 return get_experiment(experiment_id)
@router.get("/experiments/{experiment_id}/export.{extension}")
def export_experiment(experiment_id:str,extension:Literal["json","csv","zip"]):
 item=get_experiment(experiment_id)
 if item["status"]!="COMPLETED":raise HTTPException(409,"Experiment is not complete")
 if extension=="json":return Response(json.dumps(item,indent=2),media_type="application/json",headers={"Content-Disposition":f'attachment; filename="{experiment_id}.json"'})
 if extension=="zip":return Response(report_zip(item),media_type="application/zip",headers={"Content-Disposition":f'attachment; filename="{experiment_id}.zip"'})
 output=io.StringIO();writer=csv.DictWriter(output,fieldnames=["model","mathematical_method","independent_subjects","validation_macro_f1","test_macro_f1","training_seconds","inference_seconds","model_size_bytes","evaluation_scope"]);writer.writeheader()
 for result in item["results"]["results"]:writer.writerow({"model":result["model"],"mathematical_method":result["mathematical_method"],"independent_subjects":result["independent_subjects"],"validation_macro_f1":result["validation"]["macro_f1"],"test_macro_f1":result["test"]["macro_f1"],"training_seconds":result["training_seconds"],"inference_seconds":result["test"]["inference_seconds"],"model_size_bytes":result["model_size_bytes"],"evaluation_scope":result["evaluation_scope"]})
 return Response(output.getvalue(),media_type="text/csv",headers={"Content-Disposition":f'attachment; filename="{experiment_id}.csv"'})
