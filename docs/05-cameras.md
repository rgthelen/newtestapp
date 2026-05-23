# 05 — Add cameras (RTSP)

Edit `~/.config/pi5-hailo-vision/cameras.yaml` (created on first run by
`install-all.sh` from `config/cameras.example.yaml`).

```yaml
cameras:
  - id: driveway
    name: Driveway
    url: rtsp://user:pass@192.168.1.20:554/Streaming/Channels/101
    transport: tcp           # tcp (reliable) or udp (lower latency)
    resolution: [1920, 1080] # optional, downsample at decode
    fps: 15                  # target FPS to pull from camera
    detect:
      enabled: true
      min_confidence: 0.45
      classes: [person, car, truck, bicycle, dog, cat]
    track:
      enabled: true
      max_age: 30            # frames to keep a lost track
    clip_index:
      enabled: true
      every_n_frames: 30     # embed 1 frame/sec at 30fps
      only_when_tracking: true

  - id: backyard
    name: Backyard
    url: rtsp://user:pass@192.168.1.21:554/Streaming/Channels/101
    transport: tcp
    detect: { enabled: true, min_confidence: 0.4 }
    track: { enabled: true }
    clip_index: { enabled: true, every_n_frames: 60 }
```

## RTSP URL by vendor

- **Hikvision/Annke**: `rtsp://user:pass@IP:554/Streaming/Channels/101` (main),
  `…/102` (sub-stream)
- **Reolink**: `rtsp://user:pass@IP:554/h264Preview_01_main`
- **Amcrest/Dahua**: `rtsp://user:pass@IP:554/cam/realmonitor?channel=1&subtype=0`
- **Unifi Protect**: `rtsps://IP:7441/<stream-id>` (enable RTSPS per camera in
  the Protect UI)

**Tip**: for AI you usually want the **sub-stream** (lower res, lower bitrate).
A 720p 15fps sub-stream is plenty for YOLO and saves ~80% of decode CPU.

## Test a stream first

```bash
ffplay -rtsp_transport tcp rtsp://user:pass@IP:554/...
```
or for headless validation:
```bash
ffprobe -rtsp_transport tcp rtsp://... 2>&1 | head -30
```

## Reload without restart

```bash
curl -X POST http://localhost:8080/api/cameras/reload
```

The pipeline hot-reloads on config changes — no `systemctl restart` needed.
