"""Study B: constrained spatial layers with distinct regression/classification targets."""
from __future__ import annotations

import copy
import hashlib
import json
import itertools
import time
from pathlib import Path
from typing import Literal

import joblib
import numpy as np
import torch
from torch import nn
from pydantic import BaseModel, Field, model_validator
from sklearn.ensemble import RandomForestClassifier, RandomForestRegressor
from sklearn.metrics import balanced_accuracy_score, confusion_matrix, f1_score, recall_score

from .emg_deep import build_classifier, _forward
from .emg_math import gauss_legendre_rule
from .emg_research import FUNCTIONS_V2, SpatialConfig, MeasurementError, scenario, scenario_seed, measure, metrics, check_cancel, paired_interval

VARIANTS=["FIXED_EQUAL","FIXED_GQ","LEARNED_EQUAL","LEARNED_GQ","GQ_REGULARIZED"]


class StudyBRequest(BaseModel):
    study: Literal["B"] = "B"
    task: Literal["INTEGRAL_REGRESSION","RESEARCH_LABEL_CLASSIFICATION"] = "INTEGRAL_REGRESSION"
    models: list[Literal["MLP","CNN_1D","TCN","GRU","RANDOM_FOREST"]] = Field(default_factory=lambda:["MLP"],min_length=1,max_length=5)
    variants: list[Literal["FIXED_EQUAL","FIXED_GQ","LEARNED_EQUAL","LEARNED_GQ","GQ_REGULARIZED","GQ_PLUS_FEATURES","RAW_MULTICHANNEL"]] = Field(default_factory=lambda:VARIANTS.copy(),min_length=1,max_length=7)
    lambdas: list[float] = Field(default_factory=lambda:[0.01,.1,1],min_length=1,max_length=5)
    subjects: int = Field(24,ge=9,le=100)
    training_sizes: list[int] = Field(default_factory=list,max_length=3)
    seeds: list[int] = Field(default_factory=lambda:[42,73],min_length=1,max_length=5)
    epochs: int = Field(20,ge=2,le=150)
    sensors: int = Field(3,ge=2,le=5)
    frames: int = Field(48,ge=24,le=128)
    learning_rate: float = Field(.02,gt=0,le=.1)
    noise: float = Field(.03,ge=0,le=.5)
    position_std: float = Field(0,ge=0,le=.2)
    held_out_families: list[str] = Field(default_factory=lambda:["NARROW_PEAK"],max_length=5)
    noise_levels: list[float] = Field(default_factory=list,max_length=3)
    position_levels: list[float] = Field(default_factory=list,max_length=3)
    sensor_counts: list[int] = Field(default_factory=list,max_length=4)

    @model_validator(mode="after")
    def validate_budget(self):
        if any(v<0 or not np.isfinite(v) for v in self.lambdas):raise ValueError("Lambda must be finite and nonnegative")
        if len(set(self.seeds))!=len(self.seeds):raise ValueError("Repeat seeds must be independent")
        if len(set(self.models))!=len(self.models) or len(set(self.variants))!=len(self.variants):raise ValueError("Models and representations must be unique")
        if self.task=="INTEGRAL_REGRESSION":
            if any(m not in {"MLP","RANDOM_FOREST"} for m in self.models):raise ValueError("Integration regression uses the spatial layer (MLP selector) or fixed-feature Random Forest; temporal architectures apply to classification")
            if self.models==["MLP"] and all(v in {"RAW_MULTICHANNEL","GQ_PLUS_FEATURES"} for v in self.variants):raise ValueError("Spatial regression requires a collapsed spatial-weight representation")
        if any(f not in FUNCTIONS_V2 for f in self.held_out_families):raise ValueError("Unknown held-out family")
        if any(s<3 or s>int(self.subjects*.6) for s in self.training_sizes):raise ValueError("Training size must fit training subjects")
        if any(not np.isfinite(v) or v<0 or v>.5 for v in self.noise_levels):raise ValueError("Noise levels must be in [0,.5]")
        if any(not np.isfinite(v) or v<0 or v>.2 for v in self.position_levels):raise ValueError("Position standard deviations must be in [0,.2]")
        if any(v not in {2,3,4,5} for v in self.sensor_counts):raise ValueError("Sensor counts must be 2 through 5")
        budget=len(self.models)*len(self.variants)*len(self.seeds)*max(1,len(self.training_sizes))*max(1,len(self.noise_levels))*max(1,len(self.position_levels))*max(1,len(self.sensor_counts))
        if budget>140:raise ValueError("Bounded experiment limit: 140 model/representation pairs")
        return self


