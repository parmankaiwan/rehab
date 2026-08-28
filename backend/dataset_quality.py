from __future__ import annotations

import hashlib
import json
import math
import statistics
from pathlib import Path
from typing import Any

REQUIRED_LANDMARKS = ("LEFT_SHOULDER", "RIGHT_SHOULDER", "LEFT_ELBOW", "RIGHT_ELBOW", "LEFT_WRIST", "RIGHT_WRIST", "LEFT_HIP", "RIGHT_HIP")


def percentile(values: list[float], fraction: float) -> float | None:
    if not values: return None
    ordered = sorted(values); index = (len(ordered) - 1) * fraction
    low, high = math.floor(index), math.ceil(index)
    return ordered[low] if low == high else ordered[low] + (ordered[high] - ordered[low]) * (index - low)


def build_quality_report(recording_id: str, frames: list[dict], duration: float, raw_frames: int, annotated_frames: int, dropped: int, raw_valid: bool, annotated_valid: bool) -> dict[str, Any]:
    qualities = {name: sum(frame.get("tracking_quality") == name for frame in frames) for name in ("GOOD", "POOR", "LOST")}
    total = max(1, len(frames)); timestamps = [float(frame["timestamp_ms"]) for frame in frames]
    intervals = [b-a for a,b in zip(timestamps, timestamps[1:])]
    coverage: dict[str, dict[str, float | None]] = {}
    for name in REQUIRED_LANDMARKS:
        points = [frame.get("landmarks", {}).get(name) for frame in frames]
        valid = [point for point in points if point and point.get("valid", True)]
        visibility = [float(point["visibility"]) for point in valid if point.get("visibility") is not None]
        coverage[name] = {"valid_frame_ratio": len(valid)/total, "mean_visibility": statistics.fmean(visibility) if visibility else None, "minimum_visibility": min(visibility) if visibility else None}
    warnings: list[str] = []
    lost_ratio = qualities["LOST"]/total
    pose_rate = len(frames)/duration if duration else 0
    if pose_rate < 8: warnings.append("LOW_POSE_SAMPLE_RATE")
    if lost_ratio > .2: warnings.append("HIGH_TRACKING_LOSS")
    if intervals and max(intervals) > 250: warnings.append("TIMESTAMP_GAP")
    if dropped: warnings.append("VIDEO_FRAME_COUNT_MISMATCH")
    if not raw_valid: warnings.append("VIDEO_WRITE_FAILURE")
    state = "GOOD" if not warnings else "USABLE_WITH_WARNINGS"
    if lost_ratio > .5: state = "LOW_QUALITY"
    if not frames or (raw_frames == 0 and annotated_frames == 0): state = "INVALID"
    return {"dataset_schema_version":"2.0","recording_id":recording_id,"overall_technical_quality":state,"raw_video_frame_count":raw_frames,"annotated_video_frame_count":annotated_frames,"pose_sample_count":len(frames),"pose_sample_rate_hz":pose_rate,"tracking_good_ratio":qualities["GOOD"]/total,"tracking_poor_ratio":qualities["POOR"]/total,"tracking_lost_ratio":lost_ratio,"landmark_coverage":coverage,"maximum_pose_gap_ms":max(intervals) if intervals else None,"median_pose_interval_ms":statistics.median(intervals) if intervals else None,"p95_pose_interval_ms":percentile(intervals,.95),"video_duration_seconds":duration,"pose_duration_seconds":((timestamps[-1]-timestamps[0])/1000) if len(timestamps)>1 else 0,"timestamp_monotonicity_valid":all(b>=a for a,b in zip(timestamps,timestamps[1:])),"raw_video_valid":raw_valid,"annotated_video_valid":annotated_valid,"dropped_recording_frames":dropped,"tracking_timeline":[frame.get("tracking_quality","LOST") for frame in frames],"warnings":warnings}


def artifact_manifest(folder: Path) -> dict[str, dict[str, Any]]:
    result = {}
    for path in folder.iterdir():
        if path.is_file() and path.name != "metadata.json":
            digest = hashlib.sha256(path.read_bytes()).hexdigest()
            result[path.name] = {"path":path.name,"sha256":digest,"size_bytes":path.stat().st_size}
    return result


def validate_sample_integrity(folder: Path, metadata: dict) -> list[str]:
    errors=[]; rid=metadata.get("recording_id")
    for filename in ("landmarks.json","landmarks.csv","measurements.json","quality_report.json","metadata.json"):
        if not (folder/filename).is_file(): errors.append(f"MISSING_{filename.upper().replace('.','_')}")
    for filename in ("landmarks.json","measurements.json","quality_report.json"):
        try:
            parsed=json.loads((folder/filename).read_text(encoding="utf-8"))
            if parsed.get("recording_id") != rid: errors.append(f"RECORDING_ID_MISMATCH_{filename}")
        except Exception: errors.append(f"INVALID_{filename.upper().replace('.','_')}")
    if metadata.get("raw_video_stored") and not (folder/"video.mp4").is_file(): errors.append("MISSING_RAW_VIDEO")
    if metadata.get("annotated_video_stored") and not (folder/"annotated_video.mp4").is_file(): errors.append("MISSING_ANNOTATED_VIDEO")
    return errors
