# FlexMap Posture Web Dashboard

FlexMap presents the existing Python posture classifier as a calm, patient-friendly web interface.

The Master console includes an EMG mathematical comparison workspace at `/master/ml/emg-comparison`. See [docs/EMG_MATHEMATICAL_COMPARISON.md](docs/EMG_MATHEMATICAL_COMPARISON.md) for equations, hardware eligibility, model limitations, persistence, and exports.

```text
CameraManager -> PoseTracker -> PostureAnalyzer/PostureClassifier
                                      |
                               PostureSnapshot
                                      |
                          FastAPI + WebSocket/MJPEG
                                      |
                                Next.js website
```

Python remains the source of truth for tracking, measurements, four-state component classification, overall state, feedback, confidence, and readiness. The browser only validates the transport shape and renders it. In particular, the browser never assumes all components are green when the overall state is green.

## Run the bridge

From this directory:

```powershell
py -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
python -m backend.app
```

The service runs at `http://localhost:8000`. It provides:

- `GET /health`
- `GET /api/status`
- `POST /api/reset`
- `WS /ws/posture`
- `GET /video-feed` (returns 503 until an annotated frame is supplied)

`backend.posture_stream.PostureStateStore` is the thread-safe integration boundary. The running CV application should call `store.update(snapshot_from_posture_data(posture_data))` in the same process, or publish the matching `PostureSnapshot` contract to the bridge from its existing loop. It must pass the already annotated JPEG to `store.update_frame()` if camera streaming is desired. Neither path opens another camera or model.

## Run the website

```powershell
cd web
Copy-Item .env.local.example .env.local
npm install
npm run dev
```

Open <http://localhost:3000>.

## Integrated Windows application lifecycle

For normal local use, double-click `START FLEXMAP.cmd` instead of opening three
terminals. The launcher starts FastAPI, waits for `/health`, starts Next.js and
waits for its identity endpoint, then starts the existing hardware agent. The
agent remains the sole owner of the Python camera process and EMG serial reader.
It performs live monitoring only; it never starts or saves a research recording.

Run `install-flexmap-autostart.ps1` once to create a **START FLEXMAP** desktop
shortcut. The installer removes the obsolete independent hardware-agent logon
task because it could compete for the camera or serial port. It does not create
a new automatic-logon task.

Open **Master → System Diagnostics** to see verified application, camera, EMG,
and Supabase states. That page offers bounded CV/EMG reconnect actions and an
explicit **Exit FlexMap** button. Exit first cancels active acquisition, records
an `INTERRUPTED` local lifecycle event without marking the trial saved, releases
the serial port and camera, then stops only the child PIDs created by that
launcher. Closing or refreshing a browser tab does not stop shared services.

The supervisor binds its control interface to `127.0.0.1`, uses a per-session
random token, and exposes it only through Master-authenticated FastAPI routes.
Those routes are disabled unless FastAPI was launched with
`FLEXMAP_LOCAL_LIFECYCLE_ENABLED=true`; Render cannot invoke local shutdown.
If ports 3000 or 8000 belong to an unrelated program, startup stops with an
error and does not terminate that program. Runtime state and logs are under
ignored `data/runtime/`.

Browser MediaPipe remains an explicitly selected, page-scoped camera source.
The automatic application-wide source is the existing Python CV engine. Do not
enable both sources for the same physical camera at the same time; use the
source selector to hand ownership over after the previous source releases it.

To work without a camera, set `NEXT_PUBLIC_USE_MOCK_POSTURE=true` in `web/.env.local`, restart Next.js, and use the clearly labelled GREEN/ORANGE/RED/GREY controls. Mock mode never identifies its data as live.

## Tests

```powershell
pytest
cd web
npm test
```

## Configuration

Frontend URLs and stale timing are documented in `web/.env.local.example`. The backend allows only `http://localhost:3000` by default; set `FLEXMAP_CORS_ORIGINS` to a comma-separated allowlist when deploying. `FLEXMAP_WS_HZ` controls status broadcasts and is capped at 20 Hz.

FlexMap is an engineering rehabilitation research prototype. Its thresholds are configurable engineering criteria, not clinically validated diagnostic thresholds. The interface does not diagnose posture or health conditions.


## Existing CV integration

The live runtime is the existing `C:\Users\Parman\Desktop\rehab\CV part\main.py`. Its only integration change is a call to `integration.cv_web_bridge.CVWebBridge` after the existing skeleton, hand joints, posture panel, and text have been drawn. The adapter never opens a camera or creates a MediaPipe model.

