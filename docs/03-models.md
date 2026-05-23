# 03 — Models (YOLO11s + CLIP ViT-B/16)

All neural networks run on Hailo — nothing on the CPU except the tiny BPE
tokenizer that turns query text into integer IDs.

| Model | Purpose | Input | Source |
|---|---|---|---|
| `yolov11s.hef` | object detection (80 COCO classes) | 640×640 RGB uint8 | Hailo Model Zoo |
| `clip_vit_base_patch16_image.hef` | image embedding | 224×224 RGB uint8 | Hailo Model Zoo |
| `clip_vit_base_patch16_text.hef` | text embedding | 77 token IDs uint16 | Hailo Model Zoo |

> **⚠ Embedding-space coupling**: the image and text encoders only produce
> comparable embeddings if they come from the **same trained variant**. Our
> defaults pair `openai/clip-vit-base-patch16` on both sides (512-d). If you
> swap one, swap the other — the runtime has a startup probe that bails with
> a clear error if the dims don't match.

## Download

`scripts/04-download-models.sh` pulls all three HEFs + the BPE tokenizer JSON
into `~/.local/share/pi5-hailo-vision/models/`:

```bash
./scripts/04-download-models.sh
```

The script detects your hardware (`hailortcli fw-control identify`) and pulls
the architecture-matched HEFs:

- **Hailo-10H**: `hailo10h/yolov11s.hef`, `hailo10h/clip_vit_base_patch16_*.hef`
- **Hailo-8**:   `hailo8/...`
- **Hailo-8L**:  `hailo8l/...`

## Verify

```bash
hailortcli parse-hef ~/.local/share/pi5-hailo-vision/models/clip_vit_base_patch16_text.hef
hailortcli parse-hef ~/.local/share/pi5-hailo-vision/models/clip_vit_base_patch16_image.hef
hailortcli parse-hef ~/.local/share/pi5-hailo-vision/models/yolov11s.hef
```

Each command prints input shapes, output layers, and quantization info.

Quick sanity inference (YOLO):

```bash
hailortcli run ~/.local/share/pi5-hailo-vision/models/yolov11s.hef \
  --measure-fps --batch-size 1
```

Expected on Hailo-10H: ~60–80 FPS YOLO11s, ~250+ FPS for the CLIP text
encoder, ~150+ FPS for the CLIP image encoder.

## Manual fallback

The Hailo Model Zoo S3 layout shifts between releases. If the script can't
find the URL it expects:

1. Browse the [Hailo Model Zoo](https://github.com/hailo-ai/hailo_model_zoo)
   for the matching `<arch>` HEFs (`clip_vit_base_patch16_image`,
   `clip_vit_base_patch16_text`, `yolov11s`).
2. Drop them in `~/.local/share/pi5-hailo-vision/models/` with the exact
   filenames listed in the table above.
3. Or override the filenames in `~/.config/pi5-hailo-vision/app.yaml` to
   match whatever names you've used.

## Custom models

Compile your own (custom YOLO retrained, distilled CLIP, etc.) with the
[Hailo Dataflow Compiler](https://hailo.ai/developer-zone/), drop the `.hef`
in the models dir, and point `config/app.yaml` at it.

Next: [04 — Tailscale](04-tailscale.md).
