"""RTSP frame producer using PyAV.

We use PyAV (libav bindings) rather than OpenCV's VideoCapture because:
  - PyAV honors `rtsp_transport=tcp` reliably.
  - It exposes timestamps + lets us drop late frames at the decode boundary
    rather than queueing them.
"""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass
from typing import Optional

import av
import numpy as np
import structlog

log = structlog.get_logger(__name__)


@dataclass
class Frame:
    image: np.ndarray   # HxWx3 uint8 BGR
    pts: float          # presentation timestamp (seconds, monotonic-ish)
    frame_idx: int      # monotonically increasing per source


class RtspSource:
    """Background thread that reads frames and keeps only the latest.

    Consumer calls `latest()` — non-blocking; returns the most recent frame or
    None if no fresh frame is available since last call.
    """

    def __init__(
        self,
        camera_id: str,
        url: str,
        transport: str = "tcp",
        target_fps: int = 15,
    ) -> None:
        self.camera_id = camera_id
        self.url = url
        self.transport = transport
        self.target_period = 1.0 / max(1, target_fps)

        self._latest: Optional[Frame] = None
        self._latest_lock = threading.Lock()
        self._consumed = True
        self._stop = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self._frame_idx = 0
        self._last_yield_t = 0.0

        # Stats
        self.connected = False
        self.last_error: str | None = None
        self.fps_in = 0.0
        self._fps_window: list[float] = []

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(
            target=self._run, name=f"rtsp-{self.camera_id}", daemon=True
        )
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=5)

    def latest(self) -> Optional[Frame]:
        with self._latest_lock:
            if self._consumed or self._latest is None:
                return None
            self._consumed = True
            return self._latest

    def _publish(self, frame: Frame) -> None:
        with self._latest_lock:
            self._latest = frame
            self._consumed = False

    def _record_fps(self, now: float) -> None:
        self._fps_window.append(now)
        cutoff = now - 2.0
        while self._fps_window and self._fps_window[0] < cutoff:
            self._fps_window.pop(0)
        if len(self._fps_window) > 1:
            span = self._fps_window[-1] - self._fps_window[0]
            self.fps_in = (len(self._fps_window) - 1) / span if span > 0 else 0.0

    def _run(self) -> None:
        backoff = 1.0
        while not self._stop.is_set():
            try:
                self._connect_and_stream()
                backoff = 1.0
            except Exception as e:
                self.connected = False
                self.last_error = str(e)
                log.warning(
                    "rtsp.error",
                    camera_id=self.camera_id,
                    error=str(e),
                    backoff=backoff,
                )
                self._stop.wait(timeout=backoff)
                backoff = min(backoff * 2, 30.0)

    def _connect_and_stream(self) -> None:
        options = {
            "rtsp_transport": self.transport,
            "stimeout": "5000000",       # microseconds — socket timeout
            "max_delay": "500000",       # 500ms max demux delay
            "fflags": "nobuffer",
            "flags": "low_delay",
            "buffer_size": "1024000",
        }
        log.info("rtsp.connecting", camera_id=self.camera_id, url=self._redact(self.url))
        container = av.open(self.url, options=options, timeout=10)
        try:
            stream = container.streams.video[0]
            stream.thread_type = "AUTO"
            self.connected = True
            self.last_error = None
            log.info("rtsp.connected", camera_id=self.camera_id)

            for packet in container.demux(stream):
                if self._stop.is_set():
                    return
                for frame in packet.decode():
                    if self._stop.is_set():
                        return
                    now = time.monotonic()
                    # Drop frames to honor target FPS.
                    if now - self._last_yield_t < self.target_period:
                        continue
                    self._last_yield_t = now

                    img = frame.to_ndarray(format="bgr24")
                    self._frame_idx += 1
                    self._publish(
                        Frame(image=img, pts=now, frame_idx=self._frame_idx)
                    )
                    self._record_fps(now)
        finally:
            container.close()
            self.connected = False

    @staticmethod
    def _redact(url: str) -> str:
        # rtsp://user:pass@host/... -> rtsp://***@host/...
        try:
            scheme, rest = url.split("://", 1)
            if "@" in rest:
                _, host = rest.split("@", 1)
                return f"{scheme}://***@{host}"
        except ValueError:
            pass
        return url
