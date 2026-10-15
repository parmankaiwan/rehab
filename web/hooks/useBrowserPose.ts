"use client";

import { RefObject, useCallback, useEffect, useRef, useState } from "react";
import type { NormalizedLandmark, PoseLandmarker } from "@mediapipe/tasks-vision";
import type { DisplayLandmark, PostureComponent, PostureSnapshot, PostureState } from "@/types/posture";

export type BrowserPoseState = "STARTING" | "CAMERA_READY" | "LIVE" | "DENIED" | "UNAVAILABLE";

const WASM_ROOT = "https://cdn.jsdelivr.net/npm/@mediapipe/tasks-vision@1.1.1/wasm";
const MODEL_URL = "https://storage.googleapis.com/mediapipe-models/pose_landmarker/pose_landmarker_lite/float16/1/pose_landmarker_lite.task";
const NAMES: Record<number, string> = {
  0: "HEAD_CENTER", 11: "LEFT_SHOULDER", 12: "RIGHT_SHOULDER",
  13: "LEFT_ELBOW", 14: "RIGHT_ELBOW", 15: "LEFT_WRIST", 16: "RIGHT_WRIST",
  23: "LEFT_HIP", 24: "RIGHT_HIP",
};
const REQUIRED = Object.values(NAMES);

function component(state: PostureState, display_name: string, value?: number): PostureComponent {
  return { state, display_name, value, units: value == null ? undefined : "normalized" };
}

export function browserSnapshotFromLandmarks(points: NormalizedLandmark[], frame: number, fps: number): PostureSnapshot {
  const landmarks: Record<string, DisplayLandmark> = {};
  for (const [rawIndex, name] of Object.entries(NAMES)) {
    const point = points[Number(rawIndex)];
    const visibility = point?.visibility ?? 0;
    landmarks[name] = { x: point?.x ?? 0, y: point?.y ?? 0, z: point?.z, visibility, presence: point?.presence, valid: !!point && visibility >= .45 };
  }
  const validCount = REQUIRED.filter((name) => landmarks[name]?.valid).length;
  const shouldersVisible = landmarks.LEFT_SHOULDER.valid && landmarks.RIGHT_SHOULDER.valid;
  const hipsVisible = landmarks.LEFT_HIP.valid && landmarks.RIGHT_HIP.valid;
  const leftArmVisible = ["LEFT_SHOULDER", "LEFT_ELBOW", "LEFT_WRIST"].every((name) => landmarks[name].valid);
  const rightArmVisible = ["RIGHT_SHOULDER", "RIGHT_ELBOW", "RIGHT_WRIST"].every((name) => landmarks[name].valid);
  const shoulderWidth = shouldersVisible ? Math.max(.001, Math.abs(landmarks.LEFT_SHOULDER.x - landmarks.RIGHT_SHOULDER.x)) : 1;
  const shoulderLevel = shouldersVisible ? Math.abs(landmarks.LEFT_SHOULDER.y - landmarks.RIGHT_SHOULDER.y) / shoulderWidth : 1;
  const shoulderCenter = shouldersVisible ? (landmarks.LEFT_SHOULDER.x + landmarks.RIGHT_SHOULDER.x) / 2 : 0;
  const hipCenter = hipsVisible ? (landmarks.LEFT_HIP.x + landmarks.RIGHT_HIP.x) / 2 : 1;
  const trunkCenter = shouldersVisible && hipsVisible ? Math.abs(shoulderCenter - hipCenter) / shoulderWidth : 1;
  const visibilityReady = validCount === REQUIRED.length;
  const alignmentReady = shoulderLevel <= .18 && trunkCenter <= .18;
  const progress = Math.min(1, (validCount / REQUIRED.length) * .75 + (shoulderLevel <= .28 ? .125 : 0) + (trunkCenter <= .28 ? .125 : 0));
  const ready = visibilityReady && alignmentReady;
  const tracking_quality = validCount >= REQUIRED.length - 1 ? "GOOD" : validCount >= 5 ? "POOR" : "LOST";
  const overall_state: PostureState = tracking_quality === "LOST" ? "GREY" : ready ? "GREEN" : progress >= .75 ? "ORANGE" : "RED";
  const feedback: string[] = [];
  if (!visibilityReady) feedback.push("Keep your head, shoulders, arms, and hips visible.");
  if (visibilityReady && shoulderLevel > .18) feedback.push("Relax your shoulders into a comfortable level position.");
  if (visibilityReady && trunkCenter > .18) feedback.push("Bring your upper body gently toward the center.");
  const components: Record<string, PostureComponent> = {
    BODY_TRACKING_COMPLETE: component(visibilityReady ? "GREEN" : "GREY", "Body tracking"),
    LEFT_ARM_VISIBLE: component(leftArmVisible ? "GREEN" : "GREY", "Left arm visible"),
    RIGHT_ARM_VISIBLE: component(rightArmVisible ? "GREEN" : "GREY", "Right arm visible"),
    LEFT_HIP_VISIBLE: component(landmarks.LEFT_HIP.valid ? "GREEN" : "GREY", "Left hip visible"),
    RIGHT_HIP_VISIBLE: component(landmarks.RIGHT_HIP.valid ? "GREEN" : "GREY", "Right hip visible"),
    SHOULDER_LEVEL: component(shoulderLevel <= .18 ? "GREEN" : shoulderLevel <= .28 ? "ORANGE" : "RED", "Shoulder level", shoulderLevel),
    TRUNK_CENTER: component(trunkCenter <= .18 ? "GREEN" : trunkCenter <= .28 ? "ORANGE" : "RED", "Trunk center", trunkCenter),
  };
  return {
    timestamp: Date.now() / 1000, capture_frame_id: frame, connected: true, tracking_quality,
    overall_state, ready, ready_progress: progress, ready_confidence: progress,
    baseline_captured: false, ready_stage: ready ? "READY" : tracking_quality === "LOST" ? "TRACKING_INCOMPLETE" : progress >= .75 ? "ALMOST_READY" : "SEARCHING",
    landmarks, components, feedback: feedback.slice(0, 2), fps,
  };
}