The adapter keeps only the newest `PostureData` and annotated frame. A background thread serializes the existing component states, feedback, READY flag, tracking quality, measurements, and overall state, encodes the latest frame as JPEG, and posts them to the existing backend ingestion routes. Backend outages are reported periodically but never stop the CV loop.

Transport settings are optional environment variables:

```powershell
$env:FLEXMAP_WEB_BACKEND="http://localhost:8000"
$env:FLEXMAP_POSTURE_PUBLISH_HZ="15"
$env:FLEXMAP_VIDEO_PUBLISH_HZ="15"
$env:FLEXMAP_VIDEO_JPEG_QUALITY="80"
```

### Exact startup order

Terminal 1:

```powershell
cd "C:\Users\Parman\Desktop\rehab\Software part"
python -m backend.app
```

Terminal 2:

```powershell
cd "C:\Users\Parman\Desktop\rehab\CV part"
.\.venv\Scripts\Activate.ps1
python main.py
```

Terminal 3:

```powershell
cd "C:\Users\Parman\Desktop\rehab\Software part\web"
npm run dev
```

Open <http://localhost:3000>. The Reset button is delivered back to the existing `PostureAnalyzer.reset()` path without restarting the camera or MediaPipe.

## Low-latency WebRTC video

WebRTC is the default browser video transport. Posture JSON remains on `/ws/posture`; video signaling uses `POST /api/webrtc/offer`. The browser attaches the resulting media track directly to a native `<video autoplay playsInline muted>` element.

The CV-to-backend boundary uses one persistent localhost HTTP connection and a latest-frame-only buffer. This reduced measured source-frame age from roughly 1.2 seconds to approximately 30-80 ms and increased measured backend frame delivery from roughly 1.2 FPS to approximately 21-22 FPS on the current running system. JPEG encoding measured below 3 ms.

To select transport before starting Next.js:

```powershell
# Preferred low-latency mode
$env:NEXT_PUBLIC_VIDEO_TRANSPORT="WEBRTC"

# Diagnostic fallback
$env:NEXT_PUBLIC_VIDEO_TRANSPORT="MJPEG"
```

Research Mode also provides live WebRTC/MJPEG buttons plus CV FPS, estimated pose/hand rates, frame receive FPS, JPEG encode time, source/backend/data age, frame sequence, peer count, and effective queue depth. The effective video queue depth is never greater than one.

## Master Live Sensors

Authenticated Master Mode provides non-recording viewers at:

- `/master/live` - sensor overview
- `/master/live/cv` - existing CV camera, posture telemetry, Ready state, and measurements
- `/master/live/emg` - existing EMG acquisition source, bounded waveform, processing representations, and signal freshness

Live View displays current sensor data only. Opening a Live page does not create a research session, label, recording row, manifest, video, baseline, or Dataset artifact. Master CV Live has two explicit sources: **Browser MediaPipe** owns the selected browser camera and runs the pinned browser model, while **FlexMap Engine** displays the established `CV part/main.py` stream. These outputs are not equivalent or automatically synchronized. EMG Live does not open a serial port itself; the integrated backend EMG service remains the only acquisition owner.

Data Collection is separate. The CV Data and EMG Data routes require explicit research metadata and an explicit recording action before saving Dataset artifacts.

## Dataset storage modes and Supabase

`FLEXMAP_DATA_BACKEND=local|supabase` explicitly selects the authority. Local mode keeps SQLite and recording folders authoritative and can use the older controlled mirror. Supabase mode makes Postgres and the private Storage bucket authoritative for hosted browser collection data; it never silently falls back to Render's disk. Keep `FLEXMAP_SUPABASE_SYNC_ENABLED=false` in Supabase mode to prevent dual writers.

1. Create one Supabase project and run migrations `202610150001`, `202610160001`, and `202610170001` in order. The last migration creates independent private CV and EMG vault storage while preserving existing data.
2. Copy `.env.example` to `.env` and set `FLEXMAP_SUPABASE_URL` plus a backend-only `FLEXMAP_SUPABASE_SECRET_KEY` (`sb_secret_...`).
3. Set `FLEXMAP_SUPABASE_SYNC_ENABLED=true`, restart the Python backend, open **Master → Dataset Vault**, and select **Sync vault**.
4. Leave `FLEXMAP_SUPABASE_UPLOAD_ARTIFACTS=false` until private Storage capacity, consent, retention, and regional research-data requirements have been confirmed. When enabled, artifacts are uploaded to the private `flexmap-dataset` bucket.

