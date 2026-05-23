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


# Map numpy dtypes to HailoRT FormatType so the wrapper works for both
# image (uint8) and text (uint16 token IDs) HEFs.
def _hailo_format_for_dtype(dtype: np.dtype) -> Any:
    if dtype == np.uint8:
        return FormatType.UINT8
    if dtype == np.uint16:
        return FormatType.UINT16
    if dtype == np.float32:
        return FormatType.FLOAT32
    raise ValueError(f"no Hailo FormatType for numpy dtype {dtype}")


class HailoModel:
    """Single-HEF inference handle. Thread-safe via a lock.

    Supports any HEF whose input dtype is uint8 / uint16 / float32. The
    expected input numpy dtype is provided at construction so we can pick
    the right FormatType (image encoders use uint8, CLIP text encoders use
    uint16 token IDs).
    """

    def __init__(
        self,
        hef_path: Path,
        vdevice: Any | None = None,
        input_dtype: np.dtype = np.dtype(np.uint8),
    ) -> None:
        if not _HAILO_AVAILABLE:
            raise RuntimeError(
                f"hailo_platform not available — was python3-hailort installed "
                f"and the venv created with --system-site-packages?  "
                f"({_HAILO_IMPORT_ERROR})"
            )
        if not hef_path.exists():
            raise FileNotFoundError(f"HEF not found: {hef_path}")

        self.hef_path = hef_path
        self.input_dtype = input_dtype
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
            self.network_group, format_type=_hailo_format_for_dtype(input_dtype)
        )
        self.output_params = OutputVStreamParams.make(
            self.network_group, format_type=FormatType.FLOAT32
        )

        if len(self.input_vstream_info) != 1:
            raise ValueError(
                f"{hef_path.name}: expected 1 input stream, got "
                f"{len(self.input_vstream_info)}"
            )
        self.input_name = self.input_vstream_info[0].name
        self.input_shape = tuple(self.input_vstream_info[0].shape)
        log.info(
            "hailo.model.loaded",
            hef=hef_path.name,
            input_shape=self.input_shape,
            input_dtype=str(input_dtype),
            outputs=[o.name for o in self.output_vstream_info],
        )

    def infer(self, x: np.ndarray) -> dict[str, np.ndarray]:
        """Run inference on a single (un-batched) input.

        Returns dict of {output_name -> float32 ndarray} with the batch
        dim stripped.
        """
        if x.dtype != self.input_dtype:
            raise ValueError(
                f"input dtype {x.dtype} != HEF dtype {self.input_dtype}"
            )
        if tuple(x.shape) != self.input_shape:
            raise ValueError(
                f"input shape {x.shape} != HEF input {self.input_shape}"
            )

        batched = np.expand_dims(x, axis=0)

        with self._lock:
            with InferVStreams(
                self.network_group, self.input_params, self.output_params
            ) as infer_pipeline:
                with self.network_group.activate(self.network_group_params):
                    raw = infer_pipeline.infer({self.input_name: batched})

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
