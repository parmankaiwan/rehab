import json,time
from pathlib import Path
from types import SimpleNamespace
import pytest
from fastapi import HTTPException
from backend import ml

@pytest.fixture()
def ml_store(tmp_path,monkeypatch):
 monkeypatch.setattr(ml,"DB_PATH",tmp_path/"dataset.db");monkeypatch.setattr(ml,"ML_DATA_ROOT",tmp_path/"ml");ml.ML_DATA_ROOT.mkdir();ml.initialize();ml.ensure_pipelines();records={}
 for subject in range(1,7):
  for label_index,label in enumerate(("FORWARD_REACH","RETURN")):
   rid=f"REC-TEST-{subject:02d}-{label_index}";base=tmp_path/rid;base.mkdir();(base/"measurements.json").write_text(json.dumps({"samples":[{"ready":True},{"ready":False}]}));(base/"metadata.json").write_text("{}")
   records[rid]={"recording_id":rid,"subject_id":f"P{subject:03d}","session_id":f"S{subject:03d}","rehab_type":"REACHING","category":"REACHING","modality":"CV","research_label":label,"label":label,"affected_side":"RIGHT","review_status":"APPROVED","technical_quality":"GOOD","training_eligible":True,"excluded":False,"is_mock":False,"relative_path":str(base),"duration_seconds":5.0+label_index,"frame_count":100+subject,"pose_result_count":50+subject,"tracking_good_ratio":.8+subject/100,"tracking_poor_ratio":.1,"tracking_lost_ratio":.1-subject/100,"metadata":{"pose_result_rate_hz":10+subject,"actual_recorded_fps":20+subject},"artifact_references":{"measurements.json":{"sha256":rid}},"schema_versions":{"dataset":"3.0","cv":"2.0"}}
 original_settings=ml.dataset_settings
 class Settings:
  root=tmp_path
 monkeypatch.setattr(ml,"dataset_settings",lambda:Settings())
 monkeypatch.setattr(ml,"unified_recording",lambda rid:records.get(rid))
 return records

def frozen_dataset(records):
 draft=ml.dataset_from_vault(ml.DatasetFromVault(recording_ids=list(records),name="REACHING_CV_TEST"));return ml.freeze_dataset(draft["dataset_version_id"])

def test_dataset_freeze_manifest_hash_and_immutable_membership(ml_store):
 dataset=frozen_dataset(ml_store);assert dataset["status"]=="FROZEN";assert len(dataset["manifest_sha256"])==64
 base=ml.ML_DATA_ROOT/"datasets"/dataset["dataset_version_id"]
 assert (base/"dataset_manifest.csv").is_file();assert (base/"dataset_manifest.json").is_file();assert len(dataset["recording_ids"])==12
 first_id=next(iter(ml_store));frozen_label=json.loads((base/"dataset_manifest.json").read_text())[0]["research_label"]
 ml_store[first_id]["review_status"]="EXCLUDED";ml_store[first_id]["research_label"]="CHANGED_AFTER_FREEZE"
 assert ml.get_dataset(dataset["dataset_version_id"])["recording_ids"]==dataset["recording_ids"]
 assert json.loads((base/"dataset_manifest.json").read_text())[0]["research_label"]==frozen_label

def test_mixed_modality_and_ineligible_data_are_rejected(ml_store):
 first=next(iter(ml_store.values()));first["modality"]="EMG"
 with pytest.raises(HTTPException) as error:ml.dataset_from_vault(ml.DatasetFromVault(recording_ids=list(ml_store),name="MIXED"))
 assert error.value.status_code==422;assert "MULTIPLE_MODALITIES_SELECTED" in str(error.value.detail)

def test_subject_grouped_split_has_zero_leakage(ml_store):
 dataset=frozen_dataset(ml_store);split=ml.create_split(ml.SplitRequest(dataset_version_id=dataset["dataset_version_id"],seed=42))
 assert split["leakage"]["passed"] is True
 groups={}
 for row in split["assignments"]:groups.setdefault(row["subject_id"],set()).add(row["split"])
 assert all(len(value)==1 for value in groups.values())

def test_supabase_cv_and_emg_records_are_normalized(monkeypatch):
 monkeypatch.setattr(ml.browser_collections,"get_sample",lambda *_args,**_kwargs:{"sample_id":"SMP-cloud","dataset_id":"DS-1","label_at_capture":"reach","reviewed_label":"return","subject_id":"P001","review_status":"APPROVED","training_eligible":True,"technical_quality":"GOOD","persistence_status":"STORED","artifact_manifest":[],"metadata":{"rehabilitation_module_id":"REACHING"}})
 cv=ml._cloud_cv("SMP-cloud");assert cv["recording_id"]=="SMP-cloud";assert cv["research_label"]=="return";assert cv["source_backend"]=="SUPABASE_CV"
 monkeypatch.setattr(ml.cloud_emg_vault,"get_recording",lambda *_args,**_kwargs:{"recording_id":"EMG-cloud","dataset_id":"EDS-1","subject_code":"P002","research_label":"contract","review_status":"APPROVED","training_eligible":True,"technical_quality":"GOOD","persistence_status":"STORED","artifacts":[]})
 emg=ml._cloud_emg("EMG-cloud");assert emg["subject_id"]=="P002";assert emg["source_backend"]=="SUPABASE_EMG"

