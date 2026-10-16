export type CaptureType = "STILL" | "VIDEO" | "BOTH";
export type CaptureState = "IDLE" | "PREFLIGHT" | "COUNTDOWN" | "CAPTURING" | "RECORDING" | "FINALIZING" | "REVIEW" | "UPLOADING" | "VALIDATING" | "SAVED" | "CANCELLED" | "INTERRUPTED" | "UPLOAD_FAILED" | "ERROR";

export interface BrowserCollectionLabel {
  label_id: string;
  dataset_id: string;
  name: string;
  display_name: string;
  description: string;
  tracking_failure_label: boolean;
  archived: boolean;
}

export interface BrowserCollectionSample {
  sample_id: string;
  dataset_id: string;
  label_id: string;
  label_at_capture: string;
  sample_type: "STILL" | "VIDEO";
  source: "BROWSER_MEDIAPIPE";
  subject_id: string;
  created_at: string;
  technical_quality: string;
  tracking_quality: string;
  review_status: string;
  capture_state: "COMPLETE" | "INTERRUPTED";
  artifact_manifest: Array<{ name: string; object_path: string; content_type: string; size_bytes: number; sha256: string; role: string }>;
}

export interface BrowserCollectionDataset {
  dataset_id: string;
  storage_key: string;
  name: string;
  rehabilitation_module_id: string;
  description: string;
  instructions: string;
  camera_view: string;
  relevant_side: string;
  observation_profile: string;
  permitted_capture_types: CaptureType;
  protocol_id?: string | null;
  session_id?: string | null;
  data_purpose: string;
  allow_raw_media: boolean;
  allow_annotated_media: boolean;
  allow_thumbnails: boolean;
  archived: boolean;
  created_at: string;
  updated_at: string;
  label_count: number;
  still_count: number;
  video_count: number;
  reviewed_count: number;
  approved_count: number;
  last_sample_at?: string | null;
  labels?: BrowserCollectionLabel[];
  samples?: BrowserCollectionSample[];
}

export interface BrowserCollectionStatus {
  configured: boolean;
  enabled: boolean;
  missing: string[];
  bucket: string;
  durability: string;
}
