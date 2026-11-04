import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import zipfile

from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import ec, utils

from zwift_play_recovery import firmware as f
from zwift_play_recovery.constants import RecoveryError


def varint(number):
    out = bytearray()
    while number > 127:
        out.append((number & 127) | 128); number >>= 7
    out.append(number)
    return bytes(out)


def integer(field, number):
    return varint(field << 3) + varint(number)


def blob(field, data):
    return varint((field << 3) | 2) + varint(len(data)) + data


def raw_signature(key, data):
    r, s = utils.decode_dss_signature(key.sign(data, ec.ECDSA(hashes.SHA256())))
    return r.to_bytes(32, "little") + s.to_bytes(32, "little")


def fixture(hardware=0x524331, debug=0):
    key = ec.generate_private_key(ec.SECP256R1())
    image = b"Synthetic test image, not controller firmware."
    init = (integer(1, 0x02000001) + integer(2, hardware) + integer(3, 257)
            + integer(4, 0) + integer(7, len(image))
            + blob(8, integer(1, 3) + blob(2, hashlib.sha256(image).digest()[::-1]))
            + integer(9, debug) + blob(10, integer(1, 3) + blob(2, raw_signature(key, image))))
    packet = blob(2, blob(1, integer(1, 1) + blob(2, init)) + integer(2, 0)
                  + blob(3, raw_signature(key, init)))
    point = key.public_key().public_numbers()
    config = {"IMAGE_HASH": hashlib.sha256(image).hexdigest(), "INIT_HASH": hashlib.sha256(packet).hexdigest(),
              "PUBLIC_X": point.x, "PUBLIC_Y": point.y}
    return image, packet, config


class FirmwareTests(unittest.TestCase):
    def test_valid_signatures_and_metadata(self):
        image, packet, config = fixture()
        with patch.multiple(f, **config):
            result = f.validate(image, packet)
            self.assertEqual(result.image, image)

    def test_wrong_hash_rejected(self):
        image, packet, config = fixture()
        with patch.multiple(f, **config), self.assertRaises(RecoveryError):
            f.validate(image + b"!", packet)

    def test_changed_signature_rejected_even_if_allowlisted(self):
        image, packet, config = fixture()
        packet = packet[:-1] + bytes([packet[-1] ^ 1])
        config["INIT_HASH"] = hashlib.sha256(packet).hexdigest()
        with patch.multiple(f, **config), self.assertRaises(RecoveryError):
            f.validate(image, packet)

    def test_wrong_hardware_or_debug_image_rejected(self):
        for kwargs in ({"hardware": 123}, {"debug": 1}):
            image, packet, config = fixture(**kwargs)
            with patch.multiple(f, **config), self.assertRaises(RecoveryError):
                f.validate(image, packet)

    def test_zip_and_folder_load_identical_supported_data(self):
        image, packet, config = fixture()
        with tempfile.TemporaryDirectory() as directory, patch.multiple(f, **config):
            root = Path(directory)
            (root / "application.bin").write_bytes(image)
            (root / "application.dat").write_bytes(packet)
            manifest = {"manifest": {"application": {"bin_file": "app.bin", "dat_file": "app.dat"}}}
            with zipfile.ZipFile(root / "test.zip", "w") as z:
                z.writestr("manifest.json", json.dumps(manifest))
                z.writestr("app.bin", image)
                z.writestr("app.dat", packet)
            self.assertEqual(f.load(root), f.load(root / "test.zip"))

    def test_untrusted_zip_paths_and_oversized_entries_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "inside"
            root.mkdir()
            for name, data in (("../app.bin", b"fake"), ("/app.bin", b"fake"),
                               ("app.bin", bytes(f.MAX_IMAGE + 1))):
                manifest = {"manifest": {"application": {"bin_file": name, "dat_file": "app.dat"}}}
                with zipfile.ZipFile(root / "bad.zip", "w") as z:
                    z.writestr("manifest.json", json.dumps(manifest))
                    z.writestr(name, data)
                    z.writestr("app.dat", b"fake")
                with self.assertRaises(RecoveryError):
                    f.load(root / "bad.zip")
            self.assertFalse((root.parent / "app.bin").exists())

    def test_truncated_protobuf_fails(self):
        for raw in (b"\x12\x05a", b"\x80", b"\x00", b"\xff" * 11):
            with self.assertRaises(ValueError):
                f.fields(raw)
