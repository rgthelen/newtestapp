"""CLIP embeddings — image encoder on Hailo, text encoder on CPU (ONNX).

OpenAI CLIP returns 512-d (ViT-B/32) or 640-d (ResNet 50x4) embeddings. Image
and text encoders share the same embedding space, so cosine similarity between
a text query embedding and a stored image embedding is the search ranking.

Image preprocessing follows the CLIP paper:
  1. Resize so the SHORTER side == input size (e.g. 288 for RN50x4).
  2. Center crop to (input, input).
  3. RGB, [0..1], normalize with CLIP's mean/std.

For Hailo, normalization is baked into the HEF (the compiler applied input
scaling), so we hand it uint8 RGB pre-cropped to the model input size. If your
specific HEF was compiled without input normalization, set
`apply_normalization=True` and feed float32 — but that's slower (CPU mul/add)
and most Hailo Model Zoo CLIP HEFs already include it.
"""

from __future__ import annotations

import json
from pathlib import Path

import cv2
import numpy as np
import onnxruntime as ort
import structlog
from tokenizers import Tokenizer

from .hailo_runtime import HailoModel

log = structlog.get_logger(__name__)


def _l2_normalize(v: np.ndarray, axis: int = -1) -> np.ndarray:
    n = np.linalg.norm(v, axis=axis, keepdims=True)
    return v / np.maximum(n, 1e-12)


def _clip_preprocess_uint8(
    img_bgr: np.ndarray, size: tuple[int, int]
) -> np.ndarray:
    """Center-crop + resize to model input size. Returns uint8 RGB HxWx3."""
    h, w = img_bgr.shape[:2]
    short = min(h, w)
    # Crop to square first to preserve aspect ratio.
    if h > w:
        top = (h - short) // 2
        cropped = img_bgr[top : top + short, :]
    else:
        left = (w - short) // 2
        cropped = img_bgr[:, left : left + short]
    rgb = cv2.cvtColor(cropped, cv2.COLOR_BGR2RGB)
    resized = cv2.resize(rgb, size, interpolation=cv2.INTER_CUBIC)
    return resized.astype(np.uint8)


class ClipImageEncoder:
    def __init__(
        self,
        hef_path: Path,
        input_size: tuple[int, int] = (288, 288),
        vdevice=None,
    ) -> None:
        self.model = HailoModel(hef_path, vdevice=vdevice)
        self.input_size = input_size
        # Assume single output (the embedding).
        if len(self.model.output_vstream_info) != 1:
            log.warning(
                "clip.multi_output",
                outputs=[o.name for o in self.model.output_vstream_info],
            )
        self._output_name = self.model.output_vstream_info[0].name

    def encode(self, img_bgr: np.ndarray) -> np.ndarray:
        """Return a unit-norm embedding vector."""
        x = _clip_preprocess_uint8(img_bgr, self.input_size)
        out = self.model.infer(x)
        vec = out[self._output_name].reshape(-1).astype(np.float32)
        return _l2_normalize(vec)

    def close(self) -> None:
        self.model.close()


class ClipTextEncoder:
    """CPU-side text encoder. ~30ms per query — fine for interactive search."""

    def __init__(self, onnx_path: Path, tokenizer_path: Path) -> None:
        if not onnx_path.exists():
            raise FileNotFoundError(onnx_path)
        if not tokenizer_path.exists():
            raise FileNotFoundError(tokenizer_path)

        # ONNX runtime — use the default CPU EP. We could try the ARM NN EP
        # but the model is tiny and the difference is negligible.
        self.session = ort.InferenceSession(
            str(onnx_path),
            providers=["CPUExecutionProvider"],
        )
        self.tokenizer = Tokenizer.from_file(str(tokenizer_path))
        # CLIP uses a fixed 77-token context length.
        self.tokenizer.enable_padding(
            length=77, pad_id=0, pad_token="<|endoftext|>"
        )
        self.tokenizer.enable_truncation(max_length=77)

        # Probe input names.
        self._input_names = [i.name for i in self.session.get_inputs()]
        self._output_name = self.session.get_outputs()[0].name
        log.info(
            "clip.text.loaded",
            inputs=self._input_names,
            output=self._output_name,
        )

    def encode(self, text: str) -> np.ndarray:
        enc = self.tokenizer.encode(text)
        input_ids = np.array([enc.ids], dtype=np.int64)
        attention_mask = np.array([enc.attention_mask], dtype=np.int64)

        feeds: dict[str, np.ndarray] = {}
        for name in self._input_names:
            if "ids" in name or name == "input":
                feeds[name] = input_ids
            elif "mask" in name:
                feeds[name] = attention_mask
            else:
                feeds[name] = input_ids
        out = self.session.run([self._output_name], feeds)[0]
        # `out` is either (1, embed_dim) — pooled — or (1, seq_len, embed_dim).
        # Xenova's quantized text_model output is the pooled embedding.
        vec = out.reshape(out.shape[0], -1)[0].astype(np.float32)
        return _l2_normalize(vec)
