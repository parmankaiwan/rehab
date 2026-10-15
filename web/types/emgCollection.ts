import type { EmgChannel, HardwareProfile } from "./emg";

export type EmgProtocol = {
  protocol_id: string;
  protocol_version: number;
  display_name: string;
  description: string;
  rehab_type: string;
  modality: "EMG" | "CV" | "PAIRED";
  status: string;
  countdown_seconds: number;
  baseline_required: boolean;
  baseline_count: number;
  baseline_duration_seconds: number;
  required_emg_channels?: number;
  required_hardware_profile_id?: string;
  recommended_channel_map: EmgChannel[];
  trial_plan: Array<{label:string;count:number;duration_seconds:number;duration_mode:"FIXED"|"MANUAL_STOP";rest_after_seconds:number;instructions:string}>;
};
export type EmgBaselineSlot = {baseline_number:number;state:string;attempt_number:number;baseline_id?:string;attempts:Array<Record<string,unknown>>};
export type EmgCollectionTrial = {
  trial_id:string; trial_number:number; research_label:string; duration_seconds:number;
  duration_mode:"FIXED"|"MANUAL_STOP"; state:string; attempt_number:number;
  active_modality?:string; quality_result?:string; quality_warnings:string[];
  quality_reports?:Record<string,Record<string,unknown>>; markers:Array<Record<string,unknown>>;
  recording_ids:{CV?:string;EMG?:string};
};
export type EmgCollection = {
  collection_id:string; subject_id:string; session_id:string; protocol_id:string;
  protocol_version:number; rehab_type:string; modality:string; status:string;
  current_trial_id:string; controller_id?:string; revision:number;
  hardware_profile_id?:string; hardware_profile_version?:number;
  hardware_profile_snapshot?:HardwareProfile; channel_map_snapshot:EmgChannel[];
  baseline_group_id:string; baselines:EmgBaselineSlot[]; trials:EmgCollectionTrial[];
};
export type CollectionPreflight = {overall:"PASS"|"WARNING"|"BLOCKED";checked_at:string;checks:Array<{name:string;state:"PASS"|"WARNING"|"BLOCKED";message:string}>};
export type CollectionCoverage = {recordings:number;unique_subjects:number;protocol_distribution:Record<string,number>;hardware_distribution:Record<string,number>;baseline_coverage:{required:number;complete:number};ml_readiness:{eligible_recordings:number;unique_subjects:number;mock_excluded:boolean}};
