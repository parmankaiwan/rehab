import type { BrowserPoseObservation } from "@/hooks/useBrowserPose";

export interface RecorderFormat { mimeType: string; extension: ".webm" | ".mp4" }

const FORMATS: RecorderFormat[] = [
  { mimeType: "video/webm;codecs=vp9", extension: ".webm" },
  { mimeType: "video/webm;codecs=vp8", extension: ".webm" },
  { mimeType: "video/webm", extension: ".webm" },
  { mimeType: "video/mp4;codecs=avc1", extension: ".mp4" },
  { mimeType: "video/mp4", extension: ".mp4" },
];

export function selectRecorderFormat(isSupported: (mimeType: string) => boolean): RecorderFormat | null {
  return FORMATS.find((format) => isSupported(format.mimeType)) ?? null;
}

export function captureQuality(observations: BrowserPoseObservation[]): { technicalQuality: "GOOD" | "USABLE_WITH_WARNINGS" | "LOW_QUALITY" | "INVALID"; trackingQuality: string; validRatio: number } {
  if (!observations.length) return { technicalQuality: "INVALID", trackingQuality: "LOST", validRatio: 0 };
  const valid = observations.filter((item) => item.valid).length;
  const validRatio = valid / observations.length;
  const quality = observations.at(-1)?.snapshot?.tracking_quality || "LOST";
  return { technicalQuality: validRatio >= .9 ? "GOOD" : validRatio >= .6 ? "USABLE_WITH_WARNINGS" : validRatio > 0 ? "LOW_QUALITY" : "INVALID", trackingQuality: quality, validRatio };
}

export function observationsJsonl(observations: BrowserPoseObservation[], captureStartMs: number): string {
  return observations.map((item) => JSON.stringify({ ...item, playbackOffsetMs: Math.max(0, item.monotonicTimestampMs - captureStartMs), association: "TIMESTAMP_NEAREST_APPROXIMATE" })).join("\n") + "\n";
}

export function isEditableTarget(target: EventTarget | null): boolean {
  const element = target as HTMLElement | null;
  return !!element && (element.isContentEditable || ["INPUT", "TEXTAREA", "SELECT", "BUTTON"].includes(element.tagName));
}
