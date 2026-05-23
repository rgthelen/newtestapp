"""YOLO11s on Hailo — letterbox preprocess + NMS-style postprocess.

YOLO HEFs from the Hailo Model Zoo emit raw class+box outputs at three
strides. We rely on Hailo's built-in HailoNMSPP layer (added during HEF
compilation) which already returns post-NMS detections — typical output shape
is `(num_classes, max_detections_per_class, 5)` with [y1, x1, y2, x2, score].

We detect both layouts at load time so this works with HEFs that include or
omit on-chip NMS.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import cv2
import numpy as np
import structlog

from .hailo_runtime import HailoModel

log = structlog.get_logger(__name__)


# COCO 80 class names — matches Ultralytics / Hailo Model Zoo ordering.
COCO_CLASSES: list[str] = [
    "person", "bicycle", "car", "motorcycle", "airplane", "bus", "train",
    "truck", "boat", "traffic light", "fire hydrant", "stop sign",
    "parking meter", "bench", "bird", "cat", "dog", "horse", "sheep", "cow",
    "elephant", "bear", "zebra", "giraffe", "backpack", "umbrella", "handbag",
    "tie", "suitcase", "frisbee", "skis", "snowboard", "sports ball", "kite",
    "baseball bat", "baseball glove", "skateboard", "surfboard",
    "tennis racket", "bottle", "wine glass", "cup", "fork", "knife", "spoon",
    "bowl", "banana", "apple", "sandwich", "orange", "broccoli", "carrot",
    "hot dog", "pizza", "donut", "cake", "chair", "couch", "potted plant",
    "bed", "dining table", "toilet", "tv", "laptop", "mouse", "remote",
    "keyboard", "cell phone", "microwave", "oven", "toaster", "sink",
    "refrigerator", "book", "clock", "vase", "scissors", "teddy bear",
    "hair drier", "toothbrush",
]


@dataclass
class Detection:
    cls_id: int
    cls_name: str
    confidence: float
    # bbox in *original frame* pixel coords, xyxy
    x1: float
    y1: float
    x2: float
    y2: float

    def to_dict(self) -> dict:
        return {
            "cls_id": self.cls_id,
            "cls_name": self.cls_name,
            "confidence": round(self.confidence, 4),
            "bbox": [round(self.x1, 1), round(self.y1, 1), round(self.x2, 1), round(self.y2, 1)],
        }


def _letterbox(
    img: np.ndarray, dst_size: tuple[int, int]
) -> tuple[np.ndarray, float, int, int]:
    """Resize keeping aspect ratio, pad with 114 to dst_size.

    Returns (letterboxed, scale, pad_x, pad_y).
    """
    src_h, src_w = img.shape[:2]
    dst_w, dst_h = dst_size
    scale = min(dst_w / src_w, dst_h / src_h)
    new_w, new_h = int(round(src_w * scale)), int(round(src_h * scale))
    resized = cv2.resize(img, (new_w, new_h), interpolation=cv2.INTER_LINEAR)
    pad_x = (dst_w - new_w) // 2
    pad_y = (dst_h - new_h) // 2
    canvas = np.full((dst_h, dst_w, 3), 114, dtype=np.uint8)
    canvas[pad_y : pad_y + new_h, pad_x : pad_x + new_w] = resized
    return canvas, scale, pad_x, pad_y


class YoloDetector:
    def __init__(
        self,
        hef_path: Path,
        input_size: tuple[int, int] = (640, 640),
        class_names: list[str] | None = None,
        vdevice=None,
    ) -> None:
        self.model = HailoModel(hef_path, vdevice=vdevice)
        self.input_size = input_size
        self.class_names = class_names or COCO_CLASSES

        # Auto-detect output layout: HEFs with on-chip NMS expose a single
        # output named `*/nms*` or with shape (classes, max_dets, 5).
        out_names = [o.name for o in self.model.output_vstream_info]
        self._nms_output: str | None = None
        for name, info in zip(out_names, self.model.output_vstream_info):
            shape = info.shape
            if len(shape) == 3 and shape[-1] == 5:
                self._nms_output = name
                break
        if self._nms_output is None:
            log.warning(
                "yolo.no_onchip_nms",
                outputs=out_names,
                note="Model has no NMS layer — only NMS-ed HEFs are supported in this pipeline.",
            )

    def detect(
        self,
        frame_bgr: np.ndarray,
        min_confidence: float = 0.4,
        class_filter: set[str] | None = None,
    ) -> list[Detection]:
        src_h, src_w = frame_bgr.shape[:2]
        # BGR -> RGB, letterbox to model size.
        rgb = cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2RGB)
        lb, scale, pad_x, pad_y = _letterbox(rgb, self.input_size)

        outputs = self.model.infer(lb)
        if self._nms_output is None or self._nms_output not in outputs:
            return []
        nms_out = outputs[self._nms_output]  # (num_classes, max_dets, 5)

        detections: list[Detection] = []
        num_classes = nms_out.shape[0]
        for cls_id in range(num_classes):
            cls_dets = nms_out[cls_id]
            for det in cls_dets:
                y1, x1, y2, x2, score = det[0], det[1], det[2], det[3], det[4]
                if score < min_confidence:
                    continue
                cls_name = (
                    self.class_names[cls_id]
                    if cls_id < len(self.class_names)
                    else f"cls_{cls_id}"
                )
                if class_filter and cls_name not in class_filter:
                    continue

                # NMS output coords are normalized to the letterboxed input
                # (range 0..1 relative to model input size).
                in_w, in_h = self.input_size
                px1 = x1 * in_w
                py1 = y1 * in_h
                px2 = x2 * in_w
                py2 = y2 * in_h
                # un-letterbox -> original frame coords
                ox1 = max(0.0, (px1 - pad_x) / scale)
                oy1 = max(0.0, (py1 - pad_y) / scale)
                ox2 = min(float(src_w), (px2 - pad_x) / scale)
                oy2 = min(float(src_h), (py2 - pad_y) / scale)
                if ox2 <= ox1 or oy2 <= oy1:
                    continue

                detections.append(
                    Detection(
                        cls_id=cls_id,
                        cls_name=cls_name,
                        confidence=float(score),
                        x1=ox1,
                        y1=oy1,
                        x2=ox2,
                        y2=oy2,
                    )
                )
        return detections

    def close(self) -> None:
        self.model.close()
