from __future__ import annotations

import mimetypes
import os
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable
from urllib.parse import quote, urlparse

import httpx


class SupabaseVaultError(RuntimeError):
    """Raised when the optional remote vault cannot complete a request."""


@dataclass(frozen=True)
class SupabaseVaultConfig:
    url: str = ""
    secret_key: str = field(default="", repr=False)
    table: str = "flexmap_dataset_recordings"
    bucket: str = "flexmap-dataset"
    cv_bucket: str = "flexmap-cv-vault"
    emg_bucket: str = "flexmap-emg-vault"
    enabled: bool = False
    upload_artifacts: bool = False
    timeout_seconds: float = 20.0

    @classmethod
    def from_env(cls) -> "SupabaseVaultConfig":
        # SUPABASE_SECRET_KEY is the current server-key format. The service-role
        # fallback keeps existing Supabase projects working during migration.
        secret = os.getenv("FLEXMAP_SUPABASE_SECRET_KEY", "") or os.getenv(
            "SUPABASE_SECRET_KEY", ""
        ) or os.getenv("SUPABASE_SERVICE_ROLE_KEY", "")
        return cls(
            url=os.getenv("FLEXMAP_SUPABASE_URL", "").rstrip("/"),
            secret_key=secret,
            table=os.getenv(
                "FLEXMAP_SUPABASE_VAULT_TABLE", "flexmap_dataset_recordings"
            ),
            bucket=os.getenv("FLEXMAP_SUPABASE_VAULT_BUCKET", "flexmap-dataset"),
            cv_bucket=os.getenv("FLEXMAP_SUPABASE_CV_BUCKET", "flexmap-cv-vault"),
            emg_bucket=os.getenv("FLEXMAP_SUPABASE_EMG_BUCKET", "flexmap-emg-vault"),
            enabled=os.getenv("FLEXMAP_SUPABASE_SYNC_ENABLED", "false").lower()
            == "true",
            upload_artifacts=os.getenv(
                "FLEXMAP_SUPABASE_UPLOAD_ARTIFACTS", "false"
            ).lower()
            == "true",
            timeout_seconds=float(
                os.getenv("FLEXMAP_SUPABASE_TIMEOUT_SECONDS", "20")
            ),
        )

    @property
    def configured(self) -> bool:
        return bool(self.url and self.secret_key)

    def auth_headers(self) -> dict[str, str]:
        """Return documented headers for current and legacy server keys.

        New ``sb_secret_`` keys are opaque API keys, not JWTs. Legacy
        service-role JWTs remain compatible with projects that have not yet
        migrated to Supabase's current key format.
        """
        headers = {"apikey": self.secret_key}
        if not self.secret_key.startswith("sb_secret_"):
            headers["Authorization"] = f"Bearer {self.secret_key}"
        return headers

    def validate(self) -> None:
        if not self.configured:
            raise SupabaseVaultError(
                "Supabase vault is not configured; set FLEXMAP_SUPABASE_URL and "
                "FLEXMAP_SUPABASE_SECRET_KEY"
            )
        parsed = urlparse(self.url)
        local = parsed.hostname in {"localhost", "127.0.0.1"}
        if not parsed.hostname or (parsed.scheme != "https" and not local):
            raise SupabaseVaultError(
                "Supabase URL must use HTTPS (HTTP is allowed only for localhost)"
            )
        for name, value in (("table", self.table), ("bucket", self.bucket), ("cv_bucket", self.cv_bucket), ("emg_bucket", self.emg_bucket)):
            if not value or any(character not in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-_" for character in value):
                raise SupabaseVaultError(f"Invalid Supabase {name} name")


class SupabaseVaultMirror:
    """Mirrors local canonical vault metadata and, optionally, private artifacts."""

    def __init__(
        self,
        config: SupabaseVaultConfig | None = None,
        *,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        self.config = config or SupabaseVaultConfig.from_env()
        self._transport = transport

    def public_status(self) -> dict[str, Any]:
        parsed = urlparse(self.config.url) if self.config.url else None
        return {
            "configured": self.config.configured,
            "enabled": self.config.enabled,
            "upload_artifacts": self.config.upload_artifacts,
            "project_host": parsed.hostname if parsed else None,
            "table": self.config.table,
            "bucket": self.config.bucket,
        }

    def _client(self) -> httpx.Client:
        self.config.validate()
        return httpx.Client(
            base_url=self.config.url,
            headers={**self.config.auth_headers(), "User-Agent": "FlexMap-Vault/1.0"},
            timeout=self.config.timeout_seconds,
            follow_redirects=False,
            transport=self._transport,
        )

    @staticmethod
    def _raise(response: httpx.Response, operation: str) -> None:
        if response.is_success:
            return
        detail = response.text[:500].strip()
        raise SupabaseVaultError(
            f"Supabase {operation} failed ({response.status_code})"
            + (f": {detail}" if detail else "")
        )

    def check_connection(self) -> dict[str, Any]:
        status = self.public_status()
        if not self.config.configured:
            return {**status, "reachable": False, "error": "NOT_CONFIGURED"}
        try:
            with self._client() as client:
                response = client.get(
                    f"/rest/v1/{quote(self.config.table, safe='')}",
                    params={"select": "recording_id", "limit": "1"},
                )
                self._raise(response, "connection check")
            return {**status, "reachable": True, "error": None}
        except (httpx.HTTPError, SupabaseVaultError) as exc:
            return {**status, "reachable": False, "error": str(exc)}

    @staticmethod
    def _payload(record: dict[str, Any], storage_prefix: str) -> dict[str, Any]:
        metadata = record.get("metadata") or {}
        quality = record.get("quality_report")
        label = record.get("research_label") or record.get("label")
        return {
            "recording_id": record["recording_id"],
            "modality": record.get("modality", "CV"),
            "subject_id": record.get("subject_id"),
            "session_id": record.get("session_id"),
            "study_id": record.get("study_id") or metadata.get("study_id"),
            "collection_id": record.get("collection_id")
            or metadata.get("collection_id"),
            "protocol_id": record.get("protocol_id") or metadata.get("protocol_id"),
            "protocol_version": record.get("protocol_version")
            or metadata.get("protocol_version"),
            "trial_id": record.get("trial_id") or metadata.get("trial_id"),
            "rehab_type": record.get("rehab_type") or record.get("category"),
            "rehab_slug": record.get("rehab_slug"),
            "research_label": label,
            "affected_side": record.get("affected_side"),
            "created_at": record.get("created_at"),
            "duration_seconds": record.get("duration_seconds"),
            "technical_quality": record.get("technical_quality"),
            "review_status": record.get("review_status"),
            "training_eligible": bool(record.get("training_eligible")),
            "excluded": bool(record.get("excluded")),
            "is_mock": bool(record.get("is_mock") or metadata.get("is_mock")),
            "dataset_schema_version": record.get("dataset_schema_version")
            or metadata.get("dataset_schema_version"),
            "local_relative_path": record.get("relative_path"),
            "storage_prefix": storage_prefix,
            "files": record.get("files") or [],
            "metadata": metadata,
            "quality_report": quality,
            "artifact_references": record.get("artifact_references") or {},
            "schema_versions": record.get("schema_versions") or {},
            "deleted_at": record.get("deleted_at"),
            "synced_at": datetime.now(timezone.utc).isoformat(),
        }

    def _upload_file(
        self, client: httpx.Client, local_path: Path, object_path: str
    ) -> None:
        content_type = mimetypes.guess_type(local_path.name)[0] or "application/octet-stream"
        with local_path.open("rb") as handle:
            response = client.post(
                "/storage/v1/object/"
                + quote(self.config.bucket, safe="")
                + "/"
                + quote(object_path, safe="/"),
                headers={"Content-Type": content_type, "x-upsert": "true"},
                content=handle,
            )
        self._raise(response, f"artifact upload ({local_path.name})")

    def sync_recording(
        self, record: dict[str, Any], recording_path: Path | None = None
    ) -> dict[str, Any]:
        if not self.config.enabled:
            return {
                "recording_id": record.get("recording_id"),
                "status": "DISABLED",
                "artifacts_uploaded": 0,
            }
        self.config.validate()
        recording_id = str(record["recording_id"])
        modality = str(record.get("modality", "CV")).lower()
        storage_prefix = f"{modality}/{recording_id}"
        uploaded = 0
        try:
            with self._client() as client:
                if self.config.upload_artifacts and recording_path:
                    root = recording_path.resolve()
                    if not root.is_dir():
                        raise SupabaseVaultError("Local recording folder is unavailable")
                    for path in sorted(root.rglob("*")):
                        if not path.is_file():
                            continue
                        relative = path.resolve().relative_to(root).as_posix()
                        self._upload_file(
                            client, path, f"{storage_prefix}/{relative}"
                        )
                        uploaded += 1
                response = client.post(
                    f"/rest/v1/{quote(self.config.table, safe='')}",
                    params={"on_conflict": "recording_id"},
                    headers={
                        "Content-Type": "application/json",
                        "Prefer": "resolution=merge-duplicates,return=minimal",
                    },
                    json=self._payload(record, storage_prefix),
                )
                self._raise(response, "recording upsert")
        except httpx.HTTPError as exc:
            raise SupabaseVaultError(f"Supabase request failed: {exc}") from exc
        return {
            "recording_id": recording_id,
            "status": "SYNCED",
            "artifacts_uploaded": uploaded,
        }

    def sync_many(
        self, records: Iterable[tuple[dict[str, Any], Path | None]]
    ) -> dict[str, Any]:
        results = []
        for record, path in records:
            try:
                results.append(self.sync_recording(record, path))
            except SupabaseVaultError as exc:
                results.append(
                    {
                        "recording_id": record.get("recording_id"),
                        "status": "FAILED",
                        "error": str(exc),
                        "artifacts_uploaded": 0,
                    }
                )
        return {
            "total": len(results),
            "synced": sum(item["status"] == "SYNCED" for item in results),
            "failed": sum(item["status"] == "FAILED" for item in results),
            "disabled": sum(item["status"] == "DISABLED" for item in results),
            "results": results,
        }

    def mark_deleted(self, recording_id: str) -> dict[str, Any]:
        if not self.config.enabled:
            return {"recording_id": recording_id, "status": "DISABLED"}
        self.config.validate()
        try:
            with self._client() as client:
                response = client.patch(
                    f"/rest/v1/{quote(self.config.table, safe='')}",
                    params={"recording_id": f"eq.{recording_id}"},
                    headers={
                        "Content-Type": "application/json",
                        "Prefer": "return=minimal",
                    },
                    json={
                        "deleted_at": datetime.now(timezone.utc).isoformat(),
                        "training_eligible": False,
                        "review_status": "DELETED",
                    },
                )
                self._raise(response, "recording deletion sync")
        except httpx.HTTPError as exc:
            raise SupabaseVaultError(f"Supabase request failed: {exc}") from exc
        return {"recording_id": recording_id, "status": "SYNCED"}
