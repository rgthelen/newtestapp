# pi5-hailo-vision

Self-hosted multi-camera AI vision for **Raspberry Pi 5 (16GB) + Hailo-10H AI HAT**.

- **YOLO11s** object detection on Hailo (real-time, multi-stream)
- **CLIP** text/image embeddings for "find me clips of X" semantic search
- **Multi-object tracking** (IDs persist across frames)
- **RTSP ingest** for any WiFi/PoE IP camera
- **FastAPI + WebSocket** backend, modern web UI
- **Tailscale** for secure remote access from anywhere
- **systemd** service, auto-starts on boot

---

## Quick start

1. **Flash SD card** → see `docs/01-flash-and-boot.md`
2. **Install everything**:
   ```bash
   git clone https://github.com/rgthelen/newtestapp.git ~/pi5-hailo-vision
   cd ~/pi5-hailo-vision
   ./scripts/install-all.sh
   ```
3. **Add cameras** → edit `~/.config/pi5-hailo-vision/cameras.yaml`
4. **Start service**:
   ```bash
   sudo systemctl enable --now pi5-hailo-vision
   ```
5. **Open the UI** at `http://<pi-tailscale-name>:8080`

---

## What's in this repo

```
scripts/         # one-shot installers (OS, Hailo, models, Tailscale)
app/             # Python backend (pipeline + API + UI assets)
  pipeline/      # RTSP → Hailo YOLO → tracker → CLIP embeddings
  api/           # FastAPI routes + WebSocket live feed
  storage/       # SQLite + snapshot store + embedding index
  ui/            # static web UI (vanilla JS, no build step)
config/          # example camera + model config
systemd/         # service unit
docs/            # setup walkthroughs
```

---

## Docs

- [01 — Flash the SD card and first boot](docs/01-flash-and-boot.md)
- [02 — Install Hailo stack](docs/02-hailo-install.md)
- [03 — Models (YOLO11s + CLIP HEFs)](docs/03-models.md)
- [04 — Tailscale](docs/04-tailscale.md)
- [05 — Add cameras (RTSP)](docs/05-cameras.md)
- [06 — Web UI](docs/06-ui.md)
- [07 — Troubleshooting](docs/07-troubleshooting.md)
