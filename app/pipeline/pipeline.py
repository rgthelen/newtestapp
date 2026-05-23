"""Per-camera pipeline: RTSP → YOLO → tracker → CLIP snapshot/embed → DB."""

from __future__ import annotations

import asyncio
import time
from collections import deque
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

import cv2
import numpy as np
import structlog

from ..config import AppConfig, CameraConfig
from ..storage.database import Database
from .clip_embedder import ClipImageEncoder, ClipTextEncoder
from .hailo_runtime import HailoVDevice
from .rtsp_source import Frame, RtspSource
from .tracker import Sort, Track
from .yolo_detector import Detection, YoloDetector

log = structlog.get_logger(__name__)


@dataclass
class PipelineSnapshot:
    """JSON-able snapshot of a camera's current state (live UI feed)."""

    camera_id: str
    ts: float
    frame_idx: int
    width: int
    height: int
    fps_in: float
    fps_out: float
    inference_ms: float
    connected: bool
    last_error: Optional[str]
    detections: list[dict]
    tracks: list[dict]
    jpeg_b64: Optional[str] = None  # populated on demand


class CameraPipeline:
    def __init__(
        self,
        cfg: CameraConfig,
        app_cfg: AppConfig,
        yolo: YoloDetector,
        clip_image: ClipImageEncoder,
        db: Database,
    ) -> None:
        self.cfg = cfg
        self.app_cfg = app_cfg
        self.yolo = yolo
        self.clip_image = clip_image
        self.db = db

        self.source = RtspSource(
            camera_id=cfg.id,
            url=cfg.url,
            transport=cfg.transport,
            target_fps=cfg.fps,
        )
        self.tracker = Sort(
            max_age=cfg.track.max_age, min_hits=cfg.track.min_hits
        )

        self._task: Optional[asyncio.Task] = None
        self._stop = asyncio.Event()
        self._latest: Optional[PipelineSnapshot] = None
        self._latest_jpeg: bytes = b""
        self._fps_window: deque[float] = deque(maxlen=60)
        self._tracked_ids_seen: set[int] = set()

    @property
    def latest(self) -> Optional[PipelineSnapshot]:
        return self._latest

    @property
    def latest_jpeg(self) -> bytes:
        return self._latest_jpeg

    async def start(self) -> None:
        self.source.start()
        self._task = asyncio.create_task(self._run(), name=f"pipeline-{self.cfg.id}")

    async def stop(self) -> None:
        self._stop.set()
        self.source.stop()
        if self._task:
            try:
                await asyncio.wait_for(self._task, timeout=5)
            except asyncio.TimeoutError:
                self._task.cancel()

    async def _run(self) -> None:
        loop = asyncio.get_running_loop()
        log.info("pipeline.start", camera_id=self.cfg.id)
        try:
            while not self._stop.is_set():
                frame = self.source.latest()
                if frame is None:
                    await asyncio.sleep(0.005)
                    continue

                t0 = time.monotonic()
                # YOLO + tracker run in a worker thread so we don't block the loop.
                detections, confirmed_tracks, inference_ms = await loop.run_in_executor(
                    None, self._process_sync, frame
                )

                # CLIP indexing + snapshot write — async-friendly.
                await self._index_clip(frame, confirmed_tracks)

                # Update fps stats.
                now = time.monotonic()
                self._fps_window.append(now)
                fps_out = 0.0
                if len(self._fps_window) > 1:
                    span = self._fps_window[-1] - self._fps_window[0]
                    if span > 0:
                        fps_out = (len(self._fps_window) - 1) / span

                # Render overlay JPEG for the live UI.
                overlay_jpeg = await loop.run_in_executor(
                    None,
                    self._render_overlay_jpeg,
                    frame.image,
                    detections,
                    confirmed_tracks,
                )
                self._latest_jpeg = overlay_jpeg

                self._latest = PipelineSnapshot(
                    camera_id=self.cfg.id,
                    ts=now,
                    frame_idx=frame.frame_idx,
                    width=frame.image.shape[1],
                    height=frame.image.shape[0],
                    fps_in=self.source.fps_in,
                    fps_out=fps_out,
                    inference_ms=inference_ms,
                    connected=self.source.connected,
                    last_error=self.source.last_error,
                    detections=[d.to_dict() for d in detections],
                    tracks=[t.to_dict() for t in confirmed_tracks],
                )

                # Yield to the event loop.
                await asyncio.sleep(0)
        except asyncio.CancelledError:
            pass
        except Exception as e:
            log.exception("pipeline.crashed", camera_id=self.cfg.id, error=str(e))
        finally:
            log.info("pipeline.stop", camera_id=self.cfg.id)

    # ---- sync helpers (run in executor) -----------------------------------

    def _process_sync(
        self, frame: Frame
    ) -> tuple[list[Detection], list[Track], float]:
        t0 = time.monotonic()
        class_filter = set(self.cfg.detect.classes) if self.cfg.detect.classes else None
        if self.cfg.detect.enabled:
            detections = self.yolo.detect(
                frame.image,
                min_confidence=self.cfg.detect.min_confidence,
                class_filter=class_filter,
            )
        else:
            detections = []
        inference_ms = (time.monotonic() - t0) * 1000.0

        confirmed = []
        if self.cfg.track.enabled:
            confirmed = self.tracker.update(detections)
        return detections, confirmed, inference_ms

    def _render_overlay_jpeg(
        self,
        frame_bgr: np.ndarray,
        detections: list[Detection],
        tracks: list[Track],
    ) -> bytes:
        img = frame_bgr.copy()
        # Tracks (with stable IDs) take priority over raw detections.
        for t in tracks:
            x1, y1, x2, y2 = (int(v) for v in t.bbox)
            color = _track_color(t.id)
            cv2.rectangle(img, (x1, y1), (x2, y2), color, 2)
            label = f"#{t.id} {t.cls_name} {t.confidence:.2f}"
            (lw, lh), bl = cv2.getTextSize(
                label, cv2.FONT_HERSHEY_SIMPLEX, 0.5, 1
            )
            cv2.rectangle(
                img, (x1, y1 - lh - bl - 4), (x1 + lw + 4, y1), color, -1
            )
            cv2.putText(
                img, label, (x1 + 2, y1 - 4),
                cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 0, 0), 1, cv2.LINE_AA,
            )
        ok, buf = cv2.imencode(".jpg", img, [cv2.IMWRITE_JPEG_QUALITY, 75])
        return buf.tobytes() if ok else b""

    # ---- CLIP indexing ----------------------------------------------------

    async def _index_clip(self, frame: Frame, tracks: list[Track]) -> None:
        if not self.cfg.clip_index.enabled:
            return
        if frame.frame_idx % self.cfg.clip_index.every_n_frames != 0:
            return
        if self.cfg.clip_index.only_when_tracking and not tracks:
            return

        # For each confirmed track, embed the cropped bbox.
        loop = asyncio.get_running_loop()
        for t in tracks:
            crop = _crop_with_padding(
                frame.image, t.bbox, padding=self.cfg.clip_index.bbox_padding
            )
            if crop.size == 0:
                continue
            embedding = await loop.run_in_executor(
                None, self.clip_image.encode, crop
            )
            snapshot_path = self._snapshot_path(frame.frame_idx, t.id, t.cls_name)
            await loop.run_in_executor(None, _write_jpeg, snapshot_path, crop)

            await self.db.insert_event(
                camera_id=self.cfg.id,
                ts=frame.pts,
                track_id=t.id,
                cls_name=t.cls_name,
                confidence=t.confidence,
                bbox=list(t.bbox),
                snapshot_path=str(snapshot_path),
                embedding=embedding,
            )

            if t.id not in self._tracked_ids_seen:
                self._tracked_ids_seen.add(t.id)
                log.info(
                    "track.new",
                    camera_id=self.cfg.id,
                    track_id=t.id,
                    cls=t.cls_name,
                )

    def _snapshot_path(self, frame_idx: int, track_id: int, cls: str) -> Path:
        date = time.strftime("%Y%m%d")
        d = self.app_cfg.paths.snapshots_dir / self.cfg.id / date
        d.mkdir(parents=True, exist_ok=True)
        return d / f"{int(time.time())}_{frame_idx}_t{track_id}_{cls}.jpg"


