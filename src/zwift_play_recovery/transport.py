"""Secure DFU transport used by the original hardware recovery.

4096-byte flash objects; 20-byte packets; receipt every 8 packets. No reset,
resume, automatic retry, system update, or authentication bypass is implemented.
"""
import asyncio
import struct
import zlib
from .constants import DFU, CONTROL, PACKET, RecoveryError

class RemoteError(RecoveryError):
    def __init__(self, request, response):
        self.request, self.response = request, response
        self.status = response[2] if len(response) > 2 else None
        self.extended = response[3] if self.status == 11 and len(response) > 3 else None
        super().__init__('The controller rejected the firmware or command '
                         f'(DFU status {self.status}, detail {self.extended}). '
                         'Stopped without bypassing its checks.')

class Transport:
    def __init__(self, client, disconnected, log):
        self.client, self.disconnected, self.log = client, disconnected, log
        self.notifications = asyncio.Queue()

    async def start(self):
        service = self.client.services.get_service(DFU)
        if service is None or not {CONTROL, PACKET}.issubset({c.uuid for c in service.characteristics}):
            raise RuntimeError('Expected Secure DFU profile absent')
        await self.client.start_notify(CONTROL, lambda _, b: self.notifications.put_nowait(bytes(b)))

    async def response(self, request):
        raw = await asyncio.wait_for(self.notifications.get(), 20)
        self.log('response', request=request.hex(), response=raw.hex())
        if len(raw) < 3 or raw[:2] != bytes((0x60, request[0])):
            raise RuntimeError('Unexpected DFU response: ' + raw.hex())
        if raw[2] != 1:
            raise RemoteError(request, raw)
        return raw[3:]

    async def command(self, request):
        self.log('command', request=request.hex())
        await asyncio.wait_for(self.client.write_gatt_char(CONTROL, request, response=True), 15)
        return await self.response(request)

    async def write(self, packet):
        await asyncio.wait_for(self.client.write_gatt_char(PACKET, packet, response=False), 15)

    async def execute_final(self):
        try:
            await self.command(b'\x04')
            self.log('final_execute_acknowledged', show=True)
        except RemoteError:
            raise
        except Exception as error:
            # A reboot may race the ATT acknowledgement. This is not called success;
            # post-reboot profile/version verification is still mandatory.
            if self.disconnected.is_set():
                self.log('final_execute_disconnected_without_response', show=True, detail=str(error))
            else:
                raise
        try:
            await asyncio.wait_for(self.disconnected.wait(), 30)
            self.log('device_disconnected_for_activation', show=True)
        except TimeoutError:
            raise RuntimeError('Final Execute returned but the device did not reboot; stopped without reset')

class Uploader:
    PRN = 8
    PACKET_BYTES = 20

    def __init__(self, transport, log, delay=0.005):
        self.t, self.log, self.delay = transport, log, delay

    async def stream(self, payload, image, offset):
        packets = 0
        for pos in range(0, len(payload), self.PACKET_BYTES):
            chunk = payload[pos:pos + self.PACKET_BYTES]
            await self.t.write(chunk)
            offset += len(chunk)
            packets += 1
            await asyncio.sleep(self.delay)
            if packets % self.PRN == 0:
                reply = await self.t.response(b'\x03')
                self.validate_checksum(reply, image, offset)
        reply = await self.t.command(b'\x03')
        self.validate_checksum(reply, image, offset)

    @staticmethod
    def validate_checksum(reply, image, offset):
        expected = (offset, zlib.crc32(image[:offset]))
        if len(reply) != 8 or struct.unpack('<II', reply) != expected:
            raise RuntimeError(f'Offset/CRC mismatch at {offset}; object will not be executed')

    async def init(self, kind, init):
        response = await self.t.command(b'\x06\x01')
        if len(response) != 12 or struct.unpack_from('<I', response)[0] < len(init):
            raise RuntimeError('Init object limit is invalid')
        await self.t.command(b'\x02' + struct.pack('<H', self.PRN))
        # Fresh signed init resets the DFU transaction. No stale data is resumed.
        await self.t.command(b'\x01\x01' + struct.pack('<I', len(init)))
        await self.stream(init, init, 0)
        await self.t.command(b'\x04')
        self.log('signed_header_accepted_by_controller', show=True, stage=kind)

    async def firmware(self, kind, image):
        reply = await self.t.command(b'\x06\x02')
        if len(reply) != 12:
            raise RuntimeError('Invalid data selection response')
        maximum, offset, crc = struct.unpack('<III', reply)
        if maximum < 4096 or maximum > 65536 or offset != 0 or crc != 0:
            raise RuntimeError(f'Unexpected fresh flash geometry/progress: {maximum}, {offset}, {crc}')
        # Real flash pages are 4096 bytes. The fake receiver's 512-byte object
        # workaround must NOT be applied to a real nRF52832 flash page.
        last_percent = -10
        for offset in range(0, len(image), 4096):
            block = image[offset:offset + 4096]
            await self.t.command(b'\x01\x02' + struct.pack('<I', len(block)))
            await self.stream(block, image, offset)
            final = offset + len(block) == len(image)
            if final:
                self.log('full_image_crc_verified_before_activation', show=True,
                         stage=kind, bytes=len(image), crc32=f'{zlib.crc32(image):08x}')
                await self.t.execute_final()
            else:
                await self.t.command(b'\x04')
            percent = (offset + len(block)) * 100 // len(image)
            if percent >= last_percent + 10 or final:
                self.log('transfer_progress', show=True, stage=kind,
                         bytes=offset + len(block), total=len(image), percent=percent)
                last_percent = percent
