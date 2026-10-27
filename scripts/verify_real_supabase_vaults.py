"""Real-project dual-vault acceptance test using synthetic, non-patient data.

The script loads the repository-root .env but never prints credentials. It is
intentionally not part of the mock unit suite and exits non-zero on any failed
database, Storage, restart-persistence, or modality-isolation assertion.
"""
from __future__ import annotations

import base64
import json
import hashlib
import gc
import os
import subprocess
import sys
import tempfile
import uuid
from pathlib import Path

import httpx
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
load_dotenv(ROOT / ".env")

from backend.browser_collection import (  # noqa: E402
    ArtifactUpload,
    BrowserCollectionRepository,
    BrowserDatasetCreate,
    BrowserLabelCreate,
    BrowserSampleMetadata,
    BrowserSampleUpdate,
)
from backend.emg.cloud_vault import (  # noqa: E402
    EmgCloudVault,
    EmgDatasetCreate,
    EmgLabelCreate,
    EmgRecordingUpdate,
)
from backend.supabase_vault import SupabaseVaultConfig  # noqa: E402


TINY_PNG = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+A8AAQUBAScY42YAAAAASUVORK5CYII="
)


def main() -> int:
    config = SupabaseVaultConfig.from_env()
    config.validate()
    if config.url.rstrip('/') != 'https://luhrcmbtijdtbmqzommk.supabase.co':
        raise RuntimeError('Refusing to create fixtures in an unexpected Supabase project')
    marker = uuid.uuid4().hex[:10]

    cv = BrowserCollectionRepository(config)
    cv_dataset = cv.create_dataset(BrowserDatasetCreate(
        name=f"Synthetic CV acceptance {marker}",
        rehabilitation_module_id="REACHING",
        description="Automated real-Supabase acceptance fixture; no patient data.",
        initial_label_name="neutral",
        initial_label_display_name="Neutral",
        permitted_capture_types="STILL",
    ))
    cv_label = cv.create_label(cv_dataset["dataset_id"], BrowserLabelCreate(name="reaching", display_name="Reaching"))
    cv_sample = cv.save_sample(
        BrowserSampleMetadata(
            dataset_id=cv_dataset["dataset_id"], label_id=cv_label["label_id"], label_at_capture="reaching",
            sample_type="STILL", source="BROWSER_MEDIAPIPE", subject_id=f"SYNTHETIC_{marker}",
            technical_quality="GOOD", tracking_quality="GOOD", wall_clock_created_at="2026-10-18T00:00:00Z",
            performance_time_origin_ms=1000, monotonic_start_ms=10, monotonic_end_ms=20,
            observed_duration_ms=10, media_mime_type="image/png", media_extension=".png", width=1, height=1,
            model_configuration={"fixture": True}, permission_scope={"raw_media": True}, observation_count=1,
        ),
        [ArtifactUpload("image.png", "image/png", TINY_PNG), ArtifactUpload("pose_observations.json", "application/json", b"[]")],
        f"cv-real-{marker}",
    )
    cv.update_sample(cv_sample["sample_id"], BrowserSampleUpdate(reviewed_label="neutral", review_status="REJECTED", training_eligible=False, notes="Synthetic reject/relabel acceptance"))
    assert cv.get_sample(cv_sample["sample_id"])["review_status"] == "REJECTED"
    cv.update_sample(cv_sample["sample_id"], BrowserSampleUpdate(reviewed_label="reaching", review_status="APPROVED", training_eligible=True, notes="Synthetic acceptance"))
    cv.set_sample_trashed(cv_sample["sample_id"], True)
    assert cv.get_sample(cv_sample["sample_id"]) is None
    cv.set_sample_trashed(cv_sample["sample_id"], False)
    # Restore is deliberately conservative: training eligibility must be
    # explicitly re-approved after an item leaves trash.
    cv.update_sample(cv_sample["sample_id"], BrowserSampleUpdate(review_status="APPROVED", training_eligible=True, notes="Re-approved after restore"))
    cv_restarted = BrowserCollectionRepository(SupabaseVaultConfig.from_env())
    cv_retrieved = cv_restarted.get_sample(cv_sample["sample_id"])
    assert cv_retrieved and cv_retrieved["review_status"] == "APPROVED" and cv_retrieved["training_eligible"]
    cv_bytes, cv_status, _ = cv_restarted.artifact(cv_sample["sample_id"], "image.png")
    assert cv_status == 200 and cv_bytes == TINY_PNG

    emg = EmgCloudVault(config)
    emg_dataset = emg.create_dataset(EmgDatasetCreate(
        name=f"Synthetic EMG acceptance {marker}", description="Automated real-Supabase acceptance fixture; no patient data.",
        muscle_under_study="synthetic_signal", initial_label_name="rest", initial_label_display_name="Rest",
    ))
    emg.create_label(emg_dataset["dataset_id"], EmgLabelCreate(name="active", display_name="Active"))
    with tempfile.TemporaryDirectory(prefix="flexmap-emg-") as temporary:
        folder = Path(temporary)
        (folder / "emg_raw.csv").write_text("timestamp_ms,channel_1\n0,100\n1,120\n2,90\n", encoding="utf-8")
        (folder / "metadata.json").write_text(json.dumps({"fixture": True}), encoding="utf-8")
        emg_record = emg.save_recording({
            "recording_id": f"EMG-SYNTHETIC-{marker}", "dataset_id": emg_dataset["dataset_id"],
            "research_label": "rest", "subject_id": f"SYNTHETIC_{marker}", "session_id": f"SESSION_{marker}",
            "channel_count": 1, "sample_count": 3, "duration_seconds": 0.003,
            "metadata": {"raw_units": "ADC_COUNTS", "dataset_id": emg_dataset["dataset_id"]},
        }, folder)
    emg.update_recording(emg_record["recording_id"], EmgRecordingUpdate(review_status="REJECTED", training_eligible=False, review_notes="Synthetic rejection acceptance"))
    assert emg.get_recording(emg_record["recording_id"])["review_status"] == "REJECTED"
    emg.update_recording(emg_record["recording_id"], EmgRecordingUpdate(research_label="active", review_status="APPROVED", review_notes="Synthetic acceptance", training_eligible=True, excluded=False))
    emg.set_recording_trashed(emg_record["recording_id"], True)
    assert all(item["recording_id"] != emg_record["recording_id"] for item in emg.list_recordings(emg_dataset["dataset_id"]))
    emg.set_recording_trashed(emg_record["recording_id"], False)
    emg.update_recording(emg_record["recording_id"], EmgRecordingUpdate(review_status="APPROVED", review_notes="Re-approved after restore", training_eligible=True))
    emg_restarted = EmgCloudVault(SupabaseVaultConfig.from_env())
    emg_retrieved = emg_restarted.get_recording(emg_record["recording_id"])
    waveform = emg_restarted.waveform(emg_record["recording_id"], max_points=100)
    assert emg_retrieved["review_status"] == "APPROVED" and emg_retrieved["training_eligible"]
    assert [row["channel_1"] for row in waveform["samples"]] == ["100", "120", "90"]

    assert cv_retrieved["dataset_id"].startswith("DS-") and emg_retrieved["dataset_id"].startswith("EDS-")
    assert all("flexmap-emg-vault" not in item["object_path"] for item in cv_retrieved["artifact_manifest"])
    assert all("flexmap-cv-vault" not in item["object_path"] for item in emg_retrieved["artifacts"])

    unauthenticated = httpx.get(f"{config.url}/rest/v1/flexmap_browser_datasets?select=dataset_id", timeout=10)
    assert unauthenticated.status_code in {401, 403}

    # Only fixture records are changed: prevent synthetic samples entering training.
    cv.update_sample(cv_sample['sample_id'], BrowserSampleUpdate(training_eligible=False, notes='Synthetic acceptance fixture; never use for human-research training'))
    emg.update_recording(emg_record['recording_id'], EmgRecordingUpdate(training_eligible=False, excluded=True, exclusion_reason='Synthetic acceptance fixture'))

    # Separate API processes, not merely new repository objects. Each process
    # starts with an empty local vault and must retrieve the real cloud artifacts.
    child_env = os.environ.copy()
    child_env['FLEXMAP_DATA_BACKEND'] = 'supabase'
    child_env['FLEXMAP_MASTER_INTERNAL_TOKEN'] = uuid.uuid4().hex
    command = [sys.executable, str(Path(__file__).resolve()), '--verify-persisted', cv_sample['sample_id'], emg_record['recording_id']]
    first = subprocess.run(command, env=child_env, capture_output=True, text=True, timeout=90)
    second = subprocess.run(command, env=child_env, capture_output=True, text=True, timeout=90)
    if first.returncode or second.returncode:
        raise RuntimeError('Fresh-process API persistence verification failed; credentials and private responses suppressed')
    first_result, second_result = json.loads(first.stdout), json.loads(second.stdout)
    assert first_result == second_result

    report = {
        "state": "PASS", "project": "luhrcmbtijdtbmqzommk", "marker": marker,
        "cv": {"dataset_id": cv_dataset["dataset_id"], "sample_id": cv_sample["sample_id"], "artifact_verified": True, "restart_verified": True, "trash_restore_verified": True},
        "emg": {"dataset_id": emg_dataset["dataset_id"], "recording_id": emg_record["recording_id"], "waveform_points": len(waveform["samples"]), "restart_verified": True, "trash_restore_verified": True},
        "cross_vault_isolation": True, "unauthorized_access_blocked": True,
        "fixtures_excluded_from_training": True,
        "fresh_api_process_persistence": first_result,
    }
    report_path = ROOT / 'data' / 'runtime' / 'real-vault-verification' / f'{marker}.json'
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(report, indent=2), encoding='utf-8')
    print(json.dumps(report, indent=2))
    return 0