def _track_color(track_id: int) -> tuple[int, int, int]:
    # Stable per-ID color via a simple hash.
    rng = np.random.default_rng(track_id * 9176 + 1)
    c = rng.integers(60, 240, size=3)
    return int(c[0]), int(c[1]), int(c[2])


def _crop_with_padding(
    img: np.ndarray,
    bbox: tuple[float, float, float, float],
    padding: float,
) -> np.ndarray:
    h, w = img.shape[:2]
    x1, y1, x2, y2 = bbox
    bw, bh = x2 - x1, y2 - y1
    px, py = bw * padding, bh * padding
    nx1 = max(0, int(x1 - px))
    ny1 = max(0, int(y1 - py))
    nx2 = min(w, int(x2 + px))
    ny2 = min(h, int(y2 + py))
    if nx2 <= nx1 or ny2 <= ny1:
        return np.zeros((0, 0, 3), dtype=np.uint8)
    return img[ny1:ny2, nx1:nx2]


def _write_jpeg(path: Path, img: np.ndarray) -> None:
    cv2.imwrite(str(path), img, [cv2.IMWRITE_JPEG_QUALITY, 85])


# ---------------------------------------------------------------------------


class PipelineManager:
    """Owns the shared Hailo VDevice + per-camera pipelines."""

    def __init__(self, cfg: AppConfig, db: Database) -> None:
        self.cfg = cfg
        self.db = db
        self._vdevice_ctx: HailoVDevice | None = None
        self.yolo: YoloDetector | None = None
        self.clip_image: ClipImageEncoder | None = None
        self.clip_text: ClipTextEncoder | None = None
        self.pipelines: dict[str, CameraPipeline] = {}

    async def start(self) -> None:
        models_dir = self.cfg.paths.models_dir
        self._vdevice_ctx = HailoVDevice()
        vdev = self._vdevice_ctx.vdevice

        self.yolo = YoloDetector(
            hef_path=models_dir / self.cfg.models.yolo.hef,
            input_size=self.cfg.models.yolo.input_size,
            vdevice=vdev,
        )
        self.clip_image = ClipImageEncoder(
            hef_path=models_dir / self.cfg.models.clip.image_hef,
            input_size=self.cfg.models.clip.image_input_size,
            vdevice=vdev,
        )
        self.clip_text = ClipTextEncoder(
            hef_path=models_dir / self.cfg.models.clip.text_hef,
            tokenizer_path=models_dir / self.cfg.models.clip.text_tokenizer,
            vdevice=vdev,
        )

        # Sanity: image + text encoders must share an embedding space.
        import numpy as np
        probe_img = np.zeros((64, 64, 3), dtype=np.uint8)
        img_dim = self.clip_image.encode(probe_img).shape[0]
        txt_dim = self.clip_text.encode("probe").shape[0]
        if img_dim != txt_dim or img_dim != self.cfg.models.clip.embedding_dim:
            raise RuntimeError(
                f"CLIP embedding dim mismatch — image HEF emits {img_dim}, "
                f"text ONNX emits {txt_dim}, config says "
                f"{self.cfg.models.clip.embedding_dim}. Image and text "
                f"encoders MUST come from the same CLIP variant — see "
                f"docs/03-models.md."
            )

        for cam_cfg in self.cfg.cameras:
            p = CameraPipeline(
                cfg=cam_cfg,
                app_cfg=self.cfg,
                yolo=self.yolo,
                clip_image=self.clip_image,
                db=self.db,
            )
            await p.start()
            self.pipelines[cam_cfg.id] = p

        log.info(
            "pipeline_manager.started",
            cameras=list(self.pipelines.keys()),
        )

    async def stop(self) -> None:
        for p in self.pipelines.values():
            await p.stop()
        self.pipelines.clear()
        if self.yolo:
            self.yolo.close()
        if self.clip_image:
            self.clip_image.close()
        if self._vdevice_ctx:
            self._vdevice_ctx.__exit__(None, None, None)
        log.info("pipeline_manager.stopped")

    def get(self, camera_id: str) -> CameraPipeline | None:
        return self.pipelines.get(camera_id)
