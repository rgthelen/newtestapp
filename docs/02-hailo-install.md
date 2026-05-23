# 02 — Install the Hailo stack

The Pi 5 + Hailo stack has three layers:

1. **Kernel driver** (`hailo_pci`) — kernel module that talks to the M.2 device
2. **HailoRT** — userspace runtime + `hailortcli`
3. **HailoRT Python bindings** + GStreamer plugins for the pipeline

Our `scripts/02-install-hailo.sh` handles all three by installing Raspberry Pi's pre-packaged `hailo-all` (the easiest path on Bookworm).

## What the installer does

```bash
sudo apt install -y hailo-all
```

This package (maintained by Raspberry Pi) pulls in:
- `hailo-pci-dkms` (kernel driver)
- `hailort` (runtime + CLI)
- `hailort-pcie-driver`
- `python3-hailort`
- `hailo-tappas-core` (GStreamer plugins)
- `rpicam-apps` Hailo post-processing

## Verify

After install + reboot, run:

```bash
hailortcli fw-control identify
```

You should see something like:
```
Device: 0000:01:00.0
Board Name: HAILO-10H
Serial Number: ...
Firmware Version: 4.x.x
```

If you get "device not found":
- check `lspci | grep -i hailo` (device on PCIe bus?)
- check `lsmod | grep hailo` (driver loaded?)
- `sudo dmesg | grep hailo` (firmware errors?)
- see `docs/07-troubleshooting.md`

## Note on Hailo-10H vs Hailo-8/8L

The installer + our pipeline support all three. The architecture mostly differs in:
- TOPS (10H ≈ 40 TOPS @ INT4, 8 ≈ 26 TOPS, 8L ≈ 13 TOPS)
- HEF compatibility — **HEF files must be compiled for your specific architecture**. Our `scripts/04-download-models.sh` will detect your device and pull the right ones.

Next: [03 — Download models](03-models.md).
