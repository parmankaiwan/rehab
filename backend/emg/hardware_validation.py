from __future__ import annotations

import math
import platform
import time
from typing import Any

import numpy as np
import scipy
from scipy import signal


def _percentiles(values: np.ndarray) -> dict[str, float | None]:
    if not len(values):
        return {"median_interval_ms": None, "p95_interval_ms": None, "p99_interval_ms": None, "max_interval_ms": None}
    return {
        "median_interval_ms": float(np.percentile(values, 50)),
        "p95_interval_ms": float(np.percentile(values, 95)),
        "p99_interval_ms": float(np.percentile(values, 99)),
        "max_interval_ms": float(np.max(values)),
    }


def analyze_sequences(values: list[int | None], modulus: int | None = None) -> dict[str, int]:
    seq = [int(x) for x in values if x is not None]
    missing = duplicates = out_of_order = rollovers = 0
    for previous, current in zip(seq, seq[1:]):
        if current == previous:
            duplicates += 1
        elif modulus and previous > modulus * .75 and current < modulus * .25:
            rollovers += 1
            missing += max(0, (current + modulus - previous) - 1)
        elif current < previous:
            out_of_order += 1
        else:
            missing += max(0, current - previous - 1)
    return {"device_sequence_gap_count": missing, "estimated_missing_samples": missing, "duplicate_sequence_count": duplicates, "out_of_order_count": out_of_order, "sequence_rollover_count": rollovers}


def timing_validation(samples: list[dict[str, Any]], configured_rate_hz: float, device_timestamp_unit: str | None = None, sequence_modulus: int | None = None) -> dict[str, Any]:
    host = np.asarray([x["host_timestamp_ns"] for x in samples], dtype=np.float64)
    host_intervals = np.diff(host) / 1e6
    duration = (host[-1] - host[0]) / 1e9 if len(host) > 1 else 0.0
    host_rate = (len(host) - 1) / duration if duration > 0 else None
    device_values = [x.get("device_timestamp") for x in samples]
    device_available = len(device_values) > 1 and all(x is not None for x in device_values)
    unit_scale = {"NANOSECONDS": 1e-9, "MICROSECONDS": 1e-6, "MILLISECONDS": 1e-3, "SECONDS": 1.0, "SAMPLE_TICKS": 1 / configured_rate_hz}.get(device_timestamp_unit or "")
    device_rate = drift_ppm = None
    duplicate_timestamps = nonmonotonic = large_jumps = 0
    clock_source = "CONFIGURED_FIXED_RATE"
    intervals = host_intervals
    warnings: list[str] = []
    if device_available:
        raw_diff = np.diff(np.asarray(device_values, dtype=np.float64))
        duplicate_timestamps = int(np.sum(raw_diff == 0))
        nonmonotonic = int(np.sum(raw_diff < 0))
        if unit_scale:
            device_seconds = raw_diff * unit_scale
            positive = device_seconds[device_seconds > 0]
            if len(positive):
                device_rate = float(1 / np.median(positive))
                intervals = positive * 1000
                clock_source = "DEVICE_TIMESTAMP"
                expected = 1 / configured_rate_hz
                large_jumps = int(np.sum(positive > expected * 2.5))
                if duration >= 30 and configured_rate_hz:
                    drift_ppm = float((device_rate - configured_rate_hz) / configured_rate_hz * 1e6)
        else:
            warnings.append("DEVICE_TIMESTAMP_UNIT_UNKNOWN")
    sequence = analyze_sequences([x.get("device_sequence_id") for x in samples], sequence_modulus)
    if not any(x.get("device_sequence_id") is not None for x in samples):
        warnings.append("DEVICE_SEQUENCE_UNAVAILABLE_HOST_SEQUENCE_CANNOT_DETECT_PRE_INGESTION_LOSS")
    if duplicate_timestamps: warnings.append("DUPLICATE_DEVICE_TIMESTAMP")
    if nonmonotonic: warnings.append("NON_MONOTONIC_DEVICE_TIMESTAMP")
    if large_jumps: warnings.append("DEVICE_TIMESTAMP_LARGE_JUMP")
    if sequence["estimated_missing_samples"]: warnings.append("DEVICE_SEQUENCE_GAPS")
    if host_rate and abs(host_rate - configured_rate_hz) / configured_rate_hz > .05: warnings.append("HOST_RATE_OUTSIDE_5_PERCENT")
    result = "COMPLETE WITH WARNINGS" if warnings else "COMPLETE"
    return {"schema_version":"1.0", "sampling_clock_source":clock_source, "configured_sample_rate_hz":configured_rate_hz, "device_sample_rate_hz_estimated":device_rate, "host_receive_rate_hz":host_rate, "sample_count":len(samples), "duration_seconds":duration, **sequence, **_percentiles(intervals), "duplicate_device_timestamp_count":duplicate_timestamps, "nonmonotonic_device_timestamp_count":nonmonotonic, "large_device_timestamp_jump_count":large_jumps, "clock_drift_ppm":drift_ppm, "stale_periods":int(np.sum(host_intervals > 250)) if len(host_intervals) else 0, "technical_result":result, "warnings":warnings}


