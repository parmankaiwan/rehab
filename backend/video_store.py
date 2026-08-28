from __future__ import annotations

import threading
import time
from collections import deque
from dataclasses import dataclass
from typing import Optional


@dataclass(frozen=True)
class FramePacket:
    jpeg: bytes
    sequence: int
    source_timestamp: Optional[float]
    annotated_timestamp: Optional[float]
    received_monotonic: float
    jpeg_encode_ms: Optional[float]
    capture_timestamp_ns: Optional[int] = None


class FrameSubscription:
    def __init__(self, maximum: int):
        self.queue: deque[FramePacket] = deque(maxlen=maximum)
        self.dropped = 0
        self.lock = threading.Lock()
    def push(self, packet: FramePacket) -> None:
        with self.lock:
            if len(self.queue) == self.queue.maxlen: self.dropped += 1
            self.queue.append(packet)
    def drain(self) -> list[FramePacket]:
        with self.lock:
            items=list(self.queue);self.queue.clear();return items


class LatestVideoFrameStore:
    """Latest frame for live delivery plus opt-in bounded ordered recording subscriptions."""
    def __init__(self) -> None:
        self._lock=threading.Lock();self._packet=None;self._sequence=0;self._receive_fps=None;self._last_receive=None;self._subscriptions:set[FrameSubscription]=set();self.webrtc_clients=0
    def update(self,jpeg:bytes,*,sequence:Optional[int]=None,source_timestamp:Optional[float]=None,annotated_timestamp:Optional[float]=None,jpeg_encode_ms:Optional[float]=None,capture_timestamp_ns:Optional[int]=None)->FramePacket:
        now=time.monotonic()
        with self._lock:
            self._sequence=max(self._sequence+1,sequence or 0)
            if self._last_receive is not None and now>self._last_receive:
                instant=1/(now-self._last_receive);self._receive_fps=instant if self._receive_fps is None else .2*instant+.8*self._receive_fps
            self._last_receive=now;packet=FramePacket(bytes(jpeg),self._sequence,source_timestamp,annotated_timestamp,now,jpeg_encode_ms,capture_timestamp_ns);self._packet=packet;subscribers=tuple(self._subscriptions)
        for subscriber in subscribers: subscriber.push(packet)
        return packet
    def latest(self)->Optional[FramePacket]:
        with self._lock:return self._packet
    def subscribe(self,maximum:int=180)->FrameSubscription:
        subscription=FrameSubscription(maximum)
        with self._lock:self._subscriptions.add(subscription)
        return subscription
    def unsubscribe(self,subscription:FrameSubscription)->None:
        with self._lock:self._subscriptions.discard(subscription)
    def is_fresh(self,stale_after:float=2.5)->bool:
        packet=self.latest();return packet is not None and time.monotonic()-packet.received_monotonic<=stale_after
    def metrics(self)->dict:
        packet=self.latest()
        return {"transport":"WEBRTC","frame_sequence":packet.sequence if packet else None,"backend_frame_age_ms":(time.monotonic()-packet.received_monotonic)*1000 if packet else None,"source_frame_age_ms":(time.time()-packet.source_timestamp)*1000 if packet and packet.source_timestamp else None,"jpeg_encode_ms":packet.jpeg_encode_ms if packet else None,"frame_receive_fps":self._receive_fps,"webrtc_clients":self.webrtc_clients,"effective_queue_depth":1 if packet else 0,"recording_subscribers":len(self._subscriptions)}


video_store=LatestVideoFrameStore()
raw_video_store=LatestVideoFrameStore()