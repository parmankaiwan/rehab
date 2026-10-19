from __future__ import annotations

import csv
import io
import json
import math
from collections import defaultdict
from typing import Any, Iterable

import numpy as np


CV_FEATURES_V2 = [
    "movement_duration_seconds",
    "usable_tracked_frame_ratio",
    "mean_landmark_visibility",
    "left_elbow_angle_mean_deg",
    "left_elbow_rom_deg",
    "left_elbow_angular_velocity_mean_deg_s",
    "left_elbow_movement_smoothness",
    "right_elbow_angle_mean_deg",
    "right_elbow_rom_deg",
    "right_elbow_angular_velocity_mean_deg_s",
    "right_elbow_movement_smoothness",
    "trunk_displacement_shoulder_widths",
    "shoulder_compensation_shoulder_widths",
]

EMG_FEATURES_V2 = [
    "channel_count",
    "sample_count",
    "valid_sample_ratio",
    "duration_seconds",
    "sample_rate_hz",
    "channel_rms_mean",
    "channel_mav_mean",
    "channel_waveform_length_mean",
    "channel_integrated_emg_mean",
    "channel_peak_to_peak_mean",
    "channel_clipping_ratio_max",
    "channel_median_frequency_mean_hz",
]


def parse_pose_observations(content: bytes) -> list[dict[str, Any]]:
    text = content.decode("utf-8-sig").strip()
    if not text:
        return []
    if text[0] in "[{":
        try:
            parsed = json.loads(text)
        except json.JSONDecodeError:
            parsed = None
        if isinstance(parsed, list):
            return [item for item in parsed if isinstance(item, dict)]
        if isinstance(parsed, dict):
            values = parsed.get("observations") or parsed.get("samples")
            if values is None:
                return [parsed]
            return [item for item in values if isinstance(item, dict)]
    return [json.loads(line) for line in text.splitlines() if line.strip()]


def _finite(value: Any) -> float | None:
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    return result if math.isfinite(result) else None


def _landmarks(observation: dict[str, Any]) -> dict[int, dict[str, float]]:
    raw = observation.get("normalizedLandmarks") or observation.get("normalized_landmarks") or []
    result: dict[int, dict[str, float]] = {}
    for fallback_index, point in enumerate(raw):
        if not isinstance(point, dict):
            continue
        index = int(point.get("index", fallback_index))
        x, y = _finite(point.get("x")), _finite(point.get("y"))
        if x is None or y is None:
            continue
        result[index] = {
            "x": x,
            "y": y,
            "z": _finite(point.get("z")) or 0.0,
            "visibility": _finite(point.get("visibility")) or 0.0,
        }
    return result


def _angle(a: dict[str, float], b: dict[str, float], c: dict[str, float]) -> float | None:
    first = np.asarray([a["x"] - b["x"], a["y"] - b["y"]], dtype=float)
    second = np.asarray([c["x"] - b["x"], c["y"] - b["y"]], dtype=float)
    denominator = float(np.linalg.norm(first) * np.linalg.norm(second))
    if denominator <= 1e-12:
        return None
    cosine = float(np.clip(np.dot(first, second) / denominator, -1.0, 1.0))
    return math.degrees(math.acos(cosine))


def _series_features(values: list[float], times: list[float]) -> tuple[float, float, float, float]:
    if not values:
        return (math.nan, math.nan, math.nan, math.nan)
    array = np.asarray(values, dtype=float)
    mean = float(np.mean(array))
    rom = float(np.ptp(array))
    if len(array) < 2:
        return (mean, rom, math.nan, math.nan)
    time_array = np.asarray(times, dtype=float)
    delta = np.diff(time_array)
    usable = delta > 1e-6
    velocity = np.diff(array)[usable] / delta[usable]
    if not len(velocity):
        return (mean, rom, math.nan, math.nan)
    mean_velocity = float(np.mean(np.abs(velocity)))
    # A bounded descriptive smoothness score. It is not a clinical scale.
    smoothness = float(1.0 / (1.0 + np.std(np.diff(velocity)))) if len(velocity) > 1 else 1.0
    return (mean, rom, mean_velocity, smoothness)


