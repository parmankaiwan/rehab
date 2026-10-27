"""Synthetic spatial-amplitude research. No hardware or participant acquisition.

Signals are dimensionless processed envelopes, not signed surface voltages.
The target is the spatial average over the entire configured domain.
"""
from __future__ import annotations

import hashlib
import itertools
import json
import time
from typing import Callable, Literal

import numpy as np
from pydantic import BaseModel, Field, model_validator
from scipy.integrate import quad

from .emg_math import gauss_legendre_rule, estimation_metrics

STATIC = ["CONSTANT", "LINEAR", "QUADRATIC", "POLYNOMIAL", "GAUSSIAN", "NARROW_PEAK", "ASYMMETRIC", "MULTIPLE_PEAKS", "SMOOTH"]
DYNAMIC = ["MOVING_PEAK", "EXPANDING", "CONTRACTING", "MIGRATING", "TWO_REGIONS", "ASYMMETRIC_TEMPORAL", "BURSTS"]
FUNCTIONS_V2 = STATIC + DYNAMIC


class MeasurementError(BaseModel):
    independent_noise: float = Field(0, ge=0, le=2)
    correlated_noise: float = Field(0, ge=0, le=2)
    correlation_length: float = Field(.3, gt=0, le=4)
    common_mode: float = Field(0, ge=0, le=2)
    gain_std: float = Field(0, ge=0, le=.5)
    offset_std: float = Field(0, ge=0, le=1)
    drift: float = Field(0, ge=0, le=1)
    position_std: float = Field(0, ge=0, le=.5)
    sample_dropout: float = Field(0, ge=0, le=.5)
    channel_dropout: float = Field(0, ge=0, le=.5)
    saturation: float | None = Field(None, gt=0, le=10)
    quantization_bits: int | None = Field(None, ge=2, le=24)
    quantization_range: float = Field(4, gt=0, le=100)
    timing_jitter: float = Field(0, ge=0, le=.1)
    synchronization_error: float = Field(0, ge=0, le=.2)
    crosstalk: float = Field(0, ge=0, le=1)


class SpatialConfig(BaseModel):
    function: Literal["CONSTANT", "LINEAR", "QUADRATIC", "POLYNOMIAL", "GAUSSIAN", "NARROW_PEAK", "ASYMMETRIC", "MULTIPLE_PEAKS", "SMOOTH", "MOVING_PEAK", "EXPANDING", "CONTRACTING", "MIGRATING", "TWO_REGIONS", "ASYMMETRIC_TEMPORAL", "BURSTS"] = "MOVING_PEAK"
    domain: tuple[float, float] = (-1, 1)
    sensors: int = Field(3, ge=2, le=5)
    positions: list[float] | None = None
    peak_location: float = Field(0, ge=-.8, le=.8)
    peak_width: float = Field(.25, ge=.02, le=1)
    amplitude: float = Field(1, gt=0, le=3)
    regions: int = Field(2, ge=1, le=4)
    movement: float = Field(.5, ge=0, le=.8)
    temporal_profile: Literal["CONSTANT", "SINUSOIDAL", "BURSTS"] = "SINUSOIDAL"
    duration: float = Field(2, gt=.1, le=30)
    frames: int = Field(64, ge=16, le=256)
    seed: int = Field(42, ge=0, le=2**31-1)
    reference_tolerance: float = Field(1e-7, ge=1e-10, le=1e-3)
    error: MeasurementError = Field(default_factory=MeasurementError)

    @model_validator(mode="after")
    def geometry(self):
        a, b = self.domain
        if not np.isfinite([a, b]).all() or b <= a or b-a > 1000:
            raise ValueError("Spatial domain must be finite, increasing, and bounded")
        if self.positions is not None:
            if len(self.positions) != self.sensors or not np.isfinite(self.positions).all():
                raise ValueError("Provide one finite physical coordinate per sensor")
            if any(x < a or x > b for x in self.positions) or len(set(self.positions)) != self.sensors:
                raise ValueError("Electrode coordinates must be distinct and inside the domain")
        return self


