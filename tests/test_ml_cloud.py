import hashlib
import json
from pathlib import Path

import httpx

from backend.ml_cloud import MlCloudRepository
from backend.supabase_vault import SupabaseVaultConfig


def repository(monkeypatch, handler):
    monkeypatch.setenv("FLEXMAP_ML_DURABLE_STORAGE_ENABLED", "true")
    config = SupabaseVaultConfig(url="https://project.supabase.co", secret_key="sb_secret_test")
    return MlCloudRepository(config, transport=httpx.MockTransport(handler))


def test_ml_cloud_status_never_exposes_key(monkeypatch):
    repo = repository(monkeypatch, lambda request: httpx.Response(200))
    status = repo.public_status()
    assert status["enabled"] is True
    assert "sb_secret" not in json.dumps(status)


def test_artifacts_are_uploaded_privately_and_checksum_verified(tmp_path, monkeypatch):
    payload = b"model"
    (tmp_path / "model.joblib").write_bytes(payload)
    paths = []

    def handler(request):
        paths.append(request.url.path)
        if request.method == "GET":
            return httpx.Response(200, content=payload)
        return httpx.Response(200)

    manifest = repository(monkeypatch, handler).upload_artifacts("RUN-1", tmp_path)
    assert paths == [
        "/storage/v1/object/flexmap-ml-vault/runs/RUN-1/model.joblib",
        "/storage/v1/object/authenticated/flexmap-ml-vault/runs/RUN-1/model.joblib",
    ]
    assert manifest[0]["sha256"] == hashlib.sha256(payload).hexdigest()


def test_durable_artifact_can_be_retrieved_after_local_loss(monkeypatch):
    payload = b"persisted-model"
    repo = repository(monkeypatch, lambda request: httpx.Response(200, content=payload))
    assert repo.download_artifact("runs/RUN-1/model.joblib", hashlib.sha256(payload).hexdigest()) == payload


def test_comparison_is_mirrored_to_private_storage_and_metadata(tmp_path, monkeypatch):
    payload = b"comparison-model"
    (tmp_path / "mean.joblib").write_bytes(payload)
    requests = []

    def handler(request):
        requests.append((request.method, request.url.path))
        if request.method == "GET":
            return httpx.Response(200, content=payload)
        return httpx.Response(201)

    experiment = {
        "experiment_id": "EMGCMP-1", "name": "comparison", "source_type": "SYNTHETIC_SIMULATION",
        "task": "RESEARCH_LABEL_CLASSIFICATION", "status": "COMPLETED", "configuration": {},
        "results": {"results": []}, "error": None, "created_at": "2026-10-19T00:00:00Z",
        "completed_at": "2026-10-19T00:01:00Z",
    }
    manifest = repository(monkeypatch, handler).persist_comparison(experiment, tmp_path)
    assert manifest[0]["object_path"] == "comparisons/EMGCMP-1/mean.joblib"
    assert ("POST", "/rest/v1/flexmap_emg_comparison_experiments") in requests
    assert all("sb_secret_test" not in path for _, path in requests)


def test_ml_migration_is_additive_backend_only_and_does_not_mutate_storage_metadata():
    sql = Path("supabase/migrations/202610190001_ml_training_v2.sql").read_text(encoding="utf-8").lower()
    assert "create table if not exists" in sql
    assert "enable row level security" in sql
    assert "revoke all" in sql and "from anon, authenticated" in sql
    assert "to service_role" in sql
    assert "public = true" not in sql
    assert "insert into storage.buckets" not in sql
    assert "delete from" not in sql
    assert "truncate " not in sql
    assert "drop table" not in sql
    assert "on delete cascade" not in sql