def extract_cv_features(observations: Iterable[dict[str, Any]], *, visibility_threshold: float = 0.5) -> dict[str, float]:
    rows = list(observations)
    left_values: list[float] = []
    left_times: list[float] = []
    right_values: list[float] = []
    right_times: list[float] = []
    visibility: list[float] = []
    trunk: list[tuple[float, float]] = []
    shoulder_offsets: list[float] = []
    usable = 0
    timestamps: list[float] = []
    for index, row in enumerate(rows):
        timestamp_ms = _finite(row.get("playbackOffsetMs"))
        time_seconds = (timestamp_ms / 1000.0) if timestamp_ms is not None else float(index) / 30.0
        timestamps.append(time_seconds)
        points = _landmarks(row)
        visibility.extend(point["visibility"] for point in points.values())
        required = (11, 12, 13, 14, 15, 16, 23, 24)
        frame_usable = bool(row.get("valid", True)) and all(
            landmark in points and points[landmark]["visibility"] >= visibility_threshold for landmark in required
        )
        if not frame_usable:
            continue
        usable += 1
        left = _angle(points[11], points[13], points[15])
        right = _angle(points[12], points[14], points[16])
        if left is not None:
            left_values.append(left)
            left_times.append(time_seconds)
        if right is not None:
            right_values.append(right)
            right_times.append(time_seconds)
        shoulder_width = math.dist((points[11]["x"], points[11]["y"]), (points[12]["x"], points[12]["y"]))
        if shoulder_width > 1e-9:
            shoulder_mid = ((points[11]["x"] + points[12]["x"]) / 2, (points[11]["y"] + points[12]["y"]) / 2)
            hip_mid = ((points[23]["x"] + points[24]["x"]) / 2, (points[23]["y"] + points[24]["y"]) / 2)
            trunk.append(((shoulder_mid[0] - hip_mid[0]) / shoulder_width, (shoulder_mid[1] - hip_mid[1]) / shoulder_width))
            shoulder_offsets.append(abs(points[11]["y"] - points[12]["y"]) / shoulder_width)
    left = _series_features(left_values, left_times)
    right = _series_features(right_values, right_times)
    trunk_displacement = math.nan
    if trunk:
        origin = trunk[0]
        trunk_displacement = float(max(math.dist(origin, point) for point in trunk))
    duration = max(timestamps) - min(timestamps) if len(timestamps) > 1 else 0.0
    return dict(zip(CV_FEATURES_V2, [
        duration,
        usable / len(rows) if rows else 0.0,
        float(np.mean(visibility)) if visibility else 0.0,
        *left,
        *right,
        trunk_displacement,
        float(np.mean(shoulder_offsets)) if shoulder_offsets else math.nan,
    ]))


def extract_emg_features(content: bytes, *, sample_rate_hz: float | None = None) -> dict[str, float]:
    rows = list(csv.DictReader(io.StringIO(content.decode("utf-8-sig"))))
    channel_names = sorted({key for row in rows for key in row if key.startswith("channel_")})
    channels: dict[str, list[float]] = defaultdict(list)
    valid_rows = 0
    for row in rows:
        explicit_valid = str(row.get("valid", "true")).lower() in {"1", "true", "yes"}
        row_valid = explicit_valid
        for name in channel_names:
            value = _finite(row.get(name))
            if value is None:
                row_valid = False
            else:
                channels[name].append(value)
        valid_rows += int(row_valid)
    if not channel_names or not any(channels.values()):
        raise ValueError("EMG artifact contains no numeric channel samples")
    metrics: dict[str, list[float]] = defaultdict(list)
    for name in channel_names:
        raw = np.asarray(channels[name], dtype=float)
        if not len(raw):
            continue
        signal = raw - np.mean(raw)
        metrics["rms"].append(float(np.sqrt(np.mean(np.square(signal)))))
        metrics["mav"].append(float(np.mean(np.abs(signal))))
        metrics["waveform_length"].append(float(np.sum(np.abs(np.diff(signal)))))
        metrics["integrated_emg"].append(float(np.sum(np.abs(signal))))
        metrics["peak_to_peak"].append(float(np.ptp(raw)))
        minimum, maximum = float(np.min(raw)), float(np.max(raw))
        metrics["clipping"].append(float(np.mean((raw == minimum) | (raw == maximum))) if maximum > minimum else 1.0)
        if sample_rate_hz and sample_rate_hz > 0 and len(signal) >= 32 and np.std(signal) > 0:
            power = np.abs(np.fft.rfft(signal)) ** 2
            frequencies = np.fft.rfftfreq(len(signal), d=1.0 / sample_rate_hz)
            cumulative = np.cumsum(power)
            if cumulative[-1] > 0:
                metrics["median_frequency"].append(float(frequencies[np.searchsorted(cumulative, cumulative[-1] / 2)]))
    duration = (len(rows) - 1) / sample_rate_hz if sample_rate_hz and sample_rate_hz > 0 and len(rows) > 1 else math.nan
    mean = lambda name: float(np.mean(metrics[name])) if metrics[name] else math.nan
    return dict(zip(EMG_FEATURES_V2, [
        float(len(channel_names)), float(len(rows)), valid_rows / len(rows) if rows else 0.0,
        duration, float(sample_rate_hz) if sample_rate_hz else math.nan,
        mean("rms"), mean("mav"), mean("waveform_length"), mean("integrated_emg"),
        mean("peak_to_peak"), max(metrics["clipping"]) if metrics["clipping"] else math.nan,
        mean("median_frequency"),
    ]))
