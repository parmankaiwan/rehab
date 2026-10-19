from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
from typing import Any
from urllib.parse import quote, urlparse

import httpx

from .supabase_vault import SupabaseVaultConfig, SupabaseVaultError


class MlCloudRepository:
    """Optional durable metadata/artifact mirror for hosted ML experiments.

    The feature is deliberately gated until the additive ML migration has been
    reviewed and applied. Local SQLite records remain the source of truth when
    the gate is disabled, preserving every existing experiment.
    """

    bucket = "flexmap-ml-vault"

    def __init__(self, config: SupabaseVaultConfig | None = None, *, transport: httpx.BaseTransport | None = None):
        self.config = config or SupabaseVaultConfig.from_env()
        self.enabled = os.getenv("FLEXMAP_ML_DURABLE_STORAGE_ENABLED", "false").lower() == "true"
        self.transport = transport

    def _client(self) -> httpx.Client:
        self.config.validate()
        return httpx.Client(
            base_url=self.config.url,
            headers={**self.config.auth_headers(), "User-Agent": "FlexMap-ML/2.0"},
            timeout=max(30.0, self.config.timeout_seconds),
            follow_redirects=False,
            transport=self.transport,
        )

    @staticmethod
    def _raise(response: httpx.Response, operation: str) -> None:
        if response.is_success:
            return
        raise SupabaseVaultError(f"Supabase ML {operation} failed ({response.status_code}): {response.text[:240]}")

    def public_status(self) -> dict[str, Any]:
        parsed = urlparse(self.config.url) if self.config.url else None
        return {
            "configured": self.config.configured,
            "enabled": self.enabled,
            "state": "ENABLED" if self.enabled and self.config.configured else "MIGRATION_OR_ENABLEMENT_REQUIRED",
            "project_host": parsed.hostname if parsed else None,
            "bucket": self.bucket,
            "private": True,
        }

    def upsert(self, table: str, identity: str, payload: dict[str, Any]) -> None:
        if not self.enabled:
            return
        with self._client() as client:
            response = client.post(
                f"/rest/v1/{table}",
                headers={"Prefer": f"resolution=merge-duplicates,return=minimal"},
                params={"on_conflict": identity},
                json=payload,
            )
            self._raise(response, f"{table} upsert")
            if table != "flexmap_ml_feature_pipelines":
                audit = client.post("/rest/v1/flexmap_ml_audit", json={
                    "entity_type": table,
                    "entity_id": str(payload.get(identity, "")),
                    "action": "UPSERT",
                    "new_value": {"status": payload.get("status"), "updated_fields": sorted(payload)},
                    "actor": "MASTER_BACKEND",
                })
                self._raise(audit, "audit insert")

    def get(self, table: str, identity: str, value: str) -> dict[str, Any] | None:
        if not self.enabled:
            return None
        with self._client() as client:
            response = client.get(f"/rest/v1/{table}", params={"select": "*", identity: f"eq.{value}", "limit": "1"})
            self._raise(response, f"{table} read")
            rows = response.json()
        return rows[0] if rows else None

    def list(self, table: str, order: str = "created_at.desc") -> list[dict[str, Any]]:
        if not self.enabled:
            return []
        with self._client() as client:
            response = client.get(f"/rest/v1/{table}", params={"select": "*", "order": order})
            self._raise(response, f"{table} list")
            return response.json()

    def upload_artifacts(self, training_run_id: str, directory: Path) -> list[dict[str, Any]]:
        if not self.enabled:
            return []
        manifest: list[dict[str, Any]] = []
        with self._client() as client:
            for path in sorted(item for item in directory.iterdir() if item.is_file()):
                content = path.read_bytes()
                sha256 = hashlib.sha256(content).hexdigest()
                object_path = f"runs/{training_run_id}/{path.name}"
                encoded = quote(object_path, safe="/")
                response = client.post(
                    f"/storage/v1/object/{self.bucket}/{encoded}",
                    headers={"Content-Type": "application/octet-stream", "x-upsert": "true"},
                    content=content,
                )
                self._raise(response, f"artifact upload ({path.name})")
                verified = client.get(f"/storage/v1/object/authenticated/{self.bucket}/{encoded}")
                self._raise(verified, f"artifact verification ({path.name})")
                if hashlib.sha256(verified.content).hexdigest() != sha256:
                    raise SupabaseVaultError(f"Supabase ML artifact checksum mismatch ({path.name})")
                manifest.append({"name": path.name, "object_path": object_path, "byte_size": len(content), "sha256": sha256})
        return manifest

    def upload_comparison_artifacts(self, experiment_id: str, directory: Path) -> list[dict[str, Any]]:
        if not self.enabled:
            return []
        manifest: list[dict[str, Any]] = []
        with self._client() as client:
            for path in sorted(item for item in directory.iterdir() if item.is_file()):
                content = path.read_bytes()
                sha256 = hashlib.sha256(content).hexdigest()
                object_path = f"comparisons/{experiment_id}/{path.name}"
                encoded = quote(object_path, safe="/")
                response = client.post(
                    f"/storage/v1/object/{self.bucket}/{encoded}",
                    headers={"Content-Type": "application/octet-stream", "x-upsert": "true"},
                    content=content,
                )
                self._raise(response, f"comparison artifact upload ({path.name})")
                verified = client.get(f"/storage/v1/object/authenticated/{self.bucket}/{encoded}")
                self._raise(verified, f"comparison artifact verification ({path.name})")
                if hashlib.sha256(verified.content).hexdigest() != sha256:
                    raise SupabaseVaultError(f"Supabase comparison artifact checksum mismatch ({path.name})")
                manifest.append({"name": path.name, "object_path": object_path, "byte_size": len(content), "sha256": sha256})
        return manifest

    def persist_comparison(self, experiment: dict[str, Any], directory: Path) -> list[dict[str, Any]]:
        if not self.enabled:
            return []
        manifest = self.upload_comparison_artifacts(experiment["experiment_id"], directory)
        self.upsert("flexmap_emg_comparison_experiments", "experiment_id", {
            "experiment_id": experiment["experiment_id"],
            "name": experiment["name"],
            "source_type": experiment["source_type"],
            "task": experiment["task"],
            "status": experiment["status"],
            "configuration": experiment["configuration"],
            "results": experiment.get("results"),
            "artifact_manifest": manifest,
            "evaluation_scope": "DEVELOPMENT_ONLY",
            "error": experiment.get("error"),
            "created_at": experiment["created_at"],
            "completed_at": experiment.get("completed_at"),
        })
        return manifest

    def persist_run(self, run: dict[str, Any], artifact_manifest: list[dict[str, Any]]) -> None:
        self.upsert("flexmap_ml_training_runs", "training_run_id", {
            "training_run_id": run["training_run_id"],
            "dataset_version_id": run["dataset_version_id"],
            "manifest_sha256": run["manifest_sha256"],
            "split_id": run["split_id"],
            "feature_pipeline_id": run["feature_pipeline_id"],
            "task": run["task"],
            "model_type": run["model_type"],
            "status": run["status"],
            "stage": run["stage"],
            "evaluation_scope": run["evaluation_scope"],
            "configuration": run.get("model_config") or {},
            "metrics": run.get("metrics"),
            "feature_importance": run.get("feature_importance"),
            "artifact_manifest": artifact_manifest,
            "created_at": run["created_at"],
            "started_at": run.get("started_at"),
            "completed_at": run.get("completed_at"),
            "error": run.get("error"),
        })

    def download_artifact(self, object_path: str, expected_sha256: str) -> bytes:
        if not self.enabled:
            raise SupabaseVaultError("Durable ML storage is disabled")
        with self._client() as client:
            response = client.get(f"/storage/v1/object/authenticated/{self.bucket}/{quote(object_path, safe='/')}")
            self._raise(response, "artifact download")
        if hashlib.sha256(response.content).hexdigest() != expected_sha256:
            raise SupabaseVaultError("Durable ML artifact checksum mismatch")
        return response.content
