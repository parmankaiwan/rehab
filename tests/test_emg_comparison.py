import time

import joblib
import numpy as np
from fastapi.testclient import TestClient

from backend.app import app
from backend import emg_comparison
from backend.emg_deep import load_classifier


def _headers():
    return {"X-FlexMap-Master-Token": "test-master-token"}


def test_catalog_and_simulation_are_explicit_about_runtime(monkeypatch, tmp_path):
    monkeypatch.setenv("FLEXMAP_MASTER_INTERNAL_TOKEN", "test-master-token")
    client = TestClient(app)
    catalog = client.get("/api/master/ml/emg-comparison/catalog", headers=_headers())
    assert catalog.status_code == 200
    body = catalog.json()
    assert "1 channel" in body["hardware_limit"]
    assert any(item["id"] == "CNN_1D" and item["eligible"] for item in body["models"])
    result = client.post("/api/master/ml/emg-comparison/simulation", headers=_headers(), json={"function": "LINEAR", "order": 3, "frames": 30})
    assert result.status_code == 200
    assert result.json()["reference"]["available"] is True


def test_matched_comparison_persists_results_and_exports(monkeypatch, tmp_path):
    monkeypatch.setenv("FLEXMAP_MASTER_INTERNAL_TOKEN", "test-master-token")
    monkeypatch.setattr(emg_comparison, "DB_PATH", tmp_path / "comparison.sqlite3")
    monkeypatch.setattr(emg_comparison, "ROOT", tmp_path / "artifacts")
    emg_comparison.ROOT.mkdir()
    emg_comparison.initialize()
    client = TestClient(app)
    response = client.post(
        "/api/master/ml/emg-comparison/experiments",
        headers=_headers(),
        json={"name": "paired regression", "subjects": 9, "epochs": 6, "models": ["RANDOM_FOREST", "MLP"], "methods": ["ARITHMETIC_MEAN", "GAUSSIAN_QUADRATURE"]},
    )
    assert response.status_code == 200
    identifier = response.json()["experiment_id"]
    for _ in range(100):
        item = client.get(f"/api/master/ml/emg-comparison/experiments/{identifier}", headers=_headers()).json()
        if item["status"] in {"COMPLETED", "FAILED"}:
            break
        time.sleep(0.05)
    assert item["status"] == "COMPLETED", item.get("error")
    results = item["results"]["results"]
    assert len(results) == 4
    assert {row["controlled_pair_key"] for row in results} == {"RANDOM_FOREST", "MLP"}
    assert {row["mathematical_method"] for row in results} == {"ARITHMETIC_MEAN", "GAUSSIAN_QUADRATURE"}
    assert all(row["evaluation_scope"] == "DEVELOPMENT_ONLY" for row in results)
    assert len(item["results"]["statistical_comparisons"]) == 2
    assert all(pair["paired_subject_bootstrap_ci95"] is None for pair in item["results"]["statistical_comparisons"])
    assert all(pair["uncertainty_status"] == "INSUFFICIENT_INDEPENDENT_UNITS" for pair in item["results"]["statistical_comparisons"])
    assert all(row["validation"]["macro_f1_ci95"] is None for row in results)
    assert item["results"]["data_readiness"]["display_message"] == "DEVELOPMENT ONLY — INSUFFICIENT REAL DATA"
    assert item["results"]["data_readiness"]["ranking_eligible"] is False
    emg_comparison.initialize()
    assert client.get(f"/api/master/ml/emg-comparison/experiments/{identifier}", headers=_headers()).json()["status"] == "COMPLETED"
    for extension in ("json", "csv", "zip"):
        export = client.get(f"/api/master/ml/emg-comparison/experiments/{identifier}/export.{extension}", headers=_headers())
        assert export.status_code == 200
        assert export.content


def test_real_one_channel_is_blocked(monkeypatch):
    monkeypatch.setenv("FLEXMAP_MASTER_INTERNAL_TOKEN", "test-master-token")
    client = TestClient(app)
    real = client.post("/api/master/ml/emg-comparison/experiments", headers=_headers(), json={"source_type": "REAL_EMG_VAULT"})
    assert real.status_code == 422


def test_real_vault_readiness_requires_classes_subjects_channels_and_geometry(monkeypatch):
    class FakeVault:
        class Config:
            configured = True
        config = Config()
        def list_recordings(self):
            return [{"subject_id": None, "research_label": "active", "channel_count": 1, "review_status": "APPROVED", "training_eligible": True, "excluded": False, "persistence_status": "STORED"}]
    monkeypatch.setattr(emg_comparison, "EmgCloudVault", FakeVault)
    readiness = emg_comparison._real_vault_readiness()
    assert readiness["usable_classes"] == 1
    assert readiness["independent_subjects"] == 0
    assert readiness["classification_eligible"] is False
    assert readiness["spatial_gq_eligible"] is False