def adc_validation(samples: list[dict[str, Any]], profile: dict[str, Any]) -> dict[str, Any]:
    channels = sorted({key for row in samples for key in row.get("channels", {})})
    configured_min, configured_max = profile.get("adc_min_count"), profile.get("adc_max_count")
    representation = profile.get("raw_representation", "CUSTOM")
    reports = {}
    warnings = []
    for channel in channels:
        values = np.asarray([row["channels"][channel] for row in samples if channel in row.get("channels", {})], dtype=float)
        outside = np.zeros(len(values), dtype=bool)
        if configured_min is not None: outside |= values < configured_min
        if configured_max is not None: outside |= values > configured_max
        clipping = np.zeros(len(values), dtype=bool)
        if configured_min is not None: clipping |= values == configured_min
        if configured_max is not None: clipping |= values == configured_max
        channel_warnings = []
        if outside.any(): channel_warnings.append("RAW_VALUE_OUTSIDE_CONFIGURED_ADC_RANGE")
        if len(values) and clipping.mean() > .01: channel_warnings.append("CLIPPING")
        warnings.extend(f"{channel}:{warning}" for warning in channel_warnings)
        reports[channel] = {"sample_count":len(values), "minimum_observed":float(values.min()) if len(values) else None, "maximum_observed":float(values.max()) if len(values) else None, "mean":float(values.mean()) if len(values) else None, "median":float(np.median(values)) if len(values) else None, "standard_deviation":float(values.std()) if len(values) else None, "clipping_ratio":float(clipping.mean()) if len(values) else None, "out_of_range_count":int(outside.sum()), "unique_value_count":int(len(np.unique(values))), "effective_range_used":float(values.max()-values.min()) if len(values) else None, "warnings":channel_warnings}
    return {"schema_version":"1.0", "raw_representation":representation, "configured_range":{"minimum":configured_min,"maximum":configured_max}, "channels":reports, "warnings":warnings, "raw_values_clamped":False}


def conversion_config(profile: dict[str, Any]) -> dict[str, Any]:
    representation = profile.get("raw_representation")
    if representation in ("MILLIVOLTS", "MICROVOLTS"):
        return {"available":True, "output_unit":"mV" if representation == "MILLIVOLTS" else "uV", "method":"DEVICE_REPORTED_PHYSICAL_UNITS", "conversion_version":"1.0", "source_raw_representation":representation}
    required = ("adc_reference_voltage_v", "adc_bits", "adc_zero_code", "analog_frontend_gain")
    missing = [key for key in required if profile.get(key) is None]
    if missing:
        return {"available":False, "output_unit":None, "reason":"MISSING_REQUIRED_CONFIGURATION", "missing_fields":missing, "source_raw_representation":representation}
    return {"available":True, "output_unit":"V", "method":"LINEAR_ADC_TO_DERIVED_INPUT_VOLTAGE", "conversion_version":"1.0", "formula":"((raw/(2^bits-1))*Vref - zero_voltage - frontend_offset)/gain", "source_raw_representation":representation, "config":{key:profile.get(key) for key in required + ("analog_frontend_offset_v",)}}


