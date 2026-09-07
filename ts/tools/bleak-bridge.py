#!/usr/bin/env python3
"""BLE bridge for testing the TypeScript uploader against a real tag from Node.

Speaks JSON lines on stdin/stdout. Node sends {"op":"connect","address":..},
{"op":"write","data":hex}, {"op":"disconnect"}; the bridge answers
{"ev":"connected","mtu":N}, {"ev":"written"}, {"ev":"notify","data":hex},
{"ev":"disconnected"}, {"ev":"error","message":..}. bleak does the radio;
the TS code does everything the protocol requires.
"""
import asyncio, json, sys
from bleak import BleakClient, BleakScanner

ARM = "00002760-08c2-11e1-9073-0e8ac72e{:04x}"
DATA_IN, DATA_OUT = ARM.format(1), ARM.format(2)

def emit(**kw):
    sys.stdout.write(json.dumps(kw) + "\n"); sys.stdout.flush()

async def main():
    client = None
    loop = asyncio.get_running_loop()
    reader = asyncio.StreamReader()
    await loop.connect_read_pipe(lambda: asyncio.StreamReaderProtocol(reader), sys.stdin)
    while True:
        line = await reader.readline()
        if not line:
            break
        msg = json.loads(line)
        try:
            if msg["op"] == "connect":
                dev = await BleakScanner.find_device_by_address(msg["address"], timeout=15.0)
                if dev is None:
                    emit(ev="error", message="not advertising"); continue
                client = BleakClient(dev, disconnected_callback=lambda c: emit(ev="disconnected"))
                await client.connect()
                acquire = getattr(getattr(client, "_backend", None), "_acquire_mtu", None)
                if acquire:
                    try: await acquire()
                    except Exception: pass
                await client.start_notify(DATA_OUT, lambda s, d: emit(ev="notify", data=bytes(d).hex()))
                emit(ev="connected", mtu=getattr(client, "mtu_size", 23) or 23)
            elif msg["op"] == "write":
                await client.write_gatt_char(DATA_IN, bytes.fromhex(msg["data"]), response=False)
                emit(ev="written")
            elif msg["op"] == "disconnect":
                if client and client.is_connected:
                    await client.disconnect()
                emit(ev="closed")
        except Exception as e:
            emit(ev="error", message=f"{type(e).__name__}: {e}")

asyncio.run(main())
