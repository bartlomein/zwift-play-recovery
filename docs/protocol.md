# Protocol and implementation boundaries

This package uses [Bleak](https://bleak.readthedocs.io/en/latest/) for the BLE central role. It does not emulate a controller or connect to Zwift's servers.

## Discovery

Zwift's observed manufacturer company identifier is 2378. Normal Play payloads with type 02/0e identify right, and 03/0f identify left. Both physical sides in the original failed-update session used type 02 while advertising Nordic Secure DFU FE59, so bootloader side is deliberately unknown. The optional label chosen in the wizard never changes device targeting.

Recovery eligibility requires the observed `Zwift Play` local name, recognized 3- or 7-byte manufacturer payload, and FE59 without a normal application service. Before writing, the selected host-local device ID and exact payload must be rediscovered. Service enumeration must then expose Secure DFU control and packet characteristics. These are identification checks, not cryptographic proof of device identity.

## Transfer

The sender follows Nordic Secure DFU Create/Select/CRC/Execute sequencing. It uses 4096-byte flash objects (the final object may be shorter), 20-byte BLE packets, pacing, and receipt notifications every eight packets. It checks cumulative offset and CRC at receipts and before every object Execute, including the full image before activation. The 512-byte fake-receiver workaround from the investigation is **not** used on real flash.

A fresh signed init starts the transaction; data selection must then report zero offset/CRC and supported object geometry. Device rejection, unexpected packets, mismatched CRC, disconnects and nonzero initial progress stop the attempt. There is no automatic resume, system stage, rollback, Abort, erase/unlock, or retry.

Final Execute success only establishes accepted activation. Recovery is reported only after a normal application advertisement, matching normal serial/manufacturer and firmware readback. A reboot may change the host-local UUID. Failure to find it is recorded as unverified; it is not diagnosed as permanent damage.

## Sources

- [Nordic nRF5 Secure DFU](https://docs.nordicsemi.com/r/bundle/nrf5_sdk_v17.1.0/page/ble_sdk_app_dfu_bootloader.html)
- [Nordic pc-nrfutil](https://github.com/NordicSemiconductor/pc-nrfutil): protocol and signed init format references
- [Nordic iOS DFU Library](https://github.com/NordicSemiconductor/IOS-DFU-Library): sender behavior during the original investigation
- [Bleak scanner API](https://bleak.readthedocs.io/en/latest/api/scanner.html)
- [Bleak macOS behavior and permissions](https://bleak.readthedocs.io/en/latest/backends/macos.html)

The Python transport was adapted from the original local recovery implementation. No vendor firmware source, disassembly, private key, account token or Android binary is included.