def convert_physical(raw: float, profile: dict[str, Any]) -> float | None:
    cfg = conversion_config(profile)
    if not cfg["available"]: return None
    representation = profile.get("raw_representation")
    if representation == "MILLIVOLTS": return raw / 1000
    if representation == "MICROVOLTS": return raw / 1_000_000
    full_scale = 2 ** profile["adc_bits"] - 1
    zero_voltage = profile["adc_zero_code"] / full_scale * profile["adc_reference_voltage_v"]
    return ((raw / full_scale * profile["adc_reference_voltage_v"]) - zero_voltage - (profile.get("analog_frontend_offset_v") or 0)) / profile["analog_frontend_gain"]


def baseline_repeatability(trials: list[dict[str, Any]]) -> dict[str, Any]:
    channels = sorted({key for trial in trials for key in trial.get("summary", {})})
    reports, warnings = {}, []
    for channel in channels:
        rows = [trial["summary"][channel] for trial in trials if channel in trial.get("summary", {})]
        rms = np.asarray([x["rms_mean"] for x in rows if x.get("rms_mean") is not None], dtype=float)
        raw = np.asarray([x["raw_mean"] for x in rows if x.get("raw_mean") is not None], dtype=float)
        mean = float(rms.mean()) if len(rms) else None
        sd = float(rms.std(ddof=1)) if len(rms)>1 else 0.0 if len(rms)==1 else None
        cv = sd / abs(mean) if mean is not None and sd is not None and abs(mean) > 1e-12 else None
        reason = None if cv is not None else "MEAN_NEAR_ZERO_OR_INSUFFICIENT_DATA"
        channel_warnings=[]
        if cv is not None and cv > .2: channel_warnings.append("HIGH_DESCRIPTIVE_BASELINE_VARIABILITY")
        warnings.extend(f"{channel}:{x}" for x in channel_warnings)
        reports[channel]={"number_of_trials":len(rows),"mean_baseline_rms":mean,"rms_between_trial_sd":sd,"coefficient_of_variation":cv,"coefficient_of_variation_reason":reason,"raw_offset_variability":float(raw.std(ddof=1)) if len(raw)>1 else 0.0 if len(raw)==1 else None,"warnings":channel_warnings}
    return {"schema_version":"1.0","number_of_trials":len(trials),"baseline_ids":[x.get("baseline_id") for x in trials],"channels":reports,"warnings":warnings,"interpretation":"DESCRIPTIVE_ENGINEERING_METRICS_ONLY"}


def channel_check(samples: list[dict[str, Any]], profile: dict[str, Any]) -> dict[str, Any]:
    adc = adc_validation(samples, profile)
    result={}
    for channel, report in adc["channels"].items():
        if report["sample_count"] == 0: state="UNKNOWN"
        elif report["clipping_ratio"] and report["clipping_ratio"] > .01: state="CLIPPING"
        elif report["unique_value_count"] <= 2 or (report["standard_deviation"] or 0) < 1e-9: state="POSSIBLE FLATLINE"
        else: state="SIGNAL PRESENT"
        result[channel]={"technical_state":state,"anatomy_verified":False,"warnings":report["warnings"]}
    return {"schema_version":"1.0","channels":result,"limitation":"Waveform checks cannot verify electrode anatomy or placement."}


