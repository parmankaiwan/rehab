from __future__ import annotations

import os
from datetime import datetime, timezone
from typing import Any
from urllib.parse import quote

import httpx

from .supabase_vault import SupabaseVaultConfig, SupabaseVaultError

REQUIRED_SCHEMA_VERSION = "202610170001"


def data_backend_mode() -> str:
    mode = os.getenv("FLEXMAP_DATA_BACKEND", "local").strip().lower()
    if mode not in {"local", "supabase"}:
        raise SupabaseVaultError("FLEXMAP_DATA_BACKEND must be local or supabase")
    return mode


class StorageStatusService:
    """Bounded, backend-only diagnostics for the authoritative data store."""

    def __init__(self, config: SupabaseVaultConfig | None = None, *, transport: httpx.BaseTransport | None = None) -> None:
        self.config = config or SupabaseVaultConfig.from_env()
        self.transport = transport
        self.last_successful_check: str | None = None

    def check(self) -> dict[str, Any]:
        checked_at = datetime.now(timezone.utc).isoformat()
        try:
            mode = data_backend_mode()
        except SupabaseVaultError as exc:
            return self._result("INVALID_CONFIGURATION", checked_at, error=str(exc))
        if mode == "local":
            return self._result("LOCAL_READY", checked_at, mode=mode, database="LOCAL", schema="LOCAL", bucket="NOT_APPLICABLE")
        if self.config.enabled:
            return self._result("CONFIGURATION_CONFLICT", checked_at, mode=mode, error="Disable FLEXMAP_SUPABASE_SYNC_ENABLED when Supabase is authoritative.")
        if not self.config.configured:
            return self._result("NOT_CONFIGURED", checked_at, mode=mode, database="NOT_CONFIGURED", schema="UNKNOWN", bucket="NOT_CONFIGURED")

        result = self._result("CHECKING", checked_at, mode=mode)
        try:
            self.config.validate()
            with httpx.Client(
                base_url=self.config.url,
                headers={**self.config.auth_headers(), "User-Agent": "FlexMap-Storage-Status/1.0"},
                timeout=min(max(self.config.timeout_seconds, 2.0), 20.0),
                follow_redirects=False,
                transport=self.transport,
            ) as client:
                db = client.get("/rest/v1/flexmap_browser_datasets", params={"select": "dataset_id", "limit": "1"})
                if db.status_code in {401, 403}:
                    return {**result, "state": "AUTHENTICATION_FAILED", "database": "AUTHENTICATION_FAILED"}
                if db.status_code == 404:
                    return {**result, "state": "MIGRATION_REQUIRED", "database": "REACHABLE", "schema": "MIGRATION_REQUIRED"}
                db.raise_for_status()

                migration = client.get("/rest/v1/flexmap_schema_migrations", params={"select": "version", "version": f"eq.{REQUIRED_SCHEMA_VERSION}", "limit": "1"})
                schema_ok = migration.is_success and bool(migration.json())
                # Migration history alone cannot prove the deployed schema is usable.
                for table, key in (
                    ("flexmap_browser_labels", "label_id"),
                    ("flexmap_browser_samples", "sample_id,persistence_status"),
                    ("flexmap_recording_artifacts", "artifact_id"),
                    ("flexmap_cv_review_audit", "audit_id"),
                    ("flexmap_emg_datasets", "dataset_id"),
                    ("flexmap_emg_labels", "label_id"),
                    ("flexmap_emg_recordings", "recording_id,persistence_status"),
                    ("flexmap_emg_artifacts", "artifact_id"),
                    ("flexmap_emg_review_audit", "audit_id"),
                ):
                    probe = client.get(f"/rest/v1/{table}", params={"select": key, "limit": "0"})
                    if probe.status_code in {401, 403}:
                        return {**result, "state": "AUTHENTICATION_FAILED", "database": "AUTHENTICATION_FAILED"}
                    if probe.status_code in {400, 404}:
                        return {**result, "state": "MIGRATION_REQUIRED", "database": "CONNECTED", "schema": "MIGRATION_REQUIRED"}
                    probe.raise_for_status()

                bucket_states = []
                for bucket_name in (self.config.cv_bucket, self.config.emg_bucket):
                    bucket = client.get(f"/storage/v1/bucket/{quote(bucket_name, safe='')}")
                    if bucket.status_code == 404:
                        bucket_states.append("MISSING")
                    else:
                        bucket.raise_for_status()
                        bucket_states.append("PRIVATE" if not bucket.json().get("public", False) else "PUBLIC_UNSAFE")
                bucket_state = "CV_PRIVATE_EMG_PRIVATE" if bucket_states == ["PRIVATE", "PRIVATE"] else "STORAGE_UNAVAILABLE"

                pending_count = 0
                for table, key in (("flexmap_browser_samples", "sample_id"), ("flexmap_emg_recordings", "recording_id")):
                    pending = client.get(f"/rest/v1/{table}", params={"select": key, "persistence_status": "in.(DRAFT,UPLOADING,VERIFYING,FAILED,INTERRUPTED)", "limit": "1"}, headers={"Prefer": "count=exact"})
                    if pending.is_success:
                        content_range = pending.headers.get("content-range", "")
                        if "/" in content_range and content_range.rsplit("/", 1)[1].isdigit():
                            pending_count += int(content_range.rsplit("/", 1)[1])
                        else:
                            pending_count += len(pending.json())
        except (httpx.HTTPError, ValueError, SupabaseVaultError):
            return {**result, "state": "DATABASE_UNAVAILABLE", "database": "UNREACHABLE"}

        state = "READY" if schema_ok and bucket_state == "CV_PRIVATE_EMG_PRIVATE" else ("MIGRATION_REQUIRED" if not schema_ok else "STORAGE_UNAVAILABLE")
        if state == "READY":
            self.last_successful_check = checked_at
        return {**result, "state": state, "database": "CONNECTED", "schema": "CURRENT" if schema_ok else "MIGRATION_REQUIRED", "bucket": bucket_state, "pending_or_failed_uploads": pending_count, "last_successful_check": self.last_successful_check}

    def _result(self, state: str, checked_at: str, *, mode: str | None = None, database: str = "UNKNOWN", schema: str = "UNKNOWN", bucket: str = "UNKNOWN", error: str | None = None) -> dict[str, Any]:
        return {
            "mode": (mode or os.getenv("FLEXMAP_DATA_BACKEND", "local")).upper(),
            "state": state,
            "database": database,
            "schema": schema,
            "bucket": bucket,
            "checked_at": checked_at,
            "last_successful_check": self.last_successful_check,
            "pending_or_failed_uploads": None,
            "last_successful_upload": None,
            "verified_storage_bytes": None,
            **({"error": error} if error else {}),
        }
