export type PostureState = "GREEN" | "ORANGE" | "RED" | "GREY";
export type ConnectionState = "CONNECTED" | "CONNECTING" | "DISCONNECTED" | "ERROR";
export interface PostureComponent { state: PostureState; value?: number | null; units?: string | null; confidence?: number | null; display_name?: string | null; }
export interface DisplayLandmark { x: number; y: number; valid: boolean; }
export interface CvTimingStats {mean_ms?:number|null;median_ms?:number|null;p95_ms?:number|null;p99_ms?:number|null;max_ms?:number|null;samples?:number}
export interface CvPoseScheduler {pose_submitted?:number;pose_results?:number;pose_skipped_busy?:number;pose_submission_hz?:number;pose_result_hz?:number;pose_latency_mean_ms?:number|null;pose_latency_p95_ms?:number|null;buffer_depth?:number;latest_capture_frame_id?:number|null}
export interface CvPerformance {pose_scheduler?:CvPoseScheduler;pose_result_age?:CvTimingStats;quality_and_exercise_analysis?:CvTimingStats;drawing?:CvTimingStats;bridge_publish_enqueue?:CvTimingStats}
export interface PostureSnapshot { timestamp: number; capture_frame_id?:number|null; capture_timestamp_ns?:number|null; connected: boolean; tracking_quality: string; overall_state: PostureState; ready: boolean; ready_progress: number; ready_confidence?: number | null; baseline_captured?: boolean; ready_stage?: "SEARCHING" | "ALMOST_READY" | "HOLD_STILL" | "READY" | "TRACKING_INCOMPLETE" | null; landmarks?: Record<string, DisplayLandmark>; components: Record<string, PostureComponent>; feedback: string[]; confidence?: number | null; fps?: number | null; exercise_snapshot?:{cv_pipeline_version?:string;performance_profile?:string;quality_profile_id?:string;performance?:CvPerformance}; }
export const POSTURE_STATES: PostureState[] = ["GREEN", "ORANGE", "RED", "GREY"];