class SpatialWeightLayer(nn.Module):
    def __init__(self, channels, variant):
        super().__init__()
        gq=torch.tensor(gauss_legendre_rule(channels).average_weights,dtype=torch.float32)
        self.register_buffer("gq",gq)
        initial=torch.ones(channels)/channels if variant in {"FIXED_EQUAL","LEARNED_EQUAL"} else gq
        self.logits=nn.Parameter(initial.log(),requires_grad=variant in {"LEARNED_EQUAL","LEARNED_GQ","GQ_REGULARIZED"})

    def weights(self):return self.logits.softmax(dim=0)
    def forward(self,x):return torch.sum(x*self.weights()[None,:,None],dim=1,keepdim=True)
    def penalty(self):return torch.sum((self.weights()-self.gq)**2)


class SpatialTaskModel(nn.Module):
    def __init__(self, channels, frames, variant, architecture, task):
        super().__init__();self.variant=variant;self.task=task;self.architecture=architecture
        self.spatial=SpatialWeightLayer(channels,variant)
        inputs=channels if variant=="RAW_MULTICHANNEL" else 3 if variant=="GQ_PLUS_FEATURES" else 1
        self.network=build_classifier(architecture,inputs,frames,2) if task=="RESEARCH_LABEL_CLASSIFICATION" else None
        # Regression deliberately uses the spatial layer alone: a temporal head
        # could conceal integration bias. Architecture ablations apply to classification.

    def representation(self,x):
        if self.variant=="RAW_MULTICHANNEL":return x
        aggregate=self.spatial(x)
        if self.variant=="GQ_PLUS_FEATURES":return torch.cat([aggregate,x.std(dim=1,keepdim=True),x.amax(dim=1,keepdim=True)],dim=1)
        return aggregate

    def forward(self,x):
        values=self.representation(x)
        return values.squeeze(1) if self.task=="INTEGRAL_REGRESSION" else _forward(self.network,self.architecture,values)


def dataset(request,root_seed):
    """Trajectory groups contain both labels. Seeds have no class-specific ranges.

    Classes describe direction of peak travel; both share the same intensity
    distribution. Entire simulated subjects, including both trials, stay grouped.
    """
    families=["GAUSSIAN","MOVING_PEAK","EXPANDING","TWO_REGIONS","SMOOTH","POLYNOMIAL"]
    training_families=[f for f in families if f not in request.held_out_families]
    if not training_families:raise ValueError("At least one development function family is required")
    rows=[];ntrain=int(request.subjects*.6);nvalid=int(request.subjects*.2)
    for subject in range(request.subjects):
        partition="TRAIN" if subject<ntrain else "VALIDATION" if subject<ntrain+nvalid else "TEST"
        for trial in range(2):
            seed=scenario_seed(root_seed,partition,subject*2+trial);rng=np.random.default_rng(seed)
            pool=request.held_out_families if partition=="TEST" and request.held_out_families else training_families
            family=pool[int(rng.integers(len(pool)))]
            cfg=SpatialConfig(function=family,sensors=request.sensors,frames=request.frames,amplitude=float(rng.uniform(.6,1.2)),peak_width=float(rng.uniform(.12,.55)),peak_location=float(rng.uniform(-.4,.4)),movement=float(rng.uniform(.2,.65)),error=MeasurementError(independent_noise=request.noise,position_std=request.position_std),seed=root_seed)
            if request.task=="RESEARCH_LABEL_CLASSIFICATION":cfg=cfg.model_copy(update={"function":"MIGRATING","temporal_profile":"BURSTS"})
            c,t,target,ref,phase,identity=scenario(cfg,seed,partition,subject*2+trial)
            channels,_=measure(c,gauss_legendre_rule(request.sensors).nodes,t,seed,phase)
            if not ref["valid"] or not np.isfinite(channels).all():raise ValueError("Learning requires a valid reference and complete observations")
            if request.task=="RESEARCH_LABEL_CLASSIFICATION" and trial==1:
                channels=channels[:,::-1].copy();target=target[::-1].copy()
            label=trial  # label determined by travel direction, never supplied as input
            rows.append({"x":channels.astype("float32"),"target":target.astype("float32"),"label":label,"subject":f"SIM-{root_seed}-{subject}","family":c.function,"split":partition,**identity})
    ids=[r["scenario_id"] for r in rows]
    if len(ids)!=len(set(ids)):raise ValueError("Duplicate trajectories detected")
    return rows


