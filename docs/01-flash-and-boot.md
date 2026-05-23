# 01 — Flash the SD card and first boot

Everything you need from "I just unboxed this" to "the Pi is on my WiFi and
I can SSH to it from my laptop". WiFi-only setup is fully covered — no
ethernet needed.

---

## What you need

**Required**
- Raspberry Pi 5 (16 GB) — earlier Pi models won't work; the Hailo stack
  needs PCIe and Bookworm-on-arm64.
- Raspberry Pi **27 W USB-C PD** power supply (the official one). Cheaper
  supplies will brown out under Hailo load and the Pi will reboot mid-stream.
- microSD card, **64 GB minimum, A2-rated** (e.g. SanDisk Extreme,
  Samsung PRO Endurance). Continuous video workloads kill cheap cards in
  weeks — A2 + Endurance line is the right combo.
- Hailo-10H M.2 HAT (or AI HAT+ with Hailo-8 / 8L — the pipeline auto-detects).
- The **active cooler** (official PoE-style fan + heatsink). Mandatory —
  Hailo-10H + Pi 5 throttles within ~30 s without one.

**Recommended**
- NVMe SSD on the M.2 carrier so the OS isn't on SD long-term (see step 7).
- A laptop on the **same WiFi** you'll put the Pi on (needed for SSH
  discovery on first boot).

> **WiFi note (Pi 5 specific)**: the Pi 5's onboard WiFi supports
> 2.4 GHz + 5 GHz. **5 GHz networks require a regulatory domain to be set**
> (country code), and Pi Imager handles this automatically — but if you skip
> Imager's wizard, 5 GHz WiFi won't associate until you set the country.

---

## 1. Install Raspberry Pi Imager on your laptop

