#!/usr/bin/env python3
"""Push an image to the tag over BLE with the vendor's XTE protocol.

    ./python/push.py 9F:1D:00:0B:33:36 image.png            # 250x122 assumed
    ./python/push.py 9F:1D:00:0B:33:36 image.png --height 128
    ./python/push.py - image.png --dry-run                   # frames only, no BLE

The image is resized to 250x122 landscape, quantised to the four inks
(Floyd-Steinberg unless --no-dither), rotated 90 degrees into the panel's
native 122x250 portrait buffer, packed, and sent: alloc -> packets -> refresh,
with the vendor's patch loop for lost packets. Verified on the tag 2026-09-07.
docs/protocol.md has the byte layouts and the geometry this follows.
"""

import argparse
import asyncio
import sys
import time

from PIL import Image

import xte

ARM_BASE = "00002760-08c2-11e1-9073-0e8ac72e{:04x}"
SERVICE = ARM_BASE.format(0x1001)
DATA_IN = ARM_BASE.format(0x0001)
DATA_OUT = ARM_BASE.format(0x0002)

start = time.monotonic()


def stamp() -> str:
    return f"[{time.monotonic() - start:7.3f}s]"


def load_pixels(path: str, w: int, h: int, dither: bool, rotate: int = 0, pad_w: int = 0, flip_v: bool = False):
    """Return (pixels, buffer_w, buffer_h). rotate is applied after resizing to
    w x h; pad_w widens the rotated buffer with white on the right (panel
    buffers are byte-aligned, e.g. 122 -> 128)."""
    img = Image.open(path).convert("RGB")
    if img.size != (w, h):
        print(f"resizing {img.size[0]}x{img.size[1]} -> {w}x{h}")
        img = img.resize((w, h), Image.LANCZOS)
    if flip_v:
        img = img.transpose(Image.FLIP_TOP_BOTTOM)
    if rotate:
        img = img.rotate(rotate, expand=True)
    if pad_w and img.size[0] < pad_w:
        canvas = Image.new("RGB", (pad_w, img.size[1]), (255, 255, 255))
        canvas.paste(img, (0, 0))
        img = canvas
    w, h = img.size
    pal = Image.new("P", (1, 1))
    flat = [c for rgb in xte.PALETTE for c in rgb]
    pal.putpalette(flat + [0] * (768 - len(flat)))
    q = img.quantize(palette=pal, dither=Image.FLOYDSTEINBERG if dither else Image.NONE)
    raw = q.convert("RGB").tobytes()
    return [tuple(raw[i:i + 3]) for i in range(0, len(raw), 3)], w, h


