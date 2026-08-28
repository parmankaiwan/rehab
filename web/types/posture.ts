export type PostureState = "GREEN" | "ORANGE" | "RED" | "GREY";
export type ConnectionState = "CONNECTED" | "CONNECTING" | "DISCONNECTED" | "ERROR";
export interface PostureComponent { state: PostureState; value?: number | null; units?: string | null; confidence?: number | null; display_name?: string | null; }
export interface DisplayLandmark { x: number; y: number; valid: boolean; }
export interface PostureSnapshot { timestamp: number; connected: boolean; tracking_quality: string; overall_state: PostureState; ready: boolean; ready_progress: number; ready_confidence?: number | null; baseline_captured?: boolean; ready_stage?: "SEARCHING" | "ALMOST_READY" | "HOLD_STILL" | "READY" | "TRACKING_INCOMPLETE" | null; landmarks?: Record<string, DisplayLandmark>; components: Record<string, PostureComponent>; feedback: string[]; confidence?: number | null; fps?: number | null; }
export const POSTURE_STATES: PostureState[] = ["GREEN", "ORANGE", "RED", "GREY"];
