from __future__ import annotations

import json
from pathlib import Path

import httpx
import pytest

from backend.emg.cloud_vault import EmgCloudVault, EmgDatasetCreate, EmgRecordingUpdate
from backend.supabase_vault import SupabaseVaultConfig


def config() -> SupabaseVaultConfig:
    return SupabaseVaultConfig(
        url="https://project.supabase.co",
        secret_key="sb_secret_synthetic-test",
        cv_bucket="flexmap-cv-vault",
        emg_bucket="flexmap-emg-vault",
        timeout_seconds=5,
    )


def test_create_dataset_uses_emg_tables_and_normalizes_initial_label():
    paths: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        paths.append(request.url.path)
        if request.method == "GET":
            return httpx.Response(200, json=[])
        return httpx.Response(201, json=[json.loads(request.content)])

    vault = EmgCloudVault(config(), transport=httpx.MockTransport(handler))
    result = vault.create_dataset(
        EmgDatasetCreate(
            name="Synthetic flexor study",
            description="Automated fixture only",
            muscle_under_study="wrist flexor",
            initial_label_name="Active Reach",
        )
    )

    assert result["dataset_id"].startswith("EDS-")
    assert result["labels"][0]["name"] == "active_reach"
    assert "/rest/v1/flexmap_emg_datasets" in paths
    assert "/rest/v1/flexmap_emg_labels" in paths
    assert all("browser" not in path and "cv_" not in path for path in paths)


@pytest.mark.parametrize("corrupt_remote", [False, True])
def test_recording_save_uses_private_emg_bucket_and_verified_state_machine(tmp_path: Path, corrupt_remote):
    recording_dir = tmp_path / "synthetic-recording"
    recording_dir.mkdir()
    (recording_dir / "emg_raw.csv").write_text("timestamp_ms,channel_1\n0,100\n1,120\n", encoding="utf-8")
    (recording_dir / "metadata.json").write_text('{"fixture":true}', encoding="utf-8")
    transitions: list[str] = []
    uploads: list[str] = []
    objects: dict[str, bytes] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if request.method == "GET" and path.startswith("/storage/v1/object/authenticated/"):
            return httpx.Response(200, content=b"corrupt" if corrupt_remote else objects[path.replace("/authenticated/", "/")])
        if request.method == "GET" and path.endswith("flexmap_emg_datasets"):
            return httpx.Response(200, json=[{"dataset_id": "EDS-synthetic"}])
        if request.method == "GET" and path.endswith("flexmap_emg_labels"):
            return httpx.Response(200, json=[{"label_id": "ELB-reach"}])
        if request.method == "GET" and path.endswith("flexmap_emg_recordings"):
            return httpx.Response(200, json=[])
        if request.method == "POST" and path.endswith("flexmap_emg_recordings"):
            body = json.loads(request.content)
            transitions.append(body["persistence_status"])
            return httpx.Response(201, json=[body])
        if request.method == "PATCH" and path.endswith("flexmap_emg_recordings"):
            body = json.loads(request.content)
            transitions.append(body["persistence_status"])
            stored = {"dataset_id": "EDS-synthetic", "recording_id": "EMG-synthetic", **body}
            return httpx.Response(200, json=[stored] if body["persistence_status"] == "STORED" else [])
        if request.method == "POST" and path.endswith("flexmap_emg_artifacts"):
            assert request.url.params["on_conflict"] == "object_path"
            assert request.headers["prefer"] == "resolution=merge-duplicates"
            return httpx.Response(201)
        if request.method == "POST" and path.startswith("/storage/v1/object/flexmap-emg-vault/"):
            uploads.append(path)
            objects[path] = request.read()
            assert request.headers["x-upsert"] == "true"
            return httpx.Response(200)
        raise AssertionError(f"unexpected request {request.method} {request.url}")

    vault = EmgCloudVault(config(), transport=httpx.MockTransport(handler))
    def save():
        return vault.save_recording(
        {
            "recording_id": "EMG-synthetic",
            "dataset_id": "EDS-synthetic",
            "research_label": "active_reach",
            "subject_id": "SYNTHETIC_001",
            "session_id": "SESSION_001",
            "channel_count": 1,
            "sample_count": 2,
            "duration_seconds": 0.002,
            "metadata": {"raw_units": "ADC_COUNTS"},
        },
        recording_dir,
    )

    if corrupt_remote:
        from backend.supabase_vault import SupabaseVaultError
        with pytest.raises(SupabaseVaultError, match="verification failed"):
            save()
        assert transitions == ["DRAFT", "UPLOADING", "FAILED"]
        return
    result = save()
    assert transitions == ["DRAFT", "UPLOADING", "VERIFYING", "STORED"]
    assert result["persistence_status"] == "STORED"
    assert uploads
    assert all("flexmap-cv-vault" not in path for path in uploads)
    assert all("/datasets/EDS-synthetic/recordings/EMG-synthetic/" in path for path in uploads)