def report_metrics(truth,pred,task,groups):
    if task=="INTEGRAL_REGRESSION":return {**metrics(pred.reshape(-1),truth.reshape(-1)),"independent_subjects":len(set(groups)),"unit":"dimensionless processed envelope average"}
    return {"macro_f1":float(f1_score(truth,pred,average="macro",zero_division=0)),"balanced_accuracy":float(balanced_accuracy_score(truth,pred)),"per_class_recall":recall_score(truth,pred,labels=[0,1],average=None,zero_division=0).tolist(),"confusion_matrix":{"labels":["FORWARD_TRAVEL","REVERSE_TRAVEL"],"values":confusion_matrix(truth,pred,labels=[0,1]).tolist()},"independent_subjects":len(set(groups))}


def fit_model(request,variant,architecture,lam,X,y,train,valid,seed,cancel):
    torch.manual_seed(seed);torch.set_num_threads(2)
    model=SpatialTaskModel(request.sensors,request.frames,variant,architecture,request.task)
    learnable=[p for p in model.parameters() if p.requires_grad];optimizer=torch.optim.Adam(learnable,lr=request.learning_rate) if learnable else None
    criterion=nn.MSELoss() if request.task=="INTEGRAL_REGRESSION" else nn.CrossEntropyLoss()
    history=[];best=None;best_loss=float("inf");stale=0
    for epoch in range(request.epochs if optimizer else 1):
        check_cancel(cancel);model.train()
        output=model(X[train]);task_loss=criterion(output,y[train]);penalty=lam*model.spatial.penalty() if variant=="GQ_REGULARIZED" else task_loss*0
        loss=task_loss+penalty
        if optimizer:optimizer.zero_grad();loss.backward();optimizer.step()
        model.eval()
        with torch.no_grad():validation=float(criterion(model(X[valid]),y[valid]).item())
        history.append({"epoch":epoch+1,"training_loss":float(task_loss.item()),"total_loss":float(loss.item()),"validation_loss":validation,"weights":model.spatial.weights().detach().tolist()})
        if validation<best_loss-1e-8:best_loss=validation;best=copy.deepcopy(model.state_dict());stale=0
        else:stale+=1
        if stale>=10:break
    model.load_state_dict(best);model.eval();return model,history,best_loss


def fixed_features(X,variant):
    if variant=="RAW_MULTICHANNEL":values=X
    else:
        weights=np.ones(X.shape[1])/X.shape[1] if variant=="FIXED_EQUAL" else np.asarray(gauss_legendre_rule(X.shape[1]).average_weights)
        values=(weights@X)[:,None,:]
    return np.concatenate([values.mean(axis=2),values.std(axis=2),values.max(axis=2),values[:,:,::4].reshape(len(values),-1)],axis=1)


