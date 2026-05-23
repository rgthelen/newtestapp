"""Thin wrapper around HailoRT for running a single HEF.

The Hailo Python API has gone through several rewrites; the stable surface we
target is `hailo_platform` (shipped by `python3-hailort`) with InferVStreams.

We deliberately keep the abstraction tiny: load an HEF, push a batch-1 numpy
input, get the raw output tensors back. Post-processing lives in the model
wrappers (yolo_detector.py, clip_embedder.py).
"""

from __future__ import annotations

import threading
from pathlib import Path
from typing import Any

import numpy as np
import structlog

log = structlog.get_logger(__name__)

try:
    from hailo_platform import (
        HEF,
        ConfigureParams,
        FormatType,
        HailoStreamInterface,
        InferVStreams,
        InputVStreamParams,
        OutputVStreamParams,
        VDevice,
    )

    _HAILO_AVAILABLE = True
except ImportError as e:  # pragma: no cover — only on dev machines
    _HAILO_AVAILABLE = False
    _HAILO_IMPORT_ERROR = e


class HailoModel:
    """Single-HEF inference handle. Thread-safe via a lock."""

    def __init__(self, hef_path: Path, vdevice: Any | None = None) -> None:
        if not _HAILO_AVAILABLE:
            raise RuntimeError(
                f"hailo_platform not available — was python3-hailort installed "
                f"and the venv created with --system-site-packages?  "
                f"({_HAILO_IMPORT_ERROR})"
            )
        if not hef_path.exists():
            raise FileNotFoundError(f"HEF not found: {hef_path}")

        self.hef_path = hef_path
        self._lock = threading.Lock()

        # Allow sharing a VDevice across multiple models for concurrency.
        self._owns_vdevice = vdevice is None
        self.vdevice = vdevice if vdevice is not None else VDevice()
        self.hef = HEF(str(hef_path))

        configure_params = ConfigureParams.create_from_hef(
            hef=self.hef, interface=HailoStreamInterface.PCIe
        )
        self.network_group = self.vdevice.configure(self.hef, configure_params)[0]
        self.network_group_params = self.network_group.create_params()

        self.input_vstream_info = self.hef.get_input_vstream_infos()
        self.output_vstream_info = self.hef.get_output_vstream_infos()

        self.input_params = InputVStreamParams.make(
            self.network_group, format_type=FormatType.UINT8
        )
        self.output_params = OutputVStreamParams.make(
            self.network_group, format_type=FormatType.FLOAT32
        )

        # Cache the single input name (we only support single-input HEFs).
        if len(self.input_vstream_info) != 1:
            raise ValueError(
                f"{hef_path.name}: expected 1 input stream, got "
                f"{len(self.input_vstream_info)}"
            )
        self.input_name = self.input_vstream_info[0].name
        h, w, c = self.input_vstream_info[0].shape
        self.input_shape = (h, w, c)
        log.info(
            "hailo.model.loaded",
            hef=hef_path.name,
            input_shape=self.input_shape,
            outputs=[o.name for o in self.output_vstream_info],
        )

    def infer(self, image_uint8: np.ndarray) -> dict[str, np.ndarray]:
        """Run inference on a single uint8 HxWxC image.

        Returns dict of {output_name -> float32 ndarray}.
        """
        if image_uint8.dtype != np.uint8:
            raise ValueError(f"input must be uint8, got {image_uint8.dtype}")
        if image_uint8.shape != self.input_shape:
            raise ValueError(
                f"input shape {image_uint8.shape} != HEF input {self.input_shape}"
            )

        # HailoRT expects a batched array: NHWC.
        batched = np.expand_dims(image_uint8, axis=0)

        with self._lock:
            with InferVStreams(
                self.network_group, self.input_params, self.output_params
            ) as infer_pipeline:
                with self.network_group.activate(self.network_group_params):
                    raw = infer_pipeline.infer({self.input_name: batched})

        # Strip the batch dim from each output.
        return {k: v[0] for k, v in raw.items()}

    def close(self) -> None:
        if self._owns_vdevice and self.vdevice is not None:
            try:
                self.vdevice.release()
            except Exception:  # pragma: no cover
                pass


class HailoVDevice:
    """Shared VDevice handle for multiple models."""

    def __init__(self) -> None:
        if not _HAILO_AVAILABLE:
            raise RuntimeError("hailo_platform not available")
        self.vdevice = VDevice()

    def __enter__(self) -> "HailoVDevice":
        return self

    def __exit__(self, *exc: object) -> None:
        try:
            self.vdevice.release()
        except Exception:  # pragma: no cover
            pass
