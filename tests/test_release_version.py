from fastapi.testclient import TestClient
from backend.app import app


def test_deployed_version_reports_only_valid_commit_metadata(monkeypatch):
    monkeypatch.setenv('RENDER_GIT_COMMIT', 'a' * 40)
    response = TestClient(app).get('/version')
    assert response.status_code == 200
    assert response.json()['commit'] == 'a' * 40
    monkeypatch.setenv('RENDER_GIT_COMMIT', 'invalid-not-a-commit')
    assert TestClient(app).get('/version').json() == {'application': 'flexmap-api', 'release': '2026-10-27-camera-emg', 'commit': None}