def _run_study_b_condition(request,base:Path,cancel=None,progress=None):
    base.mkdir(parents=True,exist_ok=True);started=time.perf_counter();results=[];manifests=[];lambda_study=[]
    total=len(request.seeds)*max(1,len(request.training_sizes))*len(request.variants)*len(request.models);done=0
    for seed in request.seeds:
        rows=dataset(request,seed);manifest=[{k:v for k,v in r.items() if k not in {"x","target","label"}} for r in rows]
        manifests.extend(manifest);X=torch.tensor(np.stack([r["x"] for r in rows]));y=torch.tensor(np.stack([r["target"] for r in rows])) if request.task=="INTEGRAL_REGRESSION" else torch.tensor([r["label"] for r in rows],dtype=torch.long)
        validation=np.asarray([i for i,r in enumerate(rows) if r["split"]=="VALIDATION"]);test=np.asarray([i for i,r in enumerate(rows) if r["split"]=="TEST"])
        training_subjects=list(dict.fromkeys(r["subject"] for r in rows if r["split"]=="TRAIN"))
        for size in request.training_sizes or [len(training_subjects)]:
            train=np.asarray([i for i,r in enumerate(rows) if r["subject"] in training_subjects[:size]])
            for architecture in request.models:
                for variant in request.variants:
                    check_cancel(cancel);done+=1
                    if request.task=="INTEGRAL_REGRESSION" and architecture!="RANDOM_FOREST" and (architecture!="MLP" or variant in {"RAW_MULTICHANNEL","GQ_PLUS_FEATURES"}):continue
                    if architecture=="RANDOM_FOREST" and variant not in {"FIXED_EQUAL","FIXED_GQ","RAW_MULTICHANNEL"}:continue
                    start=time.perf_counter();identifier=f"{seed}-{size}-{architecture}-{variant}";history=[];weights=None
                    if architecture=="RANDOM_FOREST":
                        features=fixed_features(X.numpy(),variant);estimator=(RandomForestRegressor if request.task=="INTEGRAL_REGRESSION" else RandomForestClassifier)(n_estimators=80,random_state=seed,n_jobs=1)
                        estimator.fit(features[train],y.numpy()[train]);predictions={p:estimator.predict(features[idx]) for p,idx in (("validation",validation),("test",test))};joblib.dump(estimator,base/f"{identifier}.joblib");parameter_count=None;chosen_lambda=None
                        restored=joblib.load(base/f"{identifier}.joblib")
                        if not np.array_equal(restored.predict(features[test]),predictions["test"]):raise ValueError("Random Forest checkpoint prediction mismatch")
                    else:
                        candidates=[]
                        # Equal tuning budgets: regularized variants tune lambda
                        # at a fixed LR; other variants tune LR with the same
                        # candidate count. Lambda sensitivity therefore has no LR confound.
                        for candidate_index in range(len(request.lambdas)):
                            lam=request.lambdas[candidate_index] if variant=="GQ_REGULARIZED" else 0.0
                            lr=request.learning_rate if variant=="GQ_REGULARIZED" or len(request.lambdas)==1 else min(.1,request.learning_rate*float(np.geomspace(.5,2,len(request.lambdas))[candidate_index]))
                            tuned=request.model_copy(update={"learning_rate":lr})
                            model,hist,score=fit_model(tuned,variant,architecture,lam,X,y,train,validation,seed,cancel);candidates.append((score,lam,model,hist,lr))
                            with torch.no_grad():
                                output=model(X[validation]);validation_predictions=(output.argmax(dim=1) if request.task=="RESEARCH_LABEL_CLASSIFICATION" else output).numpy()
                            candidate_metrics=report_metrics(y.numpy()[validation],validation_predictions,request.task,[rows[i]["subject"] for i in validation])
                            lambda_study.append({"seed":seed,"training_subjects":size,"model":architecture,"variant":variant,"lambda":lam,"learning_rate":lr,"validation_task_loss":score,"validation_metrics":candidate_metrics,"test_consulted":False})
                        _,chosen_lambda,model,history,selected_lr=min(candidates,key=lambda x:x[0]);weights=model.spatial.weights().detach().tolist();predictions={}
                        with torch.no_grad():
                            for partition,idx in (("validation",validation),("test",test)):
                                output=model(X[idx]);predictions[partition]=(output.argmax(dim=1) if request.task=="RESEARCH_LABEL_CLASSIFICATION" else output).numpy()
                        payload={"state_dict":model.state_dict(),"channels":request.sensors,"frames":request.frames,"variant":variant,"architecture":architecture,"task":request.task}
                        torch.save(payload,base/f"{identifier}.pt");parameter_count=sum(p.numel() for p in model.parameters());restored=load_spatial_model(base/f"{identifier}.pt")
                        with torch.no_grad():
                            if not torch.equal(model(X[test]),restored(X[test])):raise ValueError("Checkpoint prediction mismatch")
                    result={"id":identifier,"model":architecture if request.task!="INTEGRAL_REGRESSION" or architecture=="RANDOM_FOREST" else "SPATIAL_LAYER_ONLY","variant":variant,"seed":seed,"training_subjects":size,"lambda":chosen_lambda,"weights":weights,"equal_weights":[1/request.sensors]*request.sensors,"gq_weights":list(gauss_legendre_rule(request.sensors).average_weights),"weights_minus_gq":(np.asarray(weights)-gauss_legendre_rule(request.sensors).average_weights).tolist() if weights else None,"history":history,"parameter_count":parameter_count,"runtime_seconds":time.perf_counter()-start,"information_budget":"EXPANDED" if variant in {"RAW_MULTICHANNEL","GQ_PLUS_FEATURES"} else "COLLAPSED_SIGNAL"}
                    for partition,idx in (("validation",validation),("test",test)):
                        result[partition]=report_metrics(y.numpy()[idx],predictions[partition],request.task,[rows[i]["subject"] for i in idx])
                        result[partition+"_predictions"]={"truth":y.numpy()[idx].tolist(),"prediction":predictions[partition].tolist(),"scenario_ids":[rows[i]["scenario_id"] for i in idx]}
                    results.append(result)
                    if architecture!="RANDOM_FOREST":
                        result["model_parameter_bytes"]=sum(p.numel()*p.element_size() for p in model.parameters());result["tuning_trials"]=len(candidates);result["selected_learning_rate"]=selected_lr
                    if progress:progress(done/total)
    # Pair within seed, architecture, training size. Repeated seeds, not windows,
    # supply the uncertainty units; inadequate repeats suppress intervals.
    comparisons=[];metric="rmse" if request.task=="INTEGRAL_REGRESSION" else "macro_f1"
    for variant in request.variants:
        for architecture in sorted({r["model"] for r in results}):
            differences=[]
            for row in results:
                if row["variant"]!=variant or row["model"]!=architecture:continue
                baseline=next((b for b in results if b["variant"]=="FIXED_EQUAL" and b["model"]==architecture and b["seed"]==row["seed"] and b["training_subjects"]==row["training_subjects"]),None)
                if baseline:differences.append({"seed":row["seed"],"training_subjects":row["training_subjects"],"difference":row["test"][metric]-baseline["test"][metric]})
            # Do not pool dependent learning-curve sizes into independent repeats.
            for size in sorted({d["training_subjects"] for d in differences}):
                ds=[d["difference"] for d in differences if d["training_subjects"]==size]
                comparisons.append({"model":architecture,"variant":variant,"training_subjects":size,"metric":metric,"test_difference_from_equal":float(np.mean(ds)),"uncertainty":{**paired_interval(ds,42),"unit":"INDEPENDENT_SIMULATION_REPEAT"}})
    version=hashlib.sha256(json.dumps(manifests,sort_keys=True).encode()).hexdigest()
    return {"study":"B","task":request.task,"configuration":request.model_dump(),"source_type":"SYNTHETIC MATHEMATICAL DATA","evaluation_scope":"DEVELOPMENT_ONLY","dataset_version":version,"feature_pipeline":"SPATIAL_LAYER-V2","scenario_manifest":manifests,"results":results,"regularization_validation":lambda_study,"paired_comparisons":comparisons,"runtime_seconds":time.perf_counter()-started,"peak_input_bytes":int(request.subjects*2*request.sensors*request.frames*4),"limitations":["Synthetic travel-direction labels have no clinical meaning","Classification is not evidence of integration accuracy","Spatial regression uses the layer alone to expose mathematical bias","Random Forest uses fixed features and cannot backpropagate","Held-out family option applies to regression; classification holds out independent trajectories","Weights are statistical coefficients, not physiological importance"]}