def test_related_trials_remain_in_one_partition(ml_store):
 values=list(ml_store.values());values[0]["collection_id"]="SHARED";values[2]["collection_id"]="SHARED"
 dataset=frozen_dataset(ml_store);split=ml.create_split(ml.SplitRequest(dataset_version_id=dataset["dataset_version_id"],seed=42))
 shared={x["split"] for x in split["assignments"] if x["related_trial_group"]=="SHARED"}
 assert len(shared)==1;assert split["leakage"]["related_trial_overlap"]=={}

def test_vault_delete_requires_confirmation_and_calls_modality_store(ml_store,monkeypatch):
 rid=next(iter(ml_store));deleted=[];monkeypatch.setattr(ml,"vault",SimpleNamespace(delete=lambda value:deleted.append(value)))
 with pytest.raises(HTTPException) as mismatch:ml.delete_vault_recording(rid,"WRONG")
 assert mismatch.value.status_code==422
 assert ml.delete_vault_recording(rid,rid)=={"success":True,"recording_id":rid};assert deleted==[rid]

def test_vault_delete_blocks_recordings_in_frozen_datasets(ml_store,monkeypatch):
 dataset=frozen_dataset(ml_store);rid=dataset["recording_ids"][0];deleted=[];monkeypatch.setattr(ml,"vault",SimpleNamespace(delete=lambda value:deleted.append(value)))
 with pytest.raises(HTTPException) as blocked:ml.delete_vault_recording(rid,rid)
 assert blocked.value.status_code==409;assert "frozen dataset" in blocked.value.detail;assert deleted==[]

@pytest.mark.parametrize("model_type",["RANDOM_FOREST","LOGISTIC_REGRESSION"])
def test_background_training_evaluation_and_registry(ml_store,model_type):
 dataset=frozen_dataset(ml_store);split=ml.create_split(ml.SplitRequest(dataset_version_id=dataset["dataset_version_id"],seed=42))
 for record in ml_store.values():record["research_label"]="CHANGED_AFTER_FREEZE"
 run=ml.create_run(ml.RunRequest(dataset_version_id=dataset["dataset_version_id"],split_id=split["split_id"],feature_pipeline_id="FP-CV-KINEMATICS-V1",model_type=model_type,warnings_acknowledged=True))
 for _ in range(100):
  run=ml.get_run(run["training_run_id"])
  if run["status"] not in ("QUEUED","RUNNING"):break
  time.sleep(.05)
 assert run["status"]=="COMPLETED",run.get("error");assert {"accuracy","balanced_accuracy","precision_macro","recall_macro","f1_macro","confusion_matrix"}<=run["metrics"].keys();assert run["predictions"]
 assert run["metrics"]["evaluation_scope"]=="RESEARCH";assert run["metrics"]["validation"] is not None;assert run["metrics"]["test"] is not None
 assert {x["recording_id"] for x in run["predictions"] if x["split"]=="VALIDATION"}.isdisjoint({x["recording_id"] for x in run["predictions"] if x["split"]=="TEST"})
 base=Path(run["artifact_dir"]);assert (base/"model.joblib").is_file();assert (base/"predictions.csv").is_file()
 model=ml.register_model(ml.RegisterRequest(training_run_id=run["training_run_id"]));assert model["status"]=="EXPERIMENTAL";assert model["training_run_id"]==run["training_run_id"]

def test_insufficient_subject_run_is_explicitly_development_only(ml_store):
 selected={key:value for key,value in ml_store.items() if value["subject_id"]=="P001"}
 dataset=frozen_dataset(selected);split=ml.create_split(ml.SplitRequest(dataset_version_id=dataset["dataset_version_id"],development_only=True))
 run=ml.create_run(ml.RunRequest(dataset_version_id=dataset["dataset_version_id"],split_id=split["split_id"],feature_pipeline_id="FP-CV-KINEMATICS-V1",model_type="LOGISTIC_REGRESSION",warnings_acknowledged=True))
 for _ in range(100):
  run=ml.get_run(run["training_run_id"])
  if run["status"] not in ("QUEUED","RUNNING"):break
  time.sleep(.05)
 assert run["status"]=="COMPLETED";assert run["evaluation_scope"]=="DEVELOPMENT_ONLY"
 assert run["metrics"]["validation"] is None and run["metrics"]["test"] is None
 assert run["metrics"]["development_training"]["evaluation_samples"]==2
