# 03 — Models (YOLO11s + CLIP)

We run two models on Hailo:

| Model | Purpose | Input | Source |
|---|---|---|---|
| `yolov11s.hef` | object detection (80 COCO classes) | 640×640 RGB | Hailo Model Zoo |
| `clip_vit_base_patch32.hef` | image embedding for semantic search | 224×224 RGB | Hailo Model Zoo |

CLIP text embeddings run on the Pi CPU (~30ms per query). Only the image
encoder needs the Hailo accelerator.

> **⚠ Embedding-space coupling**: CLIP image and text encoders only produce
> comparable embeddings if they come from the **same trained variant**. Our
> defaults pair `openai/clip-vit-base-patch32` on both sides (512-d). If you
> swap one, swap the other — the runtime will refuse to start if the dims
> don't match.

## Download

`scripts/04-download-models.sh` pulls HEFs from Hailo's CDN into `~/.local/share/pi5-hailo-vision/models/`:

```bash
./scripts/04-download-models.sh
```

The script detects your hardware (`hailortcli fw-control identify`) and grabs:

- **Hailo-10H**: `hailo10h/yolov11s.hef`, `hailo10h/clip_vit_base_patch32.hef`
- **Hailo-8**: `hailo8/yolov11s.hef`, `hailo8/clip_vit_base_patch32.hef`
- **Hailo-8L**: `hailo8l/yolov11s.hef`, `hailo8l/clip_vit_base_patch32.hef`

It also downloads the **CLIP text tokenizer + text encoder ONNX** (~50MB) that runs on the CPU via `onnxruntime`.

## Verify

```bash
hailortcli parse-hef ~/.local/share/pi5-hailo-vision/models/yolov11s.hef
```

Should print input shapes, output layers, and quantization info.

Quick sanity inference:

```bash
hailortcli run ~/.local/share/pi5-hailo-vision/models/yolov11s.hef \
  --measure-fps --batch-size 1
```

You should see ~60-80 FPS on Hailo-10H, ~40-50 FPS on Hailo-8.

## Custom models

Compile your own (custom YOLO retrained, etc.) using the
[Hailo Dataflow Compiler](https://hailo.ai/developer-zone/) → drop the
`.hef` in the models directory and point `config/models.yaml` at it.

Next: [04 — Tailscale](04-tailscale.md).
