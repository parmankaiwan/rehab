import math

import pytest

from backend.ml_features import extract_cv_features, extract_emg_features, parse_pose_observations


def pose_frame(elbow_x: float, timestamp_ms: int):
    points = {
        11: (0.3, 0.3), 12: (0.7, 0.3),
        13: (elbow_x, 0.5), 14: (0.7, 0.5),
        15: (0.3, 0.7), 16: (0.7, 0.7),
        23: (0.4, 0.8), 24: (0.6, 0.8),
    }
    return {
        "valid": True,
        "playbackOffsetMs": timestamp_ms,
        "normalizedLandmarks": [
            {"index": index, "x": x, "y": y, "z": 0, "visibility": 0.95}
            for index, (x, y) in points.items()
        ],
    }


def test_cv_v2_uses_landmark_geometry_and_timing():
    result = extract_cv_features([pose_frame(0.3, 0), pose_frame(0.4, 100), pose_frame(0.5, 200)])
    assert result["movement_duration_seconds"] == pytest.approx(0.2)
    assert result["usable_tracked_frame_ratio"] == 1
    assert result["mean_landmark_visibility"] == pytest.approx(0.95)
    assert result["left_elbow_rom_deg"] > 0
    assert result["left_elbow_angular_velocity_mean_deg_s"] > 0
    assert 0 <= result["left_elbow_movement_smoothness"] <= 1
    assert math.isfinite(result["trunk_displacement_shoulder_widths"])


def test_pose_parser_supports_json_and_json_lines():
    assert len(parse_pose_observations(b'[{"valid":true}]')) == 1
    assert len(parse_pose_observations(b'{"valid":true}\n{"valid":false}\n')) == 2


def test_emg_v2_preserves_channels_before_aggregation_and_gates_frequency():
    content = b"timestamp_ms,valid,channel_1,channel_2\n0,true,100,500\n1,true,110,490\n2,false,120,480\n3,true,130,470\n"
    result = extract_emg_features(content, sample_rate_hz=1000)
    assert result["channel_count"] == 2
    assert result["sample_count"] == 4
    assert result["valid_sample_ratio"] == pytest.approx(0.75)
    assert result["channel_rms_mean"] > 0
    assert math.isnan(result["channel_median_frequency_mean_hz"])


def test_emg_v2_frequency_requires_real_sampling_rate():
    rows = ["timestamp_ms,channel_1"] + [f"{i},{100 + (i % 8)}" for i in range(64)]
    without_rate = extract_emg_features("\n".join(rows).encode())
    with_rate = extract_emg_features("\n".join(rows).encode(), sample_rate_hz=1000)
    assert math.isnan(without_rate["channel_median_frequency_mean_hz"])
    assert math.isfinite(with_rate["channel_median_frequency_mean_hz"])
