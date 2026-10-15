from __future__ import annotations

import hmac
import os

from fastapi import APIRouter, Depends, Header, HTTPException, Query
from fastapi.responses import FileResponse

from .cv_recording_service import CvRecordingService
from .dataset_config import dataset_settings, load_label_taxonomy
from .dataset_models import DatasetUpdate, ExclusionUpdate, RecordingConfiguration, RehabAssignment
from .dataset_vault import DatasetVault
from .posture_stream import store
from .video_store import raw_video_store, video_store
from .video_preview import VideoPreviewService

settings = dataset_settings()
vault = DatasetVault(settings)
recorder = CvRecordingService(settings, vault, raw_video_store, video_store, store)
video_previews = VideoPreviewService(settings, vault)
router = APIRouter(prefix="/api/master", tags=["Master Dataset"])


def require_master(x_flexmap_master_token: str | None = Header(default=None)) -> None:
    expected = os.getenv("FLEXMAP_MASTER_INTERNAL_TOKEN", "")
    if not expected:
        raise HTTPException(503, "Master backend token is not configured")
    if not x_flexmap_master_token or not hmac.compare_digest(x_flexmap_master_token, expected):
        raise HTTPException(403, "Master authorization required")


protected = [Depends(require_master)]


@router.get("/dataset/settings", dependencies=protected)
def get_settings() -> dict:
    return {"labels": load_label_taxonomy(settings), "modules": [module.as_dict() for module in vault.registry.modules], "duration_presets": [3, 5, 10, 15], "default_duration": settings.default_recording_seconds, "max_duration": settings.max_recording_seconds, "countdown_seconds": settings.countdown_seconds, "store_raw_video": settings.store_raw_video_default, "store_annotated_video": settings.store_annotated_video_default, "minimum_free_bytes": settings.minimum_free_bytes}


@router.get("/recordings/preflight", dependencies=protected)
def recording_preflight():
    snapshot = store.latest()
    free = __import__("shutil").disk_usage(settings.root).free
    return {"cv_engine": video_store.is_fresh(), "camera_live": raw_video_store.is_fresh(), "pose_receiving": bool(snapshot and snapshot.connected), "storage_available": free >= settings.minimum_free_bytes, "free_storage_bytes": free, "cv_fps": snapshot.fps if snapshot else None, "camera_receive_fps": raw_video_store.metrics().get("frame_receive_fps"), "recording_state": recorder.status().state}

@router.get("/recordings/status", dependencies=protected)
def recording_status(): return recorder.status()


@router.post("/recordings/start", dependencies=protected)
def recording_start(configuration: RecordingConfiguration):
    try: return recorder.start(configuration)
    except ValueError as exc: raise HTTPException(422, str(exc)) from exc
    except RuntimeError as exc: raise HTTPException(409, str(exc)) from exc


@router.post("/recordings/cancel", dependencies=protected)
def recording_cancel():
    try: return recorder.cancel()
    except RuntimeError as exc: raise HTTPException(409, str(exc)) from exc

@router.post("/recordings/stop", dependencies=protected)
def recording_stop():
    try: return recorder.stop()
    except RuntimeError as exc: raise HTTPException(409, str(exc)) from exc


@router.post("/recordings/{recording_id}/save", dependencies=protected)
def recording_save(recording_id: str):
    try: return recorder.save(recording_id)
    except (RuntimeError, FileNotFoundError, ValueError) as exc: raise HTTPException(409, str(exc)) from exc


@router.delete("/recordings/{recording_id}/review", dependencies=protected)
def recording_discard(recording_id: str):
    try: recorder.discard(recording_id); return {"success": True}
    except (RuntimeError, FileNotFoundError) as exc: raise HTTPException(409, str(exc)) from exc


@router.get("/recordings/{recording_id}/review/{filename}", dependencies=protected)
def review_file(recording_id: str, filename: str):
    try: return FileResponse(recorder.review_path(recording_id, filename))
    except FileNotFoundError as exc: raise HTTPException(404, "File not found") from exc


@router.get("/dataset/stats", dependencies=protected)
def dataset_stats(): return vault.stats()


@router.get("/dataset/recordings", dependencies=protected)
def recordings(search: str = "", subject: str = "", category: str = "", label: str = "", affected_side: str = "", tracking: str = "", status: str = "", session_id: str = "", rehab_type: str = "", study_id: str = "", collection_id: str = "", protocol_id: str = "", trial_id: str = ""):
    return vault.list(search=search, subject=subject, category=category, label=label, affected_side=affected_side, tracking=tracking, status=status, session_id=session_id, rehab_type=rehab_type, study_id=study_id, collection_id=collection_id, protocol_id=protocol_id, trial_id=trial_id)


@router.get("/dataset/recordings/{recording_id}", dependencies=protected)
def recording_detail(recording_id: str):
    item = vault.get(recording_id)
    if not item: raise HTTPException(404, "Recording not found")
    return item


@router.patch("/dataset/recordings/{recording_id}", dependencies=protected)
def recording_update(recording_id: str, update: DatasetUpdate):
    current = vault.get(recording_id)
    if not current: raise HTTPException(404, "Recording not found")
    category, label = current["rehab_type"], update.label or current["label"]
    if category != "UNASSIGNED":
        try: vault.registry.validate_label(category, label)
        except ValueError as exc: raise HTTPException(422, str(exc)) from exc
    return vault.update(recording_id, **update.model_dump())


