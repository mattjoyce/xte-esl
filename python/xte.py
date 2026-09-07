#!/usr/bin/env python3
"""XTE protocol codec for the Poshiji PSJ-213 tag. Pure Python, no BLE.

Byte layouts in docs/protocol.md. Run this file directly to self-test
against testdata/reference.json (see testdata/README.md for provenance).
"""

import json
import struct
import sys
from pathlib import Path

MAGIC = b"XTE"
SUB_PACKET = 1211      # payload bytes per data packet
BLE_WRITE = 244        # bytes per write-without-response
BATCH = 204800         # bytes per flash batch for large images
CMD_TIMEOUT = 5.0
MAX_PATCH_ROUNDS = 3

WHITE, YELLOW, RED, BLACK = 1, 2, 3, 0
CODES = {(255, 255, 255): WHITE, (255, 255, 0): YELLOW, (255, 0, 0): RED}
PALETTE = [(255, 255, 255), (255, 255, 0), (255, 0, 0), (0, 0, 0)]


# ---- command frames ---------------------------------------------------------

def cmd_frame(cmd: int, payload: bytes = b"") -> bytes:
    frame = bytearray(MAGIC + bytes([1, 7 + len(payload), 0, cmd]) + payload)
    frame[5] = sum(frame[6:]) & 0xFF
    return bytes(frame)


def cmd_alloc(total: int) -> bytes:
    return cmd_frame(0x01, struct.pack(">I", total))


def cmd_alloc_batch(total: int, offset: int, length: int) -> bytes:
    return cmd_frame(0x01, struct.pack(">III", total, offset, length))


def cmd_verify() -> bytes:
    return cmd_frame(0x02)


def cmd_refresh(screens: int = 1) -> bytes:
    return cmd_frame(0x04, b"\x03\x03" if screens > 1 else b"\x00")


def cmd_ota() -> bytes:
    # The app builds an 8-byte array whose LEN byte says 7. Reproduce exactly.
    return cmd_frame(0x05) + b"\x00"


# ---- data packets -----------------------------------------------------------

def data_packet(chunk: bytes, idx: int, total: int) -> bytes:
    hdr = bytearray(MAGIC + b"\x02" + struct.pack(">H", 9 + len(chunk)) + bytes([0, total, idx]))
    hdr[6] = (total + idx + sum(chunk)) & 0xFF
    return bytes(hdr) + chunk


