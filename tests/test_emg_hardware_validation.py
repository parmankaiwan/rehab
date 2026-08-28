import math

import pytest

from backend.emg.hardware_profiles import HardwareProfileStore
from backend.emg.hardware_validation import (
    adc_validation, analyze_sequences, baseline_repeatability, channel_check,
    conversion_config, convert_physical, filter_response, powerline_validation,
    quick_check, timing_validation,
)


def samples(count=1000, rate=1000, channels=1):
    return [{"host_timestamp_ns":i*1_000_000,"device_timestamp":i,"device_sequence_id":i,"channels":{f"channel_{c+1}":2048+100*math.sin(2*math.pi*70*i/rate) for c in range(channels)}} for i in range(count)]


def profile(**updates):
    return {"raw_representation":"ADC_COUNTS_UNSIGNED","adc_bits":12,"adc_min_count":0,"adc_max_count":4095,"expected_sample_rate_hz":1000,"channel_count":1,**updates}


def test_sequence_gaps_duplicates_and_out_of_order():
    assert analyze_sequences([100,101,104])["estimated_missing_samples"] == 2
    assert analyze_sequences([100,101,101])["duplicate_sequence_count"] == 1
    assert analyze_sequences([100,102,101])["out_of_order_count"] == 1


def test_device_timing_keeps_clock_sources_separate():
    report=timing_validation(samples(),1000,"MILLISECONDS")
    assert report["sampling_clock_source"] == "DEVICE_TIMESTAMP"
    assert report["device_sample_rate_hz_estimated"] == pytest.approx(1000)
    assert report["host_receive_rate_hz"] == pytest.approx(1000)
    assert report["median_interval_ms"] == pytest.approx(1)


def test_unknown_timestamp_unit_does_not_calculate_drift():
    report=timing_validation(samples(),1000,"UNKNOWN")
    assert report["clock_drift_ppm"] is None
    assert "DEVICE_TIMESTAMP_UNIT_UNKNOWN" in report["warnings"]


def test_adc_unsigned_out_of_range_is_flagged_not_clamped():
    rows=[{"channels":{"channel_1":x}} for x in (0,2000,4095,5000)]
    report=adc_validation(rows,profile())
    assert report["channels"]["channel_1"]["maximum_observed"] == 5000
    assert report["channels"]["channel_1"]["out_of_range_count"] == 1
    assert report["raw_values_clamped"] is False


def test_signed_adc_accepts_negative_values():
    report=adc_validation([{"channels":{"channel_1":x}} for x in (-32768,0,32767)],profile(raw_representation="ADC_COUNTS_SIGNED",adc_bits=16,adc_min_count=-32768,adc_max_count=32767))
    assert report["channels"]["channel_1"]["out_of_range_count"] == 0


def test_conversion_requires_complete_provenance_and_is_exact():
    configured=profile(adc_reference_voltage_v=3.3,adc_zero_code=2047.5,analog_frontend_gain=1000)
    assert convert_physical(4095,configured) == pytest.approx(.00165)
    configured["adc_reference_voltage_v"]=None
    assert conversion_config(configured)["available"] is False
    assert convert_physical(4095,configured) is None


def test_baseline_repeatability_descriptive_variability():
    stable=[{"baseline_id":str(i),"summary":{"channel_1":{"rms_mean":10+x,"raw_mean":2048+x}}} for i,x in enumerate((0,.1,-.1))]
    variable=[{"baseline_id":str(i),"summary":{"channel_1":{"rms_mean":x,"raw_mean":2048+x}}} for i,x in enumerate((2,10,30))]
    assert baseline_repeatability(stable)["channels"]["channel_1"]["coefficient_of_variation"] < .02
    assert "HIGH_DESCRIPTIVE_BASELINE_VARIABILITY" in baseline_repeatability(variable)["channels"]["channel_1"]["warnings"]


def test_channel_check_detects_flatline_without_anatomy_claim():
    rows=[{"channels":{"channel_1":2048+i%7,"channel_2":2048}} for i in range(100)]
    report=channel_check(rows,profile(channel_count=2))
    assert report["channels"]["channel_1"]["technical_state"] == "SIGNAL PRESENT"
    assert report["channels"]["channel_2"]["technical_state"] == "POSSIBLE FLATLINE"
    assert report["channels"]["channel_2"]["anatomy_verified"] is False


def test_powerline_notch_attenuates_and_raw_is_unchanged():
    rows=[{"channels":{"channel_1":math.sin(2*math.pi*50*i/1000)}} for i in range(3000)]
    before=[x["channels"]["channel_1"] for x in rows]
    report=powerline_validation(rows,1000,50)["channels"]["channel_1"]
    assert report["relative_attenuation"] > .9
    assert before == [x["channels"]["channel_1"] for x in rows]


def test_filter_response_and_nyquist_warning():
    config={"processing_sample_rate_hz":1000,"bandpass_enabled":True,"bandpass_low_hz":20,"bandpass_high_hz":450,"bandpass_order":4,"notch_enabled":True,"notch_frequency_hz":50,"notch_q":30}
    assert len(filter_response(config)["frequencies_hz"]) == 512
    config["bandpass_high_hz"]=500
    assert "HIGH_CUTOFF_AT_OR_ABOVE_NYQUIST" in filter_response(config)["warnings"]


def test_quick_check_hard_failure_warning_and_complete():
    assert quick_check([],1000,1,profile())["blocking"] is True
    flat=[{"host_timestamp_ns":i*1_000_000,"channels":{"channel_1":1}} for i in range(100)]
    assert quick_check(flat,1000,1,profile())["status"] == "COMPLETE WITH WARNINGS"
    assert quick_check(samples(100),1000,1,profile())["blocking"] is False

def test_profile_versions_snapshots_and_validation_history(tmp_path):
    store=HardwareProfileStore(tmp_path)
    first=store.create({"display_name":"Board","expected_sample_rate_hz":1000})
    snapshot=store.snapshot(first["hardware_profile_id"])
    second=store.version(first["hardware_profile_id"],{"display_name":"Board","expected_sample_rate_hz":500})
    assert snapshot["profile_version"] == 1
    assert second["profile_version"] == 2
    saved=store.save_validation({"hardware_profile_id":first["hardware_profile_id"],"hardware_profile_version":1,"status":"COMPLETE"})
    assert saved["validation_run_id"].startswith("VAL-")
    history=store.validation_history(first["hardware_profile_id"])
    assert len(history) == 1
    assert history[0]["matches_current_profile"] is False