def powerline_validation(samples: list[dict[str, Any]], sample_rate_hz: float, frequency_hz: float) -> dict[str, Any]:
    channels=sorted({key for row in samples for key in row.get("channels", {})});reports={}
    b,a=signal.iirnotch(frequency_hz,30,sample_rate_hz)
    for channel in channels:
        raw=np.asarray([row["channels"][channel] for row in samples],dtype=float);centered=raw-raw.mean()
        processed=signal.lfilter(b,a,centered)
        def energy(values):
            frequencies=np.fft.rfftfreq(len(values),1/sample_rate_hz);spectrum=np.abs(np.fft.rfft(values))**2
            mask=np.abs(frequencies-frequency_hz)<=1
            return float(spectrum[mask].sum()) if len(values) else 0.0
        before,after=energy(centered),energy(processed)
        reports[channel]={"line_frequency_hz":frequency_hz,"raw_line_frequency_energy":before,"processed_line_frequency_energy":after,"relative_attenuation":1-after/before if before>0 else None,"raw_unchanged":True}
    return {"schema_version":"1.0","channels":reports,"conclusion_scope":"POWERLINE_BEHAVIOR_ONLY"}


def filter_response(config: dict[str, Any]) -> dict[str, Any]:
    fs=float(config["processing_sample_rate_hz"]);nyquist=fs/2;warnings=[];sos=[]
    if config.get("bandpass_enabled"):
        high=float(config["bandpass_high_hz"])
        if high>=nyquist: warnings.append("HIGH_CUTOFF_AT_OR_ABOVE_NYQUIST")
        elif high>nyquist*.9: warnings.append("HIGH_CUTOFF_CLOSE_TO_NYQUIST")
        if high<nyquist:sos.append(signal.butter(int(config["bandpass_order"]),[float(config["bandpass_low_hz"]),high],btype="bandpass",fs=fs,output="sos"))
    if config.get("notch_enabled") and float(config["notch_frequency_hz"])<nyquist:
        b,a=signal.iirnotch(float(config["notch_frequency_hz"]),float(config["notch_q"]),fs);sos.append(signal.tf2sos(b,a))
    combined=np.vstack(sos) if sos else np.asarray([[1,0,0,1,0,0]],dtype=float)
    freq,response=signal.sosfreqz(combined,worN=512,fs=fs)
    return {"schema_version":"1.0","sample_rate_hz":fs,"nyquist_hz":nyquist,"configuration":config,"frequencies_hz":freq.tolist(),"gain_db":(20*np.log10(np.maximum(np.abs(response),1e-12))).tolist(),"sos_coefficients":combined.tolist(),"scipy_version":scipy.__version__,"warnings":warnings,"group_delay_limitation":"IIR delay varies with frequency; no single physiological delay is claimed."}


def host_pipeline_latency(samples: list[dict[str, Any]]) -> dict[str, Any]:
    values=[(x["processing_completed_ns"]-x["host_timestamp_ns"])/1e6 for x in samples if x.get("processing_completed_ns") and x.get("host_timestamp_ns")]
    array=np.asarray(values,dtype=float)
    return {"schema_version":"1.0","metric":"HOST_PIPELINE_LATENCY","sample_count":len(values),**_percentiles(array),"limitation":"Begins at Python host ingestion; excludes ADC, device, and USB buffering before receipt."}


def quick_check(samples: list[dict[str, Any]], configured_rate_hz: float, channel_count: int, profile: dict[str, Any]) -> dict[str, Any]:
    if not samples:return {"status":"FAILED TECHNICALLY","blocking":True,"warnings":["NO_SAMPLES"]}
    channels=channel_check(samples,profile);warnings=[]
    if any(x["technical_state"]=="POSSIBLE FLATLINE" for x in channels["channels"].values()):warnings.append("POSSIBLE_FLATLINE")
    if len(channels["channels"])!=channel_count:return {"status":"FAILED TECHNICALLY","blocking":True,"warnings":["INVALID_CHANNEL_COUNT"],"channels":channels}
    timing=timing_validation(samples,configured_rate_hz)
    warnings.extend(timing["warnings"])
    return {"status":"COMPLETE WITH WARNINGS" if warnings else "COMPLETE","blocking":False,"warnings":warnings,"channels":channels,"timing":timing,"scope":"RESEARCH_ENGINEERING_QUICK_CHECK"}
