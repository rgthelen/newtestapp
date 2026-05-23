"""Simple SORT-style multi-object tracker.

Self-contained — no external tracker dependencies, just numpy + scipy's linear
sum assignment. Good enough for our use case (relatively low FPS, distinct
objects). Swap in ByteTrack later if needed.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Iterable

import numpy as np
from scipy.optimize import linear_sum_assignment

from .yolo_detector import Detection


def _iou(a: np.ndarray, b: np.ndarray) -> np.ndarray:
    """IoU between Nx4 and Mx4 arrays of xyxy boxes. Returns NxM."""
    x1 = np.maximum(a[:, None, 0], b[None, :, 0])
    y1 = np.maximum(a[:, None, 1], b[None, :, 1])
    x2 = np.minimum(a[:, None, 2], b[None, :, 2])
    y2 = np.minimum(a[:, None, 3], b[None, :, 3])
    inter = np.clip(x2 - x1, 0, None) * np.clip(y2 - y1, 0, None)
    area_a = (a[:, 2] - a[:, 0]) * (a[:, 3] - a[:, 1])
    area_b = (b[:, 2] - b[:, 0]) * (b[:, 3] - b[:, 1])
    union = area_a[:, None] + area_b[None, :] - inter
    union = np.where(union <= 0, 1e-6, union)
    return inter / union


@dataclass
class Track:
    id: int
    cls_id: int
    cls_name: str
    bbox: tuple[float, float, float, float]  # xyxy
    confidence: float
    hits: int = 1
    time_since_update: int = 0
    age: int = 1
    confirmed: bool = False
    history: list[tuple[float, float]] = field(default_factory=list)  # (cx, cy)

    @property
    def cx(self) -> float:
        return (self.bbox[0] + self.bbox[2]) / 2

    @property
    def cy(self) -> float:
        return (self.bbox[1] + self.bbox[3]) / 2

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "cls_id": self.cls_id,
            "cls_name": self.cls_name,
            "bbox": [round(v, 1) for v in self.bbox],
            "confidence": round(self.confidence, 4),
            "age": self.age,
            "confirmed": self.confirmed,
        }


class Sort:
    """SORT-lite. No Kalman — uses last bbox as the prediction.

    Pi 5 + Hailo runs the pipeline at 10-30 FPS per camera. At that frame
    rate IoU matching on previous bbox is accurate enough and dramatically
    cheaper than full Kalman.
    """

    def __init__(
        self,
        max_age: int = 30,
        min_hits: int = 3,
        iou_threshold: float = 0.3,
    ) -> None:
        self.max_age = max_age
        self.min_hits = min_hits
        self.iou_threshold = iou_threshold
        self._next_id = 1
        self._tracks: list[Track] = []

    @property
    def tracks(self) -> list[Track]:
        return list(self._tracks)

    def update(self, detections: Iterable[Detection]) -> list[Track]:
        detections = list(detections)

        # Age all existing tracks.
        for t in self._tracks:
            t.time_since_update += 1
            t.age += 1

        if detections and self._tracks:
            det_boxes = np.array(
                [[d.x1, d.y1, d.x2, d.y2] for d in detections], dtype=np.float32
            )
            trk_boxes = np.array(
                [t.bbox for t in self._tracks], dtype=np.float32
            )
            iou_mat = _iou(trk_boxes, det_boxes)

            # Penalize cross-class matches.
            for ti, t in enumerate(self._tracks):
                for di, d in enumerate(detections):
                    if d.cls_id != t.cls_id:
                        iou_mat[ti, di] = 0.0

            # Hungarian on negative IoU = max-IoU assignment.
            cost = 1.0 - iou_mat
            row_idx, col_idx = linear_sum_assignment(cost)

            matched_trk: set[int] = set()
            matched_det: set[int] = set()
            for ti, di in zip(row_idx, col_idx):
                if iou_mat[ti, di] < self.iou_threshold:
                    continue
                t = self._tracks[ti]
                d = detections[di]
                t.bbox = (d.x1, d.y1, d.x2, d.y2)
                t.confidence = d.confidence
                t.hits += 1
                t.time_since_update = 0
                t.history.append((t.cx, t.cy))
                if len(t.history) > 64:
                    t.history.pop(0)
                if t.hits >= self.min_hits:
                    t.confirmed = True
                matched_trk.add(ti)
                matched_det.add(di)

            unmatched_dets = [
                d for i, d in enumerate(detections) if i not in matched_det
            ]
        else:
            unmatched_dets = list(detections)

        # Spawn new tracks for unmatched detections.
        for d in unmatched_dets:
            self._tracks.append(
                Track(
                    id=self._next_id,
                    cls_id=d.cls_id,
                    cls_name=d.cls_name,
                    bbox=(d.x1, d.y1, d.x2, d.y2),
                    confidence=d.confidence,
                )
            )
            self._next_id += 1

        # Cull dead tracks.
        self._tracks = [
            t for t in self._tracks if t.time_since_update <= self.max_age
        ]

        return [t for t in self._tracks if t.confirmed and t.time_since_update == 0]
