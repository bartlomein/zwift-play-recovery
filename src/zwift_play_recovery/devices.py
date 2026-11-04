"""Discovery and read-only identification. This module never writes GATT."""
import asyncio
from dataclasses import dataclass, field
import re
from typing import Any

from bleak import BleakClient, BleakScanner

from .constants import COMPANY, DFU, ZAP, ZAP_V2, READABLE, RecoveryError


@dataclass
class Controller:
    address: str
    name: str
    rssi: int
    services: tuple[str, ...]
    payload: bytes
    mode: str
    side: str | None
    suffix: str | None
    eligible: bool
    device: Any = field(default=None, repr=False, compare=False)

    def record(self):
        return {"id": self.address, "name": self.name, "rssi_dbm": self.rssi,
                "services": list(self.services), "manufacturer_payload": self.payload.hex(),
                "mode": self.mode, "side": self.side, "suffix": self.suffix,
                "recovery_candidate": self.eligible}


def classify(device, advertisement):
    name = advertisement.local_name or device.name or "Unnamed device"
    services = tuple(sorted(s.lower() for s in advertisement.service_uuids))
    raw = bytes(advertisement.manufacturer_data.get(COMPANY, b""))
    # A name, a Nordic service, or Zwift company ID alone is not proof of model.
    if not (raw or DFU in services or re.search(r"zwift|nordic|\bplay\b|\bleft\b|\bright\b", name, re.I)):
        return None
    suffix = raw[-2:].hex().upper() if len(raw) in (3, 7) else None
    normal = ZAP in services or ZAP_V2 in services
    mode, side, eligible = "Other / unconfirmed model", None, False
    if normal and len(raw) in (3, 7) and raw[0] in (2, 3, 14, 15) and DFU not in services:
        mode = "Normal"
        side = "Left" if raw[0] in (3, 15) else "Right"
    elif DFU in services:
        mode = "Recovery"
        # Both physical sides advertised 02 in recovery. Never infer side here.
        eligible = (name.strip().lower() == "zwift play"
                    and len(raw) in (3, 7) and raw[0] == 2 and not normal)
    return Controller(device.address, name, advertisement.rssi, services, raw,
                      mode, side, suffix, eligible, device)


async def scan(seconds=30):
    seen = {}

    def found(device, advertisement):
        item = classify(device, advertisement)
        if item is not None:
            seen[item.address] = item

    async with BleakScanner(detection_callback=found):
        await asyncio.sleep(seconds)
    return sorted(seen.values(), key=lambda c: (-c.rssi, c.address))


def choose_identifier(controllers, identifier):
    matches = [c for c in controllers if c.address.upper() == identifier.upper()
               or c.suffix == identifier.upper()]
    if len(matches) != 1:
        raise RecoveryError("That device ID is missing or ambiguous. Scan again and use its full ID.")
    return matches[0]


def same_bootloader(original, current):
    return (original.eligible and current.eligible
            and original.address.upper() == current.address.upper()
            and original.payload == current.payload)


def normal_candidate(original, candidate):
    return (candidate.mode == "Normal" and original.suffix == candidate.suffix
            and candidate.suffix is not None)


async def inspect(controller):
    async with BleakClient(controller.device, timeout=20, pair=False) as client:
        values = {}
        for label, uuid in READABLE.items():
            char = client.services.get_characteristic(uuid)
            if char is not None and "read" in char.properties:
                raw = bytes(await asyncio.wait_for(client.read_gatt_char(char), 15))
                values[label] = (raw[0] if len(raw) == 1 else None) if label == "battery" else raw.decode("utf-8", errors="replace").rstrip("\0")
        services = [s.uuid for s in client.services]
        return {"device": controller.record(), "values": values, "services": services,
                "characteristics": [{"service": s.uuid, "uuid": c.uuid, "properties": list(c.properties)}
                                    for s in client.services for c in s.characteristics]}


def application_verified(original, result, version):
    services, values = result["services"], result["values"]
    serial = re.fullmatch(r"(02|03)-([0-9A-F]{12})", values.get("serial", "").upper())
    if not serial or not original.suffix:
        return False
    identity = serial.group(2)
    if len(original.payload) == 7 and identity != original.payload[1:].hex().upper():
        return False
    advertised_side = result["device"]["side"]
    reported_side = "Left" if serial.group(1) == "03" else "Right"
    return (bool({ZAP, ZAP_V2}.intersection(services)) and DFU not in services
            and identity.endswith(original.suffix) and advertised_side == reported_side
            and values.get("firmware") == version and values.get("manufacturer") == "Zwift Inc")


async def verify_after_reboot(original, version, timeout=90):
    candidates = {}
    ready = asyncio.Event()

    def found(device, advertisement):
        candidate = classify(device, advertisement)
        if candidate and normal_candidate(original, candidate):
            candidates[candidate.address] = candidate
            ready.set()

    try:
        async with BleakScanner(detection_callback=found):
            await asyncio.wait_for(ready.wait(), timeout)
            await asyncio.sleep(2)
    except TimeoutError:
        raise RecoveryError("Transfer completed, but the controller was not found after reboot. Recovery is UNVERIFIED; do not assume it failed or reflash automatically.") from None
    if len(candidates) != 1:
        raise RecoveryError("More than one matching identity appeared after reboot. Recovery is UNVERIFIED.")
    result = await inspect(next(iter(candidates.values())))
    if not application_verified(original, result, version):
        raise RecoveryError("The rebooted device's identity or firmware did not match. Recovery is UNVERIFIED.")
    return result