class StudyARequest(BaseModel):
    study: Literal["A"] = "A"
    simulation: SpatialConfig = Field(default_factory=SpatialConfig)
    functions: list[str] = Field(default_factory=lambda: ["CONSTANT", "POLYNOMIAL", "MOVING_PEAK", "NARROW_PEAK"], min_length=1, max_length=16)
    sweep_parameter: Literal["independent_noise", "correlation_length", "peak_width", "peak_location", "position_std", "sensors", "sample_dropout", "movement"] = "peak_width"
    sweep_values: list[float] = Field(default_factory=lambda: [.08, .25, .5], min_length=1, max_length=8)
    trials: int = Field(3, ge=2, le=20)
    optimize: bool = True
    optimization_candidates: int = Field(12, ge=2, le=64)
    optimization_objective: Literal["EXPECTED_RMSE", "WORST_RMSE"] = "EXPECTED_RMSE"
    held_out_families: list[str] = Field(default_factory=list, max_length=8)

    @model_validator(mode="after")
    def bounded(self):
        if any(f not in FUNCTIONS_V2 for f in self.functions + self.held_out_families):
            raise ValueError("Unknown spatial function")
        if len(set(self.functions)) != len(self.functions):
            raise ValueError("Function families must be unique")
        if len(self.functions)*len(self.sweep_values)*self.trials > 120:
            raise ValueError("Batch exceeds 120 independent test scenarios")
        for value in self.sweep_values:
            updated_config(self.simulation, self.sweep_parameter, value)
        return self


def updated_config(config, parameter, value):
    data = config.model_dump()
    if parameter in MeasurementError.model_fields:
        data["error"][parameter] = value
    else:
        data[parameter] = value
    if parameter == "sensors":
        if int(value) != value:
            raise ValueError("Sensor count must be an integer")
        data["sensors"] = int(value)
        data["positions"] = None
    return SpatialConfig.model_validate(data)


def field(config: SpatialConfig, x, t, phase=0.0):
    """x normalized to [-1,1], t normalized to [0,1]; dimensionless amplitude."""
    x, t = np.asarray(x), np.asarray(t)
    center, width = config.peak_location, config.peak_width
    f = config.function
    if f == "CONSTANT": return np.broadcast_arrays(x, t)[0]*0 + config.amplitude*.65
    if f == "LINEAR": return config.amplitude*(.55+.25*x+0*t)
    if f == "QUADRATIC": return config.amplitude*(.2+.5*x*x+0*t)
    if f == "POLYNOMIAL": return config.amplitude*(.3+.15*x+.35*x*x+.1*x**4+0*t)
    if f == "SMOOTH": return config.amplitude*(.5+.2*np.cos(2.3*x)+.1*np.exp(x)+0*t)
    if f in ("MOVING_PEAK", "MIGRATING", "ASYMMETRIC_TEMPORAL", "BURSTS"):
        center = center + config.movement*(np.sin(2*np.pi*t+phase) if f != "MIGRATING" else 2*t-1)
    if f == "EXPANDING": width = width*(.35+1.3*t)
    if f == "CONTRACTING": width = width*(1.65-1.3*t)
    if f == "NARROW_PEAK": width = width*.35
    peak = np.exp(-((x-center)/width)**2)
    if f == "ASYMMETRIC": peak = np.exp(-((x-center)/np.where(x<center,width*.5,width*1.5))**2)
    if f in ("MULTIPLE_PEAKS", "TWO_REGIONS"):
        peak = 0*x+0*t
        for i in range(config.regions):
            c = -.65 + 1.3*(i+.5)/config.regions
            moving = config.movement*.3*np.sin(2*np.pi*t+i+phase) if f == "TWO_REGIONS" else 0
            height = .6+.4*np.sin(2*np.pi*t*(i+1)+phase+i)**2 if f == "TWO_REGIONS" else 1
            peak = peak + height*np.exp(-((x-c-moving)/width)**2)/config.regions
    temporal = 1
    if config.temporal_profile == "SINUSOIDAL": temporal = .75+.25*np.sin(2*np.pi*t+phase)
    if config.temporal_profile == "BURSTS" or f == "BURSTS": temporal = .25+.75*np.sin(3*np.pi*t+phase)**6
    if f == "BURSTS": peak = np.exp(-((x-center)/(width*(.5+.8*np.sin(2*np.pi*t+phase)**2)))**2)
    if f == "ASYMMETRIC_TEMPORAL": temporal = .2+.8*t
    return config.amplitude*(.1+peak)*temporal


