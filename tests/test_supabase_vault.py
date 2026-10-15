from __future__ import annotations

import json
from pathlib import Path

import httpx

from backend.supabase_vault import SupabaseVaultConfig, SupabaseVaultMirror


def config(**overrides):
    values = {
        "url": "https://project.supabase.co",
        "secret_key": "sb_secret_test-never-return-this",
        "enabled": True,
        "upload_artifacts": False,
    }
    values.update(overrides)
    return SupabaseVaultConfig(**values)


def test_public_status_never_exposes_secret():
    mirror = SupabaseVaultMirror(config())
    status = mirror.public_status()
    assert status["configured"] is True
    assert status["project_host"] == "project.supabase.co"
    assert "secret" not in json.dumps(status).lower()
    assert "sb_secret_test" not in json.dumps(status)


def test_sync_upserts_recording_with_server_authorization():
    requests = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(201)

    mirror = SupabaseVaultMirror(config(), transport=httpx.MockTransport(handler))
    result = mirror.sync_recording(
        {
            "recording_id": "REC-20261015-000001",
            "modality": "CV",
            "subject_id": "P001",
            "category": "REACHING",
            "label": "FORWARD",
            "training_eligible": True,
            "metadata": {"dataset_schema_version": "3.0"},
        }
    )
    assert result == {
        "recording_id": "REC-20261015-000001",
        "status": "SYNCED",
        "artifacts_uploaded": 0,
    }
    request = requests[0]
    assert request.url.path == "/rest/v1/flexmap_dataset_recordings"
    assert request.headers["authorization"].startswith("Bearer sb_secret_")
    assert request.headers["prefer"] == "resolution=merge-duplicates,return=minimal"
    payload = json.loads(request.content)
    assert payload["recording_id"] == "REC-20261015-000001"
    assert payload["research_label"] == "FORWARD"


def test_optional_private_artifact_upload_precedes_metadata(tmp_path: Path):
    folder = tmp_path / "recording"
    folder.mkdir()
    (folder / "metadata.json").write_text("{}", encoding="utf-8")
    paths = []

    def handler(request: httpx.Request) -> httpx.Response:
        paths.append(request.url.path)
        return httpx.Response(200 if request.url.path.startswith("/storage/") else 201)

    mirror = SupabaseVaultMirror(
        config(upload_artifacts=True), transport=httpx.MockTransport(handler)
    )
    result = mirror.sync_recording(
        {"recording_id": "EMG-1", "modality": "EMG", "metadata": {}}, folder
    )
    assert result["artifacts_uploaded"] == 1
    assert paths[0] == "/storage/v1/object/flexmap-dataset/emg/EMG-1/metadata.json"
    assert paths[-1] == "/rest/v1/flexmap_dataset_recordings"


def test_disabled_sync_makes_no_request():
    def handler(_: httpx.Request) -> httpx.Response:
        raise AssertionError("disabled mirror must not access the network")

    mirror = SupabaseVaultMirror(
        config(enabled=False), transport=httpx.MockTransport(handler)
    )
    assert mirror.sync_recording({"recording_id": "REC-1"})["status"] == "DISABLED"
