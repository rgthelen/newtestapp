# 02 — Install the Hailo stack

The Pi 5 + Hailo stack has three layers, all installed by
`scripts/02-install-hailo.sh`:

| Layer | Package | What it does |
|---|---|---|
| Kernel driver | `hailo-pci-dkms` | DKMS-built `hailo_pci` module — talks to the M.2 device over PCIe. Rebuilds automatically on kernel upgrades. |
| Userspace runtime | `hailort` | `libhailort.so` + `hailortcli`. Loads HEFs, manages inference streams. |
| Device firmware | `hailofw` | Firmware blob — the device is volatile and re-flashes on every boot from this blob. |
| Python bindings | `python3-hailort` | The `hailo_platform` Python module our app uses. |
| GStreamer plugins | `hailo-tappas-core` | Hailo's GStreamer elements. Not used by our Python pipeline but handy for rpicam tooling. |

These all come from Raspberry Pi's apt repo via the `hailo-all` metapackage.
The installer pins each, verifies the kernel module built, the PCIe device
enumerates at Gen3, the firmware booted cleanly, and that the device
responds to `hailortcli`.

## Hailo-10H specifics

The Hailo-10H needs **HailoRT ≥ 4.18**. Raspberry Pi's apt occasionally
lags. The installer detects this and tells you when an upgrade is needed:

> ⚠ Detected Hailo-10H but HailoRT 4.16 is older than the minimum
> recommended for H10 (4.18).

If you hit that, grab the latest .deb bundle from
[hailo.ai/developer-zone](https://hailo.ai/developer-zone/software-downloads/)
(login required — Hailo doesn't run a public apt mirror). Download the
arm64 .debs:

- `hailort_X.Y.Z_arm64.deb`
- `hailort-pcie-driver_X.Y.Z_all.deb` (or `hailo-pci-dkms_X.Y.Z_all.deb`)
- `python3-hailort_X.Y.Z_arm64.deb`

Then:

```bash
sudo apt remove --purge hailort hailo-all python3-hailort
sudo dpkg -i hailort_*.deb hailort-pcie-driver_*.deb python3-hailort_*.deb
sudo apt -f install
sudo reboot
```

## Verify

Anytime you suspect a Hailo issue, run:

```bash
./scripts/check-hailo.sh
```

It prints a one-screen diagnostic dump covering:

- Pi 5 model + kernel + EEPROM version
- `/boot/firmware/config.txt` PCIe lines
- `lspci` link state for the Hailo device (you want Gen3 = 8GT/s)
- `hailo_pci` kernel module + DKMS build state for the current kernel
- `dmesg` lines mentioning hailo or the PCIe slot
- `/dev/hailo0` existence and permissions
- `hailortcli fw-control identify` + `hailortcli scan`
- Installed `hailo*` package versions
- HEFs present in `~/.local/share/pi5-hailo-vision/models/`

Paste that into a troubleshooting thread and the answer is usually obvious
within a few lines.

## What "good" looks like

```
$ ./scripts/check-hailo.sh

  system
  host:       vision
  model:      Raspberry Pi 5 Model B Rev 1.0
  kernel:     6.6.51+rpt-rpi-2712
  eeprom:     Tue 24 Sep 16:18:38 UTC 2024

  lspci -nn -d 1e60:
  0000:01:00.0 Co-processor [0b40]: Hailo Technologies Ltd. Hailo-10H AI Processor [1e60:45c4]

  link speed
  LnkSta:  Speed 8GT/s, Width x1

  /dev/hailo*
  crw-rw-rw- 1 root root 510, 0 May 23 18:12 /dev/hailo0

  hailortcli
  Device: 0000:01:00.0
  Board Name: HAILO-10H
  Serial Number: HLDDLBB...
  Firmware Version: 4.20.0
```

If your dump doesn't look like that, jump to
[docs/07-troubleshooting.md](07-troubleshooting.md) — the failure mode is
usually one of:

- EEPROM out of date (Pi 5 + PCIe Gen3 stability bugs in older firmware)
- Forgot to reboot after enabling `dtparam=pciex1_gen=3`
- 3rd-party M.2 carrier that needs an extra `dtoverlay`
- DKMS didn't rebuild after a kernel upgrade

Next: [03 — Download models](03-models.md).
