from pathlib import Path
import pytest
from fastapi.testclient import TestClient
from backend.app import app

RID="REC-20260827-000008"
def test_master_video_is_authenticated_and_range_streamed(monkeypatch):
 monkeypatch.setenv("FLEXMAP_MASTER_INTERNAL_TOKEN","video-test-token")
 client=TestClient(app);url=f"/api/master/dataset/recordings/{RID}/video/raw"
 if not Path("data/dataset_vault/rehab/starting_posture/recordings").exists():pytest.skip("dataset fixture unavailable")
 assert client.get(url).status_code==403
 response=client.get(url,headers={"X-FlexMap-Master-Token":"video-test-token","Range":"bytes=0-1023"})
 assert response.status_code==206
 assert response.headers["content-type"]=="video/webm"
 assert response.headers["content-length"]=="1024"
 assert response.headers["content-range"].startswith("bytes 0-1023/")
 assert response.headers["accept-ranges"]=="bytes"
 assert len(response.content)==1024
 invalid=client.get(url,headers={"X-FlexMap-Master-Token":"video-test-token","Range":"bytes=99999999-"})
 assert invalid.status_code==416
def test_video_status_rejects_path_like_recording_id(monkeypatch):
 monkeypatch.setenv("FLEXMAP_MASTER_INTERNAL_TOKEN","video-test-token")
 response=TestClient(app).get("/api/master/dataset/recordings/..%2F..%2Fsecret/video-status",headers={"X-FlexMap-Master-Token":"video-test-token"})
 assert response.status_code in (404,422)
