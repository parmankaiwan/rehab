"""Traceable Study A/B tables and publication artifacts (Agg, no GUI)."""
import csv
import hashlib
import io
import json
import subprocess
import sys
import zipfile
from pathlib import Path
import numpy as np

SOURCE_NAMES=("emg_research.py","emg_spatial_learning.py","emg_deep.py","emg_research_exports.py")
LOADED_SOURCE_HASHES={name:hashlib.sha256((Path(__file__).resolve().parent/name).read_bytes()).hexdigest() for name in SOURCE_NAMES}


def tables(payload):
    if payload["study"]=="A":
        return [{"scenario_id":r["scenario_id"],"partition":r["partition"],"seed":r["seed"],"function":r["configuration"]["function"],"sensors":r["configuration"]["sensors"],"sweep_parameter":r["sweep_parameter"],"sweep_value":r["sweep_value"],"mean_rmse":r["A1_same_measurements"]["ARITHMETIC_MEAN"]["rmse"],"gq_rmse":r["A1_same_measurements"]["GAUSSIAN_QUADRATURE"]["rmse"],"paired_rmse_gq_minus_mean":r["paired_rmse_gq_minus_mean"],"reference_method":r["reference"]["method"]} for r in payload["scenarios"]]
    return [{"model":r["model"],"variant":r["variant"],"seed":r["seed"],"training_subjects":r["training_subjects"],"lambda":r["lambda"],"validation_metric":r["validation"].get("rmse",r["validation"].get("macro_f1")),"test_metric":r["test"].get("rmse",r["test"].get("macro_f1")),"parameter_count":r["parameter_count"],"runtime_seconds":r["runtime_seconds"],"information_budget":r["information_budget"]} for r in payload["results"]]


def csv_bytes(payload):
    rows=tables(payload);out=io.StringIO()
    if rows:
        writer=csv.DictWriter(out,fieldnames=list(rows[0]));writer.writeheader();writer.writerows(rows)
    return out.getvalue().encode("utf-8")


