import json

import numpy as np
import pytest
import torch

from backend.emg_research import (SpatialConfig, MeasurementError, StudyARequest, FUNCTIONS_V2, field, reference, measure, run_scenario, run_study_a, scenario_seed)
from backend.emg_spatial_learning import SpatialWeightLayer, StudyBRequest, dataset, run_study_b, load_spatial_model
from backend.emg.research_protocol import TestDeviceConfig as DeviceConfig, ChannelIdentity, generate_packets, parse_packet, test_stream as run_test_stream
from backend.emg_math import gauss_legendre_rule


def test_domain_mapping_and_polynomial_exactness():
    config=SpatialConfig(function="POLYNOMIAL",domain=(10,30),frames=24)
    result=run_scenario(config,12)
    assert result["reference"]["method"]=="ANALYTIC_SPATIAL_AVERAGE"
    assert result["A1_same_measurements"]["GAUSSIAN_QUADRATURE"]["rmse"]<1e-12
    nodes=result["A2_same_budget"]["GAUSS_LEGENDRE"]["physical_positions"]
    assert np.allclose(nodes,20+10*np.array(gauss_legendre_rule(3).nodes))


@pytest.mark.parametrize("family",FUNCTIONS_V2)
def test_all_families_have_converged_references(family):
    config=SpatialConfig(function=family,frames=24)
    values,report=reference(config,np.linspace(0,1,24),.7)
    assert report["valid"],report
    assert np.isfinite(values).all()


def test_moving_peak_changes_shape_and_position_error_is_recorded():
    config=SpatialConfig(function="MOVING_PEAK",error=MeasurementError(position_std=.1))
    x=np.linspace(-1,1,100)
    a=field(config,x,.1);b=field(config,x,.5)
    assert np.argmax(a)!=np.argmax(b)
    result=run_scenario(config,43)
    assert not np.allclose(result["measurement"]["actual_normalized_positions"],result["nominal_nodes"])
    assert result["A1_same_measurements"]["ARITHMETIC_MEAN"]["available"]


@pytest.mark.parametrize("parameter",["independent_noise","correlated_noise","common_mode","gain_std","offset_std","drift","position_std","sample_dropout","channel_dropout","saturation","quantization_bits","timing_jitter","synchronization_error","crosstalk"])
def test_measurement_models_are_separable_and_reproducible(parameter):
    value=8 if parameter=="quantization_bits" else .05
    config=SpatialConfig(error=MeasurementError(**{parameter:value}))
    args=(config,gauss_legendre_rule(3).nodes,np.linspace(0,1,64),91,.3)
    a,meta=measure(*args);b,meta2=measure(*args)
    assert np.allclose(a,b,equal_nan=True)
    assert meta==meta2
    assert "no implicit rectification" in meta["negative_noise_policy"]


def test_sweep_optimization_holdout_and_reproducibility():
    request=StudyARequest(simulation=SpatialConfig(frames=24),functions=["POLYNOMIAL","MOVING_PEAK","NARROW_PEAK"],sweep_values=[.1,.3],trials=2,optimization_candidates=4,held_out_families=["NARROW_PEAK"])
    first=run_study_a(request);second=run_study_a(request)
    assert len(first["scenarios"])==12
    assert [s["scenario_id"] for s in first["scenarios"]]==[s["scenario_id"] for s in second["scenarios"]]
    assert np.allclose([s["paired_rmse_gq_minus_mean"] for s in first["scenarios"]],[s["paired_rmse_gq_minus_mean"] for s in second["scenarios"]])
    optimization=first["optimization"]["3"]
    assert all(s["partition"] in {"TRAIN","VALIDATION"} for s in optimization["scenario_manifest"])
    assert {s["seed"] for s in optimization["scenario_manifest"]}.isdisjoint({s["seed"] for s in first["scenarios"]})
    assert scenario_seed(42,"TRAIN",1)!=scenario_seed(42,"TEST",1)


def test_sweep_cancel_and_invalid_geometry():
    with pytest.raises(InterruptedError):run_study_a(StudyARequest(),cancel=lambda:True)
    with pytest.raises(ValueError):run_scenario(SpatialConfig(positions=[-1,0,1]),42)


def test_spatial_layer_initialization_constraints_and_real_update():
    equal=SpatialWeightLayer(3,"LEARNED_EQUAL");gq=SpatialWeightLayer(3,"LEARNED_GQ")
    assert np.allclose(equal.weights().detach(),[1/3]*3)
    assert np.allclose(gq.weights().detach(),[5/18,4/9,5/18])
    x=torch.tensor([[[.1,.1],[.8,.8],[.2,.2]]]);target=torch.tensor([[.9,.9]])
    optimizer=torch.optim.Adam(gq.parameters(),lr=.1);before=gq.weights().detach().clone()
    for _ in range(5):optimizer.zero_grad();loss=((gq(x).squeeze(1)-target)**2).mean()+.1*gq.penalty();loss.backward();optimizer.step()
    assert not torch.equal(before,gq.weights())
    assert torch.all(gq.weights()>=0)
    assert gq.weights().sum().item()==pytest.approx(1)
    assert gq.penalty().item()>0