def reference(config, times, phase):
    """Adaptive quadrature plus an independent doubled-grid convergence check."""
    if config.function in {"CONSTANT", "LINEAR", "QUADRATIC", "POLYNOMIAL"}:
        exact = {"CONSTANT":.65,"LINEAR":.55,"QUADRATIC":.2+.5/3,"POLYNOMIAL":.3+.35/3+.1/5}[config.function]
        return np.full(len(times),exact*config.amplitude), {"method":"ANALYTIC_SPATIAL_AVERAGE","tolerance":0,"valid":True,"maximum_estimated_error":0}
    values=[];errors=[]
    for t in times:
        value, error = quad(lambda x:float(field(config,x,t,phase))/2,-1,1,epsabs=config.reference_tolerance*.1,epsrel=config.reference_tolerance*.1,limit=200)
        values.append(value);errors.append(error)
    # Narrow peaks need a sufficiently fine initial grid; refinement must agree.
    size=513;previous=None;delta=float("inf")
    while size <= 16385:
        x=np.linspace(-1,1,size)
        grid=np.trapezoid(field(config,x[:,None],times[None,:],phase),x,axis=0)/2
        if previous is not None:
            delta=float(np.max(np.abs(grid-previous)))
            if delta <= config.reference_tolerance and np.max(np.abs(grid-np.asarray(values))) <= config.reference_tolerance*2:break
        previous=grid;size=size*2-1
    disagreement=float(np.max(np.abs(grid-np.asarray(values))))
    valid=max(errors)<=config.reference_tolerance and delta<=config.reference_tolerance and disagreement<=config.reference_tolerance*2
    return np.asarray(values),{"method":"ADAPTIVE_QUAD_WITH_GRID_CONVERGENCE","tolerance":config.reference_tolerance,"grid_points":min(size,16385),"grid_delta":delta,"cross_method_disagreement":disagreement,"maximum_estimated_error":max(errors),"valid":bool(valid)}


def measure(config, nodes, times, seed, phase):
    rng=np.random.default_rng(seed);e=config.error;n=len(nodes)
    actual=np.clip(np.asarray(nodes)+rng.normal(0,e.position_std,n),-1,1)
    sample_times=times[None,:]+rng.normal(0,e.timing_jitter/config.duration,(n,len(times)))+rng.normal(0,e.synchronization_error/config.duration,(n,1))
    clean=field(config,actual[:,None],np.clip(sample_times,0,1),phase)
    distances=np.abs(actual[:,None]-actual[None,:]);mix=np.exp(-distances/.25);mix/=mix.sum(axis=1,keepdims=True)
    values=(1-e.crosstalk)*clean+e.crosstalk*(mix@clean)
    values*=1+rng.normal(0,e.gain_std,(n,1));values+=rng.normal(0,e.offset_std,(n,1))
    values+=rng.normal(0,e.independent_noise,values.shape)
    covariance=np.exp(-distances/e.correlation_length)+np.eye(n)*1e-9
    values+=e.correlated_noise*(np.linalg.cholesky(covariance)@rng.normal(size=values.shape))
    values+=e.common_mode*rng.normal(size=(1,len(times)))
    values+=e.drift*np.sin(2*np.pi*.25*times[None,:]+rng.uniform(0,2*np.pi,(n,1)))
    clipped=np.zeros_like(values,dtype=bool)
    if e.saturation is not None:
        clipped=np.abs(values)>e.saturation;values=np.clip(values,-e.saturation,e.saturation)
    if e.quantization_bits is not None:
        step=e.quantization_range/(2**e.quantization_bits-1);values=np.round(values/step)*step
    missing=rng.random(values.shape)<e.sample_dropout;missing|=(rng.random((n,1))<e.channel_dropout)
    values[missing]=np.nan
    # Explicit policy: interpolate time gaps within a channel; wholly missing
    # channels remain missing and invalidate that estimator for this trajectory.
    filled=values.copy()
    for i,row in enumerate(filled):
        good=np.isfinite(row)
        if good.any():filled[i]=np.interp(times,times[good],row[good])
    return filled,{"actual_normalized_positions":actual.tolist(),"missing_fraction":float(missing.mean()),"clipped_fraction":float(clipped.mean()),"missing_policy":"WITHIN_CHANNEL_TIME_INTERPOLATION; whole-channel loss invalidates trajectory","negative_noise_policy":"SIGNED_MEASUREMENT_ERROR_PRESERVED; no implicit rectification"}


