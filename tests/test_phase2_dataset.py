from __future__ import annotations
import json,sqlite3
from pathlib import Path
import numpy as np
from backend.dataset_config import DatasetSettings
from backend.dataset_quality import artifact_manifest,build_quality_report
from backend.dataset_vault import DatasetVault
from backend.video_store import LatestVideoFrameStore

def config(tmp_path):
    labels=tmp_path/"labels.json";labels.write_text('{"STARTING_POSTURE":["acceptable_start"]}',encoding="utf-8")
    return DatasetSettings(tmp_path/"vault",labels)

def test_raw_and_annotated_stores_preserve_independent_frames_and_ids():
    raw,annotated=LatestVideoFrameStore(),LatestVideoFrameStore();raw_sub=raw.subscribe(4);ann_sub=annotated.subscribe(4)
    raw.update(b"raw",sequence=17,capture_timestamp_ns=100);annotated.update(b"annotated",sequence=17,capture_timestamp_ns=100)
    a,b=raw_sub.drain()[0],ann_sub.drain()[0]
    assert a.jpeg!=b.jpeg and a.sequence==b.sequence==17 and a.capture_timestamp_ns==b.capture_timestamp_ns==100

def test_recording_subscription_is_bounded_and_reports_drops():
    store=LatestVideoFrameStore();subscription=store.subscribe(3)
    for sequence in range(10):store.update(str(sequence).encode(),sequence=sequence)
    assert len(subscription.drain())==3 and subscription.dropped==7

def test_clean_frame_copy_is_not_modified_by_annotation():
    raw=np.zeros((10,10,3),dtype=np.uint8);annotated=raw.copy();annotated[2:5,2:5]=255
    assert not raw.any() and annotated.any() and not np.shares_memory(raw,annotated)

def test_quality_report_handles_150_frames_and_110_async_pose_results():
    frames=[]
    for index in range(110):frames.append({"timestamp_ms":index*45,"tracking_quality":"GOOD" if index<105 else "LOST","landmarks":{"LEFT_WRIST":{"valid":True,"visibility":.9}}})
    report=build_quality_report("REC-X",frames,5,150,150,0,True,True)
    assert report["raw_video_frame_count"]==150 and report["pose_sample_count"]==110
    assert report["pose_sample_rate_hz"]==22 and report["timestamp_monotonicity_valid"]
    assert report["maximum_pose_gap_ms"]==45 and len(report["tracking_timeline"])==110

def test_artifacts_receive_sha256_and_portable_relative_names(tmp_path):
    (tmp_path/"video.mp4").write_bytes(b"research-video")
    artifacts=artifact_manifest(tmp_path)
    assert len(artifacts["video.mp4"]["sha256"])==64 and artifacts["video.mp4"]["path"]=="video.mp4"

def test_database_migration_preserves_legacy_row_schema(tmp_path):
    settings=config(tmp_path);vault=DatasetVault(settings)
    with sqlite3.connect(settings.database_path) as db:columns={row[1] for row in db.execute("PRAGMA table_info(recordings)")}
    assert {"training_eligible","excluded","technical_quality","dataset_schema_version","protocol_id"}<=columns
    assert vault.scan_temp_recovery()==[]

def test_recording_paths_reject_traversal(tmp_path):
    vault=DatasetVault(config(tmp_path))
    for value in ("../secret","REC-X/../../secret","not-a-recording"):
        try:vault.recording_path(value)
        except ValueError:pass
        else:raise AssertionError("Traversal-like recording ID was accepted")

def test_only_existing_camera_manager_owns_videocapture():
    software=Path("backend").rglob("*.py")
    assert all("VideoCapture(" not in path.read_text(encoding="utf-8") for path in software)
