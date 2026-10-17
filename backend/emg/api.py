from __future__ import annotations
import asyncio, csv, os
from fastapi import (
    APIRouter,
    Depends,
    Header,
    HTTPException,
    WebSocket,
    WebSocketDisconnect,
)
from fastapi.responses import FileResponse
from fastapi.responses import Response
from .schemas import (
    BaselineRepeatabilityRequest,
    BaselineRequest,
    ConnectRequest,
    HardwareProfileRequest,
    QualityProfileRequest,
    RecordingRequest,
    RecordingMarkerRequest,
    ValidationRequest,
)
from .signal_processing import EmgProcessingConfig
from .service import EmgService
from .commissioning import EmgHardwareValidationStore, ValidationReviewRequest, ValidationRunCreate, ValidationTestRequest
from .device_scanner import scan_serial_devices
from ..dataset_config import dataset_settings
from ..master_dataset_api import require_master
from ..data_backend import data_backend_mode
from ..supabase_vault import SupabaseVaultError
from .cloud_vault import EmgCloudVault, EmgDatasetCreate, EmgLabelCreate

service = EmgService(dataset_settings())
cloud_vault = EmgCloudVault()
commissioning = EmgHardwareValidationStore(dataset_settings().root.parent, service)
router = APIRouter(
    prefix="/api/master/emg",
    tags=["Master EMG"],
    dependencies=[Depends(require_master)],
)
ws_router = APIRouter()


def persist_saved_recording(rid: str, saved: dict) -> dict:
    """Finalize an already-approved local recording in the active authority."""
    if data_backend_mode() != "supabase":
        return {**saved, "persistence_status": "LOCAL_ONLY"}
    item = service.get(rid)
    if not item:
        raise RuntimeError("Saved EMG recording could not be reopened")
    recording_path = (dataset_settings().root / item["relative_path"]).resolve()
    cloud = cloud_vault.save_recording(item, recording_path)
    return {**saved, "persistence_status": cloud["persistence_status"], "cloud_dataset_id": cloud["dataset_id"]}


@router.get("/datasets")
def cloud_datasets(include_archived: bool = False):
    if data_backend_mode() != "supabase":
        return []
    try:
        return cloud_vault.list_datasets(include_archived)
    except SupabaseVaultError as exc:
        raise HTTPException(503, "EMG cloud vault is unavailable") from exc


@router.get("/datasets/status")
def cloud_dataset_status():
    mode = data_backend_mode()
    return {"mode": mode.upper(), "authoritative": mode == "supabase", **cloud_vault.status()}


@router.post("/datasets")
def cloud_dataset_create(request: EmgDatasetCreate):
    if data_backend_mode() != "supabase":
        raise HTTPException(409, "Supabase must be authoritative before creating hosted EMG datasets")
    try:
        return cloud_vault.create_dataset(request)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    except SupabaseVaultError as exc:
        raise HTTPException(503, "EMG cloud vault is unavailable") from exc


@router.post("/datasets/{dataset_id}/labels")
def cloud_dataset_label(dataset_id: str, request: EmgLabelCreate):
    if data_backend_mode() != "supabase":
        raise HTTPException(409, "Supabase must be authoritative before editing hosted EMG datasets")
    try:
        return cloud_vault.create_label(dataset_id, request)
    except (ValueError, SupabaseVaultError) as exc:
        raise HTTPException(422 if isinstance(exc, ValueError) else 503, str(exc)) from exc


@router.get("/cloud-recordings")
def cloud_recordings(dataset_id: str = ""):
    if data_backend_mode() != "supabase":
        return []
    try:
        return cloud_vault.list_recordings(dataset_id)
    except SupabaseVaultError as exc:
        raise HTTPException(503, "EMG cloud vault is unavailable") from exc


