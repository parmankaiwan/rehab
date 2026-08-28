from __future__ import annotations

import asyncio
from typing import Any

import cv2
import numpy as np
from aiortc import RTCPeerConnection, RTCRtpSender, RTCSessionDescription, VideoStreamTrack
from aiortc.mediastreams import MediaStreamError
from av import VideoFrame
from pydantic import BaseModel

from .video_store import video_store


class RTCOffer(BaseModel):
    sdp: str
    type: str


class RTCAnswer(BaseModel):
    sdp: str
    type: str


class LatestFrameVideoTrack(VideoStreamTrack):
    """WebRTC source with an effective queue depth of exactly one."""

    def __init__(self) -> None:
        super().__init__()
        self._last_sequence = -1

    async def recv(self) -> VideoFrame:
        pts, time_base = await self.next_timestamp()
        packet = video_store.latest()
        deadline = asyncio.get_running_loop().time() + 2.5
        while packet is not None and packet.sequence == self._last_sequence:
            if asyncio.get_running_loop().time() >= deadline or not video_store.is_fresh():
                raise MediaStreamError
            await asyncio.sleep(1 / 120)
            packet = video_store.latest()
        if packet is None or not video_store.is_fresh():
            raise MediaStreamError
        image = cv2.imdecode(np.frombuffer(packet.jpeg, dtype=np.uint8), cv2.IMREAD_COLOR)
        if image is None:
            raise MediaStreamError
        self._last_sequence = packet.sequence
        frame = VideoFrame.from_ndarray(image, format="bgr24")
        frame.pts = pts
        frame.time_base = time_base
        return frame


peer_connections: set[RTCPeerConnection] = set()


async def answer_offer(offer: RTCOffer) -> RTCAnswer:
    pc = RTCPeerConnection()
    peer_connections.add(pc)
    track = LatestFrameVideoTrack()
    pc.addTrack(track)

    transceiver = pc.getTransceivers()[0]
    codecs = RTCRtpSender.getCapabilities("video").codecs
    preferred = [codec for codec in codecs if codec.mimeType.lower() in ("video/h264", "video/vp8")]
    if preferred:
        transceiver.setCodecPreferences(preferred)

    @pc.on("connectionstatechange")
    async def on_connectionstatechange() -> None:
        video_store.webrtc_clients = sum(item.connectionState == "connected" for item in peer_connections)
        if pc.connectionState in ("failed", "closed", "disconnected"):
            await pc.close()
            peer_connections.discard(pc)
            video_store.webrtc_clients = sum(item.connectionState == "connected" for item in peer_connections)

    await pc.setRemoteDescription(RTCSessionDescription(sdp=offer.sdp, type=offer.type))
    answer = await pc.createAnswer()
    await pc.setLocalDescription(answer)
    return RTCAnswer(sdp=pc.localDescription.sdp, type=pc.localDescription.type)


async def close_peers() -> None:
    await asyncio.gather(*(pc.close() for pc in tuple(peer_connections)), return_exceptions=True)
    peer_connections.clear()
    video_store.webrtc_clients = 0
