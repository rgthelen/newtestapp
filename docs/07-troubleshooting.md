# 07 — Troubleshooting

## Hailo

**One-shot diagnostic dump**
```bash
./scripts/check-hailo.sh
```
Prints lspci, link speed, dmesg, kernel module + DKMS, /dev/hailo0,
hailortcli identify, package versions, and HEFs — in one screen. Run this
first.

**`hailortcli fw-control identify` says "no device found"**
```bash
lspci -d 1e60:                   # device visible on PCIe?
sudo dmesg | grep -i hailo       # firmware load errors?
lsmod | grep hailo               # driver loaded?
```

Common causes, in order of frequency:

1. **Forgot to reboot** after `dtparam=pciex1_gen=3` was added — the link
   only renegotiates on a cold boot.
2. **EEPROM is old**. Run `sudo rpi-eeprom-update -a && sudo reboot`. Pi 5
   firmware before ~Sep 2024 has PCIe Gen3 stability bugs that show up as
   intermittent "device disappeared" errors.
3. **FFC ribbon reversed or unseated**. Power off, re-seat both ends. The
   blue tab faces the same direction on both sides of the ribbon.
4. **Linked at Gen2 instead of Gen3** — `sudo lspci -vv -d 1e60: | grep
   LnkSta` should show `8GT/s`. If `5GT/s`, `dtparam=pciex1_gen=3` isn't
   taking effect (typo, wrong file, didn't reboot).
5. **3rd-party M.2 carrier** (Pineboards, etc.). The official Pi M.2
   HAT+ Just Works; some 3rd-party HATs need a vendor-specific dtoverlay
   in `config.txt`. Check the HAT vendor's docs.
6. **DKMS didn't rebuild** after a kernel upgrade. Fix:
   ```bash
   sudo dkms autoinstall
   sudo reboot
   ```

**HailoRT version too old for Hailo-10H**
The H10 needs HailoRT ≥ 4.18. Pi's apt repo can lag — see
[docs/02-hailo-install.md](02-hailo-install.md) for the manual .deb
upgrade path.

**HailoRT can't allocate VStreams** / "device busy"
Another process owns the device. Find it:
```bash
sudo lsof /dev/hailo0
```
Our service holds the device exclusively — stop it before running
`hailortcli run` or anything else against the device:
```bash
sudo systemctl stop pi5-hailo-vision
```

**`/dev/hailo0` is owned by root and not user-readable**
```bash
sudo udevadm control --reload-rules && sudo udevadm trigger
ls -l /dev/hailo0     # should be crw-rw-rw-
```
If the udev rule is missing entirely, reinstall: `sudo apt install --reinstall hailo-pci-dkms`.

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