@router.get("/cloud-recordings/{rid}")
def cloud_recording(rid: str):
    try:
        return cloud_vault.get_recording(rid)
    except FileNotFoundError as exc:
        raise HTTPException(404, "EMG cloud recording not found") from exc
    except SupabaseVaultError as exc:
        raise HTTPException(503, "EMG cloud vault is unavailable") from exc


@router.get("/cloud-recordings/{rid}/waveform")
def cloud_recording_waveform(rid: str, max_points: int = 2000):
    try:
        return cloud_vault.waveform(rid, max_points)
    except FileNotFoundError as exc:
        raise HTTPException(404, "Raw EMG waveform not found") from exc
    except (UnicodeError, csv.Error, SupabaseVaultError) as exc:
        raise HTTPException(503, "Stored EMG waveform could not be decoded") from exc


@router.get("/cloud-recordings/{rid}/artifacts/{artifact_id}")
def cloud_recording_artifact(rid: str, artifact_id: str, range: str = Header(default="")):
    try:
        content, status_code, headers = cloud_vault.read_artifact(rid, artifact_id, range)
        return Response(content=content, status_code=status_code, headers=headers)
    except FileNotFoundError as exc:
        raise HTTPException(404, "EMG artifact not found") from exc
    except SupabaseVaultError as exc:
        raise HTTPException(503, "EMG cloud artifact is unavailable") from exc


@router.get("/commissioning/runs")
def commissioning_runs(hardware_profile_id: str = ""):
    return commissioning.list(hardware_profile_id)


@router.post("/commissioning/runs")
def commissioning_create(req: ValidationRunCreate):
    try:
        return commissioning.create(req)
    except (ValueError, KeyError) as exc:
        raise HTTPException(422, str(exc)) from exc


@router.get("/commissioning/runs/{run_id}")
def commissioning_get(run_id: str):
    try:
        return commissioning.get(run_id)
    except KeyError as exc:
        raise HTTPException(404, str(exc)) from exc


@router.post("/commissioning/runs/{run_id}/tests/{test_id}")
def commissioning_test(run_id: str, test_id: str, req: ValidationTestRequest):
    try:
        return commissioning.start_test(run_id, test_id, req)
    except KeyError as exc:
        raise HTTPException(404, str(exc)) from exc
    except (ValueError, RuntimeError) as exc:
        raise HTTPException(409, str(exc)) from exc


@router.post("/commissioning/runs/{run_id}/manual-stop")
def commissioning_manual_stop(run_id: str):
    try:
        return commissioning.stop_manual(run_id)
    except (ValueError, RuntimeError, KeyError) as exc:
        raise HTTPException(409, str(exc)) from exc


@router.post("/commissioning/runs/{run_id}/review")
def commissioning_review(run_id: str, req: ValidationReviewRequest):
    try:
        return commissioning.review_recording(run_id, req)
    except (ValueError, RuntimeError, KeyError) as exc:
        raise HTTPException(409, str(exc)) from exc


@router.post("/commissioning/runs/{run_id}/complete")
def commissioning_complete(run_id: str):
    try:
        return commissioning.complete(run_id)
    except (ValueError, RuntimeError, KeyError) as exc:
        raise HTTPException(409, str(exc)) from exc


@router.get("/commissioning/profiles/{profile_id}")
def commissioning_profile(profile_id: str, version: int | None = None):
    try:
        return commissioning.profile_validation(profile_id, version)
    except KeyError as exc:
        raise HTTPException(404, str(exc)) from exc


@router.get("/commissioning/runs/{run_id}/evidence/{name}")
def commissioning_evidence(run_id: str, name: str):
    try:
        return FileResponse(commissioning.evidence_path(run_id, name), filename=name)
    except (KeyError, FileNotFoundError) as exc:
        raise HTTPException(404, "Validation evidence not found") from exc


@router.get("/devices")
def devices(include_non_usb: bool = False):
    return scan_serial_devices(include_non_usb=include_non_usb)


@router.get("/status")
def status():
    return service.board_status()


