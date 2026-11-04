# Validation record

## Original procedure

On November 3, 2026, four failed-update Play controllers were examined on macOS. The signed 2.0.1 application was accepted by all four. Three subsequently exposed normal services with matching serials and firmware 2.0.1. One remained unreachable; a normal power press, 30-second hold and known-working charger produced no LED response. The cause is unresolved. This small set is not a population success-rate estimate.

The two right controllers and one left controller verified successfully. Separate captures for left and right supplied the identical signed application. No system/bootloader stage was flashed. Physical gameplay/button operation was not verified by these tools.

## Packaged CLI

Validated locally on macOS with Python 3.14.6, Bleak 3.0.2 and cryptography 50.0.2:

- 30 offline tests pass, including synthetic signed firmware, wrong-device selection, CRC failures, signature rejection, cancellation and post-transfer verification failure.
- Installation into a fresh project virtual environment succeeds; the installed command, help, demo and machine-readable demo output work.
- The private captured package passes hash, metadata, init signature and application boot signature checks through the packaged command. Firmware remains outside the repository.
- A real 30-second read-only BLE scan completes. It identifies the nearby Zwift Hub as inspect-only and ineligible for recovery. No Play controller was advertising during this particular scan.
- A source distribution and wheel build successfully. The GitHub Actions matrix is prepared but has not run remotely.

No additional controller was flashed, reset or written to during packaging. Real Play selection, GATT reads and full recovery with this packaged CLI remain to be validated separately. Do not equate simulated tests with real-device flashing of the refactored package. Windows and Linux hardware operation remain untested.
