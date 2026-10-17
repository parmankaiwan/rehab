from __future__ import annotations

import hashlib
import csv
import io
import json
import mimetypes
import re
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import quote

import httpx
from pydantic import BaseModel, Field, field_validator

from ..supabase_vault import SupabaseVaultConfig, SupabaseVaultError


SAFE_LABEL = re.compile(r"^[a-z][a-z0-9_]{1,63}$")


def utcnow() -> str:
    return datetime.now(timezone.utc).isoformat()


class EmgDatasetCreate(BaseModel):
    name: str = Field(min_length=2, max_length=120)
    description: str = Field(default="", max_length=1000)
    muscle_under_study: str | None = Field(default=None, max_length=120)
    recording_purpose: str | None = Field(default=None, max_length=500)
    target_count: int | None = Field(default=None, ge=0, le=1_000_000)
    initial_label_name: str = Field(min_length=2, max_length=64)
    initial_label_display_name: str | None = Field(default=None, max_length=120)

    @field_validator("name", "description", "muscle_under_study", "recording_purpose", mode="before")
    @classmethod
    def strip_text(cls, value: Any) -> Any:
        return value.strip() if isinstance(value, str) else value

    @field_validator("initial_label_name")
    @classmethod
    def normalize_label(cls, value: str) -> str:
        normalized = value.strip().lower().replace(" ", "_").replace("-", "_")
        if not SAFE_LABEL.fullmatch(normalized):
            raise ValueError("Label ID must use lowercase letters, numbers, and underscores")
        return normalized


class EmgLabelCreate(BaseModel):
    name: str = Field(min_length=2, max_length=64)
    display_name: str | None = Field(default=None, max_length=120)
    description: str = Field(default="", max_length=500)

    @field_validator("name")
    @classmethod
    def normalize_label(cls, value: str) -> str:
        normalized = value.strip().lower().replace(" ", "_").replace("-", "_")
        if not SAFE_LABEL.fullmatch(normalized):
            raise ValueError("Label ID must use lowercase letters, numbers, and underscores")
        return normalized


