# 01 — Flash the SD card and first boot

## You need
- Raspberry Pi 5 (16GB)
- Hailo-10H M.2 HAT (or AI HAT+ with Hailo-8/8L — pipeline auto-detects)
- 64GB+ SD card (A2 rated) or, better, an NVMe SSD on the M.2 HAT carrier
- USB-C 27W PSU, ethernet for first boot

## 1. Pi Imager
1. Install [Raspberry Pi Imager](https://www.raspberrypi.com/software/) on your laptop.
2. Choose:
   - **Device**: Raspberry Pi 5
   - **OS**: Raspberry Pi OS (64-bit) — **Bookworm** (the Hailo stack requires it)
   - **Storage**: your SD/NVMe
3. Click the gear icon and pre-configure:
   - hostname: `vision`
   - user/password
   - WiFi SSID/PSK (so the Pi can be SSH'd to immediately)
   - enable SSH (use password auth for now; we'll lock down via Tailscale later)
4. Write the image.

## 2. First boot
1. Slot the Hailo-10H HAT before powering up (FFC cable + M.2 slot, screws snug — don't over-torque).
2. Boot the Pi. Wait ~90s for cloudinit to settle.
3. From your laptop:
   ```bash
   ssh <user>@vision.local
   ```
4. Update + reboot:
   ```bash
   sudo apt update && sudo apt full-upgrade -y
   sudo reboot
   ```

## 3. Enable PCIe Gen3 (important for Hailo throughput)
The AI HAT runs at PCIe Gen2 by default. For Hailo-8/8L and especially Hailo-10H, force Gen3:

```bash
sudo nano /boot/firmware/config.txt
```
Add at the bottom:
```
dtparam=pciex1_gen=3
```
Reboot:
```bash
sudo reboot
```

Verify the M.2 link came up at Gen3:
```bash
sudo lspci -vv | grep -iE "hailo|lnksta"
```
You should see `LnkSta: Speed 8GT/s` (Gen3).

## 4. Optional but recommended
- **Boot from NVMe** instead of SD: `sudo raspi-config` → Advanced → Boot Order → NVMe first. SD cards will eventually corrupt under continuous video write workloads.
- **Active cooler**: the Hailo-10H + Pi 5 will throttle without one.

Next: [02 — Install the Hailo stack](02-hailo-install.md).