def test_stored_idempotency_key_skips_artifact_upload(tmp_path: Path):
    existing = {"recording_id": "EMG-existing", "dataset_id": "EDS-one", "persistence_status": "STORED"}

    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if path.endswith("flexmap_emg_datasets"):
            return httpx.Response(200, json=[{"dataset_id": "EDS-one"}])
        if path.endswith("flexmap_emg_labels"):
            return httpx.Response(200, json=[{"label_id": "ELB-one"}])
        if path.endswith("flexmap_emg_recordings") and request.method == "GET":
            return httpx.Response(200, json=[existing])
        raise AssertionError("an idempotent retry must not write")

    vault = EmgCloudVault(config(), transport=httpx.MockTransport(handler))
    assert vault.save_recording(
        {"recording_id": "EMG-existing", "dataset_id": "EDS-one", "research_label": "rest", "metadata": {}},
        tmp_path,
    ) == existing


def test_cloud_only_recording_reopens_waveform_and_preserves_byte_range():
    csv_bytes = b"timestamp_ms,channel_1\n0,100\n1,120\n2,90\n"

    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if path.endswith("flexmap_emg_recordings"):
            return httpx.Response(200, json=[{"recording_id":"EMG-cloud","signal_units":"ADC_COUNTS","sample_rate_hz":1000,"duration_seconds":0.003}])
        if path.endswith("flexmap_emg_artifacts"):
            return httpx.Response(200, json=[{"artifact_id":"artifact-1","artifact_role":"RAW:emg_raw.csv","object_path":"datasets/EDS-one/recordings/EMG-cloud/raw/emg_raw.csv","content_type":"text/csv","byte_size":len(csv_bytes),"sha256":"0"*64,"processing_version":None}])
        if path.startswith("/storage/v1/object/authenticated/flexmap-emg-vault/"):
            if request.headers.get("range"):
                assert request.headers["range"] == "bytes=0-9"
                return httpx.Response(206, content=csv_bytes[:10], headers={"content-range":f"bytes 0-9/{len(csv_bytes)}","accept-ranges":"bytes","content-type":"text/csv"})
            return httpx.Response(200, content=csv_bytes, headers={"content-type":"text/csv"})
        raise AssertionError(request.url)

    vault = EmgCloudVault(config(), transport=httpx.MockTransport(handler))
    waveform = vault.waveform("EMG-cloud", max_points=2)
    content, status, headers = vault.read_artifact("EMG-cloud", "artifact-1", "bytes=0-9")

    assert waveform["raw_units"] == "ADC_COUNTS"
    assert waveform["sample_rate_hz"] == 1000
    assert [row["channel_1"] for row in waveform["samples"]] == ["100", "90"]
    assert status == 206 and content == csv_bytes[:10]
    assert headers["content-range"].startswith("bytes 0-9/")


def test_emg_relabel_approval_and_training_eligibility_are_audited():
    current = {
        "recording_id": "EMG-review",
        "dataset_id": "EDS-one",
        "research_label": "rest",
        "review_status": "REVIEW_REQUIRED",
        "training_eligible": False,
        "excluded": False,
        "revision": 2,
        "artifacts": [{"artifact_id": "artifact-1"}],
    }
    audits: list[dict] = []

    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if request.method == "GET" and path.endswith("flexmap_emg_labels"):
            return httpx.Response(200, json=[{"label_id": "ELB-active", "name": "active"}])
        if request.method == "PATCH" and path.endswith("flexmap_emg_recordings"):
            return httpx.Response(200, json=[{**current, **json.loads(request.content)}])
        if request.method == "POST" and path.endswith("flexmap_emg_review_audit"):
            audits.append(json.loads(request.content))
            return httpx.Response(201)
        raise AssertionError(f"unexpected request {request.method} {request.url}")

    vault = EmgCloudVault(config(), transport=httpx.MockTransport(handler))
    vault.get_recording = lambda _recording_id: current
    result = vault.update_recording(
        "EMG-review",
        EmgRecordingUpdate(research_label="active", review_status="APPROVED", review_notes="clean", training_eligible=True),
    )

    assert result["research_label"] == "active"
    assert result["label_id"] == "ELB-active"
    assert result["training_eligible"] is True
    assert result["revision"] == 3
    assert result["artifacts"] == current["artifacts"]
    assert audits[0]["action"] == "RELABELLED"


def test_emg_rejection_and_trash_force_exclusion_and_are_audited():
    current = {
        "recording_id": "EMG-reject",
        "dataset_id": "EDS-one",
        "research_label": "rest",
        "review_status": "APPROVED",
        "training_eligible": True,
        "excluded": False,
        "revision": 1,
        "trashed_at": None,
        "artifacts": [],
    }
    actions: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if request.method == "PATCH" and path.endswith("flexmap_emg_recordings"):
            return httpx.Response(200, json=[{**current, **json.loads(request.content)}])
        if request.method == "POST" and path.endswith("flexmap_emg_review_audit"):
            actions.append(json.loads(request.content)["action"])
            return httpx.Response(201)
        raise AssertionError(f"unexpected request {request.method} {request.url}")

    vault = EmgCloudVault(config(), transport=httpx.MockTransport(handler))
    vault.get_recording = lambda _recording_id: current
    rejected = vault.update_recording("EMG-reject", EmgRecordingUpdate(review_status="REJECTED"))
    trashed = vault.set_recording_trashed("EMG-reject", True)

    assert rejected["excluded"] is True and rejected["training_eligible"] is False
    assert trashed["trashed_at"] and trashed["training_eligible"] is False
    assert actions == ["REVIEW_UPDATED", "TRASHED"]