def test_learned_and_raw_representations_are_real_and_disclosed():
    rows = emg_comparison._fixture({"seed": 7, "subjects": 9})
    learned, learned_meta = emg_comparison._representation(rows, "LEARNED_SPATIAL_WEIGHTS", 7)
    raw, raw_meta = emg_comparison._representation(rows, "RAW_MULTICHANNEL", 7)
    assert learned.shape == (18, 6)
    assert sum(learned_meta["weights"]) == 1
    assert learned_meta["selection"] == "TRAINING_SUBJECTS_ONLY_INNER_HOLDOUT"
    assert raw.shape == (18, 18)
    assert raw_meta["information_budget"] == "EXPANDED_RAW_MULTICHANNEL_BASELINE"


def test_subject_splits_do_not_leak_and_intervals_require_five_independent_units():
    rows = emg_comparison._fixture({"seed": 11, "subjects": 30})
    split_subjects = {name: {row["subject"] for row in rows if row["split"] == name} for name in ("TRAIN", "VALIDATION", "TEST")}
    assert split_subjects["TRAIN"].isdisjoint(split_subjects["VALIDATION"])
    assert split_subjects["TRAIN"].isdisjoint(split_subjects["TEST"])
    assert split_subjects["VALIDATION"].isdisjoint(split_subjects["TEST"])
    truth = np.asarray(["REST", "ACTIVATION"] * 6)
    groups = np.asarray([f"S-{index}" for index in range(6) for _ in range(2)])
    score = emg_comparison._score_predictions(truth, truth.copy(), 0.01, groups, 11)
    assert score["macro_f1_ci95"]["unit"] == "SUBJECT"
    assert score["independent_subjects"] == 6


def test_pytorch_mlp_runs_inside_the_comparison_worker(monkeypatch, tmp_path):
    monkeypatch.setenv("FLEXMAP_MASTER_INTERNAL_TOKEN", "test-master-token")
    monkeypatch.setattr(emg_comparison, "DB_PATH", tmp_path / "deep.sqlite3")
    monkeypatch.setattr(emg_comparison, "ROOT", tmp_path / "deep-artifacts")
    emg_comparison.ROOT.mkdir(); emg_comparison.initialize()
    client = TestClient(app)
    created = client.post("/api/master/ml/emg-comparison/experiments", headers=_headers(), json={"models": ["MLP"], "methods": ["GAUSSIAN_QUADRATURE"], "subjects": 9, "epochs": 8})
    assert created.status_code == 200
    identifier = created.json()["experiment_id"]
    for _ in range(200):
        item = client.get(f"/api/master/ml/emg-comparison/experiments/{identifier}", headers=_headers()).json()
        if item["status"] in {"COMPLETED", "FAILED"}: break
        time.sleep(0.05)
    assert item["status"] == "COMPLETED", item.get("error")
    result = item["results"]["results"][0]
    assert result["deep_learning"]["framework"] == "PYTORCH"
    assert result["training_history"]
    assert (tmp_path / "deep-artifacts" / identifier / "GAUSSIAN_QUADRATURE-MLP.pt").is_file()


def test_all_required_models_train_for_matched_mean_and_gq_and_reload(monkeypatch, tmp_path):
    monkeypatch.setenv("FLEXMAP_MASTER_INTERNAL_TOKEN", "test-master-token")
    monkeypatch.setattr(emg_comparison, "DB_PATH", tmp_path / "all-models.sqlite3")
    monkeypatch.setattr(emg_comparison, "ROOT", tmp_path / "all-model-artifacts")
    emg_comparison.ROOT.mkdir(); emg_comparison.initialize()
    client = TestClient(app)
    models = ["RANDOM_FOREST", "MLP", "CNN_1D", "TCN", "GRU"]
    methods = ["ARITHMETIC_MEAN", "GAUSSIAN_QUADRATURE"]
    created = client.post(
        "/api/master/ml/emg-comparison/experiments",
        headers=_headers(),
        json={"models": models, "methods": methods, "subjects": 15, "epochs": 4, "seed": 23},
    )
    assert created.status_code == 200
    identifier = created.json()["experiment_id"]
    for _ in range(500):
        item = client.get(f"/api/master/ml/emg-comparison/experiments/{identifier}", headers=_headers()).json()
        if item["status"] in {"COMPLETED", "FAILED"}: break
        time.sleep(0.05)
    assert item["status"] == "COMPLETED", item.get("error")
    results = item["results"]["results"]
    assert {(row["model"], row["mathematical_method"]) for row in results} == {(model, method) for model in models for method in methods}
    assert all(row["dataset_version_id"] == "SYNTHETIC-SPATIAL-V1" for row in results)
    assert all(row["evaluation_scope"] == "DEVELOPMENT_ONLY" for row in results)
    base = tmp_path / "all-model-artifacts" / identifier
    for method in methods:
        assert joblib.load(base / f"{method}-RANDOM_FOREST.joblib")
        for architecture in ("MLP", "CNN_1D", "TCN", "GRU"):
            restored, payload = load_classifier(base / f"{method}-{architecture}.pt")
            assert restored is not None and payload["architecture"] == architecture
