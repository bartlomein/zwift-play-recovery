COMPANY = 2378
DFU = "0000fe59-0000-1000-8000-00805f9b34fb"
ZAP = "00000001-19ca-4651-86e5-fa29dcdd09d1"
ZAP_V2 = "0000fc82-0000-1000-8000-00805f9b34fb"
CONTROL = "8ec90001-f315-4f60-9fb8-838830daea50"
PACKET = "8ec90002-f315-4f60-9fb8-838830daea50"
READABLE = {
    "firmware": "00002a26-0000-1000-8000-00805f9b34fb",
    "serial": "00002a25-0000-1000-8000-00805f9b34fb",
    "hardware": "00002a27-0000-1000-8000-00805f9b34fb",
    "manufacturer": "00002a29-0000-1000-8000-00805f9b34fb",
    "battery": "00002a19-0000-1000-8000-00805f9b34fb",
}


class RecoveryError(Exception):
    """An actionable error that should be shown without a traceback."""