def placement_weights(nodes):
    """Integral of linear interpolation with constant boundary extension / 2."""
    nodes=np.asarray(nodes)
    if np.any(np.diff(nodes)<=0):raise ValueError("Placement nodes must be strictly ordered")
    boundaries=np.r_[-1,(nodes[:-1]+nodes[1:])/2,1]
    return np.diff(boundaries)/2


def scenario_seed(root, partition, index):
    return int.from_bytes(hashlib.sha256(f"flexmap-v2:{root}:{partition}:{index}".encode()).digest()[:4],"big")


def scenario(config, seed, partition, index):
    rng=np.random.default_rng(seed)
    varied=config.model_copy(update={"amplitude":config.amplitude*rng.uniform(.8,1.2),"peak_location":float(np.clip(config.peak_location+rng.uniform(-.08,.08),-.8,.8))})
    phase=float(rng.uniform(0,2*np.pi));times=np.linspace(0,1,config.frames);target,ref=reference(varied,times,phase)
    identity=hashlib.sha256(json.dumps({"config":varied.model_dump(),"phase":phase,"seed":seed},sort_keys=True).encode()).hexdigest()
    return varied,times,target,ref,phase,{"scenario_id":identity,"trajectory_id":identity,"partition":partition,"seed":seed,"index":index}


def metrics(estimate,target,valid_reference=True):
    if not valid_reference or not np.isfinite(estimate).all():
        return {"available":False,"rmse":None,"mae":None,"bias":None,"maximum_absolute_error":None,"reason":"INVALID_REFERENCE" if not valid_reference else "WHOLE_CHANNEL_DROPOUT"}
    result=estimation_metrics(estimate,target);result["maximum_absolute_error"]=float(np.max(np.abs(estimate-target)));return result


