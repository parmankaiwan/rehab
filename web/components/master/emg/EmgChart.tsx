"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import type { EmgChannel, EmgChannelDisplayStats, EmgGraphSettings, EmgSample, SignalRepresentation } from "@/types/emg";

const colors = ["#79d5c2", "#82b7e8", "#e8ad72", "#c69add"];
export const DEFAULT_EMG_GRAPH_SETTINGS: EmgGraphSettings = {
  signalType: "raw", compareSignalType: "off", timeWindowSec: 10,
  yScaleMode: "auto", manualYMin: 0, manualYMax: 4095,
  autoPaddingPercent: 10, showGrid: true, showStats: true,
  showChannelLabels: true, showUnits: true, centerSignal: false,
  traceThickness: "normal", traceStyle: "line", visibleChannels: [],
  focusedChannel: null, statsSource: "visible", theme: "dark",
};

export function sampleValue(sample: EmgSample, channelId: string, signal: SignalRepresentation) {
  const value = signal === "raw" ? sample.channels[channelId] : sample.processed?.[channelId]?.[signal];
  return Number.isFinite(value) ? value as number : undefined;
}

export function calculateEmgStats(samples: EmgSample[], channelId: string, signalType: SignalRepresentation): EmgChannelDisplayStats | null {
  const values = samples.map(sample => ({ value: sampleValue(sample, channelId, signalType), timestamp: sample.host_timestamp_ns })).filter((item): item is { value: number; timestamp: number } => item.value !== undefined);
  if (!values.length) return null;
  let minimum = values[0].value, maximum = values[0].value, sum = 0;
  for (const item of values) { minimum = Math.min(minimum, item.value); maximum = Math.max(maximum, item.value); sum += item.value; }
  return { channelId, signalType, current: values.at(-1)!.value, minimum, maximum, peakToPeak: maximum - minimum, mean: sum / values.length, sampleCount: values.length, windowStartTimestamp: values[0].timestamp, windowEndTimestamp: values.at(-1)!.timestamp, unit: signalType === "raw" ? "ADC counts" : "derived ADC-count units" };
}

type Props = { samples: EmgSample[]; channels: EmgChannel[]; paused: boolean; initialSignal?: SignalRepresentation; settings?: EmgGraphSettings; hardwareRange?: [number, number] };

