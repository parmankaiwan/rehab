import type { DisplayLandmark, PostureState } from "@/types/posture";

const EDGES = [
  ["LEFT_SHOULDER", "RIGHT_SHOULDER"], ["LEFT_SHOULDER", "LEFT_ELBOW"],
  ["LEFT_ELBOW", "LEFT_WRIST"], ["RIGHT_SHOULDER", "RIGHT_ELBOW"],
  ["RIGHT_ELBOW", "RIGHT_WRIST"], ["LEFT_SHOULDER", "LEFT_HIP"],
  ["RIGHT_SHOULDER", "RIGHT_HIP"], ["LEFT_HIP", "RIGHT_HIP"],
] as const;

export function BrowserPoseOverlay({ landmarks, state }: { landmarks?: Record<string, DisplayLandmark>; state: PostureState }) {
  if (!landmarks) return null;
  const point = (name: string) => landmarks[name];
  return <svg className={`browser-pose-overlay state-${state.toLowerCase()}`} viewBox="0 0 1 1" preserveAspectRatio="none" aria-hidden="true">
    {EDGES.map(([a, b]) => point(a)?.valid && point(b)?.valid ? <line key={`${a}-${b}`} x1={1-point(a).x} y1={point(a).y} x2={1-point(b).x} y2={point(b).y}/> : null)}
    {Object.entries(landmarks).map(([name, value]) => value.valid ? <circle key={name} cx={1-value.x} cy={value.y} r=".009"/> : null)}
  </svg>;
}
