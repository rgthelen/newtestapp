# 07 — Troubleshooting

## Hailo

**`hailortcli fw-control identify` says "no device found"**
```bash
lspci | grep -i hailo            # device visible on PCIe?
sudo dmesg | grep -i hailo       # firmware load errors?
sudo modprobe hailo_pci          # driver loaded?
```
99% of "no device" reports are PCIe Gen3 cabling/seating — re-seat the FFC
ribbon and confirm `dtparam=pciex1_gen=3` is in `/boot/firmware/config.txt`.

**HailoRT can't allocate VStreams**
Another process owns the device. Find it:
```bash
sudo lsof /dev/hailo0
```
Our service holds the device exclusively — stop it before running
`hailortcli run` manually:
```bash
sudo systemctl stop pi5-hailo-vision
```

## RTSP

**Stream drops every few seconds / artifacting**
Switch transport from `udp` to `tcp` in `cameras.yaml`. WiFi is lossy and UDP
will tear.

**High latency (5+ seconds behind real time)**
Use the camera's sub-stream (lower bitrate) and set `latency: 0` in the
GStreamer source — already the default in `app/pipeline/rtsp_source.py`. Also
check that the camera and Pi are on the same WiFi band/AP.

## Performance

**FPS is way below expected**
```bash
# inference-side fps (Hailo)
hailortcli run ~/.local/share/pi5-hailo-vision/models/yolov11s.hef --measure-fps

# pipeline-side fps (visible in UI top bar)
curl http://localhost:8080/api/stats
```
If Hailo FPS is high but pipeline FPS is low → bottleneck is decode/CPU.
Try sub-streams, lower per-camera FPS, or fewer cameras.

**Pi 5 throttling**
```bash
vcgencmd measure_temp
vcgencmd get_throttled         # 0x0 is good; anything else = throttling
```
Active cooler is mandatory under load.

## UI

**WebSocket disconnects from Tailscale**
Tailscale has a 60s idle timeout for some clients. The UI auto-reconnects
(see `app/ui/app.js` → `connectWs`) — if you see flicker, that's the
reconnect (~200ms gap).

## Logs

```bash
journalctl -u pi5-hailo-vision -f --since "10 min ago"
```

App also writes structured JSON logs to
`~/.local/state/pi5-hailo-vision/logs/pi5-hailo-vision.log`.