def run_scenario(config, seed, partition="TEST", index=0, optimized=None):
    c,t,target,ref,phase,identity=scenario(config,seed,partition,index);rule=gauss_legendre_rule(c.sensors)
    normalized=(2*(np.asarray(c.positions)-c.domain[0])/(c.domain[1]-c.domain[0])-1) if c.positions else np.asarray(rule.nodes)
    if c.positions and not np.allclose(normalized,rule.nodes,atol=1e-9):
        raise ValueError("A1 fixed GQ requires its nominal electrode positions to match the ordered Gaussian nodes; use position_std for measurement mismatch")
    measured,diagnostics=measure(c,normalized,t,seed,phase)
    started=time.perf_counter();mean=measured.mean(axis=0);mean_seconds=time.perf_counter()-started
    started=time.perf_counter();gq=np.asarray(rule.average_weights)@measured;gq_seconds=time.perf_counter()-started
    a1={"ARITHMETIC_MEAN":metrics(mean,target,ref["valid"]),"GAUSSIAN_QUADRATURE":metrics(gq,target,ref["valid"])}
    a1["ARITHMETIC_MEAN"]["computation_seconds"]=mean_seconds;a1["GAUSSIAN_QUADRATURE"]["computation_seconds"]=gq_seconds
    placements={"GAUSS_LEGENDRE":(normalized,np.asarray(rule.average_weights)),"UNIFORM":(np.linspace(-1,1,c.sensors),placement_weights(np.linspace(-1,1,c.sensors))),"MIDPOINT":(np.linspace(-1+1/c.sensors,1-1/c.sensors,c.sensors),np.ones(c.sensors)/c.sensors)}
    if optimized is not None:placements["OPTIMIZED"]=(np.asarray(optimized),placement_weights(optimized))
    a2={}
    for name,(nodes,weights) in placements.items():
        samples,_=measure(c,nodes,t,seed,phase);start=time.perf_counter();prediction=weights@samples;elapsed=time.perf_counter()-start
        a2[name]={"normalized_positions":nodes.tolist(),"physical_positions":(c.domain[0]+(nodes+1)*(c.domain[1]-c.domain[0])/2).tolist(),"weights":weights.tolist(),"estimator":"GAUSS_LEGENDRE" if name=="GAUSS_LEGENDRE" else "PIECEWISE_LINEAR_CONSTANT_BOUNDARIES" if name in {"UNIFORM","OPTIMIZED"} else "COMPOSITE_MIDPOINT","metrics":metrics(prediction,target,ref["valid"]),"computation_seconds":elapsed}
    x=np.linspace(-1,1,25)
    return {**identity,"configuration":c.model_dump(),"source_type":"SYNTHETIC MATHEMATICAL DATA","units":"dimensionless processed envelope spatial average","reference":ref,"time_seconds":(t*c.duration).tolist(),"reference_curve":target.tolist(),"mean_curve":np.nan_to_num(mean,nan=0).tolist() if np.isfinite(mean).all() else None,"gq_curve":gq.tolist() if np.isfinite(gq).all() else None,"error_curve":(gq-target).tolist() if np.isfinite(gq).all() else None,"field":{"normalized_x":x.tolist(),"amplitude":field(c,x[:,None],t[None,:],phase).tolist()},"weights":list(rule.average_weights),"nominal_nodes":list(rule.nodes),"measurement":diagnostics,"A1_same_measurements":a1,"A2_same_budget":a2,"paired_rmse_gq_minus_mean":a1["GAUSSIAN_QUADRATURE"]["rmse"]-a1["ARITHMETIC_MEAN"]["rmse"] if all(v["available"] for v in a1.values()) else None}


def check_cancel(cancel):
    if cancel and cancel():raise InterruptedError("Research experiment cancelled")


def optimize_placement(config, request, cancel):
    """Random-search fit on TRAIN; choose finalist on VALIDATION, never TEST."""
    rng=np.random.default_rng(config.seed);n=config.sensors
    candidates=[list(gauss_legendre_rule(n).nodes),np.linspace(-1,1,n).tolist()]
    candidates += [np.sort(rng.uniform(-.98,.98,n)).tolist() for _ in range(request.optimization_candidates-2)]
    families=[f for f in request.functions if f not in request.held_out_families]
    if not families:raise ValueError("Placement optimization needs at least one training function family")
    scenarios={p:[scenario(config.model_copy(update={"function":f}),scenario_seed(config.seed,p,i),p,i) for i,f in enumerate(families)] for p in ("TRAIN","VALIDATION")}
    def score(nodes,partition):
        errors=[]
        for c,t,target,ref,phase,_ in scenarios[partition]:
            samples,_=measure(c,nodes,t,scenario_seed(config.seed,partition,len(errors)),phase)
            m=metrics(placement_weights(nodes)@samples,target,ref["valid"])
            errors.append(m["rmse"] if m["available"] else 1e6)
        return float(max(errors) if request.optimization_objective=="WORST_RMSE" else np.mean(errors))
    scored=[]
    for nodes in candidates:
        check_cancel(cancel);scored.append({"nodes":nodes,"training_rmse":score(nodes,"TRAIN")})
    finalists=sorted(scored,key=lambda x:x["training_rmse"])[:min(3,len(scored))]
    for candidate in finalists:candidate["validation_rmse"]=score(candidate["nodes"],"VALIDATION")
    selected=min(finalists,key=lambda x:x["validation_rmse"])
    return {"objective":request.optimization_objective,"selected":selected,"candidate_count":len(candidates),"finalists":finalists,"scenario_manifest":[{**s[-1],"configuration":s[0].model_dump(),"phase":s[4],"reference":s[3]} for values in scenarios.values() for s in values],"selection":"TRAIN search, VALIDATION finalist selection; TEST never consulted","interpretation":"Proposed mathematical coordinates only; no anatomical or clinical optimality claim"}