def packet_count(n: int) -> int:
    return -(-n // SUB_PACKET)


def data_packets(payload: bytes):
    total = packet_count(len(payload))
    if total > 255:
        raise ValueError("more than 255 packets: split into batches")
    for i in range(total):
        yield data_packet(payload[i * SUB_PACKET:(i + 1) * SUB_PACKET], i, total)


def ble_chunks(packet: bytes, size: int = BLE_WRITE):
    return [packet[i:i + size] for i in range(0, len(packet), size)]


# ---- responses --------------------------------------------------------------

def parse_response(r: bytes):
    """Return (cmd, status) or None if the frame is not an XTE response."""
    if len(r) < 8 or r[:3] != MAGIC:
        return None
    return r[6], r[7]


def bitmap_bits(r: bytes, start: int):
    """Received-packet bitmap, MSB first, 1 = received."""
    bits = []
    for b in r[start:]:
        bits.extend((b >> (7 - i)) & 1 for i in range(8))
    return bits


# ---- pixels -----------------------------------------------------------------

def pack_bwry(pixels, w: int, h: int) -> bytes:
    """pixels: row-major iterable of (r, g, b); exact palette colours only."""
    padw = -(-w // 4) * 4
    it = iter(pixels)
    out = bytearray()
    for _ in range(h):
        row = [CODES.get(tuple(next(it))[:3], BLACK) for _ in range(w)]
        row += [0] * (padw - w)
        for i in range(0, padw, 4):
            out.append(row[i] << 6 | row[i + 1] << 4 | row[i + 2] << 2 | row[i + 3])
    return bytes(out)


def _runs(out: bytearray, count: int, value: int) -> None:
    while count > 0:
        k = min(count, 255)
        out += bytes([k, value])
        count -= k


def rle(data: bytes) -> bytes:
    """Vendor RLE: two halves encoded independently as (count, value) pairs."""
    half = len(data) // 2
    out = bytearray()
    for part in (data[:half], data[half:]):
        if not part:
            continue
        cur, cnt = part[0], 1
        for b in part[1:]:
            if b == cur:
                cnt += 1
            else:
                _runs(out, cnt, cur)
                cur, cnt = b, 1
        _runs(out, cnt, cur)
    return bytes(out)


def container(images, compress: bool = True) -> bytes:
    """images: list of (x, y, w, h, packed_bytes). Returns the XTEK payload."""
    n = len(images)
    buf = bytearray(b"XTEK" + bytes(8) + bytes([n]) + bytes(4 * n))
    offsets = []
    for x, y, w, h, data in images:
        offsets.append(len(buf))
        enc = rle(data) if compress else data
        ctype = 1 if compress and len(enc) <= len(data) else 0
        if ctype == 0:
            enc = data
        buf += struct.pack(">IIIIBI", x, y, w, h, ctype, len(enc)) + enc
    struct.pack_into(">I", buf, 8, len(buf))
    for i, off in enumerate(offsets):
        struct.pack_into(">I", buf, 13 + 4 * i, off)
    struct.pack_into(">I", buf, 4, sum(buf[12:]))
    return bytes(buf)


def image_payload(pixels, w: int, h: int, compress: bool = True) -> bytes:
    return container([(0, 0, w, h, pack_bwry(pixels, w, h))], compress)


# ---- self-test --------------------------------------------------------------

def _pixels(ref, key):
    pal = [tuple(c) for c in ref["palette"]]
    return [pal[int(ch)] for ch in ref[key]]


def selftest() -> int:
    ref_path = Path(__file__).resolve().parent.parent / "testdata" / "reference.json"
    ref = json.loads(ref_path.read_text())
    w, h = ref["w"], ref["h"]
    fails = 0

    def check(name, got: bytes, want_hex: str):
        nonlocal fails
        ok = got.hex() == want_hex
        fails += not ok
        print(f"{'ok  ' if ok else 'FAIL'} {name} ({len(got)} B)")
        if not ok:
            want = bytes.fromhex(want_hex)
            for i, (a, b) in enumerate(zip(got, want)):
                if a != b:
                    print(f"      first diff at {i}: got {a:02x} want {b:02x}")
                    break
            if len(got) != len(want):
                print(f"      length {len(got)} vs {len(want)}")

    noise = _pixels(ref, "pixels")
    payload = image_payload(noise, w, h)
    check("image container (noise, falls back to raw)", payload, ref["container"])
    check("image container (noise, raw forced)", image_payload(noise, w, h, compress=False), ref["container_raw"])
    bands = image_payload(_pixels(ref, "pixels_bands"), w, h)
    check("image container (bands, RLE)", bands, ref["container_bands"])
    assert bands[13 + 4 + 16] == 1, "bands image should have chosen RLE"
    check("cmd alloc", cmd_alloc(len(payload)), ref["alloc"])
    check("cmd alloc batch", cmd_alloc_batch(300000, 204800, 95200), ref["alloc_batch"])
    check("cmd verify", cmd_verify(), ref["verify"])
    check("cmd refresh 1", cmd_refresh(1), ref["refresh1"])
    check("cmd refresh 2", cmd_refresh(2), ref["refresh2"])
    check("cmd ota", cmd_ota(), ref["ota"])
    pk = list(data_packets(payload))
    for idx in ref["packets"]:
        chunks = ble_chunks(pk[int(idx)])
        check(f"data packet {idx} ({len(chunks)} writes)", b"".join(chunks), "".join(ref["packets"][idx]))
        assert [len(c) for c in chunks] == [len(bytes.fromhex(c)) for c in ref["packets"][idx]]
    print(f"{'ALL OK' if not fails else f'{fails} FAILED'}: {w}x{h}, payload {len(payload)} B, {packet_count(len(payload))} packets")
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(selftest())
