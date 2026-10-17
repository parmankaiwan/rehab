import json

import httpx
import pytest

from backend.browser_collection import (
    ArtifactUpload,
    BrowserCollectionRepository,
    BrowserDatasetCreate,
    BrowserLabelCreate,
    BrowserSampleMetadata,
)
from backend.supabase_vault import SupabaseVaultConfig, SupabaseVaultError


def config(url: str = "https://example.supabase.co", key: str = "secret") -> SupabaseVaultConfig:
    return SupabaseVaultConfig(url=url, secret_key=key, cv_bucket="flexmap-cv-vault", timeout_seconds=5)


def test_missing_storage_configuration_is_explicit_and_blocks_writes():
    repository = BrowserCollectionRepository(config("", ""))
    assert repository.status()["configured"] is False
    assert repository.status()["missing"] == ["FLEXMAP_SUPABASE_URL", "FLEXMAP_SUPABASE_SECRET_KEY"]
    with pytest.raises(SupabaseVaultError):
        repository.list_datasets()


def test_label_names_are_normalized_and_unsafe_names_rejected():
    assert BrowserLabelCreate(name="Trunk Lean").name == "trunk_lean"
    with pytest.raises(ValueError):
        BrowserLabelCreate(name="../private")


def test_create_dataset_uses_stable_ids_and_persists_initial_label():
    calls = []

    def handler(request: httpx.Request):
        calls.append((request.method, request.url.path, json.loads(request.content or b"{}") if request.method == "POST" else None))
        if request.method == "GET":
            return httpx.Response(200, json=[])
        return httpx.Response(201, json=[json.loads(request.content)])

    repository = BrowserCollectionRepository(config(), transport=httpx.MockTransport(handler))
    result = repository.create_dataset(BrowserDatasetCreate(name="Starting Position", rehabilitation_module_id="REACHING", initial_label_name="acceptable start"))
    assert result["dataset_id"].startswith("DS-")
    assert result["labels"][0]["label_id"].startswith("LBL-")
    assert result["labels"][0]["name"] == "acceptable_start"
    assert any(path.endswith("flexmap_browser_datasets") and body["storage_key"] not in result["name"] for _, path, body in calls if body)


def test_duplicate_dataset_name_is_rejected():
    def handler(request: httpx.Request):
        if request.method == "GET":
            return httpx.Response(200, json=[{"dataset_id": "DS-existing"}])
        raise AssertionError("duplicate must not write")

    repository = BrowserCollectionRepository(config(), transport=httpx.MockTransport(handler))
    with pytest.raises(ValueError, match="already exists"):
        repository.create_dataset(BrowserDatasetCreate(name="Existing", rehabilitation_module_id="REACHING", initial_label_name="ready"))


def sample_metadata() -> BrowserSampleMetadata:
    return BrowserSampleMetadata(
        dataset_id="DS-one", label_id="LBL-one", label_at_capture="lean", sample_type="STILL", source="BROWSER_MEDIAPIPE",
        subject_id="SYNTHETIC_001", technical_quality="GOOD", tracking_quality="GOOD", wall_clock_created_at="2026-10-16T00:00:00Z",
        performance_time_origin_ms=1000, monotonic_start_ms=10, monotonic_end_ms=20, observed_duration_ms=10,
        media_mime_type="image/jpeg", media_extension=".jpg", width=640, height=480,
        model_configuration={"delegate": "CPU"}, permission_scope={"raw_media": True}, observation_count=1,
    )


def test_idempotent_sample_retry_returns_existing_without_upload():
    existing = {"sample_id": "SMP-existing", "idempotency_key": "retry-key"}
    repository = BrowserCollectionRepository(config())
    repository.get_dataset = lambda _dataset_id: {"storage_key": "safe", "archived": False, "permitted_capture_types": "BOTH", "allow_raw_media": True, "labels": [{"label_id": "LBL-one", "archived": False}]}

    def handler(request: httpx.Request):
        if request.url.path.endswith("flexmap_browser_samples") and request.method == "GET":
            return httpx.Response(200, json=[existing])
        raise AssertionError("retry must not upload or create")

    repository._transport = httpx.MockTransport(handler)
    result = repository.save_sample(sample_metadata(), [ArtifactUpload("image.jpg", "image/jpeg", b"jpeg"), ArtifactUpload("pose_observations.json", "application/json", b"[]")], "retry-key")
    assert result == existing


def test_sample_is_verified_before_stored_and_uses_opaque_paths():
    repository = BrowserCollectionRepository(config())
    repository.get_dataset = lambda _dataset_id: {"storage_key": "ignored", "archived": False, "permitted_capture_types": "BOTH", "allow_raw_media": True, "labels": [{"label_id": "LBL-one", "archived": False}]}
    transitions = []
    object_paths = []

    def handler(request: httpx.Request):
        path = request.url.path
        if path.endswith("flexmap_browser_samples") and request.method == "GET":
            return httpx.Response(200, json=[])
        if path.endswith("flexmap_browser_samples") and request.method == "POST":
            body = json.loads(request.content)
            transitions.append(body["persistence_status"])
            return httpx.Response(201, json=[body])
        if path.endswith("flexmap_browser_samples") and request.method == "PATCH":
            body = json.loads(request.content)
            transitions.append(body["persistence_status"])
            return httpx.Response(200, json=[body] if body["persistence_status"] == "STORED" else [])
        if path.endswith("flexmap_recording_artifacts"):
            return httpx.Response(201)
        if path.startswith("/storage/v1/object/authenticated/"):
            return httpx.Response(200, content=b"jpeg" if path.endswith("image.jpg") else b"[]")
        if path.startswith("/storage/v1/object/") and request.method == "POST":
            object_paths.append(path)
            return httpx.Response(200)
        raise AssertionError(f"unexpected request {request.method} {path}")

    repository._transport = httpx.MockTransport(handler)
    result = repository.save_sample(sample_metadata(), [ArtifactUpload("image.jpg", "image/jpeg", b"jpeg"), ArtifactUpload("pose_observations.json", "application/json", b"[]")], "new-key")
    assert transitions == ["DRAFT", "UPLOADING", "VERIFYING", "STORED"]
    assert result["persistence_status"] == "STORED"
    assert all("/datasets/DS-one/recordings/SMP-" in path for path in object_paths)
    assert any("/raw/image.jpg" in path for path in object_paths)
    assert any("/observations/pose_observations.json" in path for path in object_paths)


def test_still_media_type_must_match_extension():
    data = sample_metadata().model_dump()
    data["media_extension"] = ".mp4"
    with pytest.raises(ValueError, match="do not match"):
        BrowserSampleMetadata(**data)


def test_legacy_cv_artifacts_remain_readable_after_bucket_separation():
    paths = []

    def handler(request: httpx.Request):
        paths.append(request.url.path)
        if "/flexmap-cv-vault/" in request.url.path:
            return httpx.Response(404)
        if "/flexmap-dataset/" in request.url.path:
            return httpx.Response(206, content=b"legacy", headers={"content-range": "bytes 0-5/6"})
        raise AssertionError(request.url.path)

    repository = BrowserCollectionRepository(config(), transport=httpx.MockTransport(handler))
    with repository._client() as client:
        response = repository._read_artifact(client, "legacy/sample/image.jpg", {"Range": "bytes=0-5"})

    assert response.status_code == 206
    assert response.content == b"legacy"
    assert paths == [
        "/storage/v1/object/authenticated/flexmap-cv-vault/legacy/sample/image.jpg",
        "/storage/v1/object/authenticated/flexmap-dataset/legacy/sample/image.jpg",
    ]
