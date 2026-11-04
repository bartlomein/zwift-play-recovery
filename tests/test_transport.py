"""Offline DFU receiver simulation; no radio, firmware fixtures or device writes."""
import asyncio
import struct
import unittest
import zlib
from zwift_play_recovery.transport import Uploader, RemoteError

class Receiver:
    def __init__(self, image, corrupt=False, reject_init=False):
        self.image = image
        self.init_data, self.data = bytearray(), bytearray()
        self.selected = 1
        self.prn = self.packets = self.object_end = 0
        self.queue = asyncio.Queue()
        self.executed = []
        self.created_sizes = []
        self.activated = False
        self.corrupt, self.reject_init = corrupt, reject_init

    @property
    def active(self):
        return self.init_data if self.selected == 1 else self.data

    def checksum(self):
        crc = zlib.crc32(self.active)
        if self.corrupt and self.selected == 2:
            crc ^= 1
        return struct.pack('<II', len(self.active), crc)

    async def response(self, request):
        if request != b'\x03':
            raise AssertionError('Only PRN responses are queued')
        return await asyncio.wait_for(self.queue.get(), 1)

    async def command(self, request):
        op = request[0]
        if op == 6:
            self.selected = request[1]
            return struct.pack('<III', 512 if self.selected == 1 else 4096,
                               len(self.active), zlib.crc32(self.active))
        if op == 2:
            self.prn = struct.unpack_from('<H', request, 1)[0]
            self.packets = 0
        elif op == 1:
            self.selected = request[1]
            size = struct.unpack_from('<I', request, 2)[0]
            self.packets = 0
            if self.selected == 1:
                self.init_data.clear()
                self.data.clear()
            else:
                self.created_sizes.append(size)
                if size % 4096 and len(self.data) + size != len(self.image):
                    raise AssertionError('Non-final flash object is not page aligned')
            self.object_end = len(self.active) + size
        elif op == 3:
            return self.checksum()
        elif op == 4:
            if len(self.active) != self.object_end:
                raise AssertionError('Executing incomplete object')
            if self.selected == 1 and self.reject_init:
                raise RemoteError(request, bytes.fromhex('60040b07'))
            self.executed.append((self.selected, len(self.active)))
        else:
            raise AssertionError('Unexpected command')
        return b''

    async def write(self, chunk):
        if len(chunk) > 20 or len(self.active) + len(chunk) > self.object_end:
            raise AssertionError('Packet bounds violated')
        self.active.extend(chunk)
        self.packets += 1
        if self.prn and self.packets % self.prn == 0:
            self.queue.put_nowait(self.checksum())

    async def execute_final(self):
        if bytes(self.data) != self.image or len(self.data) != self.object_end:
            raise AssertionError('Activating invalid or incomplete image')
        self.activated = True


class ProtocolTests(unittest.IsolatedAsyncioTestCase):
    async def test_multiblock_with_partial_final_page_and_prn(self):
        image = bytes(i % 251 for i in range(8200))
        receiver = Receiver(image)
        uploader = Uploader(receiver, lambda *a, **k: None, delay=0)
        await uploader.init('application', bytes(range(213)))
        await uploader.firmware('application', image)
        self.assertEqual(receiver.created_sizes, [4096, 4096, 8])
        self.assertTrue(receiver.activated)
        self.assertEqual(receiver.executed, [(1, 213), (2, 4096), (2, 8192)])

    async def test_crc_failure_stops_before_object_execute(self):
        receiver = Receiver(bytes(4096), corrupt=True)
        uploader = Uploader(receiver, lambda *a, **k: None, delay=0)
        await uploader.init('application', bytes(213))
        with self.assertRaisesRegex(RuntimeError, 'CRC mismatch'):
            await uploader.firmware('application', bytes(4096))
        self.assertFalse(receiver.activated)
        self.assertFalse(any(kind == 2 for kind, _ in receiver.executed))

    async def test_header_rejection_sends_no_firmware(self):
        receiver = Receiver(bytes(4096), reject_init=True)
        uploader = Uploader(receiver, lambda *a, **k: None, delay=0)
        with self.assertRaises(RemoteError) as error:
            await uploader.init('application', bytes(213))
        self.assertEqual(error.exception.extended, 7)
        self.assertEqual(receiver.data, b'')
        self.assertFalse(receiver.activated)

    async def test_nonzero_fresh_progress_is_rejected(self):
        receiver = Receiver(bytes(4096))
        uploader = Uploader(receiver, lambda *a, **k: None, delay=0)
        await uploader.init('application', bytes(213))
        receiver.data.extend(bytes(20))
        with self.assertRaisesRegex(RuntimeError, 'Unexpected fresh flash'):
            await uploader.firmware('application', bytes(4096))
        self.assertEqual(receiver.created_sizes, [])
