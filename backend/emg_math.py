from __future__ import annotations

import io
import json
import math
import time
import zipfile
from dataclasses import dataclass
from typing import Any, Literal

import numpy as np
from numpy.polynomial.legendre import leggauss


Method = Literal["ARITHMETIC_MEAN", "GAUSSIAN_QUADRATURE", "UNIFORM_BASELINE"]
FUNCTIONS = ("CONSTANT", "LINEAR", "POLYNOMIAL", "CENTRAL_PEAK", "OFF_CENTER_PEAK", "MULTIPLE_PEAKS", "NARROW_PEAK", "NOISY")


@dataclass(frozen=True)
class QuadratureRule:
    order: int
    nodes: tuple[float, ...]
    average_weights: tuple[float, ...]


def gauss_legendre_rule(order: int) -> QuadratureRule:
    if order not in {2, 3, 4, 5}:
        raise ValueError("Gauss-Legendre order must be 2, 3, 4, or 5")
    nodes, integral_weights = leggauss(order)
    return QuadratureRule(order, tuple(float(x) for x in nodes), tuple(float(w / 2.0) for w in integral_weights))


def geometry_report(positions: list[float], order: int, tolerance: float = 0.03) -> dict[str, Any]:
    rule = gauss_legendre_rule(order)
    valid = len(positions) == order and all(math.isfinite(x) and -1 <= x <= 1 for x in positions)
    deviations = [abs(a - b) for a, b in zip(sorted(positions), rule.nodes)] if valid else []
    matched = valid and max(deviations, default=math.inf) <= tolerance
    reason = None if matched else "Physical channel positions do not match the selected Gauss-Legendre nodes; direct GQ is blocked."
    return {"valid": valid, "matches_gaussian_nodes": matched, "positions": positions, "required_nodes": list(rule.nodes), "max_node_error": max(deviations) if deviations else None, "warning": reason, "reason": reason}


def spatial_average(values: np.ndarray, method: Method, *, positions: list[float] | None = None) -> np.ndarray:
    array = np.asarray(values, dtype=float)
    if array.ndim == 1:
        array = array[:, None]
    channels = array.shape[0]
    if method == "ARITHMETIC_MEAN":
        return np.mean(array, axis=0)
    if method == "GAUSSIAN_QUADRATURE":
        if positions is not None and not geometry_report(positions, channels)["matches_gaussian_nodes"]:
            raise ValueError("Geometry mismatch: Gaussian quadrature requires measurements at the selected nodes")
        weights = np.asarray(gauss_legendre_rule(channels).average_weights)
        return weights @ array
    if method == "UNIFORM_BASELINE":
        if positions is None or len(positions) != channels:
            raise ValueError("Uniform baseline requires channel positions")
        order = np.argsort(positions)
        return np.trapezoid(array[order], np.asarray(positions)[order], axis=0) / (max(positions) - min(positions))
    raise ValueError(f"Unsupported spatial method: {method}")


def spatial_function(name: str, x: np.ndarray) -> np.ndarray:
    if name == "CONSTANT": return np.ones_like(x) * 0.65
    if name == "LINEAR": return 0.55 + 0.25 * x
    if name == "POLYNOMIAL": return 0.3 + 0.15 * x + 0.35 * x**2 + 0.1 * x**4
    if name == "CENTRAL_PEAK": return 0.15 + np.exp(-(x / 0.38) ** 2)
    if name == "OFF_CENTER_PEAK": return 0.12 + 0.9 * np.exp(-((x - 0.38) / 0.28) ** 2)
    if name == "MULTIPLE_PEAKS": return 0.1 + 0.65 * np.exp(-((x + 0.45) / 0.22) ** 2) + 0.8 * np.exp(-((x - 0.4) / 0.25) ** 2)
    if name == "NARROW_PEAK": return 0.08 + np.exp(-((x - 0.12) / 0.09) ** 2)
    if name == "NOISY": return 0.25 + 0.45 * np.exp(-(x / 0.4) ** 2)
    raise ValueError(f"Unknown simulation function: {name}")


def estimation_metrics(estimate: np.ndarray, reference: np.ndarray | None) -> dict[str, Any]:
    if reference is None:
        return {"available": False, "reference_available": False, "message": "NO REFERENCE TRUTH: ESTIMATION ACCURACY CANNOT BE DETERMINED", "mae": None, "rmse": None, "bias": None, "absolute_bias": None, "relative_error_percent": None, "correlation": None}
    estimate, reference = np.asarray(estimate), np.asarray(reference)
    error = estimate - reference
    denominator = float(np.mean(np.abs(reference)))
    correlation = float(np.corrcoef(estimate, reference)[0, 1]) if len(estimate) > 1 and np.std(estimate) and np.std(reference) else None
    return {"available": True, "reference_available": True, "message": None, "mae": float(np.mean(np.abs(error))), "rmse": float(np.sqrt(np.mean(error**2))), "bias": float(np.mean(error)), "absolute_bias": float(abs(np.mean(error))), "relative_error_percent": float(np.mean(np.abs(error)) / denominator * 100) if denominator > 1e-12 else None, "correlation": correlation}