def finish_artifacts(payload,folder,experiment_id,configuration):
    import matplotlib
    matplotlib.use("Agg")
    from matplotlib import pyplot as plt
    try:revision=subprocess.check_output(["git","rev-parse","HEAD"],text=True,stderr=subprocess.DEVNULL).strip()
    except (OSError,subprocess.SubprocessError):revision="UNKNOWN"
    payload.update({"experiment_id":experiment_id,"code_version":revision,"code_artifact_hashes":LOADED_SOURCE_HASHES,"python_version":sys.version.split()[0],"source_artifact_ids":[],"configuration_sha256":hashlib.sha256(json.dumps(configuration,sort_keys=True).encode()).hexdigest()})
    (folder/"results.json").write_text(json.dumps(payload,indent=2,allow_nan=False),encoding="utf-8")
    (folder/"comparison.csv").write_bytes(csv_bytes(payload))
    def save_table(name,rows):
        rows=list(rows)
        if not rows:return
        out=io.StringIO();writer=csv.DictWriter(out,fieldnames=list(rows[0]));writer.writeheader();writer.writerows(rows);(folder/name).write_text(out.getvalue(),encoding="utf-8")
    if payload["study"]=="A":
        save_table("signal_curves.csv",({"scenario_id":r["scenario_id"],"split":r["partition"],"time_seconds":t,"reference":r["reference_curve"][i],"equal_mean":r["mean_curve"][i] if r["mean_curve"] else None,"gq":r["gq_curve"][i] if r["gq_curve"] else None,"units":"dimensionless envelope average"} for r in payload["scenarios"] for i,t in enumerate(r["time_seconds"])))
        save_table("placement_comparison.csv",({"scenario_id":r["scenario_id"],"split":r["partition"],"placement":name,"sensor_count":len(p["weights"]),"positions":json.dumps(p["normalized_positions"]),"weights":json.dumps(p["weights"]),"rmse":p["metrics"]["rmse"],"estimator":p["estimator"]} for r in payload["scenarios"] for name,p in r["A2_same_budget"].items()))
        save_table("sweep_summary.csv",({"value":r["value"],"independent_trajectories":r["independent_trajectories"],"valid_trajectories":r["valid_trajectories"],"mean_rmse":r["mean_rmse"],"gq_rmse":r["gq_rmse"]} for r in payload["sweep_summary"]))
    else:
        save_table("learning_history.csv",({"model_id":r["id"],"epoch":h["epoch"],"training_loss":h["training_loss"],"validation_loss":h["validation_loss"],"weights":json.dumps(h["weights"])} for r in payload["results"] for h in r["history"]))
        save_table("spatial_weights.csv",({"model_id":r["id"],"variant":r["variant"],"channel":i+1,"learned_weight":w,"equal_weight":r["equal_weights"][i],"gq_weight":r["gq_weights"][i],"difference_from_gq":r["weights_minus_gq"][i]} for r in payload["results"] if r["weights"] for i,w in enumerate(r["weights"])))
        save_table("predictions.csv",({"model_id":r["id"],"partition":partition,"scenario_id":sid,"truth":json.dumps(r[partition+"_predictions"]["truth"][i]),"prediction":json.dumps(r[partition+"_predictions"]["prediction"][i])} for r in payload["results"] for partition in ("validation","test") for i,sid in enumerate(r[partition+"_predictions"]["scenario_ids"])))
        save_table("regularization_validation.csv",({"seed":r["seed"],"training_subjects":r["training_subjects"],"model":r["model"],"variant":r["variant"],"lambda":r["lambda"],"validation_task_loss":r["validation_task_loss"]} for r in payload["regularization_validation"]))
        (folder/"scenario_manifest.json").write_text(json.dumps(payload["scenario_manifest"],indent=2),encoding="utf-8")
    units="macro F1 / dimensionless normalized weights" if payload.get("task")=="RESEARCH_LABEL_CLASSIFICATION" else "dimensionless envelope spatial average"
    title=f"Study {payload['study']} | SYNTHETIC MATHEMATICAL DATA | TEST\nDataset {payload['dataset_version'][:20]} | {units}"
    figures=[]
    if payload["study"]=="A":
        figure,axes=plt.subplots(2,2,figsize=(12,8));first=next((s for s in payload["scenarios"] if s["configuration"]["function"]=="MOVING_PEAK"),payload["scenarios"][0])
        for name,key in (("Reference","reference_curve"),("Equal mean","mean_curve"),("GQ","gq_curve")):
            if first[key] is not None:axes[0,0].plot(first["time_seconds"],first[key],label=name)
        axes[0,0].set(xlabel="Time (s)",ylabel="Spatial average",title=f'{first["configuration"]["function"]}; n={first["configuration"]["sensors"]}; width={first["configuration"]["peak_width"]}');axes[0,0].legend()
        for method in ("mean","gq"):
            axes[0,1].plot([r["value"] for r in payload["sweep_summary"]],[r[method+"_rmse"] for r in payload["sweep_summary"]],"o-",label=method)
        axes[0,1].set(xlabel=payload["configuration"]["sweep_parameter"],ylabel="RMSE (envelope units)");axes[0,1].legend()
        field=first["field"];heatmap=axes[1,0].imshow(field["amplitude"],aspect="auto",origin="lower",extent=[0,first["time_seconds"][-1],-1,1]);axes[1,0].set(xlabel="Time (s)",ylabel="Normalized spatial coordinate");figure.colorbar(heatmap,ax=axes[1,0],label="Envelope amplitude")
        placements=first["A2_same_budget"]
        means=[]
        for name in placements:
            valid=[s["A2_same_budget"][name]["metrics"]["rmse"] for s in payload["scenarios"] if s["A2_same_budget"][name]["metrics"]["rmse"] is not None]
            means.append(float(np.mean(valid)) if valid else float("nan"))
        axes[1,1].bar(list(placements),means);axes[1,1].tick_params(axis="x",rotation=20);axes[1,1].set(ylabel="A2 RMSE (envelope units)",title=f'Mean across {len(payload["scenarios"])} held-out trajectories')
        figures.append(("study_a",figure))
    else:
        figure,axes=plt.subplots(2,2,figsize=(12,8));results=payload["results"];metric="rmse" if payload["task"]=="INTEGRAL_REGRESSION" else "macro_f1"
        exemplar=results[0];subset=[r for r in results if r["model"]==exemplar["model"] and r["training_subjects"]==exemplar["training_subjects"] and r.get("sensors")==exemplar.get("sensors") and r.get("noise")==exemplar.get("noise") and r.get("position_std")==exemplar.get("position_std")]
        variant_names=list(dict.fromkeys(r["variant"] for r in subset))
        for i,variant in enumerate(variant_names):
            group=[r for r in subset if r["variant"]==variant];axes[0,0].bar(i,np.mean([r["test"][metric] for r in group]))
            weights=[r["weights"] for r in group if r["weights"]]
            if weights:axes[0,1].plot(range(1,len(weights[0])+1),np.mean(weights,axis=0),"o-",label=variant)
        axes[0,0].set_xticks(range(len(variant_names)),[v.replace("_"," ") for v in variant_names],rotation=25,ha="right",fontsize=7)
        axes[0,0].set(ylabel="Test "+metric,title=f'{exemplar["model"]}: mean across {len(payload["configuration"]["seeds"])} repeats')
        axes[0,1].set(xlabel="Channel",ylabel="Mean normalized spatial weight");axes[0,1].legend(fontsize=7)
        histories=next((r["history"] for r in results if len(r["history"])>1),[])
        if histories:
            for name in ("training_loss","validation_loss"):axes[1,0].plot([r["epoch"] for r in histories],[r[name] for r in histories],label=name)
            axes[1,0].legend();axes[1,0].set(xlabel="Epoch",ylabel="Task loss")
        candidates=[r for r in payload["regularization_validation"] if r["variant"]=="GQ_REGULARIZED" and r["model"]==payload["configuration"]["models"][0] and r["seed"]==exemplar["seed"] and r["training_subjects"]==exemplar["training_subjects"] and r.get("sensors")==exemplar.get("sensors") and r.get("noise")==exemplar.get("noise") and r.get("position_std")==exemplar.get("position_std")]
        if candidates:axes[1,1].scatter([r["lambda"] for r in candidates],[r["validation_task_loss"] for r in candidates])
        axes[1,1].set(xlabel="Lambda",ylabel="Validation task loss (no test selection)",title=f'First repeat (seed {exemplar["seed"]}); fixed learning rate');figures.append(("study_b",figure))
    for name,figure in figures:
        figure.suptitle(title,fontsize=10,y=.99,va="top");figure.tight_layout(rect=(0,.02,1,.9));figure.savefig(folder/f"{name}.svg");figure.savefig(folder/f"{name}.png",dpi=300);plt.close(figure)
    (folder/"methodology.txt").write_text("FlexMap software research\n"+title+"\n"+json.dumps({"configuration":configuration,"limitations":payload["limitations"],"code_version":revision},indent=2)+"\nStudy A: domain-average targets; A1 same observations, A2 same sensor budget.\nStudy B: lambda/epochs chosen with validation only; held-out test reported separately.\nNo clinical or physical validation.\n",encoding="utf-8")
    manifest=[{"name":p.relative_to(folder).as_posix(),"sha256":hashlib.sha256(p.read_bytes()).hexdigest(),"byte_size":p.stat().st_size} for p in sorted(folder.rglob("*")) if p.is_file()]
    (folder/"artifact_manifest.json").write_text(json.dumps(manifest,indent=2),encoding="utf-8")
    return manifest


def package(folder):
    out=io.BytesIO()
    with zipfile.ZipFile(out,"w",zipfile.ZIP_DEFLATED) as archive:
        for path in sorted(folder.rglob("*")):
            if path.is_file():archive.write(path,path.relative_to(folder).as_posix())
    return out.getvalue()