@router.post("/connect")
def connect(req: ConnectRequest):
    try:
        return service.connect_verified(req)
    except RuntimeError as exc:
        raise HTTPException(409, str(exc)) from exc


@router.post("/disconnect")
def disconnect():
    return service.disconnect()


@router.post("/reconnect")
def reconnect():
    try:
        return service.reconnect()
    except RuntimeError as exc:
        raise HTTPException(409, str(exc)) from exc


@router.get("/serial-diagnostics")
def serial_diagnostics():
    return service.serial_diagnostics()


@router.post("/board-test")
def board_test():
    return service.board_test()


@router.get("/firmware/status")
def firmware_status(port: str = ""):
    device = next(
        (
            item
            for item in scan_serial_devices()
            if item["port"].casefold() == port.casefold()
        ),
        None,
    )
    return service.firmware.status(device)


@router.get("/firmware/releases")
def firmware_releases():
    return service.firmware.releases()


@router.post("/firmware/flash")
def firmware_flash():
    raise HTTPException(
        409,
        "FLASH DISABLED: no supported board family and trusted firmware artifact are configured.",
    )


@router.get("/rehab-modules")
def modules():
    return [
        {**x.as_dict(), "emg_stats": service.stats(x.slug)}
        for x in service.registry.modules
    ]


@router.get("/rehab/{slug}/stats")
def stats(slug: str):
    try:
        return service.stats(slug)
    except ValueError as exc:
        raise HTTPException(404, str(exc)) from exc


@router.get("/rehab/{slug}/recordings")
def recordings(
    slug: str,
    label: str = "",
    mock: str = "",
    hardware_profile_id: str = "",
    hardware_version: int | None = None,
    channel_count: int | None = None,
    processing_version: str = "",
    quality_profile_id: str = "",
    study_id: str = "",
    collection_id: str = "",
    protocol_id: str = "",
    trial_id: str = "",
):
    try:
        return service.list(
            slug,
            label,
            mock,
            hardware_profile_id,
            hardware_version,
            channel_count,
            processing_version,
            quality_profile_id,
            study_id,
            collection_id,
            protocol_id,
            trial_id,
        )
    except ValueError as exc:
        raise HTTPException(404, str(exc)) from exc


@router.post("/recordings/start")
def start(req: RecordingRequest):
    try:
        return service.start_recording(req)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(409, str(exc)) from exc


@router.get("/recordings/status")
def recording_status():
    return service.recording_status()


@router.post("/recordings/cancel")
def cancel():
    return service.cancel()


@router.post("/recordings/stop")
def stop_recording():
    try:
        return service.stop_recording()
    except RuntimeError as exc:
        raise HTTPException(409, str(exc)) from exc


@router.post("/recordings/markers")
def recording_marker(req: RecordingMarkerRequest):
    try:
        return service.add_recording_marker(req.event_type, req.notes)
    except RuntimeError as exc:
        raise HTTPException(409, str(exc)) from exc


@router.post("/recordings/{rid}/save")
def save(rid: str):
    try:
        local = service.get(rid) or service.save(rid)
        return persist_saved_recording(rid, local)
    except SupabaseVaultError as exc:
        raise HTTPException(503, "EMG recording is preserved locally but durable cloud storage failed") from exc
    except (RuntimeError, ValueError) as exc:
        raise HTTPException(409, str(exc)) from exc


@router.post("/recordings/{rid}/sync")
def retry_cloud_sync(rid: str):
    item = service.get(rid)
    if not item:
        raise HTTPException(404, "EMG recording not found")
    try:
        return persist_saved_recording(rid, item)
    except SupabaseVaultError as exc:
        raise HTTPException(503, "EMG recording remains local; durable cloud storage retry failed") from exc


@router.delete("/recordings/{rid}/review")
def discard(rid: str):
    try:
        return service.discard(rid)
    except RuntimeError as exc:
        raise HTTPException(409, str(exc)) from exc


@router.get("/recordings/{rid}")
def detail(rid: str):
    x = service.get(rid)
    if not x:
        raise HTTPException(404, "EMG recording not found")
    return x