def simulate(function_name: str = "CENTRAL_PEAK", order: int = 3, noise_std: float = 0.0, position_error: float = 0.0, seed: int = 42, frames: int = 120) -> dict[str, Any]:
    if function_name not in FUNCTIONS: raise ValueError("Unsupported simulation function")
    rng = np.random.default_rng(seed); rule = gauss_legendre_rule(order); t = np.linspace(0, 2 * np.pi, frames); dense_x = np.linspace(-1, 1, 10001)
    nodes = np.asarray(rule.nodes) + rng.normal(0, position_error, order); nodes = np.clip(nodes, -1, 1)
    modulation = 0.75 + 0.25 * np.sin(t)
    dense = spatial_function(function_name, dense_x)[:, None] * modulation[None, :]
    sampled = spatial_function(function_name, nodes)[:, None] * modulation[None, :] + rng.normal(0, noise_std, (order, frames))
    sampled = np.maximum(sampled, 0); reference = np.trapezoid(dense, dense_x, axis=0) / 2
    started = time.perf_counter(); mean = spatial_average(sampled, "ARITHMETIC_MEAN"); mean_time = time.perf_counter() - started
    started = time.perf_counter(); gq = np.asarray(rule.average_weights) @ sampled; gq_time = time.perf_counter() - started
    mean_metrics, gq_metrics = estimation_metrics(mean, reference), estimation_metrics(gq, reference)
    improvement = None if not mean_metrics["rmse"] else 100 * (mean_metrics["rmse"] - gq_metrics["rmse"]) / mean_metrics["rmse"]
    winner = "TIE" if abs(mean_metrics["rmse"] - gq_metrics["rmse"]) < 1e-12 else ("GAUSSIAN_QUADRATURE" if gq_metrics["rmse"] < mean_metrics["rmse"] else "ARITHMETIC_MEAN")
    return {"source_type":"SYNTHETIC_SIMULATION","evaluation_scope":"DEVELOPMENT_ONLY","function":function_name,"seed":seed,"order":order,"nodes":nodes.tolist(),"ideal_nodes":list(rule.nodes),"weights":list(rule.average_weights),"time":t.tolist(),"channel_curves":sampled.tolist(),"mean_curve":mean.tolist(),"gq_curve":gq.tolist(),"reference_curve":reference.tolist(),"reference":{"available":True,"dense_points":len(dense_x),"method":"dense trapezoidal average"},"mean_metrics":{**mean_metrics,"computation_seconds":mean_time},"gq_metrics":{**gq_metrics,"computation_seconds":gq_time},"methods":{"ARITHMETIC_MEAN":{**mean_metrics,"computation_seconds":mean_time},"GAUSSIAN_QUADRATURE":{**gq_metrics,"computation_seconds":gq_time}},"comparison":{"winner":winner,"gq_rmse_improvement_percent":improvement},"gq_rmse_improvement_percent":improvement,"limitations":["Synthetic mathematical validation only","Not measured human EMG","Sparse estimates use a dense numerical reference"]}


def slider_demo(amplitudes: list[float]) -> dict[str, Any]:
    if len(amplitudes) != 3 or any(x < 0 or not math.isfinite(x) for x in amplitudes): raise ValueError("Three finite nonnegative amplitudes are required")
    weights = gauss_legendre_rule(3).average_weights; mean = sum(amplitudes) / 3; gq = sum(w*x for w,x in zip(weights, amplitudes))
    contributions = [{"channel": index + 1, "amplitude": x, "weight": w, "contribution": w * x} for index, (w, x) in enumerate(zip(weights, amplitudes))]
    return {"source_type":"SYNTHETIC_MATHEMATICAL_DEMONSTRATION","amplitudes":amplitudes,"arithmetic_mean":mean,"gaussian_quadrature":{"estimate":gq,"contributions":contributions},"gaussian_quadrature_value":gq,"difference":gq-mean,"mean_contributions":[x/3 for x in amplitudes],"gq_contributions":[w*x for w,x in zip(weights,amplitudes)],"weights":list(weights)}


def report_zip(experiment: dict[str, Any]) -> bytes:
    buffer=io.BytesIO()
    with zipfile.ZipFile(buffer,"w",zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("research_report.json",json.dumps(experiment,indent=2))
        simulation=experiment.get("simulation") or experiment
        curves=zip(simulation.get("time",[]),simulation.get("mean_curve",[]),simulation.get("gq_curve",[]),simulation.get("reference_curve",[]))
        archive.writestr("signal_curves.csv","time,arithmetic_mean,gaussian_quadrature,reference\n"+"\n".join(",".join(map(str,row)) for row in curves))
        results=(experiment.get("results") or {}).get("results",[])
        if results:
            header="model,mathematical_method,validation_macro_f1,test_macro_f1,training_seconds,model_size_bytes\n"
            body="\n".join(f'{row["model"]},{row["mathematical_method"]},{row["validation"]["macro_f1"]},{row["test"]["macro_f1"]},{row["training_seconds"]},{row["model_size_bytes"]}' for row in results)
            archive.writestr("model_comparison.csv",header+body)
        archive.writestr("README.txt","FlexMap research export\nRanking metric: validation macro F1. Held-out test results were not used for model selection.\nSynthetic results are mathematical demonstrations, not clinical evidence.\nPrivate participant media is excluded.\n")
    return buffer.getvalue()