def verify_persisted(cv_id: str, emg_id: str) -> int:
    with tempfile.TemporaryDirectory(prefix='flexmap-persistence-api-') as temporary:
        os.environ['FLEXMAP_DATASET_ROOT'] = temporary
        from fastapi.testclient import TestClient
        from backend.app import app
        with TestClient(app) as client:
            headers = {'x-flexmap-master-token': os.environ['FLEXMAP_MASTER_INTERNAL_TOKEN']}
            cv_path = f'/api/master/browser-collections/samples/{cv_id}'
            emg_path = f'/api/master/emg/cloud-recordings/{emg_id}'
            cv_response = client.get(cv_path, headers=headers)
            emg_response = client.get(emg_path, headers=headers)
            assert cv_response.status_code == emg_response.status_code == 200
            image = client.get(f'{cv_path}/artifacts/image.png', headers=headers)
            waveform = client.get(f'{emg_path}/waveform', headers=headers)
            assert image.status_code == waveform.status_code == 200
            assert image.content == TINY_PNG
            assert [row['channel_1'] for row in waveform.json()['samples']] == ['100', '120', '90']
            assert client.get(cv_path).status_code in (401,403)
            assert client.get(emg_path).status_code in (401,403)
            assert cv_response.json()['training_eligible'] is False
            assert emg_response.json()['training_eligible'] is False
            assert client.get(f'/api/master/browser-collections/samples/{emg_id}', headers=headers).status_code == 404
            assert client.get(f'/api/master/emg/cloud-recordings/{cv_id}', headers=headers).status_code == 404
            print(json.dumps({'cv_id': cv_id, 'emg_id': emg_id, 'cv_sha256': hashlib.sha256(image.content).hexdigest(), 'waveform_sha256': hashlib.sha256(waveform.content).hexdigest(), 'unauthorized_blocked': True}))
        # sqlite3 connection context managers commit but do not close; collect
        # unreachable initialization handles before Windows removes the test DB.
        gc.collect()
    return 0


if __name__ == "__main__":
    if len(sys.argv) == 4 and sys.argv[1] == '--verify-persisted':
        raise SystemExit(verify_persisted(sys.argv[2], sys.argv[3]))
    raise SystemExit(main())
