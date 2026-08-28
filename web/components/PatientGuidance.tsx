import { CheckCircle2, Compass } from "lucide-react";
import { PostureSnapshot } from "@/types/posture";

const sentence = (value: string) => value.toLowerCase().replace(/^./, (letter) => letter.toUpperCase());

export function PatientGuidance({ snapshot, unavailable }: { snapshot: PostureSnapshot | null; unavailable: boolean }) {
  if (snapshot?.ready && !unavailable) return <section className="patient-guidance patient-guidance--ready"><CheckCircle2/><div><span className="eyebrow">Live guidance</span><h2>READY TO BEGIN</h2><p>Hold naturally and prepare to begin.</p></div></section>;
  const messages = unavailable ? ["Start the FlexMap Python posture service."] : snapshot?.feedback.slice(0, 2) ?? [];
  const fallback = snapshot?.overall_state === "GREY" ? "Keep your upper body visible" : "Hold your position";
  return <section className="patient-guidance"><Compass/><div><span className="eyebrow">Live guidance</span><h2>{sentence(messages[0] ?? fallback)}</h2>{messages[1] && <p>{sentence(messages[1])}</p>}</div></section>;
}
