#!/usr/bin/env bash
# Download YOLO11s + CLIP HEFs for the detected Hailo architecture,
# plus the CLIP text encoder ONNX (CPU side).
set -euo pipefail

echo "==> [4/6] models"

MODELS_DIR="$HOME/.local/share/pi5-hailo-vision/models"
mkdir -p "$MODELS_DIR"

# --- detect arch -------------------------------------------------------------
ARCH="hailo8"  # safe default
if command -v hailortcli >/dev/null 2>&1 && hailortcli fw-control identify >/dev/null 2>&1; then
    BOARD="$(hailortcli fw-control identify | awk -F': ' '/Board Name/ {print tolower($2)}' | tr -d '\r ')"
    case "$BOARD" in
        *10h*) ARCH="hailo10h" ;;
        *8l*)  ARCH="hailo8l"  ;;
        *8*)   ARCH="hailo8"   ;;
    esac
fi
echo "    detected arch: $ARCH"

# --- HEFs from Hailo Model Zoo ----------------------------------------------
# Hailo publishes HEFs at https://hailo-model-zoo.s3.eu-west-2.amazonaws.com/
# Layout (verify with `hailomz info <model>` if URLs change):
#   ModelZoo/<release>/<arch>/<model>.hef
HAILO_MZ_BASE="https://hailo-csdata.s3.eu-west-2.amazonaws.com/resources/hefs"
RELEASE="v2.13.0"

declare -A HEFS=(
    [yolov11s.hef]="${HAILO_MZ_BASE}/${RELEASE}/${ARCH}/yolov11s.hef"
    # CLIP ViT-B/16 image + text encoders — must be the matching pair.
    [clip_vit_base_patch16_image.hef]="${HAILO_MZ_BASE}/${RELEASE}/${ARCH}/clip_vit_base_patch16_image.hef"
    [clip_vit_base_patch16_text.hef]="${HAILO_MZ_BASE}/${RELEASE}/${ARCH}/clip_vit_base_patch16_text.hef"
)

for name in "${!HEFS[@]}"; do
    dest="$MODELS_DIR/$name"
    if [[ -f "$dest" && -s "$dest" ]]; then
        echo "    [skip] $name (already present, $(du -h "$dest" | cut -f1))"
        continue
    fi
    url="${HEFS[$name]}"
    echo "    [pull] $name <- $url"
    if ! curl -fSL --retry 3 --retry-delay 2 -o "$dest" "$url"; then
        rm -f "$dest"
        cat <<EOF >&2

    ⚠  Failed to download $name for arch $ARCH.
       The Hailo Model Zoo URL scheme changes between releases.
       Manual fallback:
         1. Browse https://github.com/hailo-ai/hailo_model_zoo
         2. Find HEF for $ARCH matching this model
         3. Place at $dest
EOF
        exit 1
    fi
done

# --- CLIP BPE tokenizer (CPU, JSON — converts text to token IDs) ------------
# The tokenizer is part of openai/clip-vit-base-patch16 on Hugging Face and is
# identical to ViT-B/32's tokenizer (same vocab). We use Xenova's mirror which
# exposes a single `tokenizer.json` file in HF tokenizers format.
TEXT_TOK="$MODELS_DIR/clip_tokenizer.json"

if [[ ! -f "$TEXT_TOK" ]]; then
    echo "    [pull] clip_tokenizer.json"
    curl -fSL --retry 3 -o "$TEXT_TOK" \
        "https://huggingface.co/Xenova/clip-vit-base-patch16/resolve/main/tokenizer.json"
fi

echo "    models in $MODELS_DIR:"
ls -lh "$MODELS_DIR" | sed 's/^/    /'