[raspberrypi.com/software](https://www.raspberrypi.com/software/) — Mac,
Windows, Linux. Open it once it's installed.

## 2. Pick the OS and target

| Field | Value |
|---|---|
| **CHOOSE DEVICE** | Raspberry Pi 5 |
| **CHOOSE OS** | *Raspberry Pi OS (64-bit)* — **must be Bookworm** (Imager's current default) |
| **CHOOSE STORAGE** | your SD card |

Do **not** pick Lite — the Hailo stack pulls some packages that resolve
cleanly only against the desktop image's repos on first install. (You can
strip the desktop later if you want; just don't start from Lite.)

## 3. Click the gear icon — pre-configure everything

This is the step that makes the headless boot Just Work.

| Setting | Value |
|---|---|
| **Set hostname** | `vision` |
| **Set username & password** | pick a username + a strong password |
| **Configure wireless LAN** | tick the box, enter your SSID and PSK |
| **Wireless LAN country** | **set this!** — your ISO country code (US, GB, DE, ...) |
| **Locale settings** | your timezone + keyboard layout |
| **Services → Enable SSH** | tick, use **password authentication** for now (we'll switch to Tailscale-brokered SSH later) |

Important details:
- **SSID is case-sensitive**.
- **Hidden SSIDs**: Imager does not handle these reliably; either temporarily
  un-hide the SSID for first boot, or use the post-boot WiFi script
  (`scripts/add-wifi.sh`) and provide ethernet for the very first boot.
- **WPA3-only networks**: should work, but if the Pi doesn't associate, fall
  back to a WPA2/WPA3 transition-mode SSID on your AP.

Now click **WRITE**. Takes ~5 min.

## 4. Insert the SD card and assemble the hardware

Power **off** before:
1. Mount the active cooler.
2. Mount the M.2 HAT carrier on the Pi 5 GPIO and slot the Hailo-10H M.2
   card. FFC ribbon: blue tabs both sides, contacts facing the right way.
   Screws snug — don't over-torque.
3. Insert the SD card.
4. Plug in the USB-C power. The red LED comes on; the green LED starts
   activity-blinking after ~2 s.

## 5. Find the Pi on your network

Allow ~90 s for first boot (filesystem resize + cloudinit + WiFi association).

From your laptop:

```bash
# mDNS — works on any OS with Bonjour / Avahi running
ping -c 3 vision.local
```

If that fails, the Pi probably didn't get on WiFi (common reasons: wrong
PSK, wrong country code, 5 GHz / hidden SSID issue). Fallbacks:

```bash
# (Linux/Mac) scan your ARP cache for new MACs starting "d8:3a:dd"
# or "dc:a6:32" / "e4:5f:01" — those are Raspberry Pi prefixes.
arp -a | grep -iE 'd8:3a:dd|dc:a6:32|e4:5f:01|2c:cf:67|b8:27:eb'

# Or sweep your subnet for SSH
nmap -p 22 --open 192.168.1.0/24
```

You can also open the Raspberry Pi Imager → menu → **Choose a Pi** to find
it on the local network.

If you still can't find it: connect a monitor + USB keyboard temporarily,
log in, and run the WiFi helper (next section).

## 6. First SSH

```bash
ssh <user>@vision.local
```

(Replace `<user>` with whatever you set in Imager.)

First-time host key — type `yes` to accept. You should be at a Bash prompt.

### Update + reboot

```bash
sudo apt update && sudo apt full-upgrade -y
sudo reboot
```

Wait ~30 s, reconnect:

```bash
ssh <user>@vision.local
```

## 7. Enable PCIe Gen3 (REQUIRED for Hailo throughput)

The M.2 HAT defaults to PCIe Gen2 (~5 GT/s). For both Hailo-8 family and
Hailo-10H you want Gen3 — without it you'll see noticeable inference
slowdowns and dropped frames.

```bash
sudo sed -i '/^dtparam=pciex1_gen=3/d' /boot/firmware/config.txt
echo 'dtparam=pciex1_gen=3' | sudo tee -a /boot/firmware/config.txt
sudo reboot
```

After reboot, verify:

```bash
sudo lspci -vv 2>/dev/null | grep -iE "hailo|lnksta"
```

Look for `LnkSta: Speed 8GT/s` — that's Gen3.

> The installer (`scripts/01-system-setup.sh`) does this for you, but if
> you'd like to confirm the Pi survives Gen3 before installing the rest of
> the stack, do it here first.

## 8. (Optional) Boot from NVMe instead of SD

Strongly recommended for any long-term deployment. SD cards die under the
continuous write load of snapshots + logs.

1. Clone the SD to NVMe: in the Pi's GUI session, use **SD Card Copier**
   (Accessories menu). Or headless:
   ```bash
   sudo rpi-clone nvme0n1
   ```
2. Set boot order: `sudo raspi-config` → Advanced Options → Boot Order →
   *NVMe / USB Boot*.
3. Power off, remove the SD card, power on. The Pi boots from NVMe.

## 9. (Optional) Set a static IP

You don't need this if you're using Tailscale — your Pi will always be
`vision` on your tailnet. But for plain LAN access:

```bash
sudo nmcli con mod "preconfigured" \
    ipv4.method manual \
    ipv4.addresses 192.168.1.50/24 \
    ipv4.gateway 192.168.1.1 \
    ipv4.dns "1.1.1.1 8.8.8.8"
sudo nmcli con down "preconfigured" && sudo nmcli con up "preconfigured"
```

Replace `preconfigured` with the connection name shown by `nmcli con show`
if different.

---

## Adding / changing WiFi networks after first boot

Use the helper script in this repo:

```bash
./scripts/add-wifi.sh "MyOtherSSID" "the-password"
```

It wraps `nmcli` (Bookworm uses NetworkManager) and:

- Adds the network without removing your existing one — the Pi will
  auto-reconnect to whichever is in range.
- Sets the country code if it wasn't already configured.
- Works for both 2.4 GHz and 5 GHz networks.

To remove a network:
```bash
sudo nmcli con delete "MyOtherSSID"
```

To list known networks:
```bash
nmcli con show
```

To scan available networks:
```bash
nmcli device wifi list
```

---

## What's next

You now have a Pi 5 on WiFi, SSH-able, with PCIe Gen3 enabled.

Continue with **[02 — Install the Hailo stack](02-hailo-install.md)**, or
just run the one-shot installer that wraps every step from here on out:

```bash
git clone https://github.com/rgthelen/newtestapp.git ~/pi5-hailo-vision
cd ~/pi5-hailo-vision
./scripts/install-all.sh
```

If anything goes sideways, [docs/07-troubleshooting.md](07-troubleshooting.md)
covers the common failure modes.
