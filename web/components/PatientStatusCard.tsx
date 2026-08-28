import { getStatusContent } from "@/lib/patientCopy";
import { PostureSnapshot, PostureState } from "@/types/posture";
import { StateIcon } from "./icons";
import { ReadinessIndicator } from "./ReadinessIndicator";

export function PatientStatusCard({ snapshot, unavailable }: { snapshot: PostureSnapshot | null; unavailable: boolean }) {
  const state: PostureState = unavailable ? "GREY" : snapshot?.overall_state ?? "GREY";
  const ready = !!snapshot?.ready && !unavailable;
  const content = getStatusContent(state, ready, unavailable);
  return <section className={`patient-status state-${state.toLowerCase()}`} aria-live="polite">
    <div className="patient-status-top"><span className="status-icon"><StateIcon state={state} size={25}/></span><span className="eyebrow">Current status</span></div>
    <h2>{content.title}</h2><p>{content.subtitle}</p>
    {!ready && <ReadinessIndicator ready={false} progress={snapshot?.ready_progress ?? 0} unavailable={unavailable}/>} 
  </section>;
}
