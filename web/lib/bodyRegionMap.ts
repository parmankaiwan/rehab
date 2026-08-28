import { PostureSnapshot, PostureState } from "@/types/posture";

export type BodyRegion = "HEAD" | "SHOULDERS" | "LEFT_SHOULDER" | "RIGHT_SHOULDER" | "TRUNK" | "HIPS" | "LEFT_ARM" | "RIGHT_ARM";
export type CoachStage = "TRACKING" | "POSITIONING" | "ALIGNMENT" | "HOLDING" | "READY";

export interface CoachInstruction { stage: CoachStage; primary: string; secondary?: string; key?: string; region: BodyRegion | null; state: PostureState; }

export const COMPONENT_REGION: Record<string, BodyRegion> = {
  HEAD_LEVEL: "HEAD", HEAD_CENTERED: "HEAD",
  SHOULDER_LEVEL: "SHOULDERS", SHOULDER_SYMMETRY: "SHOULDERS",
  TRUNK_VERTICAL: "TRUNK", TRUNK_UPRIGHT: "TRUNK", TRUNK_CENTERED: "TRUNK", FRONT_FACING: "TRUNK",
  HIP_LEVEL: "HIPS", HIP_SYMMETRY: "HIPS",
  LEFT_ARM_VISIBLE: "LEFT_ARM", RIGHT_ARM_VISIBLE: "RIGHT_ARM",
};

export const REGION_COMPONENTS: Record<BodyRegion, string[]> = {
  HEAD: ["HEAD_LEVEL", "HEAD_CENTERED"], SHOULDERS: ["SHOULDER_LEVEL", "SHOULDER_SYMMETRY"],
  LEFT_SHOULDER: ["SHOULDER_LEVEL"], RIGHT_SHOULDER: ["SHOULDER_LEVEL"],
  TRUNK: ["TRUNK_VERTICAL", "TRUNK_CENTERED", "FRONT_FACING"], HIPS: ["HIP_LEVEL", "HIP_SYMMETRY"],
  LEFT_ARM: ["LEFT_ARM_VISIBLE"], RIGHT_ARM: ["RIGHT_ARM_VISIBLE"],
};

const priorities = ["LEFT_ARM_VISIBLE", "RIGHT_ARM_VISIBLE", "LEFT_HIP_VISIBLE", "RIGHT_HIP_VISIBLE", "BODY_TRACKING_COMPLETE", "FRONT_FACING", "TRUNK_VERTICAL", "TRUNK_CENTERED", "SHOULDER_LEVEL", "SHOULDER_SYMMETRY", "HEAD_LEVEL", "HEAD_CENTERED", "HIP_LEVEL", "HIP_SYMMETRY"];
const messages: Record<string, string> = { LEFT_ARM_VISIBLE: "KEEP LEFT ARM VISIBLE", RIGHT_ARM_VISIBLE: "KEEP RIGHT ARM VISIBLE", LEFT_HIP_VISIBLE: "KEEP BOTH HIPS VISIBLE", RIGHT_HIP_VISIBLE: "KEEP BOTH HIPS VISIBLE", BODY_TRACKING_COMPLETE: "STEP FULLY INTO VIEW", FRONT_FACING: "FACE THE CAMERA", TRUNK_VERTICAL: "SIT UPRIGHT", TRUNK_CENTERED: "CENTER YOUR TRUNK", SHOULDER_LEVEL: "RELAX YOUR SHOULDERS", SHOULDER_SYMMETRY: "FACE YOUR SHOULDERS FORWARD", HEAD_LEVEL: "LEVEL YOUR HEAD", HEAD_CENTERED: "CENTER YOUR HEAD", HIP_LEVEL: "LEVEL YOUR HIPS", HIP_SYMMETRY: "FACE YOUR HIPS FORWARD" };

function regionFor(key: string, feedback: string): BodyRegion | null {
  if (key === "SHOULDER_LEVEL" && /right shoulder/i.test(feedback)) return "RIGHT_SHOULDER";
  if (key === "SHOULDER_LEVEL" && /left shoulder/i.test(feedback)) return "LEFT_SHOULDER";
  return COMPONENT_REGION[key] ?? null;
}

export function selectCoach(snapshot: PostureSnapshot | null): CoachInstruction {
  if (!snapshot) return { stage: "TRACKING", primary: "STEP FULLY INTO VIEW", region: null, state: "GREY" };
  if (snapshot.ready) return { stage: "READY", primary: "READY", secondary: "Your starting position is set.", region: null, state: "GREEN" };
  const components = snapshot.components;
  const trackingKey = priorities.slice(0, 5).find((key) => components[key]?.state === "GREY");
  const key = trackingKey ?? priorities.slice(5).find((name) => ["RED", "ORANGE"].includes(components[name]?.state));
  if (!key && (snapshot.ready_stage === "HOLD_STILL" || snapshot.ready_progress > 0)) return { stage: "HOLDING", primary: "HOLD POSITION", secondary: "Hold naturally while your position is confirmed.", region: null, state: "ORANGE" };
  if (!key) return { stage: "HOLDING", primary: "HOLD POSITION", region: null, state: "ORANGE" };
  const feedbackPattern: Record<string, RegExp> = {
    LEFT_ARM_VISIBLE: /left arm/i, RIGHT_ARM_VISIBLE: /right arm/i,
    LEFT_HIP_VISIBLE: /hip|frame/i, RIGHT_HIP_VISIBLE: /hip|frame/i,
    BODY_TRACKING_COMPLETE: /visible|frame|back/i, FRONT_FACING: /face|forward/i,
    TRUNK_VERTICAL: /tall|upright|trunk/i, TRUNK_CENTERED: /center|trunk|body/i,
    SHOULDER_LEVEL: /shoulder/i, SHOULDER_SYMMETRY: /shoulder|face/i,
    HEAD_LEVEL: /head|level/i, HEAD_CENTERED: /head|center/i,
    HIP_LEVEL: /hip|level/i, HIP_SYMMETRY: /hip|face/i,
  };
  const raw = snapshot.feedback.find((message) => feedbackPattern[key]?.test(message)) ?? messages[key];
  const stage: CoachStage = trackingKey ? "TRACKING" : priorities.indexOf(key) <= 7 ? "POSITIONING" : "ALIGNMENT";
  return { stage, primary: (raw || "ADJUST YOUR POSITION").toUpperCase(), region: regionFor(key, raw || ""), key, state: components[key]?.state ?? snapshot.overall_state };
}

export function regionState(snapshot: PostureSnapshot | null, region: BodyRegion): PostureState {
  const states = REGION_COMPONENTS[region].map((key) => snapshot?.components[key]?.state).filter(Boolean) as PostureState[];
  return states.includes("GREY") ? "GREY" : states.includes("RED") ? "RED" : states.includes("ORANGE") ? "ORANGE" : "GREEN";
}
