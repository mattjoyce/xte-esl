#!/usr/bin/env python3
"""Push an image to the tag over BLE with the XTE protocol.

    ./python/push.py 9F:1D:00:0B:33:36 label.png --no-dither   # flat graphics
    ./python/push.py 9F:1D:00:0B:33:36 photo.jpg               # dithered
    ./python/push.py - label.png --dry-run                     # frames only, no BLE

The image is resized to 250x122 landscape, quantised to the four inks
(Floyd-Steinberg unless --no-dither), rotated 90 degrees counter-clockwise
into the panel's native 122x250 portrait buffer, packed, and sent:
alloc -> packets -> refresh, with the patch loop for lost packets.
Verified on a PSJ-213 (firmware 4.0.2) on 2026-09-07 for the no-loss path;
the patch loop follows docs/protocol.md 8.3 and has not been exercised.

Exit status 0 only after the tag acknowledges the refresh. The panel then
flickers for about 20 seconds: that is the refresh, not a failure.
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

CMD_TIMEOUT = 5.0        # spec 4.3
MAX_PATCH_ROUNDS = 3     # spec 8.3
SCAN_TIMEOUT = 15.0
SETTLE = 0.1             # spec 8.2 step 7

PANEL_W, PANEL_H = 250, 122   # as viewed; buffer is PANEL_H x PANEL_W after rotation

start = time.monotonic()


class PushError(Exception):
    """The push did not complete. The message says why, in protocol terms."""


def stamp() -> str:
    return f"[{time.monotonic() - start:7.3f}s]"


def load_pixels(path: str, w: int, h: int, dither: bool, rotate: int):
    """Open, resize to w x h, quantise to the four inks, rotate. Returns (pixels, bw, bh)."""
    img = Image.open(path).convert("RGB")
    if img.size != (w, h):
        print(f"resizing {img.size[0]}x{img.size[1]} -> {w}x{h}")
        img = img.resize((w, h), Image.LANCZOS)
    pal = Image.new("P", (1, 1))
    flat = [c for rgb in xte.PALETTE for c in rgb]
    pal.putpalette(flat + [0] * (768 - len(flat)))
    img = img.quantize(palette=pal, dither=Image.FLOYDSTEINBERG if dither else Image.NONE).convert("RGB")
    if rotate:
        img = img.rotate(rotate, expand=True)
    raw = img.tobytes()
    return [tuple(raw[i:i + 3]) for i in range(0, len(raw), 3)], img.size[0], img.size[1]


DISCONNECTED = object()


async def push(address: str, payload: bytes, interval: float, multi_screen: bool) -> list:
    """Run spec 8.2 (with 8.3 patching). Returns the frame log. Raises PushError."""
    from bleak import BleakClient, BleakScanner

    print(f"{stamp()} scanning for {address} ...")
    dev = await BleakScanner.find_device_by_address(address, timeout=SCAN_TIMEOUT)
    if dev is None:
        raise PushError(f"{address} not advertising within {SCAN_TIMEOUT:.0f}s. "
                        f"Try: bluetoothctl disconnect {address}")

    inbox: asyncio.Queue = asyncio.Queue()
    log: list = []                                  # (t, direction, bytes), kept for post-mortem

    def on_notify(_sender, data: bytearray) -> None:
        b = bytes(data)
        log.append((time.monotonic() - start, "<-", b))
        print(f"{stamp()} <- {b.hex(' ')}")
        inbox.put_nowait(b)

    def on_disconnect(_client) -> None:
        inbox.put_nowait(DISCONNECTED)

    async def expect(cmd: int) -> xte.Response:
        deadline = time.monotonic() + CMD_TIMEOUT
        while True:
            try:
                item = await asyncio.wait_for(inbox.get(), max(0.0, deadline - time.monotonic()))
            except TimeoutError:
                raise PushError(f"no response to command {cmd:#04x} within {CMD_TIMEOUT:.0f}s") from None
            if item is DISCONNECTED:
                raise PushError(f"tag disconnected while waiting for command {cmd:#04x}")
            resp = xte.parse_response(item)
            if resp is None:
                print(f"{stamp()}    (ignoring malformed frame)")
            elif resp.cmd != cmd:
                print(f"{stamp()}    (ignoring reply to {resp.cmd:#04x}, wanted {cmd:#04x})")
            else:
                return resp

    async with BleakClient(dev, disconnected_callback=on_disconnect) as client:
        # bleak's BlueZ backend only fills mtu_size after this private call; fall back to 23.
        acquire = getattr(getattr(client, "_backend", None), "_acquire_mtu", None)
        if acquire:
            try:
                await acquire()
            except Exception as e:                  # noqa: BLE001 - diagnostic only
                print(f"{stamp()} mtu query failed ({e}), assuming 23")
        mtu = getattr(client, "mtu_size", 23) or 23
        chunk = min(xte.BLE_WRITE, mtu - 3)
        print(f"{stamp()} connected, mtu {mtu}, write chunk {chunk}")
        await client.start_notify(DATA_OUT, on_notify)

        async def write(frame: bytes, what: str) -> None:
            log.append((time.monotonic() - start, "->", frame))
            for piece in xte.ble_chunks(frame, chunk):
                try:
                    await client.write_gatt_char(DATA_IN, piece, response=False)
                except Exception as e:
                    raise PushError(f"BLE write failed during {what}: {e}") from e
                await asyncio.sleep(interval)

        packets = xte.data_packets(payload)
        print(f"{stamp()} -> alloc {len(payload)} B, {len(packets)} packets")
        await write(xte.cmd_alloc(len(payload)), "alloc")
        r = await expect(0x01)
        if r.status != xte.STATUS_OK:
            raise PushError(f"tag refused allocation, status {r.status:#04x}")

        async def send(indices) -> None:
            for i in indices:
                await write(packets[i], f"packet {i}")
            print(f"{stamp()} sent {len(indices)} packets")

        await send(range(len(packets)))
        for attempt in range(MAX_PATCH_ROUNDS + 1):
            await asyncio.sleep(SETTLE)
            print(f"{stamp()} -> refresh")
            await write(xte.cmd_refresh(multi_screen), "refresh")
            r = await expect(0x04)
            if r.status == xte.STATUS_OK:
                print(f"{stamp()} refresh acknowledged; panel now redraws for ~20 s")
                return log
            if r.status != xte.STATUS_MISSING:
                raise PushError(f"refresh returned unknown status {r.status:#04x}")
            missing = r.missing_packets(len(packets))
            print(f"{stamp()} tag reports {len(missing)} missing: {missing}")
            if not missing:
                raise PushError("refresh returned 0x68 but the bitmap shows nothing missing: "
                                "host and tag disagree about the packet count")
            if attempt == MAX_PATCH_ROUNDS:
                raise PushError(f"still {len(missing)} packets missing after {MAX_PATCH_ROUNDS} patch rounds")
            await send(missing)
        raise PushError("refresh never acknowledged")   # unreachable, kept so every exit is named


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("address", help="tag BLE address (python/scan.py shows it), or - with --dry-run")
    ap.add_argument("image")
    ap.add_argument("--width", type=int, default=PANEL_W, help="panel width as viewed")
    ap.add_argument("--height", type=int, default=PANEL_H, help="panel height as viewed")
    ap.add_argument("--no-dither", action="store_true", help="nearest ink per pixel; use for flat graphics")
    ap.add_argument("--no-rle", action="store_true", help="send the image uncompressed (compression 00)")
    ap.add_argument("--interval", type=float, default=0.005, help="seconds between BLE writes (spec 4.2)")
    ap.add_argument("--multi-screen", action="store_true", help="refresh payload 03 03 for two-screen tags")
    ap.add_argument("--rotate", type=int, default=90, choices=[0, 90, 180, 270],
                    help="counter-clockwise rotation into the native buffer. 90 is verified for the PSJ-213; "
                         "other values are for untested tags")
    ap.add_argument("--dry-run", action="store_true", help="print frames, do not connect")
    a = ap.parse_args()

    px, bw, bh = load_pixels(a.image, a.width, a.height, not a.no_dither, a.rotate)
    payload = xte.image_payload(px, bw, bh, compress=not a.no_rle)
    info = xte.container_info(payload)["images"][0]
    print(f"buffer {bw}x{bh}, payload {len(payload)} B, {xte.packet_count(len(payload))} packets, "
          f"{'RLE' if info['compressed'] else 'raw'}")
    if a.dry_run:
        print("alloc  ", xte.cmd_alloc(len(payload)).hex(" "))
        for i, p in enumerate(xte.data_packets(payload)):
            print(f"pkt {i:3d}", p[:12].hex(" "), f"... ({len(p)} B, {len(xte.ble_chunks(p))} writes)")
        print("refresh", xte.cmd_refresh(a.multi_screen).hex(" "))
        return 0
    try:
        asyncio.run(push(a.address, payload, a.interval, a.multi_screen))
    except PushError as e:
        print(f"{stamp()} FAILED: {e}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
