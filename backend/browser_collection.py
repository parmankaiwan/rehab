from __future__ import annotations

import hashlib
import json
import re
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal
from urllib.parse import quote

import httpx
from pydantic import BaseModel, Field, field_validator, model_validator

from .supabase_vault import SupabaseVaultConfig, SupabaseVaultError

SAFE_ID = re.compile(r"^[a-z][a-z0-9_]{1,63}$")
ALLOWED_MEDIA_TYPES = {
    "image/jpeg": ".jpg",
    "image/png": ".png",
    "video/webm": ".webm",
    "video/mp4": ".mp4",
}


class BrowserDatasetCreate(BaseModel):
    name: str = Field(min_length=2, max_length=120)
    rehabilitation_module_id: str = Field(min_length=1, max_length=64)
    description: str = Field(default="", max_length=1000)
    initial_label_name: str = Field(min_length=2, max_length=96)
    initial_label_display_name: str | None = Field(default=None, max_length=120)
    instructions: str = Field(default="", max_length=2000)
    camera_view: str = Field(default="FRONT", pattern=r"^(FRONT|LEFT|RIGHT|OTHER)$")
    relevant_side: str = Field(default="N/A", pattern=r"^(LEFT|RIGHT|BILATERAL|N/A)$")
    observation_profile: str = Field(default="FULL_POSE", max_length=64)
    permitted_capture_types: Literal["STILL", "VIDEO", "BOTH"] = "BOTH"
    protocol_id: str | None = Field(default=None, max_length=80)
    session_id: str | None = Field(default=None, max_length=80)
    data_purpose: str = Field(default="RESEARCH", max_length=120)
    allow_raw_media: bool = True
    allow_annotated_media: bool = False
    allow_thumbnails: bool = True

    @field_validator("name", "initial_label_name", "description", "instructions", mode="before")
    @classmethod
    def strip_text(cls, value: Any) -> Any:
        return value.strip() if isinstance(value, str) else value

    @field_validator("initial_label_name")
    @classmethod
    def safe_label(cls, value: str) -> str:
        candidate = value.lower().replace(" ", "_").replace("-", "_")
        if not SAFE_ID.fullmatch(candidate):
            raise ValueError("Label ID must use lowercase letters, numbers, and underscores")
        return candidate


class BrowserDatasetUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=2, max_length=120)
    description: str | None = Field(default=None, max_length=1000)
    instructions: str | None = Field(default=None, max_length=2000)
    archived: bool | None = None

    @field_validator("name", "description", "instructions", mode="before")
    @classmethod
    def strip_text(cls, value: Any) -> Any:
        return value.strip() if isinstance(value, str) else value

    @model_validator(mode="after")
    def require_change(self):
        if all(value is None for value in (self.name, self.description, self.instructions, self.archived)):
            raise ValueError("No dataset update supplied")
        return self


class BrowserLabelCreate(BaseModel):
    name: str = Field(min_length=2, max_length=96)
    display_name: str | None = Field(default=None, max_length=120)
    description: str = Field(default="", max_length=500)
    tracking_failure_label: bool = False

    @field_validator("name", mode="before")
    @classmethod
    def normalize_name(cls, value: Any) -> Any:
        if not isinstance(value, str):
            return value
        candidate = value.strip().lower().replace(" ", "_").replace("-", "_")
        if not SAFE_ID.fullmatch(candidate):
            raise ValueError("Label ID must use lowercase letters, numbers, and underscores")
        return candidate


class BrowserSampleUpdate(BaseModel):
    reviewed_label: str | None = Field(default=None, max_length=120)
    notes: str | None = Field(default=None, max_length=2000)
    review_status: Literal["REVIEW_REQUIRED", "REVIEWED", "APPROVED", "REJECTED"] | None = None
    training_eligible: bool | None = None
    training_ineligibility_reason: str | None = Field(default=None, max_length=500)

    @model_validator(mode="after")
    def require_change(self):
        if all(value is None for value in self.model_dump().values()):
            raise ValueError("No sample update supplied")
        if self.training_eligible and self.review_status != "APPROVED":
            raise ValueError("Only approved samples may be training eligible")
        return self


