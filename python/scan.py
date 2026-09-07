#!/usr/bin/env python3
"""Watch the tag's advertisements and dump every field that changes.

The manufacturer-data payload almost certainly carries battery / model /
screen info. Leave this running for a while (or between screen updates) and
diff the lines to work out which byte is which.
"""

import argparse
import asyncio
import time

from bleak import BleakScanner


def hexdump(data: bytes) -> str:
    return " ".join(f"{b:02x}" for b in data)


async def main(address: str | None, seconds: float) -> None:
    seen: dict[str, str] = {}
    start = time.monotonic()

    def on_detect(device, adv) -> None:
        if address and device.address.upper() != address.upper():
            return
        parts = [f"rssi={adv.rssi:4d}"]
        if adv.local_name:
            parts.append(f"name={adv.local_name}")
        for cid, payload in adv.manufacturer_data.items():
            parts.append(f"mfr[0x{cid:04x}]={hexdump(payload)}")
        for uuid, payload in adv.service_data.items():
            parts.append(f"svc[{uuid}]={hexdump(payload)}")
        if adv.service_uuids:
            parts.append(f"uuids={','.join(adv.service_uuids)}")
        line = "  ".join(parts)

        # RSSI jitters constantly; key on everything else so we only print
        # when the payload itself actually changes.
        key = line.split("  ", 1)[1] if "  " in line else line
        if seen.get(device.address) == key:
            return
        seen[device.address] = key
        print(f"[{time.monotonic() - start:7.1f}s] {device.address}  {line}", flush=True)

    async with BleakScanner(on_detect):
        await asyncio.sleep(seconds)


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("-a", "--address", help="only show this MAC")
    ap.add_argument("-t", "--seconds", type=float, default=60.0)
    asyncio.run(main(**vars(ap.parse_args())))