Those four steps describe the optional mirror in **local** mode. For authoritative hosted storage, apply all three versioned migrations and follow [Supabase setup](SUPABASE_SETUP.md). The authoritative buckets are `flexmap-cv-vault` and `flexmap-emg-vault`; the legacy bucket is retained for compatibility. For governed existing-data transfer, use the dry-run/checkpoint workflow in [local-to-Supabase migration](LOCAL_TO_SUPABASE_MIGRATION.md).

Never put the Supabase secret key in a `NEXT_PUBLIC_*` variable, browser code, Git, or Cloudflare Pages frontend settings. The Master backend is the only component allowed to use it. The SQL migration enables RLS, removes `anon` and `authenticated` table access, and keeps the Storage bucket private.

### Browser CV Collection Studio

`/master/cv-data` creates durable browser dataset and posture-label records without editing repository JSON. `/master/cv-data/studio?dataset=DS-...` uses the existing `useBrowserPose` stream for both the preview and capture: a still is inferred from the same frozen clean frame, and video uses `MediaRecorder` on that same stream without microphone audio. Pose callback timestamps are associated to video playback approximately; they are not encoded-frame IDs. Browser classifier output remains separate from the research label and technical quality.

Browser datasets, labels, samples, review metadata, and private artifacts are written directly by the authenticated API to Supabase. They do not depend on Render's ephemeral disk or the legacy SQLite mirror. Samples move through `DRAFT → UPLOADING → VERIFYING → STORED`; only verified stored samples appear in counts and playback. If credentials or migrations are missing, the Studio blocks cloud save and reports the storage state.

New browser samples use source `BROWSER_MEDIAPIPE`, begin as `REVIEW_REQUIRED`, and are not training eligible. Existing Python-engine recordings retain their original source, recorder, local-first storage, and playback paths.

## Render deployment

The repository includes a `render.yaml` Blueprint for two free-tier services:

- `flexmap-rehab-web-parmankaiwan`: the Next.js website
- `flexmap-rehab-api-parmankaiwan`: the FastAPI, WebSocket, and MJPEG API

Create a Render Blueprint from this repository and enter `MASTER_PASSWORD` when
Render requests it. Render generates the session, master-service, and CV-engine
tokens; they are not stored in Git.

The Next.js service reaches the API over its public HTTPS endpoint. Render's
free web services cannot receive private-network traffic, so replacing
`FLEXMAP_BACKEND_URL` with an internal hostname will make Master API requests
return 502 responses.

Camera and EMG hardware remain attached to the local acquisition computer. To
send the existing CV output to Render, copy the generated `FLEXMAP_ENGINE_TOKEN`
from the API service into the local CV process and start the existing engine:

```powershell
$env:FLEXMAP_WEB_BACKEND="https://flexmap-rehab-api-parmankaiwan.onrender.com"
$env:FLEXMAP_ENGINE_TOKEN="paste-the-render-api-token-here"
cd "C:\Users\Parman\Desktop\rehab\CV part"
.\.venv\Scripts\Activate.ps1
python main.py
```

Do not put the engine token in a `NEXT_PUBLIC_*` variable. The Render free tier
has an ephemeral filesystem and can sleep while idle. Configure the private
Supabase vault mirror before using the deployed system for persistent research
records; until then, treat the Render deployment as a live/demo environment and
do not collect patient recordings into it.

### Automatic local CV and EMG

The hosted website cannot open Windows cameras or COM ports directly. The local
hardware agent keeps those devices connected so the CV and EMG Live sections
work as soon as they are opened.

1. Copy `.env.agent.example` to `.env.agent`.
2. In Render, open the API service's **Environment** page, copy
   `FLEXMAP_ENGINE_TOKEN`, and place it in `.env.agent`. This private file is
   ignored by Git.
3. Confirm the EMG port (normally `COM9`) and the one-channel settings.
4. Run `install-flexmap-autostart.ps1` once from PowerShell.

The installer creates a per-user Windows logon task and starts the agent
immediately. The agent launches the existing CV engine, automatically selects
the configured or first USB serial EMG device, reconnects after interruptions,
and publishes to the authenticated Render ingestion endpoints. It does not
start a recording or save a Dataset Vault entry.
