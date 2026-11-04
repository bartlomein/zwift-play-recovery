"""One explicitly selected controller per transaction; verified reboot required."""
import asyncio
from datetime import datetime, timezone
import json
from pathlib import Path
import uuid

from bleak import BleakClient

from .constants import RecoveryError
from .devices import scan, same_bootloader, verify_after_reboot
from .firmware import validate
from .transport import Transport, Uploader


class Session:
    def __init__(self, directory, callback=None):
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        self.folder = Path(directory).expanduser() / (stamp + "-" + uuid.uuid4().hex[:8])
        self.folder.mkdir(parents=True, exist_ok=False)
        self.callback = callback

    def __call__(self, event, show=False, **details):
        row = {"time": datetime.now(timezone.utc).isoformat(), "event": event, **details}
        with (self.folder / "events.jsonl").open("a", encoding="utf-8") as out:
            out.write(json.dumps(row) + "\n")
        if show and self.callback:
            self.callback(event, details)

    def save(self, result):
        (self.folder / "result.json").write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")


def confirmation_text(target):
    if not target.eligible or not target.suffix:
        raise RecoveryError("This is not a confirmed Play recovery candidate. No firmware will be sent.")
    return "FLASH " + target.suffix


async def recover(target, firmware, confirmation, session, label=None):
    if confirmation != confirmation_text(target):
        raise RecoveryError("Confirmation did not match the selected controller. Nothing was sent.")
    # Validate again immediately before any BLE write, even for library callers.
    firmware = validate(firmware.image, firmware.init)
    result = {"selected_device": target.record(), "user_label": label,
              "firmware": firmware.record(), "state": "preflight", "recovered": False,
              "system_stage_written": False, "physical_button_test": "Not tested"}
    client = None
    try:
        session("preflight", show=True, target=target.record())
        candidates = [c for c in await scan(5) if same_bootloader(target, c)]
        if len(candidates) != 1:
            raise RecoveryError("The selected controller changed or disappeared. Scan again; nothing was sent.")
        current = candidates[0]
        disconnected = asyncio.Event()
        client = BleakClient(current.device, timeout=20, pair=False,
                             disconnected_callback=lambda _: disconnected.set())
        await asyncio.wait_for(client.connect(), 25)
        transport = Transport(client, disconnected, session)
        await transport.start()
        uploader = Uploader(transport, session)
        result["state"] = "sending_signed_header"
        session.save(result)
        await uploader.init("application", firmware.init)
        result["state"] = "transferring"
        session.save(result)
        await uploader.firmware("application", firmware.image)
        result["state"] = "transferred_verification_pending"
        result["application_bytes_transferred"] = len(firmware.image)
        session.save(result)
        await client.disconnect()
        client = None
        await asyncio.sleep(3)
        session("verifying_reboot", show=True)
        verification = await verify_after_reboot(target, firmware.version)
        result.update(state="verified", recovered=True, verification=verification)
        session("recovery_verified", show=True, version=firmware.version,
                side=verification["device"]["side"], suffix=target.suffix,
                battery=verification["values"].get("battery"))
    except asyncio.CancelledError:
        result["error"] = "Interrupted. Device state is uncertain; no automatic retry was started."
        session("interrupted", error=result["error"])
        raise
    except Exception as error:
        result["error"] = f"{type(error).__name__}: {error}"
        session("stopped", show=True, message=str(error) or "Bluetooth timed out.")
    finally:
        if client is not None:
            try:
                await asyncio.wait_for(client.disconnect(), 10)
            except Exception as error:
                session("disconnect_cleanup", detail=str(error))
        session.save(result)
    return result
