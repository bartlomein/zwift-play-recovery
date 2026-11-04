from types import SimpleNamespace
import unittest
from zwift_play_recovery import devices as d
from zwift_play_recovery.constants import COMPANY, DFU, ZAP_V2, RecoveryError


def controller(payload="0255667788a101", services=(DFU,), name="Zwift Play", address="ORIGINAL"):
    return d.classify(SimpleNamespace(address=address, name=name),
        SimpleNamespace(local_name=name, rssi=-55, service_uuids=services,
                        manufacturer_data={COMPANY: bytes.fromhex(payload)}))


class DeviceTests(unittest.TestCase):
    def test_recovery_never_guesses_side_from_02(self):
        for raw in ("02a101", "0255667788a101"):
            item = controller(raw)
            self.assertTrue(item.eligible)
            self.assertIsNone(item.side)

    def test_normal_sides_and_non_recovery(self):
        for prefix, side in (("0e", "Right"), ("0f", "Left"), ("02", "Right"), ("03", "Left")):
            item = controller(prefix + "a101", (ZAP_V2,))
            self.assertEqual(item.side, side)
            self.assertFalse(item.eligible)

    def test_other_models_and_nordic_devices_cannot_flash(self):
        for name, raw in (("Nordic", ""), ("Zwift Ride", "02a101"),
                          ("Zwift Hub", "06a101"), ("Zwift Play", "0e")):
            self.assertFalse(controller(raw, name=name).eligible)
        self.assertFalse(controller(services=(DFU, ZAP_V2)).eligible)

    def test_preflight_requires_exact_payload_id_and_recovery_mode(self):
        original = controller()
        self.assertTrue(d.same_bootloader(original, controller()))
        self.assertFalse(d.same_bootloader(original, controller(address="OTHER")))
        self.assertFalse(d.same_bootloader(original, controller("0255667788b202")))
        self.assertFalse(d.same_bootloader(original, controller("0fa101", (ZAP_V2,))))

    def test_suffix_collision_requires_full_device_id(self):
        first, second = controller(address="ONE"), controller(address="TWO")
        with self.assertRaises(RecoveryError):
            d.choose_identifier([first, second], "A101")
        self.assertIs(d.choose_identifier([first, second], "ONE"), first)

    def test_rebooted_uuid_can_change_but_serial_cannot(self):
        original = controller()
        normal = controller("0fa101", (ZAP_V2,), address="NEW")
        result = {"device": normal.record(), "services": [ZAP_V2],
                  "values": {"serial": "03-55667788A101", "firmware": "2.0.1", "manufacturer": "Zwift Inc"}}
        self.assertTrue(d.normal_candidate(original, normal))
        self.assertTrue(d.application_verified(original, result, "2.0.1"))
        for key, value in (("serial", "03-00000000A101"), ("serial", "02-55667788A101"),
                           ("firmware", "0.0.0"), ("manufacturer", "Other")):
            changed = {**result, "values": {**result["values"], key: value}}
            self.assertFalse(d.application_verified(original, changed, "2.0.1"))
        self.assertFalse(d.application_verified(original, {**result, "services": [ZAP_V2, DFU]}, "2.0.1"))
