#!/usr/bin/env python3
"""Interactive GATT shell for the tag.

Connects, enumerates the GATT table, subscribes to every notify/indicate
characteristic, then reads hex from stdin and writes it to the data-in
characteristic. Everything the tag sends back is printed with a timestamp,
so a session doubles as a protocol capture.

    ./tools/probe.py 9F:1D:00:0B:33:36
    > 01                 # write bytes 0x01
    > 00 0a ff           # whitespace is ignored
    > :char 2760...0002  # switch the write target
    > :quit
"""

import argparse
import asyncio
import sys
import time

from bleak import BleakClient, BleakScanner

# Arm Ltd. proprietary base: E0262760-08C2-11E1-9073-0E8AC72E<part>.
# This tag zeroes the leading bytes, giving 00002760-...
ARM_BASE = "00002760-08c2-11e1-9073-0e8ac72e{:04x}"
P1_SERVICE = ARM_BASE.format(0x1001)  # Cordio "proprietary service P1"
D1_DATA_IN = ARM_BASE.format(0x0001)  # write-without-response, host -> tag
D2_DATA_OUT = ARM_BASE.format(0x0002)  # notify, tag -> host

start = time.monotonic()


def stamp() -> str:
    return f"[{time.monotonic() - start:7.3f}s]"


def hexdump(data: bytes) -> str:
    printable = "".join(chr(b) if 32 <= b < 127 else "." for b in data)
    return f"{' '.join(f'{b:02x}' for b in data)}  |{printable}|"


async def read_line() -> str:
    """Read stdin without blocking the asyncio loop (so notifies keep printing)."""
    return await asyncio.get_running_loop().run_in_executor(None, sys.stdin.readline)


async def main(address: str, write_char: str) -> None:
    # Bleak resolves an address through its scan cache, so a tag that is
    # already connected (and therefore silent) looks "not found". Scan first.
    print(f"{stamp()} scanning for {address} ...")
    target = await BleakScanner.find_device_by_address(address, timeout=15.0)
    if target is None:
        sys.exit(f"{address} not advertising — is it still connected elsewhere? "
                 f"Try: bluetoothctl disconnect {address}")

    async with BleakClient(target) as client:
        print(f"{stamp()} connected to {address}\n")

        for service in client.services:
            print(f"  service {service.uuid}  {service.description}")
            for char in service.characteristics:
                print(f"    char  {char.uuid}  {','.join(char.properties)}")
                if {"notify", "indicate"} & set(char.properties):
                    uuid = char.uuid

                    def handler(_sender, data: bytes, uuid: str = uuid) -> None:
                        print(f"\n{stamp()} NOTIFY {uuid[4:8]} ({len(data):3d}) {hexdump(data)}\n> ", end="", flush=True)

                    await client.start_notify(char, handler)
        print(f"\n{stamp()} subscribed; writing to {write_char}. Ctrl-D to quit.\n")

        while True:
            print("> ", end="", flush=True)
            line = (await read_line()).strip()
            if not line:
                if not sys.stdin.isatty():
                    break
                continue
            if line in (":quit", ":q"):
                break
            if line.startswith(":char "):
                write_char = line.split(None, 1)[1]
                print(f"{stamp()} write target -> {write_char}")
                continue
            if line.startswith(":sleep "):
                await asyncio.sleep(float(line.split()[1]))
                continue
            try:
                payload = bytes.fromhex(line.replace(",", " "))
            except ValueError as exc:
                print(f"  not hex: {exc}")
                continue
            print(f"{stamp()} WRITE  ({len(payload):3d}) {hexdump(payload)}")
            await client.write_gatt_char(write_char, payload, response=False)
            await asyncio.sleep(0.3)  # give the tag a moment to answer


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("address")
    ap.add_argument("-c", "--write-char", default=D1_DATA_IN)
    asyncio.run(main(**vars(ap.parse_args())))