class BrowserSampleMetadata(BaseModel):
    dataset_id: str
    label_id: str
    label_at_capture: str = Field(min_length=1, max_length=120)
    sample_type: Literal["STILL", "VIDEO"]
    source: Literal["BROWSER_MEDIAPIPE"] = "BROWSER_MEDIAPIPE"
    subject_id: str = Field(min_length=1, max_length=64, pattern=r"^[A-Za-z0-9_-]+$")
    session_id: str | None = Field(default=None, max_length=80)
    protocol_id: str | None = Field(default=None, max_length=80)
    trial_id: str | None = Field(default=None, max_length=100)
    attempt_number: int = Field(default=1, ge=1)
    notes: str = Field(default="", max_length=2000)
    capture_state: Literal["COMPLETE", "INTERRUPTED"] = "COMPLETE"
    technical_quality: Literal["GOOD", "USABLE_WITH_WARNINGS", "LOW_QUALITY", "INVALID"]
    tracking_quality: str = Field(max_length=32)
    wall_clock_created_at: datetime
    performance_time_origin_ms: float
    monotonic_start_ms: float
    monotonic_end_ms: float
    requested_duration_ms: float | None = Field(default=None, ge=0)
    observed_duration_ms: float = Field(ge=0)
    verified_media_duration_ms: float | None = Field(default=None, ge=0)
    timing_association: str = Field(default="TIMESTAMP_NEAREST_APPROXIMATE", max_length=80)
    timing_uncertainty_ms: float | None = Field(default=None, ge=0)
    synchronization_status: Literal["NOT_CONFIGURED"] = "NOT_CONFIGURED"
    media_mime_type: str | None = None
    media_extension: str | None = None
    width: int = Field(gt=0, le=8192)
    height: int = Field(gt=0, le=8192)
    mirrored_preview: bool = True
    orientation: str = Field(default="LANDSCAPE", max_length=32)
    model_configuration: dict[str, Any]
    classifier_output: dict[str, Any] | None = None
    permission_scope: dict[str, bool]
    observation_count: int = Field(ge=0)

    @model_validator(mode="after")
    def validate_media(self):
        if self.media_mime_type:
            expected = ALLOWED_MEDIA_TYPES.get(self.media_mime_type)
            if not expected or expected != self.media_extension:
                raise ValueError("Media MIME type and extension do not match")
        return self


@dataclass(frozen=True)
class ArtifactUpload:
    name: str
    content_type: str
    content: bytes


