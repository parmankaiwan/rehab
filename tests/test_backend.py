import time

from fastapi.testclient import TestClient

from backend.app import app
from backend.posture_stream import store
from backend.video_store import LatestVideoFrameStore, video_store
from backend.schemas import PostureSnapshot, PostureState


client = TestClient(app)


def sample() -> PostureSnapshot:
    return PostureSnapshot(timestamp=time.perf_counter(), tracking_quality="GOOD", overall_state=PostureState.GREEN, ready=True, ready_progress=1, components={}, feedback=[])


def test_health_status_and_reset():
    assert client.get("/health").json() == {"status": "ok"}
    store.update(sample())
    assert client.get("/api/status").json()["cv_engine"] == "running"
    assert client.post("/api/reset").json() == {"success": True}


def test_snapshot_serialization():
    payload = sample().model_dump(mode="json")
    assert PostureSnapshot.model_validate(payload).overall_state == PostureState.GREEN


def test_websocket_connection():
    store.update(sample())
    with client.websocket_connect("/ws/posture") as socket:
        assert socket.receive_json()["overall_state"] == "GREEN"


def test_engine_snapshot_and_frame_ingestion():
    payload = sample().model_dump(mode="json")
    response = client.post("/api/engine/snapshot", json=payload)
    assert response.status_code == 200
    assert "reset_generation" in response.json()
    with client.websocket_connect("/ws/posture") as socket:
        assert socket.receive_json()["ready"] is True

    jpeg = bytes((255, 216)) + b"fake-jpeg-payload" + bytes((255, 217))
    response = client.post("/api/engine/frame", content=jpeg, headers={"content-type": "image/jpeg"})
    assert response.json() == {"success": True}
    assert video_store.latest().jpeg == jpeg


def test_mjpeg_serializes_latest_frame():
    import asyncio

    video_store.update(bytes((255, 216)) + b"fresh-frame" + bytes((255, 217)))

    async def first_chunk():
        stream = __import__("backend.posture_stream", fromlist=["mjpeg_frames"]).mjpeg_frames(interval=0)
        chunk = await anext(stream)
        await stream.aclose()
        return chunk

    assert b"Content-Type: image/jpeg" in asyncio.run(first_chunk())

def test_latest_video_buffer_replaces_old_frames():
    buffer = LatestVideoFrameStore()
    first = bytes((255, 216)) + b"first" + bytes((255, 217))
    newest = bytes((255, 216)) + b"newest" + bytes((255, 217))
    buffer.update(first, sequence=100)
    buffer.update(newest, sequence=103)
    packet = buffer.latest()
    assert packet is not None
    assert packet.sequence == 103
    assert packet.jpeg == newest
    assert buffer.metrics()["effective_queue_depth"] == 1


def test_webrtc_track_requests_newest_frame():
    import asyncio
    import cv2
    import numpy as np
    from backend.webrtc_video import LatestFrameVideoTrack

    ok, jpeg = cv2.imencode(".jpg", np.zeros((48, 64, 3), dtype=np.uint8))
    assert ok
    video_store.update(jpeg.tobytes(), sequence=201)
    video_store.update(jpeg.tobytes(), sequence=204)

    async def receive():
        track = LatestFrameVideoTrack()
        frame = await track.recv()
        return frame, track._last_sequence

    frame, sequence = asyncio.run(receive())
    assert frame.width == 64
    assert frame.height == 48
    assert sequence == 204

def test_webrtc_offer_delivers_video():
    import asyncio
    import cv2
    import numpy as np
    from aiortc import RTCPeerConnection, RTCSessionDescription
    from backend.webrtc_video import RTCOffer, answer_offer, close_peers

    async def exchange():
        ok, jpeg = cv2.imencode(".jpg", np.full((48, 64, 3), 127, dtype=np.uint8))
        assert ok
        video_store.update(jpeg.tobytes(), sequence=301)
        receiver = RTCPeerConnection(configuration=None)
        received_track = asyncio.get_running_loop().create_future()

        @receiver.on("track")
        def on_track(track):
            if not received_track.done():
                received_track.set_result(track)

        receiver.addTransceiver("video", direction="recvonly")
        offer = await receiver.createOffer()
        await receiver.setLocalDescription(offer)
        answer = await answer_offer(RTCOffer(sdp=receiver.localDescription.sdp, type=receiver.localDescription.type))
        await receiver.setRemoteDescription(RTCSessionDescription(sdp=answer.sdp, type=answer.type))
        async def publish_fresh_frames():
            for sequence in range(302, 402):
                video_store.update(jpeg.tobytes(), sequence=sequence)
                await asyncio.sleep(.03)
        producer = asyncio.create_task(publish_fresh_frames())
        track = await asyncio.wait_for(received_track, timeout=5)
        frame = await asyncio.wait_for(track.recv(), timeout=5)
        await producer
        await receiver.close()
        await close_peers()
        return frame

    frame = asyncio.run(exchange())
    assert frame.width == 64
    assert frame.height == 48