def load_spatial_model(path):
    payload=torch.load(path,map_location="cpu",weights_only=True)
    model=SpatialTaskModel(payload["channels"],payload["frames"],payload["variant"],payload["architecture"],payload["task"])
    model.load_state_dict(payload["state_dict"]);model.eval();return model


def run_study_b(request,base:Path,cancel=None,progress=None):
    conditions=list(itertools.product(request.sensor_counts or [request.sensors],request.noise_levels or [request.noise],request.position_levels or [request.position_std]))
    outputs=[];started=time.perf_counter()
    for index,(sensors,noise,position) in enumerate(conditions):
        check_cancel(cancel)
        config=request.model_copy(update={"sensors":sensors,"noise":noise,"position_std":position,"sensor_counts":[],"noise_levels":[],"position_levels":[]})
        directory=base if len(conditions)==1 else base/f"condition-{index}"
        output=_run_study_b_condition(config,directory,cancel,(lambda value,i=index:progress((i+value)/len(conditions))) if progress else None)
        condition={"sensors":sensors,"noise":noise,"position_std":position}
        for row in output["results"]:
            row.update(condition)
            if len(conditions)>1:row["id"]=f"condition-{index}/"+row["id"]
        for row in output["regularization_validation"]+output["paired_comparisons"]:row.update(condition)
        outputs.append(output)
    result=outputs[0]
    if len(outputs)>1:
        for key in ("results","scenario_manifest","regularization_validation","paired_comparisons"):result[key]=[r for o in outputs for r in o[key]]
        result["dataset_version"]=hashlib.sha256(json.dumps(result["scenario_manifest"],sort_keys=True).encode()).hexdigest()
    result["configuration"]=request.model_dump();result["runtime_seconds"]=time.perf_counter()-started;result["robustness_conditions"]=[{"sensors":s,"noise":n,"position_std":p} for s,n,p in conditions]
    return result