export function useBrowserPose(enabled = true): {
  videoRef: RefObject<HTMLVideoElement | null>;
  snapshot: PostureSnapshot | null;
  state: BrowserPoseState;
  error: string;
  restart: () => void;
} {
  const videoRef = useRef<HTMLVideoElement>(null);
  const [snapshot, setSnapshot] = useState<PostureSnapshot | null>(null);
  const [state, setState] = useState<BrowserPoseState>("STARTING");
  const [error, setError] = useState("");
  const [generation, setGeneration] = useState(0);
  const restart = useCallback(() => setGeneration((value) => value + 1), []);

  useEffect(() => {
    if (!enabled) return;
    let stopped = false;
    let stream: MediaStream | null = null;
    let landmarker: PoseLandmarker | null = null;
    let animation = 0;
    let totalFrames = 0;
    let fpsFrames = 0;
    let lastInference = 0;
    let fpsStarted = performance.now();
    setState("STARTING"); setError(""); setSnapshot(null);
    const run = async () => {
      try {
        if (!navigator.mediaDevices?.getUserMedia) throw new Error("This browser does not support camera access.");
        stream = await navigator.mediaDevices.getUserMedia({ audio: false, video: { facingMode: "user", width: { ideal: 1280 }, height: { ideal: 720 } } });
        if (stopped) return;
        const video = videoRef.current;
        if (!video) throw new Error("Camera display is not ready.");
        video.srcObject = stream; await video.play(); setState("CAMERA_READY");
        const { FilesetResolver, PoseLandmarker } = await import("@mediapipe/tasks-vision");
        const vision = await FilesetResolver.forVisionTasks(WASM_ROOT);
        try {
          landmarker = await PoseLandmarker.createFromOptions(vision, { baseOptions: { modelAssetPath: MODEL_URL, delegate: "GPU" }, runningMode: "VIDEO", numPoses: 1, minPoseDetectionConfidence: .5, minPosePresenceConfidence: .5, minTrackingConfidence: .5 });
        } catch {
          landmarker = await PoseLandmarker.createFromOptions(vision, { baseOptions: { modelAssetPath: MODEL_URL, delegate: "CPU" }, runningMode: "VIDEO", numPoses: 1, minPoseDetectionConfidence: .5, minPosePresenceConfidence: .5, minTrackingConfidence: .5 });
        }
        const detect = () => {
          if (stopped || !landmarker) return;
          const now = performance.now();
          if (video.readyState >= 2 && now - lastInference >= 50) {
            lastInference = now; totalFrames += 1; fpsFrames += 1;
            const result = landmarker.detectForVideo(video, now);
            const fps = fpsFrames * 1000 / Math.max(1, now - fpsStarted);
            if (result.landmarks[0]) { setSnapshot(browserSnapshotFromLandmarks(result.landmarks[0], totalFrames, fps)); setState("LIVE"); }
            else { setSnapshot(null); setState("CAMERA_READY"); }
            if (fpsFrames >= 120) { fpsFrames = 0; fpsStarted = now; }
          }
          animation = requestAnimationFrame(detect);
        };
        animation = requestAnimationFrame(detect);
      } catch (cause) {
        if (stopped) return;
        const denied = cause instanceof DOMException && ["NotAllowedError", "SecurityError"].includes(cause.name);
        setState(denied ? "DENIED" : "UNAVAILABLE");
        setError(denied ? "Camera permission was not granted." : cause instanceof Error ? cause.message : "Browser camera could not start.");
      }
    };
    void run();
    return () => {
      stopped = true; cancelAnimationFrame(animation); landmarker?.close();
      stream?.getTracks().forEach((track) => track.stop());
      if (videoRef.current) videoRef.current.srcObject = null;
    };
  }, [enabled, generation]);
  return { videoRef, snapshot, state, error, restart };
}
