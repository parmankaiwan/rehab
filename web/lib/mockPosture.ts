import { PostureSnapshot, PostureState } from "@/types/posture";
const keys = ["TRUNK_VERTICAL","TRUNK_CENTERED","FRONT_FACING","BODY_TRACKING_COMPLETE","HEAD_LEVEL","HEAD_CENTERED","SHOULDER_LEVEL","SHOULDER_SYMMETRY","HIP_LEVEL","HIP_SYMMETRY"];
export function mockSnapshot(state: PostureState = "GREEN"): PostureSnapshot {
  const components = Object.fromEntries(keys.map((key, index) => [key, { state: state === "GREEN" && [5,6].includes(index) ? "ORANGE" : state, value: index % 2 ? .08 : 4.2, units: index % 2 ? "SW" : "deg", confidence: .96 }]));
  return { timestamp: performance.now()/1000, connected: true, tracking_quality: state === "GREY" ? "PARTIAL" : "GOOD", overall_state: state, ready: state === "GREEN", ready_progress: state === "GREEN" ? 1 : state === "ORANGE" ? .62 : 0, components, feedback: state === "GREEN" ? [] : state === "ORANGE" ? ["Relax your right shoulder", "Keep your head centered"] : state === "RED" ? ["Sit tall", "Face the camera"] : ["Keep your upper body in frame"], confidence: .96, fps: 29.7 };
}