@router.get("/recordings/{rid}/files/{name}")
def artifact(rid: str, name: str):
    try:
        return FileResponse(service.file(rid, name), filename=name)
    except FileNotFoundError as exc:
        raise HTTPException(404, "File not found") from exc


@router.get("/recordings/{rid}/waveform")
def waveform(rid: str, max_points: int = 2000):
    x = service.get(rid)
    if not x:
        raise HTTPException(404, "EMG recording not found")
    import csv

    with service.file(rid, "emg_raw.csv").open(encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    stride = max(1, len(rows) // max(1, min(max_points, 5000)))
    return {
        "recording_id": rid,
        "raw_units": "ADC_COUNTS",
        "samples": rows[::stride][:5000],
    }


@router.get("/processing/config")
def processing_config():
    return service.processing_config()


@router.put("/processing/config")
def processing_update(config: EmgProcessingConfig):
    return service.apply_processing_config(config)


@router.post("/processing/reset")
def processing_reset():
    return service.reset_processing()


@router.put("/processing/display")
def processing_display(signals: list[str]):
    try:
        return service.select_display_signals(signals)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc


@router.get("/signal-quality")
def signal_quality():
    return service.signal_quality_report()


@router.post("/baseline/start")
def baseline_start(req: BaselineRequest):
    try:
        return service.start_baseline(req)
    except (RuntimeError, ValueError) as exc:
        raise HTTPException(409, str(exc)) from exc


@router.post("/baseline/stop")
def baseline_stop():
    return service.baseline_status()


@router.get("/baseline/status")
def baseline_status():
    return service.baseline_status()


@router.get("/baselines")
def baselines():
    return service.list_baselines()


@router.get("/baselines/{bid}")
def baseline(bid: str):
    value = service.get_baseline(bid)
    if not value:
        raise HTTPException(404, "Baseline not found")
    return value


@router.post("/recordings/{rid}/reprocess")
def reprocess(
    rid: str, config: EmgProcessingConfig, preferred_for_review: bool = False
):
    try:
        return service.reprocess(rid, config, preferred_for_review)
    except FileNotFoundError as exc:
        raise HTTPException(404, "EMG recording not found") from exc
    except RuntimeError as exc:
        raise HTTPException(409, str(exc)) from exc


@router.get("/recordings/{rid}/processing-runs")
def processing_runs(rid: str):
    return service.processing_runs(rid)


@router.get("/recordings/{rid}/processing-runs/{proc_id}/waveform")
def processing_waveform(rid: str, proc_id: str, max_points: int = 2000):
    value = service.processing_waveform(rid, proc_id, max_points)
    if not value:
        raise HTTPException(404, "Processing run not found")
    return value


@router.get("/recordings/{rid}/signal-quality")
def recording_signal_quality(rid: str):
    runs = service.processing_runs(rid)
    if not runs:
        return {
            "status": "NOT_YET_GENERATED",
            "message": "RAW RECORDING — Processing not yet generated",
        }
    return runs[0]


@router.get("/hardware-profiles")
def hardware_profiles(include_archived: bool = False):
    return service.hardware_profiles(include_archived)


@router.post("/hardware-profiles")
def hardware_profile_create(req: HardwareProfileRequest):
    try:
        return service.create_hardware_profile(req.model_dump())
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from exc


@router.get("/hardware-profiles/{profile_id}")
def hardware_profile(profile_id: str):
    value = service.hardware_profile(profile_id)
    if not value:
        raise HTTPException(404, "Hardware profile not found")
    return value


@router.post("/hardware-profiles/{profile_id}/versions")
def hardware_profile_version(profile_id: str, req: HardwareProfileRequest):
    try:
        return service.version_hardware_profile(profile_id, req.model_dump())
    except KeyError as exc:
        raise HTTPException(404, "Hardware profile not found") from exc


@router.post("/hardware-profiles/{profile_id}/archive")
def hardware_profile_archive(profile_id: str):
    try:
        return service.archive_hardware_profile(profile_id)
    except KeyError as exc:
        raise HTTPException(404, "Hardware profile not found") from exc


@router.get("/hardware-profiles/{profile_id}/validations")
def validation_history(profile_id: str):
    return service.hardware_history(profile_id)


@router.get("/hardware-profiles/{profile_id}/validations/{run_id}/download")
def validation_download(profile_id: str, run_id: str):
    try:
        return FileResponse(
            service.hardware.validation_report_path(profile_id, run_id),
            filename="hardware_validation_report.json",
        )
    except FileNotFoundError as exc:
        raise HTTPException(404, "Validation report not found") from exc


@router.post("/quality-profiles")
def quality_profile(req: QualityProfileRequest):
    return service.create_quality_profile(req.model_dump())


@router.post("/validation/timing")
def validate_timing(req: ValidationRequest):
    try:
        return service.validate_timing(req.hardware_profile_id)
    except KeyError as exc:
        raise HTTPException(404, "Hardware profile not found") from exc


@router.post("/validation/adc")
def validate_adc(req: ValidationRequest):
    try:
        return service.validate_adc(req.hardware_profile_id)
    except KeyError as exc:
        raise HTTPException(404, "Hardware profile not found") from exc


@router.post("/validation/channels")
def validate_channels(req: ValidationRequest):
    try:
        return service.validate_channels(req.hardware_profile_id)
    except KeyError as exc:
        raise HTTPException(404, "Hardware profile not found") from exc


@router.post("/validation/powerline")
def validate_powerline(req: ValidationRequest):
    try:
        return service.validate_powerline(req.hardware_profile_id)
    except KeyError as exc:
        raise HTTPException(404, "Hardware profile not found") from exc


@router.post("/validation/filter-response")
def validate_filter(req: ValidationRequest):
    try:
        return service.validate_filter(req.hardware_profile_id)
    except KeyError as exc:
        raise HTTPException(404, "Hardware profile not found") from exc


@router.get("/validation/host-latency")
def validate_latency():
    return service.validate_latency()


@router.post("/validation/quick-check")
def validate_quick(req: ValidationRequest):
    try:
        return service.quick_signal_check(req.hardware_profile_id)
    except KeyError as exc:
        raise HTTPException(404, "Hardware profile not found") from exc


@router.post("/validation/baseline-repeatability")
def validate_baseline(req: BaselineRepeatabilityRequest):
    try:
        return service.baseline_repeatability_report(
            req.hardware_profile_id, req.baseline_ids
        )
    except KeyError as exc:
        raise HTTPException(404, "Hardware profile or baseline not found") from exc


@router.post("/validation/report")
def validation_report(req: ValidationRequest):
    try:
        return service.generate_hardware_report(req.hardware_profile_id, req.notes)
    except KeyError as exc:
        raise HTTPException(404, "Hardware profile not found") from exc


@router.post("/recordings/{rid}/hardware-profile/{profile_id}")
def assign_hardware(rid: str, profile_id: str):
    try:
        return service.assign_hardware_profile(rid, profile_id)
    except (KeyError, FileNotFoundError) as exc:
        raise HTTPException(404, "Recording or profile not found") from exc


@router.post("/ws-ticket")
def ticket():
    return {"ticket": service.issue_ticket(), "expires_seconds": 60}


@ws_router.websocket("/ws/emg")
async def emg_socket(ws: WebSocket, ticket: str = ""):
    if not service.consume_ticket(ticket):
        await ws.close(code=4403)
        return
    await ws.accept()
    after = 0
    try:
        while True:
            batch = service.batch(after)
            after = batch["latest_sequence_id"]
            if batch["samples"]:
                await ws.send_json(batch)
            await ws.send_json(service.board_status())
            await asyncio.sleep(0.04)
    except (WebSocketDisconnect, RuntimeError):
        pass
