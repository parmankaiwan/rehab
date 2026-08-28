import { getHeroContent } from "@/lib/patientCopy";
import { PostureState } from "@/types/posture";

export function PatientHero({ state, ready, unavailable }: { state: PostureState; ready: boolean; unavailable: boolean }) {
  const content = getHeroContent(state, ready, unavailable);
  return <section className="patient-hero" aria-live="polite"><span className="eyebrow">Posture readiness</span><h1>{content.title}</h1><p>{content.subtitle}</p></section>;
}
