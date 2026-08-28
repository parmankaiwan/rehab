"use client";
import { useEffect, useMemo, useState } from "react";
import { selectCoach, CoachInstruction } from "@/lib/bodyRegionMap";
import { PostureSnapshot } from "@/types/posture";
import { ReadinessRing } from "./ReadinessRing";

const COACH_MESSAGE_MIN_DISPLAY_MS = 400;

export function SmartReadyCoach({ snapshot, onInstruction }: { snapshot: PostureSnapshot | null; onInstruction?: (instruction: CoachInstruction) => void }) {
  const next = useMemo(() => selectCoach(snapshot), [snapshot]);
  const [shown, setShown] = useState(next);
  useEffect(() => {
    if (next.primary === shown.primary && next.stage === shown.stage) return;
    const timer = window.setTimeout(() => setShown(next), COACH_MESSAGE_MIN_DISPLAY_MS);
    return () => window.clearTimeout(timer);
  }, [next, shown.primary, shown.stage]);
  useEffect(() => onInstruction?.(shown), [shown, onInstruction]);
  return <section className={`smart-coach state-${shown.state.toLowerCase()}`} aria-live="polite">
    <div className="coach-message"><span className="eyebrow">{shown.stage === "READY" ? "POSITION SET" : shown.stage === "HOLDING" ? "ALMOST THERE" : "NEXT STEP"}</span><h2>{shown.primary}</h2>{shown.secondary && <p>{shown.secondary}</p>}<span className="coach-stage">{shown.stage}</span></div>
    <ReadinessRing progress={snapshot?.ready_progress ?? 0} ready={!!snapshot?.ready}/>
  </section>;
}
