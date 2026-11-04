# Contributing

Start with the offline tests and demo. Use `scan` or `inspect` for physical diagnostics. A real firmware transfer requires the device owner's explicit authorization and must remain limited to the selected controller.

Preserve these boundaries:

- Unknown firmware and unconfirmed device types are rejected; do not add force or signature-bypass flags.
- Bootloader advertisements do not establish left/right. Never target a device by a guessed side, strongest RSSI or list position saved from an earlier scan.
- A completed transfer is not a verified recovery. Check the rebooted device's identity and firmware before reporting success.
- Do not commit firmware, captures, disassemblies, private keys, account information, hardware serials or raw nearby-device inventories. Use fictional fixtures.
- New firmware support needs documented provenance, permission assessment, metadata/signature checks and independent hardware validation. Do not simply remove the fingerprint allowlist.

Tests use `unittest` and synthetic signed fixtures generated at runtime. To run them: `python -m unittest discover -s tests -v`.
