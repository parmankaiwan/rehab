"use client";

import { useCallback, useMemo, useState } from "react";
import { usePostureStream } from "@/hooks/usePostureStream";
import { PostureState } from "@/types/posture";
import { BodyRegion, CoachInstruction, regionState, selectCoach } from "@/lib/bodyRegionMap";
import { CompactPostureComponents } from "./CompactPostureComponents";
import { LiveCameraView } from "./LiveCameraView";
import { PatientHeader } from "./PatientHeader";
import { PatientHero } from "./PatientHero";
import { ResearchMetrics } from "./ResearchMetrics";
import { SmartReadyCoach } from "./SmartReadyCoach";
import { LiveBodyMap } from "./LiveBodyMap";
import { SettingsPanel, SettingsState } from "./SettingsPanel";

export function PatientDashboard() {
  const stream = usePostureStream();
  const [settingsOpen, setSettingsOpen] = useState(false);
  const [settings, setSettings] = useState<SettingsState>({ research: false, measurements: false, hands: true, skeleton: true });
  const [manualRegion, setManualRegion] = useState<BodyRegion | null>(null);
  const [hoverRegion, setHoverRegion] = useState<BodyRegion | null>(null);
  const unavailable = stream.connectionState !== "CONNECTED" || stream.isStale;
  const snapshot = unavailable ? null : stream.snapshot;
  const state = snapshot?.overall_state ?? "GREY";
  const automaticCoach = useMemo(() => selectCoach(snapshot), [snapshot]);
  const [coach, setCoach] = useState<CoachInstruction>(automaticCoach);
  const handleCoach = useCallback((instruction: CoachInstruction) => setCoach(instruction), []);
  const selectRegion = useCallback((region: BodyRegion | null) => setManualRegion((current) => current === region ? null : region), []);
  const activeRegion = snapshot?.ready ? null : manualRegion ?? hoverRegion ?? coach.region;
  const highlightState = activeRegion ? regionState(snapshot, activeRegion) : state;
  const mirrored = process.env.NEXT_PUBLIC_CAMERA_MIRRORED === "true";
  const reset = async () => { try { await fetch(`${process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://localhost:8000"}/api/reset`, { method: "POST" }); } catch { /* status UI already handles offline state */ } };
  return <>
    <PatientHeader connection={stream.connectionState} cvLive={!!snapshot} mock={stream.isMock} onSettings={() => setSettingsOpen(true)} onReset={reset}/>
    <main className="patient-main">
      <div className="hero-row"><PatientHero state={state} ready={!!snapshot?.ready} unavailable={unavailable}/>{stream.isMock && <div className="mock-controls" aria-label="Mock posture state">{(["GREEN", "ORANGE", "RED", "GREY"] as PostureState[]).map((value) => <button key={value} onClick={() => stream.setMockState(value)}>{value}</button>)}</div>}</div>
      <div className="patient-grid">
        <LiveCameraView snapshot={snapshot} unavailable={!snapshot} research={settings.research} activeRegion={activeRegion} highlightState={highlightState} mirrored={mirrored} coachPrimary={coach.primary}/>
        <aside className="coach-column"><SmartReadyCoach snapshot={snapshot} onInstruction={handleCoach}/></aside>
      </div>
      <div className="posture-tools"><LiveBodyMap snapshot={snapshot} active={activeRegion} onSelect={selectRegion}/><CompactPostureComponents snapshot={snapshot} research={settings.research} measurements={settings.measurements || settings.research} activeRegion={activeRegion} onHover={setHoverRegion} onSelect={selectRegion}/></div>
      {settings.research && <ResearchMetrics snapshot={stream.snapshot} stale={stream.isStale}/>} 
    </main>
    <footer>FlexMap is an engineering rehabilitation research prototype. Posture criteria are configurable and are not clinical diagnostic thresholds.</footer>
    <SettingsPanel open={settingsOpen} onOpenChange={setSettingsOpen} value={settings} onChange={setSettings}/>
  </>;
}