class EmgCloudVault:
    """Authoritative, modality-isolated Supabase storage for approved EMG data."""

    def __init__(self, config: SupabaseVaultConfig | None = None, *, transport: httpx.BaseTransport | None = None):
        self.config = config or SupabaseVaultConfig.from_env()
        self.transport = transport

    def _client(self) -> httpx.Client:
        self.config.validate()
        return httpx.Client(
            base_url=self.config.url,
            headers={**self.config.auth_headers(), "User-Agent": "FlexMap-EMG-Vault/1.0"},
            timeout=max(30.0, self.config.timeout_seconds),
            follow_redirects=False,
            transport=self.transport,
        )

    @staticmethod
    def _raise(response: httpx.Response, operation: str) -> None:
        if response.is_success:
            return
        detail = response.text[:300].strip()
        raise SupabaseVaultError(f"Supabase {operation} failed ({response.status_code})" + (f": {detail}" if detail else ""))

    def status(self) -> dict[str, Any]:
        return {
            "configured": self.config.configured,
            "bucket": self.config.emg_bucket,
            "durability": "SUPABASE_PRIVATE" if self.config.configured else "NOT_CONFIGURED",
        }

    def list_datasets(self, include_archived: bool = False) -> list[dict[str, Any]]:
        params = {"select": "*", "order": "updated_at.desc", "deleted_at": "is.null"}
        if not include_archived:
            params["archived"] = "eq.false"
        with self._client() as client:
            datasets = client.get("/rest/v1/flexmap_emg_datasets", params=params)
            self._raise(datasets, "EMG dataset list")
            rows = datasets.json()
            labels = client.get("/rest/v1/flexmap_emg_labels", params={"select": "*", "archived": "eq.false"})
            self._raise(labels, "EMG label list")
            recordings = client.get(
                "/rest/v1/flexmap_emg_recordings",
                params={"select": "dataset_id,review_status,training_eligible,duration_seconds,channel_count,created_at", "trashed_at": "is.null", "persistence_status": "eq.STORED"},
            )
            self._raise(recordings, "EMG recording aggregates")
        label_rows = labels.json()
        recording_rows = recordings.json()
        return [
            {
                **row,
                "labels": [item for item in label_rows if item["dataset_id"] == row["dataset_id"]],
                "recording_count": sum(item["dataset_id"] == row["dataset_id"] for item in recording_rows),
                "approved_count": sum(item["dataset_id"] == row["dataset_id"] and item["review_status"] == "APPROVED" for item in recording_rows),
                "training_eligible_count": sum(item["dataset_id"] == row["dataset_id"] and item["training_eligible"] for item in recording_rows),
                "duration_seconds": sum(float(item.get("duration_seconds") or 0) for item in recording_rows if item["dataset_id"] == row["dataset_id"]),
                "channel_count": max([int(item.get("channel_count") or 0) for item in recording_rows if item["dataset_id"] == row["dataset_id"]] or [0]),
                "last_recording_at": max([item.get("created_at") or "" for item in recording_rows if item["dataset_id"] == row["dataset_id"]] or [""]) or None,
            }
            for row in rows
        ]

    def create_dataset(self, request: EmgDatasetCreate) -> dict[str, Any]:
        dataset_id = f"EDS-{uuid.uuid4().hex}"
        label_id = f"ELB-{uuid.uuid4().hex}"
        now = utcnow()
        dataset = {
            "dataset_id": dataset_id,
            "storage_key": uuid.uuid4().hex,
            **request.model_dump(exclude={"initial_label_name", "initial_label_display_name"}),
            "archived": False,
            "created_at": now,
            "updated_at": now,
        }
        label = {
            "label_id": label_id,
            "dataset_id": dataset_id,
            "name": request.initial_label_name,
            "display_name": request.initial_label_display_name or request.initial_label_name.replace("_", " ").title(),
            "description": "",
            "archived": False,
            "created_at": now,
            "updated_at": now,
        }
        with self._client() as client:
            duplicate = client.get("/rest/v1/flexmap_emg_datasets", params={"select": "dataset_id", "name": f"ilike.{request.name}", "deleted_at": "is.null", "limit": "1"})
            self._raise(duplicate, "EMG duplicate dataset check")
            if duplicate.json():
                raise ValueError("An EMG dataset with this name already exists")
            created = client.post("/rest/v1/flexmap_emg_datasets", headers={"Prefer": "return=representation"}, json=dataset)
            self._raise(created, "EMG dataset creation")
            created_label = client.post("/rest/v1/flexmap_emg_labels", headers={"Prefer": "return=representation"}, json=label)
            if not created_label.is_success:
                client.patch("/rest/v1/flexmap_emg_datasets", params={"dataset_id": f"eq.{dataset_id}"}, json={"deleted_at": utcnow(), "archived": True})
                self._raise(created_label, "EMG initial label creation")
        return {**dataset, "labels": [label], "recording_count": 0}

    def create_label(self, dataset_id: str, request: EmgLabelCreate) -> dict[str, Any]:
        now = utcnow()
        label = {
            "label_id": f"ELB-{uuid.uuid4().hex}",
            "dataset_id": dataset_id,
            **request.model_dump(),
            "display_name": request.display_name or request.name.replace("_", " ").title(),
            "archived": False,
            "created_at": now,
            "updated_at": now,
        }
        with self._client() as client:
            response = client.post("/rest/v1/flexmap_emg_labels", headers={"Prefer": "return=representation"}, json=label)
            self._raise(response, "EMG label creation")
        return label

    def list_recordings(self, dataset_id: str = "") -> list[dict[str, Any]]:
        params = {
            "select": "*",
            "trashed_at": "is.null",
            "order": "created_at.desc",
        }
        if dataset_id:
            params["dataset_id"] = f"eq.{dataset_id}"
        with self._client() as client:
            response = client.get("/rest/v1/flexmap_emg_recordings", params=params)
            self._raise(response, "EMG recording list")
            return response.json()

    def get_recording(self, recording_id: str) -> dict[str, Any]:
        with self._client() as client:
            response = client.get("/rest/v1/flexmap_emg_recordings", params={"select": "*", "recording_id": f"eq.{recording_id}", "limit": "1"})
            self._raise(response, "EMG recording lookup")
            rows = response.json()
            if not rows:
                raise FileNotFoundError(recording_id)
            artifacts = client.get("/rest/v1/flexmap_emg_artifacts", params={"select": "artifact_id,artifact_role,object_path,content_type,byte_size,sha256,processing_version", "recording_id": f"eq.{recording_id}", "order": "created_at.asc"})
            self._raise(artifacts, "EMG artifact list")
        return {**rows[0], "artifacts": artifacts.json()}

    def read_artifact(self, recording_id: str, artifact_id: str, range_header: str = "") -> tuple[bytes, int, dict[str, str]]:
        with self._client() as client:
            index = client.get("/rest/v1/flexmap_emg_artifacts", params={"select": "object_path,content_type", "recording_id": f"eq.{recording_id}", "artifact_id": f"eq.{artifact_id}", "limit": "1"})
            self._raise(index, "EMG artifact lookup")
            rows = index.json()
            if not rows:
                raise FileNotFoundError(artifact_id)
            headers = {"Range": range_header} if range_header else {}
            data = client.get(f"/storage/v1/object/authenticated/{quote(self.config.emg_bucket, safe='')}/{quote(rows[0]['object_path'], safe='/')}", headers=headers)
            self._raise(data, "EMG artifact read")
        forwarded = {name: value for name in ("content-type", "content-range", "accept-ranges", "content-length") if (value := data.headers.get(name))}
        forwarded.setdefault("content-type", rows[0]["content_type"])
        return data.content, data.status_code, forwarded

    def waveform(self, recording_id: str, max_points: int = 2000) -> dict[str, Any]:
        detail = self.get_recording(recording_id)
        raw = next((item for item in detail["artifacts"] if item["object_path"].endswith("/emg_raw.csv")), None)
        if not raw:
            raise FileNotFoundError("emg_raw.csv")
        if int(raw.get("byte_size") or 0) > 50 * 1024 * 1024:
            raise SupabaseVaultError("Raw EMG artifact exceeds the bounded waveform viewer limit")
        content, _, _ = self.read_artifact(recording_id, str(raw["artifact_id"]))
        rows = list(csv.DictReader(io.StringIO(content.decode("utf-8-sig"))))
        limit = max(1, min(max_points, 5000))
        stride = max(1, (len(rows) + limit - 1) // limit)
        return {
            "recording_id": recording_id,
            "raw_units": detail.get("signal_units") or "ADC_COUNTS",
            "sample_rate_hz": detail.get("sample_rate_hz"),
            "duration_seconds": detail.get("duration_seconds"),
            "samples": rows[::stride][:limit],
        }

    def save_recording(self, record: dict[str, Any], recording_path: Path) -> dict[str, Any]:
        dataset_id = record.get("dataset_id") or (record.get("metadata") or {}).get("dataset_id")
        if not dataset_id:
            raise SupabaseVaultError("EMG recording has no selected cloud dataset")
        recording_id = str(record["recording_id"])
        metadata = record.get("metadata") or {}
        label_name = str(record.get("research_label") or metadata.get("research_label") or "")
        with self._client() as client:
            dataset_response = client.get("/rest/v1/flexmap_emg_datasets", params={"select": "dataset_id", "dataset_id": f"eq.{dataset_id}", "archived": "eq.false", "deleted_at": "is.null", "limit": "1"})
            self._raise(dataset_response, "EMG dataset lookup")
            if not dataset_response.json():
                raise ValueError("Selected EMG dataset is unavailable")
            label_response = client.get("/rest/v1/flexmap_emg_labels", params={"select": "label_id", "dataset_id": f"eq.{dataset_id}", "name": f"eq.{label_name}", "archived": "eq.false", "limit": "1"})
            self._raise(label_response, "EMG label lookup")
            labels = label_response.json()
            if not labels:
                raise ValueError("The recording label is not defined in the selected EMG dataset")
            existing = client.get("/rest/v1/flexmap_emg_recordings", params={"select": "*", "idempotency_key": f"eq.{recording_id}", "limit": "1"})
            self._raise(existing, "EMG idempotency check")
            if existing.json() and existing.json()[0].get("persistence_status") == "STORED":
                return existing.json()[0]

            prefix = f"datasets/{dataset_id}/recordings/{recording_id}"
            now = utcnow()
            payload = {
                "recording_id": recording_id,
                "dataset_id": dataset_id,
                "label_id": labels[0]["label_id"],
                "research_label": label_name,
                "subject_code": record.get("subject_id") or metadata.get("subject_id"),
                "session_id": record.get("session_id") or metadata.get("session_id"),
                "protocol_id": metadata.get("protocol_id"),
                "protocol_version": metadata.get("protocol_version"),
                "trial_id": metadata.get("trial_id"),
                "attempt_number": metadata.get("attempt_number") or 1,
                "tested_side": record.get("affected_side") or metadata.get("affected_side"),
                "muscle_under_study": metadata.get("muscle_under_study"),
                "channel_count": int(record.get("channel_count") or metadata.get("channel_count") or 1),
                "sample_count": int(record.get("sample_count") or metadata.get("sample_count") or 0),
                "sample_rate_hz": record.get("measured_sample_rate_hz") or metadata.get("measured_sample_rate_hz"),
                "duration_seconds": float(record.get("duration_seconds") or metadata.get("duration_actual") or 0),
                "signal_units": metadata.get("raw_units") or "ADC_COUNTS",
                "hardware_snapshot": metadata.get("hardware_profile_snapshot") or {},
                "processing_versions": metadata.get("processing_provenance") or {},
                "metadata": metadata,
                "quality_report": record.get("quality_report"),
                "persistence_status": "DRAFT",
                "review_status": "REVIEW_REQUIRED",
                "training_eligible": False,
                "storage_prefix": prefix,
                "artifact_manifest": [],
                "idempotency_key": recording_id,
                "created_at": record.get("created_at") or metadata.get("created_at_utc") or now,
                "updated_at": now,
            }
            if existing.json():
                draft = client.patch("/rest/v1/flexmap_emg_recordings", params={"recording_id": f"eq.{recording_id}"}, headers={"Prefer": "return=representation"}, json=payload)
            else:
                draft = client.post("/rest/v1/flexmap_emg_recordings", headers={"Prefer": "return=representation"}, json=payload)
            self._raise(draft, "EMG recording draft")
            manifest: list[dict[str, Any]] = []
            try:
                transition = client.patch("/rest/v1/flexmap_emg_recordings", params={"recording_id": f"eq.{recording_id}"}, json={"persistence_status": "UPLOADING", "updated_at": utcnow()})
                self._raise(transition, "EMG upload transition")
                for path in sorted(recording_path.rglob("*")):
                    if not path.is_file():
                        continue
                    relative = path.relative_to(recording_path).as_posix()
                    folder = "raw" if path.name == "emg_raw.csv" else "processed" if relative.startswith("processing/") else "metadata"
                    object_path = f"{prefix}/{folder}/{relative}"
                    content_type = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
                    digest = hashlib.sha256()
                    with path.open("rb") as source:
                        for chunk in iter(lambda: source.read(1024 * 1024), b""):
                            digest.update(chunk)
                    with path.open("rb") as source:
                        upload = client.post(f"/storage/v1/object/{quote(self.config.emg_bucket, safe='')}/{quote(object_path, safe='/')}", headers={"Content-Type": content_type, "x-upsert": "true"}, content=source)
                    self._raise(upload, f"EMG artifact upload ({path.name})")
                    # Confirm remote bytes before claiming durable, verified storage.
                    with client.stream("GET", f"/storage/v1/object/authenticated/{quote(self.config.emg_bucket, safe='')}/{quote(object_path, safe='/')}") as verified:
                        if not verified.is_success:
                            verified.read()
                            self._raise(verified, "EMG artifact verification")
                        remote_digest = hashlib.sha256()
                        remote_size = 0
                        for chunk in verified.iter_bytes():
                            remote_digest.update(chunk)
                            remote_size += len(chunk)
                    if remote_size != path.stat().st_size or remote_digest.hexdigest() != digest.hexdigest():
                        raise SupabaseVaultError("EMG artifact verification failed")
                    artifact = {"name": relative, "object_path": object_path, "content_type": content_type, "size_bytes": path.stat().st_size, "sha256": digest.hexdigest(), "verification_status": "VERIFIED"}
                    index = client.post("/rest/v1/flexmap_emg_artifacts", params={"on_conflict": "object_path"}, headers={"Prefer": "resolution=merge-duplicates"}, json={"recording_id": recording_id, "artifact_role": folder.upper() + ":" + relative, "object_path": object_path, "content_type": content_type, "byte_size": artifact["size_bytes"], "sha256": artifact["sha256"], "verification_status": "VERIFIED", "verified_at": utcnow()})
                    self._raise(index, "EMG artifact index")
                    manifest.append(artifact)
                verifying = client.patch("/rest/v1/flexmap_emg_recordings", params={"recording_id": f"eq.{recording_id}"}, json={"persistence_status": "VERIFYING", "artifact_manifest": manifest, "updated_at": utcnow()})
                self._raise(verifying, "EMG verification transition")
                completed_at = utcnow()
                completed = client.patch("/rest/v1/flexmap_emg_recordings", params={"recording_id": f"eq.{recording_id}", "persistence_status": "eq.VERIFYING"}, headers={"Prefer": "return=representation"}, json={"persistence_status": "STORED", "verified_at": completed_at, "updated_at": completed_at})
                self._raise(completed, "EMG recording finalization")
                rows = completed.json()
                if not rows:
                    raise SupabaseVaultError("EMG finalization lost its state transition")
                return rows[0]
            except Exception as exc:
                client.patch("/rest/v1/flexmap_emg_recordings", params={"recording_id": f"eq.{recording_id}"}, json={"persistence_status": "FAILED", "failure_reason": type(exc).__name__, "artifact_manifest": manifest, "updated_at": utcnow()})
                raise