@router.delete("/dataset/recordings/{recording_id}", dependencies=protected)
def recording_delete(recording_id: str, confirm: str = Query(...)):
    if confirm != recording_id: raise HTTPException(422, "Confirmation must match the recording ID")
    try: vault.delete(recording_id); return {"success": True}
    except FileNotFoundError as exc: raise HTTPException(404, "Recording not found") from exc


@router.get("/dataset/recordings/{recording_id}/files/{filename}", dependencies=protected)
def recording_file(recording_id: str, filename: str):
    item = vault.get(recording_id)
    if not item or filename != __import__("pathlib").Path(filename).name or filename not in item.get("files", []): raise HTTPException(404, "File not found")
    base = (settings.root / item["relative_path"]).resolve(); path = (base / filename).resolve()
    if path.parent != base or not path.is_file(): raise HTTPException(404, "File not found")
    return FileResponse(path, filename=filename if filename != "video.mp4" else None)


@router.get("/dataset/recordings/{recording_id}/video-status", dependencies=protected)
def recording_video_status(recording_id: str):
    try: return video_previews.status(recording_id)
    except (FileNotFoundError, ValueError) as exc: raise HTTPException(404, str(exc)) from exc

@router.post("/dataset/recordings/{recording_id}/video/{variant}/preview", dependencies=protected)
def generate_video_preview(recording_id: str, variant: str):
    try: return video_previews.generate(recording_id, variant)
    except FileNotFoundError as exc: raise HTTPException(404, "Video not found") from exc
    except ValueError as exc: raise HTTPException(422, str(exc)) from exc
    except RuntimeError as exc: raise HTTPException(503, str(exc)) from exc

@router.get("/dataset/recordings/{recording_id}/video/{variant}", dependencies=protected)
def recording_video(recording_id: str, variant: str, original: bool = False, download: bool = False):
    try:
        source, preview = video_previews.paths(recording_id, variant)
        if not source.is_file(): raise FileNotFoundError(source)
        state = video_previews.status(recording_id)[variant]
        path = source if original or state["preview_status"] != "READY" else preview
        return FileResponse(path, media_type="video/webm" if path.suffix == ".webm" else "video/mp4", filename=path.name if download else None, headers={"Accept-Ranges": "bytes"})
    except FileNotFoundError as exc: raise HTTPException(404, "Video not found") from exc
    except ValueError as exc: raise HTTPException(422, str(exc)) from exc

@router.get("/dataset/manifest", dependencies=protected)
def manifest(): return FileResponse(vault.generate_manifest(), filename="dataset_manifest.csv")

@router.patch("/dataset/recordings/{recording_id}/exclusion", dependencies=protected)
def recording_exclusion(recording_id: str, update: ExclusionUpdate):
    try: return vault.set_excluded(recording_id, update.excluded, update.reason)
    except FileNotFoundError as exc: raise HTTPException(404, "Recording not found") from exc


@router.get("/dataset/training-manifest", dependencies=protected)
def training_manifest():
    vault.generate_manifests()
    return FileResponse(settings.training_manifest_path, filename="training_manifest.csv")
@router.get("/rehab-modules", dependencies=protected)
def rehab_modules(): return vault.module_summaries()

@router.get("/rehab-modules/{slug}", dependencies=protected)
def rehab_module(slug: str):
    try:
        module=vault.registry.by_slug(slug)
        return {**module.as_dict(), "stats":vault.stats(module.id)}
    except ValueError as exc: raise HTTPException(404,str(exc)) from exc

@router.get("/rehab-modules/{slug}/stats", dependencies=protected)
def rehab_stats(slug: str):
    try: module=vault.registry.by_slug(slug);return vault.stats(module.id)
    except ValueError as exc: raise HTTPException(404,str(exc)) from exc

@router.get("/rehab-modules/{slug}/labels", dependencies=protected)
def rehab_labels(slug: str):
    try: module=vault.registry.by_slug(slug);return {"rehab_type":module.id,"rehab_slug":module.slug,"labels":[{"id":x,"display_name":y} for x,y in module.label_options]}
    except ValueError as exc: raise HTTPException(404,str(exc)) from exc

@router.get("/rehab-modules/{slug}/recordings", dependencies=protected)
def rehab_recordings(slug: str, label: str="", search: str=""):
    try: module=vault.registry.by_slug(slug)
    except ValueError as exc: raise HTTPException(404,str(exc)) from exc
    return vault.list(rehab_type=module.id,label=label,search=search)

@router.get("/rehab-modules/{slug}/manifest", dependencies=protected)
def rehab_manifest(slug: str):
    try:return FileResponse(vault.module_manifest(slug),filename="dataset_manifest.csv")
    except ValueError as exc:raise HTTPException(404,str(exc)) from exc

@router.get("/rehab-modules/{slug}/training-manifest", dependencies=protected)
def rehab_training_manifest(slug: str):
    try:return FileResponse(vault.module_manifest(slug,True),filename="training_manifest.csv")
    except ValueError as exc:raise HTTPException(404,str(exc)) from exc

@router.patch("/dataset/recordings/{recording_id}/rehab", dependencies=protected)
def assign_recording_rehab(recording_id: str, update: RehabAssignment):
    try:return vault.assign_rehab(recording_id,update.rehab_type,update.label,update.confirm)
    except FileNotFoundError as exc:raise HTTPException(404,"Recording not found") from exc
    except (ValueError,FileExistsError) as exc:raise HTTPException(422,str(exc)) from exc