export function EmgChart({ samples, channels, paused, initialSignal = "raw", settings, hardwareRange }: Props) {
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const frozen = useRef<EmgSample[]>([]);
  const scales = useRef<Record<string, [number, number]>>({});
  const [legacySignals, setLegacySignals] = useState<SignalRepresentation[]>([initialSignal]);
  useEffect(() => { if (settings) return; const handler = (event: Event) => setLegacySignals((event as CustomEvent<SignalRepresentation[]>).detail); window.addEventListener("emg-signal-selection", handler); return () => window.removeEventListener("emg-signal-selection", handler); }, [settings]);
  const graph = useMemo(() => settings || { ...DEFAULT_EMG_GRAPH_SETTINGS, signalType: legacySignals[0] || initialSignal, compareSignalType: legacySignals[1] || "off" }, [settings, initialSignal, legacySignals]);
  if (!paused) frozen.current = samples;
  const rows = paused ? frozen.current : samples;
  const newest = rows.at(-1)?.host_timestamp_ns || 0;
  const cutoff = newest - graph.timeWindowSec * 1e9;
  const visible = useMemo(() => rows.filter(sample => sample.valid && sample.host_timestamp_ns >= cutoff), [rows, cutoff]);
  const shownChannels = channels.filter(channel => (!graph.visibleChannels.length || graph.visibleChannels.includes(channel.internal_id)) && (!graph.focusedChannel || graph.focusedChannel === channel.internal_id));
  const statRows = graph.statsSource === "visible" ? visible : rows.filter(sample => sample.valid);
  const stats = shownChannels.map(channel => calculateEmgStats(statRows, channel.internal_id, graph.signalType));

  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;
    const draw = () => {
      const dpr = window.devicePixelRatio || 1, width = canvas.clientWidth, height = canvas.clientHeight;
      canvas.width = Math.max(1, Math.round(width * dpr)); canvas.height = Math.max(1, Math.round(height * dpr));
      const ctx = canvas.getContext("2d"); if (!ctx) return;
      ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
      const dark = graph.theme === "dark", plotLeft = 52, plotRight = width - 14, plotTop = 16, plotBottom = height - 28;
      ctx.fillStyle = dark ? "#101b25" : "#fbfcfa"; ctx.fillRect(0, 0, width, height);
      if (graph.showGrid) {
        ctx.strokeStyle = dark ? "rgba(190,216,226,.11)" : "rgba(49,95,125,.11)"; ctx.lineWidth = 1;
        for (let i = 0; i <= 5; i++) { const x = plotLeft + (plotRight - plotLeft) * i / 5; ctx.beginPath(); ctx.moveTo(x, plotTop); ctx.lineTo(x, plotBottom); ctx.stroke(); }
        for (let i = 0; i <= shownChannels.length * 2; i++) { const y = plotTop + (plotBottom - plotTop) * i / Math.max(1, shownChannels.length * 2); ctx.beginPath(); ctx.moveTo(plotLeft, y); ctx.lineTo(plotRight, y); ctx.stroke(); }
      }
      ctx.font = "11px system-ui"; ctx.fillStyle = dark ? "#93a9b4" : "#64747b";
      for (let i = 0; i <= 5; i++) { const secondsAgo = graph.timeWindowSec * (1 - i / 5); ctx.fillText(i === 5 ? "Now" : `-${secondsAgo.toFixed(secondsAgo < 2 ? 1 : 0)}s`, plotLeft + (plotRight - plotLeft) * i / 5 - 10, height - 9); }
      if (!visible.length || !shownChannels.length) { ctx.fillText("WAITING FOR VALID EMG DATA", plotLeft, 42); return; }
      const signals = [graph.signalType, ...(graph.compareSignalType === "off" || graph.compareSignalType === graph.signalType ? [] : [graph.compareSignalType])];
      shownChannels.forEach((channel, channelIndex) => {
        const rowHeight = (plotBottom - plotTop) / shownChannels.length, top = plotTop + rowHeight * channelIndex + 18, bottom = plotTop + rowHeight * (channelIndex + 1) - 10;
        const series = signals.map(signal => visible.map(sample => ({ timestamp: sample.host_timestamp_ns, value: sampleValue(sample, channel.internal_id, signal) })).filter((point): point is { timestamp: number; value: number } => point.value !== undefined));
        const all = series.flat().map(point => point.value); if (!all.length) return;
        const center = graph.centerSignal ? all.reduce((sum, value) => sum + value, 0) / all.length : 0;
        let targetMin = Math.min(...all) - center, targetMax = Math.max(...all) - center;
        if (graph.yScaleMode === "manual" && graph.manualYMin < graph.manualYMax) [targetMin, targetMax] = [graph.manualYMin, graph.manualYMax];
        else if (graph.yScaleMode === "hardware" && hardwareRange) [targetMin, targetMax] = hardwareRange;
        else { const span = Math.max(1, targetMax - targetMin), pad = span * graph.autoPaddingPercent / 100; targetMin -= pad; targetMax += pad; }
        const key = `${channel.internal_id}:${signals.join("+")}`; const previous = scales.current[key];
        if (graph.yScaleMode === "auto" && previous) { targetMin = targetMin < previous[0] ? targetMin : previous[0] + (targetMin - previous[0]) * .08; targetMax = targetMax > previous[1] ? targetMax : previous[1] + (targetMax - previous[1]) * .08; }
        scales.current[key] = [targetMin, targetMax]; const span = Math.max(1e-9, targetMax - targetMin);
        if (graph.showChannelLabels) { ctx.fillStyle = dark ? "#e2edf0" : "#1d4358"; ctx.font = "600 11px system-ui"; ctx.fillText(channel.display_name, plotLeft + 4, top - 5); }
        series.forEach((points, signalIndex) => {
          const reduced = peakPreservingPoints(points, Math.max(1, Math.floor(plotRight - plotLeft)), cutoff, newest);
          ctx.beginPath(); ctx.strokeStyle = signalIndex ? "#f0b56b" : colors[channelIndex % colors.length]; ctx.globalAlpha = signalIndex ? .68 : 1; ctx.lineWidth = graph.traceThickness === "thin" ? 1 : graph.traceThickness === "thick" ? 2.7 : 1.7;
          reduced.forEach((point, index) => { const x = plotLeft + (point.timestamp - cutoff) / Math.max(1, newest - cutoff) * (plotRight - plotLeft), y = bottom - ((point.value - center - targetMin) / span) * (bottom - top); if (!index) ctx.moveTo(x, y); else if (graph.traceStyle === "step") { const prior = reduced[index - 1]; const priorY = bottom - ((prior.value - center - targetMin) / span) * (bottom - top); ctx.lineTo(x, priorY); ctx.lineTo(x, y); } else ctx.lineTo(x, y); });
          ctx.stroke(); ctx.globalAlpha = 1;
        });
        ctx.fillStyle = dark ? "#71857b" : "#6b7d74"; ctx.font = "10px system-ui"; ctx.fillText(format(targetMax), 4, top + 6); ctx.fillText(format(targetMin), 4, bottom);
      });
    };
    draw(); const observer = new ResizeObserver(draw); observer.observe(canvas); return () => observer.disconnect();
  }, [visible, shownChannels, graph, hardwareRange, cutoff, newest]);

  return <div className={`emg-scope emg-scope--${graph.theme}`}>
    <canvas ref={canvasRef} className="emg-canvas" aria-label="Live EMG waveform" />
    {graph.showStats && <div className="emg-channel-stat-grid" title={graph.statsSource === "visible" ? `Statistics calculated from visible ${graph.timeWindowSec}-second window.` : "Statistics calculated since graph clear."}>{stats.map((item, index) => item && <div key={item.channelId}><strong>{shownChannels[index].display_name}</strong><span><small>Current</small>{format(item.current)}</span><span><small>Min</small>{format(item.minimum)}</span><span><small>Max</small>{format(item.maximum)}</span><span><small>P-P</small>{format(item.peakToPeak)}</span>{graph.showUnits && <em>{item.unit}</em>}</div>)}</div>}
    {graph.showStats && stats.some(Boolean) && <details className="emg-graph-details"><summary>Graph details</summary>{stats.map((item, index) => item && <p key={item.channelId}><strong>{shownChannels[index].display_name}</strong> · Mean {format(item.mean)} · {item.sampleCount.toLocaleString()} displayed samples · {item.unit}</p>)}</details>}
  </div>;
}

function format(value: number) { return Math.abs(value) >= 100 ? value.toFixed(0) : value.toFixed(2); }

export function peakPreservingPoints(points: { timestamp: number; value: number }[], width: number, start: number, end: number) {
  if (points.length <= width * 2) return points;
  const buckets = new Map<number, { min: typeof points[number]; max: typeof points[number] }>();
  for (const point of points) { const key = Math.max(0, Math.min(width - 1, Math.floor((point.timestamp - start) / Math.max(1, end - start) * width))), bucket = buckets.get(key); if (!bucket) buckets.set(key, { min: point, max: point }); else { if (point.value < bucket.min.value) bucket.min = point; if (point.value > bucket.max.value) bucket.max = point; } }
  return [...buckets.values()].flatMap(bucket => bucket.min.timestamp <= bucket.max.timestamp ? [bucket.min, bucket.max] : [bucket.max, bucket.min]);
}
