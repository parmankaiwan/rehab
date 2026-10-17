import httpx

from backend.data_backend import StorageStatusService
from backend.supabase_vault import SupabaseVaultConfig


def config(**overrides):
    values = {"url": "https://project.supabase.co", "secret_key": "sb_secret_test", "cv_bucket": "flexmap-cv-vault", "emg_bucket": "flexmap-emg-vault", "enabled": False, "timeout_seconds": 5}
    values.update(overrides)
    return SupabaseVaultConfig(**values)


def test_local_mode_does_not_contact_supabase(monkeypatch):
    monkeypatch.setenv("FLEXMAP_DATA_BACKEND", "local")
    service = StorageStatusService(config(), transport=httpx.MockTransport(lambda _: (_ for _ in ()).throw(AssertionError("no network"))))
    status = service.check()
    assert status["state"] == "LOCAL_READY"
    assert status["database"] == "LOCAL"


def test_supabase_status_performs_database_schema_and_private_bucket_checks(monkeypatch):
    monkeypatch.setenv("FLEXMAP_DATA_BACKEND", "supabase")
    paths = []

    def handler(request: httpx.Request):
        paths.append(request.url.path)
        assert request.headers["apikey"] == "sb_secret_test"
        assert "authorization" not in request.headers
        if request.url.path.endswith("flexmap_schema_migrations"):
            return httpx.Response(200, json=[{"version": "202610170001"}])
        if request.url.path.startswith("/storage/v1/bucket"):
            return httpx.Response(200, json={"id": request.url.path.rsplit("/", 1)[-1], "public": False})
        if request.url.path.endswith("flexmap_browser_samples"):
            return httpx.Response(200, json=[], headers={"content-range": "*/0"})
        return httpx.Response(200, json=[])

    status = StorageStatusService(config(), transport=httpx.MockTransport(handler)).check()
    assert status["state"] == "READY"
    assert status["database"] == "CONNECTED"
    assert status["schema"] == "CURRENT"
    assert status["bucket"] == "CV_PRIVATE_EMG_PRIVATE"
    assert len(paths) == 6


def test_database_failure_has_distinct_state(monkeypatch):
    monkeypatch.setenv("FLEXMAP_DATA_BACKEND", "supabase")

    def handler(_: httpx.Request):
        raise httpx.ConnectError("offline")

    status = StorageStatusService(config(), transport=httpx.MockTransport(handler)).check()
    assert status["state"] == "DATABASE_UNAVAILABLE"
    assert status["database"] == "UNREACHABLE"


def test_authoritative_mode_rejects_optional_mirror_conflict(monkeypatch):
    monkeypatch.setenv("FLEXMAP_DATA_BACKEND", "supabase")
    status = StorageStatusService(config(enabled=True)).check()
    assert status["state"] == "CONFIGURATION_CONFLICT"