async def push(address: str, payload: bytes, interval: float, screens: int) -> None:
    from bleak import BleakClient, BleakScanner

    print(f"{stamp()} scanning for {address} ...")
    dev = await BleakScanner.find_device_by_address(address, timeout=15.0)
    if dev is None:
        sys.exit(f"{address} not advertising. Try: bluetoothctl disconnect {address}")

    inbox: asyncio.Queue = asyncio.Queue()

    def on_notify(_sender, data: bytearray) -> None:
        print(f"{stamp()} <- {bytes(data).hex(' ')}")
        inbox.put_nowait(bytes(data))

    async def expect(cmd: int, timeout: float = xte.CMD_TIMEOUT) -> bytes:
        deadline = time.monotonic() + timeout
        while True:
            left = deadline - time.monotonic()
            if left <= 0:
                raise TimeoutError(f"no response to cmd {cmd:#04x}")
            r = await asyncio.wait_for(inbox.get(), left)
            parsed = xte.parse_response(r)
            if parsed and parsed[0] == cmd:
                return r
            print(f"{stamp()}    (ignoring frame, wanted cmd {cmd:#04x})")

    async with BleakClient(dev) as client:
        if hasattr(client, "_backend") and hasattr(client._backend, "_acquire_mtu"):
            try:
                await client._backend._acquire_mtu()   # BlueZ: ask for the negotiated MTU
            except Exception as e:
                print(f"{stamp()} mtu query failed ({e}), using default")
        mtu = getattr(client, "mtu_size", 23) or 23
        chunk = min(xte.BLE_WRITE, mtu - 3)
        print(f"{stamp()} connected, mtu {mtu}, write chunk {chunk}")
        await client.start_notify(DATA_OUT, on_notify)

        async def write(frame: bytes) -> None:
            for piece in xte.ble_chunks(frame, chunk):
                await client.write_gatt_char(DATA_IN, piece, response=False)
                await asyncio.sleep(interval)

        packets = list(xte.data_packets(payload))
        print(f"{stamp()} -> alloc {len(payload)} B, {len(packets)} packets")
        await write(xte.cmd_alloc(len(payload)))
        r = await expect(0x01)
        if r[7] != 0xFF:
            sys.exit(f"alloc refused, status {r[7]:#04x}")

        async def send(indices) -> None:
            for i in indices:
                await write(packets[i])
            print(f"{stamp()} sent {len(indices)} packets")

        await send(range(len(packets)))
        for attempt in range(xte.MAX_PATCH_ROUNDS + 1):
            await asyncio.sleep(0.1)
            print(f"{stamp()} -> refresh")
            await write(xte.cmd_refresh(screens))
            r = await expect(0x04)
            if r[7] == 0xFF:
                print(f"{stamp()} done, image on screen")
                return
            if r[7] != 0x68:
                sys.exit(f"refresh returned unknown status {r[7]:#04x}")
            missing = [i for i, bit in enumerate(xte.bitmap_bits(r, 8)[:len(packets)]) if not bit]
            print(f"{stamp()} tag reports {len(missing)} missing: {missing}")
            if not missing:
                continue
            if attempt == xte.MAX_PATCH_ROUNDS:
                sys.exit("gave up patching")
            await send(missing)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("address", help="tag BLE address, or - with --dry-run")
    ap.add_argument("image")
    ap.add_argument("--width", type=int, default=250)
    ap.add_argument("--height", type=int, default=122)
    ap.add_argument("--no-dither", action="store_true")
    ap.add_argument("--no-rle", action="store_true", help="send compressType 0")
    ap.add_argument("--interval", type=float, default=0.005, help="seconds between BLE writes")
    ap.add_argument("--screens", type=int, default=1)
    ap.add_argument("--rotate", type=int, default=90, choices=[0, 90, 180, 270],
                    help="rotate the resized image before packing, counter-clockwise; "
                         "90 is correct for the PSJ-213 (portrait 122x250 buffer)")
    ap.add_argument("--pad-width", type=int, default=0, help="pad buffer width with white, e.g. 128")
    ap.add_argument("--flip-v", action="store_true", help="mirror top/bottom before rotating")
    ap.add_argument("--dry-run", action="store_true", help="print frames, do not connect")
    a = ap.parse_args()

    px, bw, bh = load_pixels(a.image, a.width, a.height, not a.no_dither, a.rotate, a.pad_width, a.flip_v)
    print(f"buffer {bw}x{bh}")
    payload = xte.image_payload(px, bw, bh, compress=not a.no_rle)
    n = xte.packet_count(len(payload))
    print(f"payload {len(payload)} B, {n} packets, compress={payload[13 + 4 + 16]}")
    if a.dry_run:
        print("alloc  ", xte.cmd_alloc(len(payload)).hex(" "))
        for i, p in enumerate(xte.data_packets(payload)):
            print(f"pkt {i:3d}", p[:12].hex(" "), f"... ({len(p)} B, {len(xte.ble_chunks(p))} writes)")
        print("refresh", xte.cmd_refresh(a.screens).hex(" "))
        return
    asyncio.run(push(a.address, payload, a.interval, a.screens))


if __name__ == "__main__":
    main()
