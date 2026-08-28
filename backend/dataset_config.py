from __future__ import annotations
import json,os
from dataclasses import dataclass
from pathlib import Path
PROJECT_ROOT=Path(__file__).resolve().parent.parent
@dataclass(frozen=True)
class DatasetSettings:
 root:Path
 labels_path:Path
 modules_path:Path=PROJECT_ROOT/"config"/"rehab_modules.json"
 default_recording_seconds:float=5
 max_recording_seconds:float=120
 countdown_seconds:int=3
 store_raw_video_default:bool=True
 store_annotated_video_default:bool=True
 store_preview_default:bool=True
 video_codec:str="mp4v"
 target_video_fps:float=20
 recording_frame_queue_max:int=180
 minimum_free_bytes:int=536870912
 quality_good_tracking_min:float=.8
 quality_pose_rate_min:float=8
 @property
 def rehab_dir(self):return self.root/"rehab"
 @property
 def global_manifests_dir(self):return self.root/"global_manifests"
 @property
 def temp_dir(self):return self.root/"temp"
 @property
 def recordings_dir(self):return self.root/"recordings"
 @property
 def database_path(self):return self.root/"dataset.db"
 @property
 def manifest_path(self):return self.root/"dataset_manifest.csv"
 @property
 def training_manifest_path(self):return self.root/"training_manifest.csv"
def dataset_settings()->DatasetSettings:
 return DatasetSettings(root=Path(os.getenv("FLEXMAP_DATASET_ROOT",PROJECT_ROOT/"data"/"dataset_vault")).resolve(),labels_path=Path(os.getenv("FLEXMAP_DATASET_LABELS",PROJECT_ROOT/"config"/"dataset_labels.json")).resolve(),modules_path=Path(os.getenv("FLEXMAP_REHAB_MODULES",PROJECT_ROOT/"config"/"rehab_modules.json")).resolve(),default_recording_seconds=float(os.getenv("FLEXMAP_DEFAULT_RECORDING_SECONDS","5")),max_recording_seconds=float(os.getenv("FLEXMAP_MAX_RECORDING_SECONDS","120")),countdown_seconds=int(os.getenv("FLEXMAP_COUNTDOWN_SECONDS","3")),store_raw_video_default=os.getenv("FLEXMAP_STORE_RAW_VIDEO","true").lower()=="true",store_annotated_video_default=os.getenv("FLEXMAP_STORE_ANNOTATED_VIDEO","true").lower()=="true",store_preview_default=os.getenv("FLEXMAP_STORE_PREVIEW","true").lower()=="true",video_codec=os.getenv("FLEXMAP_VIDEO_CODEC","mp4v"),target_video_fps=float(os.getenv("FLEXMAP_RECORDING_FPS","20")),recording_frame_queue_max=int(os.getenv("FLEXMAP_RECORDING_QUEUE_MAX","180")),minimum_free_bytes=int(os.getenv("FLEXMAP_MIN_FREE_BYTES","536870912")))
def load_label_taxonomy(settings):
 data=json.loads(settings.labels_path.read_text(encoding="utf-8"))
 if not isinstance(data,dict) or not all(isinstance(k,str) and isinstance(v,list) and all(isinstance(x,str) for x in v) for k,v in data.items()):raise ValueError("Dataset label taxonomy is invalid")
 return data