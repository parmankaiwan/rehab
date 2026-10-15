import { describe, expect, it } from "vitest";
import { calculateEmgStats, peakPreservingPoints, sampleValue } from "./EmgChart";
import type { EmgSample } from "@/types/emg";

function samples(raw: number[], processed: Record<string, number[]> = {}): EmgSample[] {
  return raw.map((value, index) => ({ sequence_id: index + 1, host_timestamp_ns: index * 1_000_000_000, t_ms: index * 1000, valid: true, channels: { channel_1: value }, processed: { channel_1: Object.fromEntries(Object.entries(processed).map(([name, values]) => [name, values[index]])) } }));
}

describe("EMG display statistics", () => {
  it("calculates current, min, max and peak-to-peak from raw values", () => {
    const result = calculateEmgStats(samples([100, 200, 150, 350, 120]), "channel_1", "raw");
    expect(result).toMatchObject({ current: 120, minimum: 100, maximum: 350, peakToPeak: 250, sampleCount: 5 });
  });

  it("preserves negative filtered values", () => {
    const rows = samples([0, 0, 0, 0], { filtered: [-100, 50, 200, -300] });
    expect(calculateEmgStats(rows, "channel_1", "filtered")).toMatchObject({ current: -300, minimum: -300, maximum: 200, peakToPeak: 500 });
  });

  it("uses existing RMS values without recomputing raw RMS", () => {
    const rows = samples([100, 200, 300, 400], { rms: [10, 12, 18, 16] });
    expect(calculateEmgStats(rows, "channel_1", "rms")).toMatchObject({ current: 16, minimum: 10, maximum: 18 });
    expect(sampleValue(rows[2], "channel_1", "rms")).toBe(18);
  });

  it("updates statistics when the caller changes the visible window", () => {
    const rows = samples([100, 400, 180, 250]);
    expect(calculateEmgStats(rows, "channel_1", "raw")).toMatchObject({ minimum: 100, maximum: 400 });
    expect(calculateEmgStats(rows.slice(-2), "channel_1", "raw")).toMatchObject({ minimum: 180, maximum: 250 });
  });

  it("bounds a 30-second 1000 Hz render while preserving extrema", () => {
    const points = Array.from({ length: 30_000 }, (_, index) => ({ timestamp: index * 1_000_000, value: index === 12_345 ? 4095 : index === 23_456 ? 0 : 2048 }));
    const rendered = peakPreservingPoints(points, 1000, 0, 30_000_000_000);
    expect(rendered.length).toBeLessThanOrEqual(2000);
    expect(Math.min(...rendered.map(point => point.value))).toBe(0);
    expect(Math.max(...rendered.map(point => point.value))).toBe(4095);
  });
});
