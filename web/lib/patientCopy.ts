import { PostureState } from "@/types/posture";

export interface PatientCopy { title: string; subtitle: string; }

export function getHeroContent(state: PostureState, ready: boolean, unavailable = false): PatientCopy {
  if (unavailable) return { title: "TRACKING UNAVAILABLE", subtitle: "Waiting for current posture information." };
  if (state === "GREEN" && ready) return { title: "READY TO BEGIN", subtitle: "Your starting position is acceptable." };
  if (state === "GREEN") return { title: "HOLD POSITION", subtitle: "Stay naturally in this position for a moment." };
  if (state === "ORANGE") return { title: "ALMOST READY", subtitle: "Make one small adjustment." };
  if (state === "RED") return { title: "ADJUST YOUR POSITION", subtitle: "Follow the guidance beside the camera." };
  return { title: "STEP FULLY INTO VIEW", subtitle: "Keep your upper body visible so FlexMap can check your position." };
}

export function getStatusContent(state: PostureState, ready: boolean, unavailable = false): PatientCopy {
  if (unavailable) return { title: "TRACKING UNAVAILABLE", subtitle: "Current posture information is unavailable." };
  if (state === "GREEN" && ready) return { title: "READY", subtitle: "Your starting position is acceptable." };
  if (state === "GREEN") return { title: "HOLD POSITION", subtitle: "Stay naturally in this position." };
  if (state === "ORANGE") return { title: "SMALL ADJUSTMENT", subtitle: "You are close to the starting position." };
  if (state === "RED") return { title: "ADJUST POSITION", subtitle: "Change your position before starting." };
  return { title: "TRACKING INCOMPLETE", subtitle: "FlexMap cannot see enough of your upper body." };
}

export const patientComponentLabels: Record<PostureState, string> = {
  GREEN: "Ready", ORANGE: "Close", RED: "Adjust", GREY: "Not tracked",
};
