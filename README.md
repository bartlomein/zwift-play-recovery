# Zwift Play Recovery

A guided command-line tool for finding Zwift Play controllers and attempting recovery when a failed update leaves them in Bluetooth recovery mode.

**Experimental and unofficial.** The original procedure restored firmware operation on three of four controllers in one session. The fourth accepted the application but remained unresponsive; its cause is unknown. Button/gameplay operation was not verified by the tool. This is not a general firmware updater or a guaranteed repair.

Firmware is **not included**. Public distribution permission has not been established. See [firmware and publication](docs/firmware.md) before sharing a release.

## Start here

Install [Python 3.11 or newer](https://www.python.org/downloads/). Open Terminal in this repository folder, then run:

```sh
python3 -m venv .venv
source .venv/bin/activate
python -m pip install .
zwift-play
```

On Windows, use `py -m venv .venv` and `.venv\Scripts\Activate.ps1` instead of the first two lines. Windows and Linux hardware operation are **not yet tested**; macOS is the initial hardware-tested platform. Bluetooth permission belongs to the terminal or app running Python.

If you already use [uv](https://docs.astral.sh/uv/), run `uv run zwift-play` from this folder. No PyPI package or hosted GitHub repository is assumed by these instructions.

Preview the interface without connecting to anything:

```sh
zwift-play --demo
```

```text
  #  Controller                 State                     Signal
  -- -------------------------- ------------------------- ------
  1  Left A101                  Normal                    -49 dBm
  2  Side unknown B202          Recovery                  -57 dBm

Choose a controller number, or q to quit:
```

The demo uses fictional devices and never accesses Bluetooth.

## What the wizard does

1. Scans for nearby devices for 30 seconds.
2. Shows normal controllers as Left/Right when their advertisement identifies the side. Recovery-mode devices may say **Side unknown**; match their suffix with the product label or Companion. A user-supplied side label is not treated as verified identity.
3. Lets you inspect a controller without writing anything, or choose recovery for an eligible Play bootloader.
4. Checks your local firmware file and shows the exact target before asking you to type `FLASH` plus its four-character suffix.
5. Transfers one signed application and reads the controller's identity and running version after reboot. Another controller requires a separate run and confirmation.

Close Zwift and Companion before recovering. Keep the selected controller charged, powered, and near the computer. A wrong or interrupted update can leave it unusable. The program does not start a firmware transfer merely because a controller is discovered.

## Commands

| Command | What it does |
| --- | --- |
| `zwift-play` | Interactive scan, selection and recovery wizard |
| `zwift-play scan --details` | Read-only names, side, device IDs, RSSI, services and advertisement data |
| `zwift-play inspect --device B202` | Read-only services and available firmware/serial/battery values |
| `zwift-play firmware /path/to/update.zip` | Validate a local supported firmware package; no Bluetooth access |
| `zwift-play recover --device B202 --firmware /path/to/update.zip` | Recover one controller, still requiring interactive confirmation |

`zwift-play doctor` checks Bluetooth scanning. `zwift-play scan --json` produces structured output. Scan duration can be changed with `--seconds 10`. A four-character suffix must be unique; otherwise use the full ID from the list. On macOS, that ID is a local Bluetooth UUID, not the controller's MAC address.

## Supported firmware and device state

Version 0.1 accepts only the exact documented **Zwift Play 2.0.1 / RC1 application** and its matching signed init packet. It checks their pinned SHA-256 fingerprints, signed metadata, init signature and application boot signature. Unknown versions, modifications and incomplete captures are rejected. The reference verification key came from a captured bootloader and is not a vendor-published trust anchor; real-device signature/compatibility checks are not bypassed.

Provide a local Nordic ZIP containing `manifest.application`, or a directory containing `application.bin` and `application.dat`. Only the application is used, even if a ZIP contains system components. It does not install bootloader/SoftDevice updates, force normal controllers into DFU, bypass protection, reset hardware, resume partial transfers, or automatically retry. A controller rejecting the image is left for investigation.

The exact target must still advertise the same Bluetooth ID, Zwift manufacturer payload, Play name and Secure DFU service immediately before connecting. After reboot, its Bluetooth ID can change; the program checks the identity suffix and, when known, the full hardware identity against the normal-mode serial, as well as firmware version and manufacturer. A two-byte suffix is not globally unique; multiple matching normal advertisements cause verification to stop.

## When it cannot help

- No light and no discoverable Bluetooth signal: this tool has no connection through which to recover the device.
- A different Zwift product, Nordic development board, or unconfirmed device model: inspect-only, never selected automatically for flashing.
- Normal firmware is running: read the details and use Companion for ordinary updates.
- Transfer completed but verification timed out: **recovery is unverified**, not a confirmed failed flash. Check power, other connections and the report before attempting anything else.
- Unsupported firmware or a missing firmware file: ask Zwift for an authorized recovery package. This repo does not download firmware, authenticate to Zwift, or capture Companion traffic.

Reports are saved locally in `~/.zwift-play-recovery/reports/`. Override with `--reports ./reports`. They include selected-device identifiers and transfer diagnostics; review them before sharing. Reports do not contain firmware bytes or unrelated nearby-device inventories.

## Development

```sh
python -m pip install -e .
python -m unittest discover -s tests -v
```

Tests simulate controllers and signed test images. They never require a radio or real firmware. Hardware validation of the packaged CLI should start with `doctor`, `scan`, and `inspect`; tests passing does not establish a successful physical recovery.

Exit codes: 0 completed/cancelled safely, 1 no relevant devices, 2 error or recovery not verified, 130 interrupted. Recovery requires an interactive terminal and has no unattended `--yes` option.

## Project status

The transfer algorithm was exercised on real hardware during the original investigation. The packaged CLI has a separate [validation record](docs/validation.md). The source is MIT-licensed; that license does not cover Zwift firmware, trademarks, or third-party code. The project is not affiliated with or endorsed by Zwift.

See [protocol notes](docs/protocol.md), [firmware and publication](docs/firmware.md), and [contributing](CONTRIBUTING.md).
