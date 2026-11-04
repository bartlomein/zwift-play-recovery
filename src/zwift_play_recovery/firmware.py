"""Load a local package; preserve and verify the exact supported signed image."""
from dataclasses import dataclass
import hashlib
import json
from pathlib import Path, PurePosixPath
import zipfile

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import ec, utils

from .constants import RecoveryError

IMAGE_HASH = "73f09fd1c5721b2ed7498d486387f23711af9abfdd7f3762ef29ae1f112c0333"
INIT_HASH = "b3f39184069c2c8c30edbc9f6822880d000c9501b0429e2e6962cf757d7f8cdb"
PUBLIC_X = int("b895108746a6c8ad79bc55ba0dea6240ec350f4cd8633b1fcdf71bc74baedb19", 16)
PUBLIC_Y = int("ac642462cca9fffcc0ac440470fdbc3da7521926922f99287b46aa542a2a92e0", 16)
MAX_IMAGE = 2 * 1024 * 1024


@dataclass(frozen=True)
class Firmware:
    image: bytes
    init: bytes
    version: str = "2.0.1"

    def record(self):
        return {"version": self.version, "image_bytes": len(self.image),
                "sha256": hashlib.sha256(self.image).hexdigest(),
                "init_sha256": hashlib.sha256(self.init).hexdigest(),
                "hardware_id": "RC1", "signed_application_only": True}


def fields(data):
    if not isinstance(data, (bytes, bytearray)):
        raise ValueError("Missing protobuf message")
    pos = 0

    def varint():
        nonlocal pos
        result = 0
        for shift in range(0, 70, 7):
            if pos >= len(data):
                raise ValueError("Truncated protobuf")
            byte = data[pos]; pos += 1
            if shift == 63 and byte > 1:
                raise ValueError("Oversized protobuf integer")
            result |= (byte & 127) << shift
            if not byte & 128:
                return result
        raise ValueError("Oversized protobuf integer")

    result = []
    while pos < len(data):
        key = varint(); number, wire = key >> 3, key & 7
        if not 0 < number <= 0x1fffffff:
            raise ValueError("Invalid protobuf field")
        if wire == 0:
            value = varint()
        elif wire in (1, 2, 5):
            size = varint() if wire == 2 else (8 if wire == 1 else 4)
            if size > len(data) - pos:
                raise ValueError("Truncated protobuf field")
            value = data[pos:pos + size]; pos += size
        else:
            raise ValueError("Unsupported protobuf field")
        result.append((number, wire, value))
    return result


def value(message, number, wire, default=None):
    matches = [v for n, w, v in message if n == number and w == wire]
    if len(matches) > 1:
        raise ValueError("Duplicate singular protobuf field")
    return matches[0] if matches else default


def signature(raw):
    if not isinstance(raw, bytes) or len(raw) != 64:
        raise ValueError("Expected 64-byte ECDSA signature")
    return utils.encode_dss_signature(int.from_bytes(raw[:32], "little"), int.from_bytes(raw[32:], "little"))


def validate(image, init):
    # A signature alone is not sufficient evidence of supported compatibility.
    if hashlib.sha256(image).hexdigest() != IMAGE_HASH or hashlib.sha256(init).hexdigest() != INIT_HASH:
        raise RecoveryError("Unsupported or modified firmware. This release accepts only the documented Play 2.0.1 application and matching signed header.")
    try:
        signed = fields(value(fields(init), 2, 2))
        if value(signed, 2, 0) != 0:
            raise ValueError("Unsupported signature type")
        command = fields(value(signed, 1, 2))
        if value(command, 1, 0, 1) != 1:
            raise ValueError("Expected INIT command")
        message = value(command, 2, 2)
        info = fields(message)
        digest = fields(value(info, 8, 2))
        if (value(info, 1, 0) != 0x02000001 or value(info, 2, 0) != 0x524331
                or value(info, 4, 0, 0) != 0 or value(info, 5, 0, 0) != 0
                or value(info, 6, 0, 0) != 0 or value(info, 7, 0) != len(image)
                or value(info, 9, 0, 0) != 0 or value(digest, 1, 0) != 3
                or value(digest, 2, 2) != hashlib.sha256(image).digest()[::-1]):
            raise ValueError("Signed metadata does not match the supported application")
        key = ec.EllipticCurvePublicNumbers(PUBLIC_X, PUBLIC_Y, ec.SECP256R1()).public_key()
        key.verify(signature(value(signed, 3, 2)), message, ec.ECDSA(hashes.SHA256()))
        boot_signatures = [fields(v) for n, w, v in info if n == 10 and w == 2]
        if len(boot_signatures) != 1 or value(boot_signatures[0], 1, 0) != 3:
            raise ValueError("Expected signed application boot validation")
        key.verify(signature(value(boot_signatures[0], 2, 2)), image, ec.ECDSA(hashes.SHA256()))
    except (ValueError, TypeError, InvalidSignature) as error:
        raise RecoveryError("Firmware signature or metadata validation failed.") from error
    return Firmware(image, init)


def bounded_file(path, limit):
    with path.open("rb") as source:
        data = source.read(limit + 1)
    if len(data) > limit:
        raise RecoveryError("Firmware file exceeds the size limit.")
    return data


def load(path):
    path = Path(path).expanduser()
    try:
        if path.is_dir():
            return validate(bounded_file(path / "application.bin", MAX_IMAGE),
                            bounded_file(path / "application.dat", 512))
        with zipfile.ZipFile(path) as archive:
            names = archive.namelist()
            if len(names) > 32 or len(names) != len(set(names)):
                raise RecoveryError("The ZIP contains too many or duplicate entries.")

            def member(name, limit):
                if not isinstance(name, str):
                    raise RecoveryError("Invalid firmware filename in manifest.")
                p = PurePosixPath(name)
                if p.is_absolute() or ".." in p.parts or "\\" in name:
                    raise RecoveryError("Unsafe filename in firmware manifest.")
                info = archive.getinfo(name)
                if info.file_size > limit or info.flag_bits & 1:
                    raise RecoveryError("Oversized or encrypted firmware entry.")
                with archive.open(info) as source:
                    data = source.read(limit + 1)
                if len(data) > limit:
                    raise RecoveryError("Firmware entry exceeds the size limit.")
                return data

            manifest = json.loads(member("manifest.json", 16384))
            application = manifest["manifest"]["application"]
            return validate(member(application["bin_file"], MAX_IMAGE), member(application["dat_file"], 512))
    except RecoveryError:
        raise
    except (OSError, zipfile.BadZipFile, KeyError, ValueError, TypeError, RuntimeError) as error:
        raise RecoveryError("Could not load firmware. Select a Nordic ZIP with an application entry, or a folder containing application.bin and application.dat.") from error