def paired_interval(values,seed):
    values=np.asarray([v for v in values if v is not None],dtype=float)
    if len(values)<5:return {"available":False,"independent_units":len(values),"reason":"INSUFFICIENT_INDEPENDENT_TRAJECTORIES"}
    rng=np.random.default_rng(seed);means=np.mean(rng.choice(values,(1000,len(values)),replace=True),axis=1)
    return {"available":True,"independent_units":len(values),"unit":"INDEPENDENT_TRAJECTORY","lower":float(np.percentile(means,2.5)),"upper":float(np.percentile(means,97.5)),"iterations":1000}


def run_study_a(request, cancel=None, progress=None):
    start=time.perf_counter();optimizations={};rows=[];total=len(request.functions)*len(request.sweep_values)*request.trials
    for value in request.sweep_values:
        config=updated_config(request.simulation,request.sweep_parameter,value)
        key=str(config.sensors)
        if request.optimize and key not in optimizations:optimizations[key]=optimize_placement(config,request,cancel)
        nodes=optimizations[key]["selected"]["nodes"] if request.optimize else None
        for function,trial in itertools.product(request.functions,range(request.trials)):
            check_cancel(cancel);index=len(rows);seed=scenario_seed(config.seed,"TEST",index)
            result=run_scenario(config.model_copy(update={"function":function}),seed,"TEST",index,nodes)
            result.update({"sweep_parameter":request.sweep_parameter,"sweep_value":value,"trial":trial});rows.append(result)
            if progress:progress((index+1)/total)
    groups=[]
    for value in request.sweep_values:
        subset=[r for r in rows if r["sweep_value"]==value]
        valid=[r for r in subset if r["paired_rmse_gq_minus_mean"] is not None]
        groups.append({"value":value,"independent_trajectories":len(subset),"valid_trajectories":len(valid),"mean_rmse":float(np.mean([r["A1_same_measurements"]["ARITHMETIC_MEAN"]["rmse"] for r in valid])) if valid else None,"gq_rmse":float(np.mean([r["A1_same_measurements"]["GAUSSIAN_QUADRATURE"]["rmse"] for r in valid])) if valid else None,"paired_interval":paired_interval([r["paired_rmse_gq_minus_mean"] for r in subset],request.simulation.seed)})
    return {"study":"A","source_type":"SYNTHETIC MATHEMATICAL DATA","dataset_version":"SPATIAL-ENVELOPE-V2","feature_pipeline":"SPATIAL_AVERAGE-V2","evaluation_scope":"DEVELOPMENT_ONLY","configuration":request.model_dump(),"optimization":optimizations,"sweep_summary":groups,"scenarios":rows,"runtime_seconds":time.perf_counter()-start,"limitations":["Envelope approximation; not complete surface-EMG physics","A1 isolates weighting; A2 also changes placement and estimator","Independent units are trajectories, not time windows","Missing channels invalidate rather than silently renormalize GQ","No physiological or clinical interpretation"]}