class BrowserCollectionRepository:
    """Durable Master-only browser collection store using private Supabase resources."""

    def __init__(self, config: SupabaseVaultConfig | None = None, *, transport: httpx.BaseTransport | None = None):
        self.config = config or SupabaseVaultConfig.from_env()
        self._transport = transport

    def status(self) -> dict[str, Any]:
        missing = []
        if not self.config.url:
            missing.append("FLEXMAP_SUPABASE_URL")
        if not self.config.secret_key:
            missing.append("FLEXMAP_SUPABASE_SECRET_KEY")
        return {
            "configured": self.config.configured,
            "enabled": self.config.configured,
            "missing": missing,
            "bucket": self.config.bucket,
            "durability": "SUPABASE_PRIVATE" if self.config.configured else "NOT_CONFIGURED",
        }

    def _client(self) -> httpx.Client:
        self.config.validate()
        return httpx.Client(
            base_url=self.config.url,
            headers={"apikey": self.config.secret_key, "Authorization": f"Bearer {self.config.secret_key}", "User-Agent": "FlexMap-Browser-Collection/1.0"},
            timeout=max(30.0, self.config.timeout_seconds),
            follow_redirects=False,
            transport=self._transport,
        )

    @staticmethod
    def _raise(response: httpx.Response, operation: str) -> None:
        if response.is_success:
            return
        detail = response.text[:500].strip()
        raise SupabaseVaultError(f"Supabase {operation} failed ({response.status_code})" + (f": {detail}" if detail else ""))

    @staticmethod
    def _now() -> str:
        return datetime.now(timezone.utc).isoformat()

    def list_datasets(self, *, search: str = "", module_id: str = "", capture_type: str = "", status: str = "") -> list[dict[str, Any]]:
        params: dict[str, str] = {"select": "*", "order": "updated_at.desc"}
        if search:
            safe = search.replace("%", "").replace(",", " ")[:80]
            params["or"] = f"(name.ilike.*{safe}*,description.ilike.*{safe}*)"
        if module_id:
            params["rehabilitation_module_id"] = f"eq.{module_id}"
        if capture_type:
            params["permitted_capture_types"] = f"in.({capture_type},BOTH)"
        if status == "ARCHIVED":
            params["archived"] = "eq.true"
        elif status == "ACTIVE":
            params["archived"] = "eq.false"
        with self._client() as client:
            response = client.get("/rest/v1/flexmap_browser_datasets", params=params)
            self._raise(response, "dataset list")
            datasets = response.json()
            labels = client.get("/rest/v1/flexmap_browser_labels", params={"select": "dataset_id", "archived": "eq.false"})
            self._raise(labels, "label count")
            samples = client.get("/rest/v1/flexmap_browser_samples", params={"select": "dataset_id,sample_type,review_status,created_at", "trashed_at": "is.null"})
            self._raise(samples, "sample count")
        label_counts: dict[str, int] = {}
        sample_stats: dict[str, dict[str, Any]] = {}
        for label in labels.json():
            label_counts[label["dataset_id"]] = label_counts.get(label["dataset_id"], 0) + 1
        for sample in samples.json():
            current = sample_stats.setdefault(sample["dataset_id"], {"still_count": 0, "video_count": 0, "reviewed_count": 0, "approved_count": 0, "last_sample_at": None})
            current["still_count" if sample["sample_type"] == "STILL" else "video_count"] += 1
            current["reviewed_count"] += sample["review_status"] != "REVIEW_REQUIRED"
            current["approved_count"] += sample["review_status"] == "APPROVED"
            current["last_sample_at"] = max(filter(None, [current["last_sample_at"], sample.get("created_at")]), default=None)
        return [{**dataset, "label_count": label_counts.get(dataset["dataset_id"], 0), **sample_stats.get(dataset["dataset_id"], {"still_count": 0, "video_count": 0, "reviewed_count": 0, "approved_count": 0, "last_sample_at": None})} for dataset in datasets]

    def create_dataset(self, request: BrowserDatasetCreate) -> dict[str, Any]:
        dataset_id = f"DS-{uuid.uuid4().hex}"
        label_id = f"LBL-{uuid.uuid4().hex}"
        now = self._now()
        payload = {"dataset_id": dataset_id, "storage_key": uuid.uuid4().hex, **request.model_dump(exclude={"initial_label_name", "initial_label_display_name"}), "archived": False, "created_at": now, "updated_at": now}
        label = {"label_id": label_id, "dataset_id": dataset_id, "name": request.initial_label_name, "display_name": request.initial_label_display_name or request.initial_label_name.replace("_", " ").title(), "description": "", "tracking_failure_label": False, "archived": False, "created_at": now, "updated_at": now}
        with self._client() as client:
            duplicate = client.get("/rest/v1/flexmap_browser_datasets", params={"select": "dataset_id", "name": f"ilike.{request.name}", "rehabilitation_module_id": f"eq.{request.rehabilitation_module_id}", "limit": "1"})
            self._raise(duplicate, "duplicate dataset check")
            if duplicate.json():
                raise ValueError("A dataset with this name already exists in the selected rehabilitation module")
            response = client.post("/rest/v1/flexmap_browser_datasets", headers={"Prefer": "return=representation"}, json=payload)
            self._raise(response, "dataset creation")
            label_response = client.post("/rest/v1/flexmap_browser_labels", headers={"Prefer": "return=representation"}, json=label)
            if not label_response.is_success:
                client.delete("/rest/v1/flexmap_browser_datasets", params={"dataset_id": f"eq.{dataset_id}"})
                self._raise(label_response, "initial label creation")
        return {**payload, "labels": [label], "label_count": 1, "still_count": 0, "video_count": 0, "reviewed_count": 0, "approved_count": 0}

    def get_dataset(self, dataset_id: str) -> dict[str, Any] | None:
        with self._client() as client:
            response = client.get("/rest/v1/flexmap_browser_datasets", params={"select": "*", "dataset_id": f"eq.{dataset_id}", "limit": "1"})
            self._raise(response, "dataset read")
            rows = response.json()
            if not rows:
                return None
            labels = client.get("/rest/v1/flexmap_browser_labels", params={"select": "*", "dataset_id": f"eq.{dataset_id}", "order": "created_at"})
            self._raise(labels, "dataset labels")
            samples = client.get("/rest/v1/flexmap_browser_samples", params={"select": "*", "dataset_id": f"eq.{dataset_id}", "trashed_at": "is.null", "order": "created_at.desc"})
            self._raise(samples, "dataset samples")
        return {**rows[0], "labels": labels.json(), "samples": samples.json()}

    def update_dataset(self, dataset_id: str, update: BrowserDatasetUpdate) -> dict[str, Any]:
        values = update.model_dump(exclude_none=True)
        values["updated_at"] = self._now()
        with self._client() as client:
            if update.name is not None:
                current = self.get_dataset(dataset_id)
                if not current:
                    raise FileNotFoundError(dataset_id)
                duplicate = client.get("/rest/v1/flexmap_browser_datasets", params={"select": "dataset_id", "name": f"ilike.{update.name}", "rehabilitation_module_id": f"eq.{current['rehabilitation_module_id']}", "dataset_id": f"neq.{dataset_id}", "limit": "1"})
                self._raise(duplicate, "duplicate dataset check")
                if duplicate.json():
                    raise ValueError("A dataset with this name already exists in the selected rehabilitation module")
            response = client.patch("/rest/v1/flexmap_browser_datasets", params={"dataset_id": f"eq.{dataset_id}"}, headers={"Prefer": "return=representation"}, json=values)
            self._raise(response, "dataset update")
            rows = response.json()
        if not rows:
            raise FileNotFoundError(dataset_id)
        return rows[0]

    def create_label(self, dataset_id: str, request: BrowserLabelCreate) -> dict[str, Any]:
        now = self._now()
        payload = {"label_id": f"LBL-{uuid.uuid4().hex}", "dataset_id": dataset_id, "name": request.name, "display_name": request.display_name or request.name.replace("_", " ").title(), "description": request.description, "tracking_failure_label": request.tracking_failure_label, "archived": False, "created_at": now, "updated_at": now}
        with self._client() as client:
            response = client.post("/rest/v1/flexmap_browser_labels", headers={"Prefer": "return=representation"}, json=payload)
            self._raise(response, "label creation")
        return payload

    def get_sample(self, sample_id: str, *, include_trashed: bool = False) -> dict[str, Any] | None:
        params = {"select": "*", "sample_id": f"eq.{sample_id}", "limit": "1"}
        if not include_trashed:
            params["trashed_at"] = "is.null"
        with self._client() as client:
            response = client.get("/rest/v1/flexmap_browser_samples", params=params)
            self._raise(response, "sample read")
            rows = response.json()
        return rows[0] if rows else None

    def update_sample(self, sample_id: str, update: BrowserSampleUpdate) -> dict[str, Any]:
        current = self.get_sample(sample_id, include_trashed=True)
        if not current:
            raise FileNotFoundError(sample_id)
        values = update.model_dump(exclude_none=True)
        values["updated_at"] = self._now()
        if values.get("training_eligible") is False and not values.get("training_ineligibility_reason"):
            values["training_ineligibility_reason"] = "REVIEWER_EXCLUDED"
        with self._client() as client:
            response = client.patch("/rest/v1/flexmap_browser_samples", params={"sample_id": f"eq.{sample_id}"}, headers={"Prefer": "return=representation"}, json=values)
            self._raise(response, "sample update")
            rows = response.json()
            if not rows:
                raise FileNotFoundError(sample_id)
            if "reviewed_label" in values and values["reviewed_label"] != current.get("reviewed_label"):
                audit = {"sample_id": sample_id, "previous_label": current.get("reviewed_label") or current.get("label_at_capture"), "new_label": values["reviewed_label"], "changed_at": self._now()}
                audit_response = client.post("/rest/v1/flexmap_browser_label_audit", json=audit)
                self._raise(audit_response, "label audit")
        return rows[0]

    def set_sample_trashed(self, sample_id: str, trashed: bool) -> dict[str, Any]:
        if not self.get_sample(sample_id, include_trashed=True):
            raise FileNotFoundError(sample_id)
        now = self._now()
        values = {"trashed_at": now if trashed else None, "updated_at": now}
        with self._client() as client:
            response = client.patch("/rest/v1/flexmap_browser_samples", params={"sample_id": f"eq.{sample_id}"}, headers={"Prefer": "return=representation"}, json=values)
            self._raise(response, "sample trash update")
            rows = response.json()
        return rows[0]

    def save_sample(self, metadata: BrowserSampleMetadata, artifacts: list[ArtifactUpload], idempotency_key: str) -> dict[str, Any]:
        dataset = self.get_dataset(metadata.dataset_id)
        if not dataset or dataset.get("archived"):
            raise ValueError("Dataset is unavailable or archived")
        label = next((item for item in dataset["labels"] if item["label_id"] == metadata.label_id and not item["archived"]), None)
        if not label:
            raise ValueError("Selected posture label is unavailable")
        permitted = dataset["permitted_capture_types"]
        if permitted not in {"BOTH", metadata.sample_type}:
            raise ValueError("This dataset does not permit the selected capture type")
        if metadata.permission_scope.get("raw_media", False) and not dataset["allow_raw_media"]:
            raise ValueError("Raw media storage is not permitted for this dataset")
        media = [item for item in artifacts if item.content_type in ALLOWED_MEDIA_TYPES]
        if metadata.permission_scope.get("raw_media", False) and len(media) != 1:
            raise ValueError("Exactly one raw media artifact is required")
        if not metadata.permission_scope.get("raw_media", False) and media:
            raise ValueError("Media was supplied for a landmarks-only capture")
        if not any(item.name.startswith("pose_observations") for item in artifacts):
            raise ValueError("Pose observations are required")
        if sum(len(item.content) for item in artifacts) > 150 * 1024 * 1024:
            raise ValueError("Capture package exceeds the 150 MB limit")
        sample_id = f"SMP-{uuid.uuid4().hex}"
        prefix = f"browser/{dataset['storage_key']}/{sample_id}"
        manifest: list[dict[str, Any]] = []
        uploaded_paths: list[str] = []
        with self._client() as client:
            existing = client.get("/rest/v1/flexmap_browser_samples", params={"select": "*", "idempotency_key": f"eq.{idempotency_key}", "limit": "1"})
            self._raise(existing, "idempotency check")
            rows = existing.json()
            if rows:
                return rows[0]
            try:
                for artifact in artifacts:
                    safe_name = Path(artifact.name).name
                    if safe_name != artifact.name or not safe_name:
                        raise ValueError("Unsafe artifact name")
                    object_path = f"{prefix}/{safe_name}"
                    response = client.post(f"/storage/v1/object/{quote(self.config.bucket, safe='')}/{quote(object_path, safe='/')}", headers={"Content-Type": artifact.content_type, "x-upsert": "false"}, content=artifact.content)
                    self._raise(response, f"artifact upload ({safe_name})")
                    uploaded_paths.append(object_path)
                    manifest.append({"name": safe_name, "object_path": object_path, "content_type": artifact.content_type, "size_bytes": len(artifact.content), "sha256": hashlib.sha256(artifact.content).hexdigest(), "role": "RAW" if artifact in media else "OBSERVATION"})
                payload = {"sample_id": sample_id, "dataset_id": metadata.dataset_id, "label_id": metadata.label_id, "label_at_capture": metadata.label_at_capture, "reviewed_label": None, "sample_type": metadata.sample_type, "source": metadata.source, "subject_id": metadata.subject_id, "session_id": metadata.session_id, "protocol_id": metadata.protocol_id, "trial_id": metadata.trial_id, "attempt_number": metadata.attempt_number, "notes": metadata.notes, "capture_state": metadata.capture_state, "technical_quality": metadata.technical_quality, "tracking_quality": metadata.tracking_quality, "review_status": "REVIEW_REQUIRED", "training_eligible": False, "training_ineligibility_reason": "REVIEW_REQUIRED", "storage_prefix": prefix, "artifact_manifest": manifest, "metadata": metadata.model_dump(mode="json"), "idempotency_key": idempotency_key, "created_at": self._now(), "server_received_at": self._now(), "updated_at": self._now()}
                response = client.post("/rest/v1/flexmap_browser_samples", headers={"Prefer": "return=representation"}, json=payload)
                self._raise(response, "sample completion")
            except Exception:
                # The row is authoritative. If completion fails, remove the
                # temporary objects so a partial package never appears saved.
                for object_path in reversed(uploaded_paths):
                    client.delete(f"/storage/v1/object/{quote(self.config.bucket, safe='')}/{quote(object_path, safe='/')}")
                raise
        return payload

    def artifact(self, sample_id: str, filename: str, range_header: str | None = None) -> tuple[bytes, int, dict[str, str]]:
        safe_name = Path(filename).name
        if safe_name != filename:
            raise FileNotFoundError(filename)
        with self._client() as client:
            response = client.get("/rest/v1/flexmap_browser_samples", params={"select": "artifact_manifest", "sample_id": f"eq.{sample_id}", "trashed_at": "is.null", "limit": "1"})
            self._raise(response, "sample artifact lookup")
            rows = response.json()
            if not rows:
                raise FileNotFoundError(filename)
            artifact = next((item for item in rows[0]["artifact_manifest"] if item["name"] == safe_name), None)
            if not artifact:
                raise FileNotFoundError(filename)
            headers = {"Range": range_header} if range_header else {}
            data = client.get(f"/storage/v1/object/authenticated/{quote(self.config.bucket, safe='')}/{quote(artifact['object_path'], safe='/')}", headers=headers)
            self._raise(data, "artifact read")
        forwarded = {name: value for name in ("content-type", "content-range", "accept-ranges", "content-length") if (value := data.headers.get(name))}
        return data.content, data.status_code, forwarded
