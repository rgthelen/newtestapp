"""CLIP embeddings — image AND text encoders both on Hailo (HEF).

CLIP returns 512-d (ViT-B/16, ViT-B/32) or larger embeddings depending on the
variant. Image and text encoders share the same embedding space, so cosine
similarity between a text query and a stored image embedding is the search
ranking.

Image preprocessing follows the CLIP paper:
  1. Resize so the SHORTER side == input size (e.g. 224 for ViT-B/16).
  2. Center crop to (input, input).
  3. RGB, [0..1], normalize with CLIP's mean/std.

For Hailo HEFs, normalization is baked into the HEF (the compiler applied
input scaling), so we hand it uint8 RGB pre-cropped to the model input size.

Text preprocessing:
  1. BPE-tokenize with CLIP's tokenizer.json -> 77 token IDs (pad/truncate).
  2. Feed uint16 IDs to the text-encoder HEF.
  3. The HEF returns the pooled (EOS-token) embedding.
"""

from __future__ import annotations

from pathlib import Path

import cv2
import numpy as np
import structlog
from tokenizers import Tokenizer

from .hailo_runtime import HailoModel

log = structlog.get_logger(__name__)


CLIP_CONTEXT_LENGTH = 77
EOT_TOKEN = "<|endoftext|>"


def _l2_normalize(v: np.ndarray, axis: int = -1) -> np.ndarray:
    n = np.linalg.norm(v, axis=axis, keepdims=True)
    return v / np.maximum(n, 1e-12)


def _clip_preprocess_uint8(
    img_bgr: np.ndarray, size: tuple[int, int]
) -> np.ndarray:
    """Center-crop + resize to model input size. Returns uint8 RGB HxWx3."""
    h, w = img_bgr.shape[:2]
    short = min(h, w)
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
        input_size: tuple[int, int] = (224, 224),
        vdevice=None,
    ) -> None:
        self.model = HailoModel(hef_path, vdevice=vdevice, input_dtype=np.dtype(np.uint8))
        self.input_size = input_size
        if len(self.model.output_vstream_info) != 1:
            log.warning(
                "clip.image.multi_output",
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
    """CLIP text encoder on Hailo (HEF).

    The HEF expects a single fixed-length input of token IDs. CLIP uses a
    77-token context; tokens are uint16 (vocab ~49408 fits comfortably). We
    do BPE tokenization on the CPU (negligible cost — it's a string split)
    then run the encoder on Hailo.
    """

    def __init__(
        self,
        hef_path: Path,
        tokenizer_path: Path,
        context_length: int = CLIP_CONTEXT_LENGTH,
        vdevice=None,
    ) -> None:
        if not tokenizer_path.exists():
            raise FileNotFoundError(tokenizer_path)

        self.context_length = context_length
        self.model = HailoModel(
            hef_path, vdevice=vdevice, input_dtype=np.dtype(np.uint16)
        )

        # Discover the EOS token id (CLIP uses `<|endoftext|>` for padding too).
        self.tokenizer = Tokenizer.from_file(str(tokenizer_path))
        eot_id = self.tokenizer.token_to_id(EOT_TOKEN)
        if eot_id is None:
            raise RuntimeError(
                f"tokenizer at {tokenizer_path} is missing {EOT_TOKEN}"
            )
        self._eot_id = eot_id
        self.tokenizer.enable_padding(
            length=context_length, pad_id=eot_id, pad_token=EOT_TOKEN
        )
        self.tokenizer.enable_truncation(max_length=context_length)

        if len(self.model.output_vstream_info) != 1:
            log.warning(
                "clip.text.multi_output",
                outputs=[o.name for o in self.model.output_vstream_info],
            )
        self._output_name = self.model.output_vstream_info[0].name

        # The HEF input shape is typically (77,) or (1, 77) — adapt.
        in_shape = self.model.input_shape
        self._input_shape = in_shape
        log.info("clip.text.loaded", input_shape=in_shape)

    def encode(self, text: str) -> np.ndarray:
        enc = self.tokenizer.encode(text)
        ids = np.asarray(enc.ids, dtype=np.uint16)
        if ids.shape[0] != self.context_length:
            # Defensive — tokenizer padding should have handled this.
            buf = np.full(self.context_length, self._eot_id, dtype=np.uint16)
            n = min(self.context_length, ids.shape[0])
            buf[:n] = ids[:n]
            ids = buf
        # Reshape to whatever the HEF expects (e.g. (77,) or (1, 77)).
        ids = ids.reshape(self._input_shape)
        out = self.model.infer(ids)
        vec = out[self._output_name].reshape(-1).astype(np.float32)
        return _l2_normalize(vec)

    def close(self) -> None:
        self.model.close()