def test_scenario_groups_and_learning_objectives_are_separate(tmp_path):
    request=StudyBRequest(subjects=9,epochs=3,seeds=[11],frames=24,lambdas=[0,.1])
    rows=dataset(request,11)
    groups={s:{r["subject"] for r in rows if r["split"]==s} for s in ("TRAIN","VALIDATION","TEST")}
    assert groups["TRAIN"].isdisjoint(groups["TEST"])
    assert groups["VALIDATION"].isdisjoint(groups["TEST"])
    assert all(r["family"]=="NARROW_PEAK" for r in rows if r["split"]=="TEST")
    result=run_study_b(request,tmp_path)
    assert len(result["results"])==5
    assert all("rmse" in r["test"] and "macro_f1" not in r["test"] for r in result["results"])
    assert all(not r["test_consulted"] for r in result["regularization_validation"])
    assert all(load_spatial_model(p) for p in tmp_path.glob("*.pt"))


@pytest.mark.parametrize("architecture",["MLP","CNN_1D","TCN","GRU"])
def test_actual_compatible_classification_training(architecture,tmp_path):
    request=StudyBRequest(task="RESEARCH_LABEL_CLASSIFICATION",models=[architecture],subjects=9,epochs=3,seeds=[37],frames=24,lambdas=[.1])
    result=run_study_b(request,tmp_path)
    assert len(result["results"])==5
    assert all("macro_f1" in r["test"] and "rmse" not in r["test"] for r in result["results"])
    assert all(r["parameter_count"]>0 for r in result["results"])
    assert all(p["available"] is False for p in [r["uncertainty"] for r in result["paired_comparisons"]])


@pytest.mark.parametrize("channels",[1,2,3,4])
def test_device_packet_recording_and_retrieval(channels,tmp_path):
    config=DeviceConfig(channels=[ChannelIdentity(channel_id=f"channel_{i+1}") for i in range(channels)])
    line=generate_packets(config)[0]
    assert len(parse_packet(line,config)["values"])==channels
    report=run_test_stream(config,tmp_path)
    assert report["source_type"]=="TEST_DEVICE"
    assert len(report["waveform"])==channels
    assert report["recording_integrity"]["metadata_matches"]
    assert report["recording_integrity"]["samples_retrieved"]==200
    assert report["clock_rate_hz"]==pytest.approx(1000)
    assert report["interchannel_skew_us"] is None


@pytest.mark.parametrize("fault,key",[("DROPPED","sequence_gaps"),("OUT_OF_ORDER","out_of_order_packets"),("DUPLICATE","duplicate_packets"),("CHANNEL_MISMATCH","invalid_packets"),("INVALID_NUMERIC","invalid_packets"),("DISCONNECT","disconnect_events"),("SATURATION","clipped_values")])
def test_device_faults_are_detected(fault,key):
    report=run_test_stream(DeviceConfig(channels=[ChannelIdentity(channel_id="channel_1")],fault=fault))
    assert report[key]>0


def test_device_clock_diagnostics_do_not_claim_physical_synchronization():
    config=DeviceConfig(channels=[ChannelIdentity(channel_id="channel_1")],fault="TIMESTAMP_DRIFT")
    assert run_test_stream(config)["clock_rate_hz"]<990
    jitter=run_test_stream(config.model_copy(update={"fault":"TIMING_JITTER"}))
    assert jitter["timing_residual_jitter_us"]>0


def test_expanded_input_ablations_and_learning_sizes_are_disclosed(tmp_path):
    request=StudyBRequest(task="RESEARCH_LABEL_CLASSIFICATION",models=["CNN_1D","RANDOM_FOREST"],variants=["FIXED_EQUAL","FIXED_GQ","GQ_PLUS_FEATURES","RAW_MULTICHANNEL"],subjects=12,training_sizes=[3,5],epochs=3,seeds=[31],frames=24)
    result=run_study_b(request,tmp_path)
    assert {r["training_subjects"] for r in result["results"]}=={3,5}
    assert all(r["information_budget"]=="EXPANDED" for r in result["results"] if r["variant"] in {"RAW_MULTICHANNEL","GQ_PLUS_FEATURES"})
    assert all(r["variant"] in {"FIXED_EQUAL","FIXED_GQ","RAW_MULTICHANNEL"} for r in result["results"] if r["model"]=="RANDOM_FOREST")
    for p in result["paired_comparisons"]:assert p["uncertainty"]["independent_units"]==1


def test_reference_rejects_disagreeing_quadrature(monkeypatch):
    from backend import emg_research
    monkeypatch.setattr(emg_research,"quad",lambda *args,**kwargs:(0,0))
    _,report=reference(SpatialConfig(function="GAUSSIAN",frames=16),np.linspace(0,1,16),0)
    assert report["valid"] is False
    assert report["cross_method_disagreement"]>0.01


def test_robustness_conditions_preserve_matched_comparisons(tmp_path):
    request=StudyBRequest(subjects=9,epochs=2,seeds=[19],frames=24,variants=["FIXED_EQUAL","LEARNED_GQ"],sensor_counts=[2,3],noise_levels=[0,.1])
    result=run_study_b(request,tmp_path)
    assert len(result["robustness_conditions"])==4
    assert len(result["results"])==8
    assert len({r["id"] for r in result["results"]})==8
    for row in result["results"]:
        assert len(row["weights"])==row["sensors"]
        assert (tmp_path/(row["id"]+".pt")).is_file()
