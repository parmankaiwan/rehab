# FlexMap Posture Web Dashboard

FlexMap presents the existing Python posture classifier as a calm, patient-friendly web interface.

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

Live View displays current sensor data only. Opening a Live page does not create a research session, label, recording row, manifest, video, baseline, or Dataset artifact. CV Live does not open a camera or create a pose engine; `CV part/main.py` remains the only camera and MediaPipe owner. EMG Live does not open a serial port itself; the integrated backend EMG service remains the only acquisition owner.

Data Collection is separate. The CV Data and EMG Data routes require explicit research metadata and an explicit recording action before saving Dataset artifacts.

## Supabase Dataset Vault mirror

The canonical local SQLite database and recording folders remain the acquisition source of truth. An optional server-only Supabase mirror can copy both CV and EMG metadata into Postgres and, when explicitly enabled, copy recording artifacts into a private Storage bucket. A network failure never removes the local recording.

1. Create a Supabase project and run [`supabase/migrations/202610150001_flexmap_dataset_vault.sql`](supabase/migrations/202610150001_flexmap_dataset_vault.sql) once in its SQL editor.
2. Copy `.env.example` to `.env` and set `FLEXMAP_SUPABASE_URL` plus a backend-only `FLEXMAP_SUPABASE_SECRET_KEY` (`sb_secret_...`).
3. Set `FLEXMAP_SUPABASE_SYNC_ENABLED=true`, restart the Python backend, open **Master → Dataset Vault**, and select **Sync vault**.
4. Leave `FLEXMAP_SUPABASE_UPLOAD_ARTIFACTS=false` until private Storage capacity, consent, retention, and regional research-data requirements have been confirmed. When enabled, artifacts are uploaded to the private `flexmap-dataset` bucket.

Never put the Supabase secret key in a `NEXT_PUBLIC_*` variable, browser code, Git, or Cloudflare Pages frontend settings. The Master backend is the only component allowed to use it. The SQL migration enables RLS, removes `anon` and `authenticated` table access, and keeps the Storage bucket private.

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
