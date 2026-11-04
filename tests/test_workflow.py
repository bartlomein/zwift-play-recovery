import asyncio
import contextlib
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

from zwift_play_recovery import cli, recovery
from zwift_play_recovery.constants import RecoveryError
from zwift_play_recovery.firmware import Firmware
from test_devices import controller


class WorkflowTests(unittest.IsolatedAsyncioTestCase):
    async def test_confirmation_failure_never_accesses_radio(self):
        with patch.object(recovery, "scan", new_callable=AsyncMock) as scan:
            with self.assertRaises(RecoveryError):
                await recovery.recover(controller(), Firmware(b"x", b"y"), "FLASH WRONG", MagicMock())
            scan.assert_not_awaited()

    async def test_preflight_change_stops_before_connection(self):
        with tempfile.TemporaryDirectory() as tmp, patch.object(recovery, "validate", return_value=Firmware(b"x", b"y")), \
                patch.object(recovery, "scan", new_callable=AsyncMock, return_value=[controller(address="CHANGED")]), \
                patch.object(recovery, "BleakClient") as client:
            result = await recovery.recover(controller(), Firmware(b"x", b"y"), "FLASH A101", recovery.Session(tmp))
            self.assertFalse(result["recovered"])
            client.assert_not_called()

    async def test_init_rejection_does_not_send_image_or_try_system(self):
        with tempfile.TemporaryDirectory() as tmp, patch.object(recovery, "validate", return_value=Firmware(b"x", b"y")), \
                patch.object(recovery, "scan", new_callable=AsyncMock, return_value=[controller()]), \
                patch.object(recovery, "BleakClient") as client_factory, \
                patch.object(recovery, "Transport") as transport_factory, \
                patch.object(recovery, "Uploader") as uploader_factory:
            client = client_factory.return_value
            client.connect = AsyncMock(); client.disconnect = AsyncMock()
            transport_factory.return_value.start = AsyncMock()
            uploader = uploader_factory.return_value
            uploader.init = AsyncMock(side_effect=RecoveryError("Signature rejected"))
            uploader.firmware = AsyncMock()
            result = await recovery.recover(controller(), Firmware(b"x", b"y"), "FLASH A101", recovery.Session(tmp))
            self.assertFalse(result["recovered"])
            uploader.init.assert_awaited_once_with("application", b"y")
            uploader.firmware.assert_not_awaited()
            client.disconnect.assert_awaited_once()

    async def test_transferred_is_not_recovered_until_readback(self):
        for verification_error in (None, RecoveryError("No normal advertisement")):
            with tempfile.TemporaryDirectory() as tmp, patch.object(recovery, "validate", return_value=Firmware(b"x", b"y")), \
                    patch.object(recovery, "scan", new_callable=AsyncMock, return_value=[controller()]), \
                    patch.object(recovery, "BleakClient") as client_factory, \
                    patch.object(recovery, "Transport") as transport_factory, \
                    patch.object(recovery, "Uploader") as uploader_factory, \
                    patch.object(recovery, "verify_after_reboot", new_callable=AsyncMock) as verify, \
                    patch.object(recovery.asyncio, "sleep", new_callable=AsyncMock):
                client = client_factory.return_value
                client.connect = AsyncMock(); client.disconnect = AsyncMock()
                transport_factory.return_value.start = AsyncMock()
                uploader = uploader_factory.return_value
                uploader.init = AsyncMock(); uploader.firmware = AsyncMock()
                verify.side_effect = verification_error
                verify.return_value = {"device": {"side": "Left"}, "values": {"battery": 90}}
                result = await recovery.recover(controller(), Firmware(b"x", b"y"), "FLASH A101", recovery.Session(tmp))
                self.assertEqual(result["recovered"], verification_error is None)
                self.assertEqual(result["application_bytes_transferred"], 1)
                self.assertFalse(result["system_stage_written"])
                self.assertEqual(result["state"], "transferred_verification_pending" if verification_error else "verified")
                uploader.firmware.assert_awaited_once()

    async def test_interrupted_transfer_preserves_report_and_disconnects(self):
        with tempfile.TemporaryDirectory() as tmp, patch.object(recovery, "validate", return_value=Firmware(b"x", b"y")), \
                patch.object(recovery, "scan", new_callable=AsyncMock, return_value=[controller()]), \
                patch.object(recovery, "BleakClient") as client_factory, \
                patch.object(recovery, "Transport") as transport_factory, \
                patch.object(recovery, "Uploader") as uploader_factory:
            client = client_factory.return_value
            client.connect = AsyncMock(); client.disconnect = AsyncMock()
            transport_factory.return_value.start = AsyncMock()
            uploader = uploader_factory.return_value
            uploader.init = AsyncMock()
            uploader.firmware = AsyncMock(side_effect=asyncio.CancelledError())
            session = recovery.Session(tmp)
            with self.assertRaises(asyncio.CancelledError):
                await recovery.recover(controller(), Firmware(b"x", b"y"), "FLASH A101", session)
            client.disconnect.assert_awaited_once()
            self.assertIn('Interrupted', (session.folder / "result.json").read_text())

    async def test_wizard_cancel_never_calls_recovery(self):
        args = cli.parser().parse_args(["wizard"])
        with patch.object(cli.devices, "scan", new_callable=AsyncMock, return_value=[controller()]), \
                patch.object(cli, "prompt", side_effect=["q"]), \
                patch.object(cli, "recover", new_callable=AsyncMock) as recover, \
                contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(await cli.execute(args), 0)
            recover.assert_not_awaited()

    async def test_demo_never_accesses_bluetooth(self):
        with patch.object(cli.devices, "scan", new_callable=AsyncMock) as scan, \
                contextlib.redirect_stdout(io.StringIO()) as output:
            args = cli.parser().parse_args(["--demo"])
            self.assertEqual(await cli.execute(args), 0)
            scan.assert_not_awaited()
            self.assertIn("fictional", output.getvalue())

    async def test_demo_json_is_valid_json(self):
        with contextlib.redirect_stdout(io.StringIO()) as output:
            await cli.execute(cli.parser().parse_args(["scan", "--demo", "--json"]))
            self.assertEqual(len(json.loads(output.getvalue())), 2)

    def test_demo_doctor_does_not_run_real_diagnostics(self):
        with patch.object(cli, "execute", new_callable=AsyncMock) as execute, contextlib.redirect_stderr(io.StringIO()):
            self.assertEqual(cli.main(["--demo", "doctor"]), 2)
            execute.assert_not_called()

    def test_noninteractive_recovery_refused(self):
        with patch("sys.stdin.isatty", return_value=False), contextlib.redirect_stderr(io.StringIO()):
            self.assertEqual(cli.main(["recover", "--device", "A101"]), 2)

    def test_logs_preserve_stage_when_interrupted(self):
        with tempfile.TemporaryDirectory() as tmp:
            session = recovery.Session(tmp)
            session("transfer_progress", bytes=4096)
            session.save({"state": "transferring", "recovered": False})
            self.assertIn('"transferring"', (session.folder / "result.json").read_text())

    def test_scan_duration_bounds(self):
        for value in ("0", "-1", "999", "nan"):
            with self.assertRaises(Exception):
                cli.seconds(value)

    def test_dragged_and_windows_paths(self):
        self.assertEqual(cli.normalize_path('"/tmp/my update.zip"'), '/tmp/my update.zip')
        with patch.object(cli.platform, "system", return_value="Darwin"):
            self.assertEqual(cli.normalize_path('/tmp/my\\ update.zip'), '/tmp/my update.zip')
        with patch.object(cli.platform, "system", return_value="Windows"):
            self.assertEqual(cli.normalize_path(r'C:\Users\User\my update.zip'), r'C:\Users\User\my update.zip')
