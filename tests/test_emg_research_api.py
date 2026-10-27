import hashlib
import json
import zipfile
import io

from fastapi.testclient import TestClient
from backend.app import app
from backend import emg_comparison as engine


def test_research_auth_exports_recovery_and_test_device(monkeypatch,tmp_path):
    monkeypatch.setenv("FLEXMAP_MASTER_INTERNAL_TOKEN","research-test-token")
    monkeypatch.setattr(engine,"DB_PATH",tmp_path/"experiments.sqlite3")
    monkeypatch.setattr(engine,"ROOT",tmp_path/"research")
    engine.ROOT.mkdir();engine.initialize()
    client=TestClient(app);headers={"X-FlexMap-Master-Token":"research-test-token"}
    assert client.get("/api/master/ml/emg-comparison/research/catalog").status_code==403
    assert client.get("/api/master/ml/emg-comparison/research/catalog",headers=headers).status_code==200
    config={"study":"A","simulation":{"frames":24},"functions":["POLYNOMIAL","MOVING_PEAK"],"sweep_values":[.15,.3],"trials":2,"optimization_candidates":2}
    # Execute the same worker synchronously in this API regression to avoid a
    # test-owned spawn pool. Actual subprocess execution is exercised by acceptance.
    class Immediate:
        def add_done_callback(self,callback):callback(self)
    def submit(fn,*args):fn(*args);return Immediate()
    monkeypatch.setattr(engine.research_processes,"submit",submit)
    prefix="/api/master/ml/emg-comparison"
    created=client.post(prefix+"/research/experiments",headers=headers,json=config)
    assert created.status_code==200,created.text
    identifier=created.json()["experiment_id"]
    saved=client.get(prefix+f"/experiments/{identifier}",headers=headers).json()
    assert saved["status"]=="COMPLETED",saved.get("error")
    assert len(saved["results"]["scenarios"])==8
    before=hashlib.sha256(json.dumps(saved,sort_keys=True).encode()).hexdigest()
    engine.initialize()
    reopened=client.get(prefix+f"/experiments/{identifier}",headers=headers).json()
    assert hashlib.sha256(json.dumps(reopened,sort_keys=True).encode()).hexdigest()==before
    assert client.post(prefix+f"/experiments/{identifier}/cancel",headers=headers).status_code==409
    for ext in ("json","csv","zip"):
        result=client.get(prefix+f"/experiments/{identifier}/export.{ext}",headers=headers)
        assert result.status_code==200
        if ext=="zip":
            names=zipfile.ZipFile(io.BytesIO(result.content)).namelist()
            assert {"results.json","comparison.csv","study_a.png","study_a.svg","artifact_manifest.json"}.issubset(names)
    assert client.get(prefix+f"/experiments/{identifier}/figures/study_a.png",headers=headers).content.startswith(b"\x89PNG")
    device=client.post(prefix+"/research/test-device",headers=headers,json={"channels":[{"channel_id":f"channel_{i}"} for i in (1,2,3)]}).json()
    read=client.get(prefix+"/research/test-device/"+device["test_recording_id"],headers=headers)
    assert read.status_code==200
    assert read.json()["recording_integrity"]["sha256"]==device["recording_integrity"]["sha256"]
    assert len(read.json()["waveform"])==3
