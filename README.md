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