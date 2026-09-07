#!/usr/bin/env python3
"""XTE protocol codec for the Poshiji PSJ-213 tag. Pure Python, no BLE.

Byte layouts in docs/protocol.md. Run this file directly to self-test
against testdata/reference.json (see testdata/README.md for provenance).

Public surface a port should mirror:

    image_payload(pixels, w, h)      -> container bytes      (spec 7)
    data_packets(payload)            -> list of packet bytes (spec 6.2)
    ble_chunks(packet)               -> list of writes       (spec 4.2)
    cmd_alloc / cmd_verify / cmd_refresh / cmd_ota            (spec 6.1)
    parse_response(notification)     -> Response | None      (spec 6.3)
    Response.missing_packets(total)  -> list of indexes      (spec 6.4)
    XTEError                         every precondition failure

Timing policy (timeouts, retry counts) lives in the transport, not here.
"""

import json
import struct
import sys
from dataclasses import dataclass
from pathlib import Path

MAGIC = b"XTE"
SUB_PACKET = 1211      # payload bytes per data packet
BLE_WRITE = 244        # bytes per write-without-response
BATCH = 204800         # largest container this codec sends as one batch (spec 8.2)
MAX_CMD_PAYLOAD = 248  # command frame length is a u8
U32 = 0xFFFFFFFF

CODE_BLACK, CODE_WHITE, CODE_YELLOW, CODE_RED = 0, 1, 2, 3
CODES = {(255, 255, 255): CODE_WHITE, (255, 255, 0): CODE_YELLOW, (255, 0, 0): CODE_RED}
PALETTE = [(255, 255, 255), (255, 255, 0), (255, 0, 0), (0, 0, 0)]


class XTEError(ValueError):
    """A caller broke a precondition of the protocol. Never raised on the vector path."""


def _u32(name: str, v: int) -> int:
    if not isinstance(v, int) or not 0 <= v <= U32:
        raise XTEError(f"{name} must be a u32, got {v!r}")
    return v


# ---- command frames ---------------------------------------------------------

def cmd_frame(cmd: int, payload: bytes = b"") -> bytes:
    if not 0 <= cmd <= 255:
        raise XTEError(f"command must be a byte, got {cmd!r}")
    if len(payload) > MAX_CMD_PAYLOAD:
        raise XTEError(f"command payload is {len(payload)} bytes, limit {MAX_CMD_PAYLOAD}")
    frame = bytearray(MAGIC + bytes([1, 7 + len(payload), 0, cmd]) + payload)
    frame[5] = sum(frame[6:]) & 0xFF
    return bytes(frame)


def cmd_alloc(total: int) -> bytes:
    """Allocate flash for a whole container (spec 6.1, 11 bytes)."""
    return cmd_frame(0x01, struct.pack(">I", _u32("total", total)))


def cmd_alloc_batch(total: int, offset: int, length: int) -> bytes:
    """Allocate flash for one batch of a large container (spec 6.1, 19 bytes)."""
    return cmd_frame(0x01, struct.pack(">III", _u32("total", total), _u32("offset", offset), _u32("length", length)))


def cmd_verify() -> bytes:
    return cmd_frame(0x02)


def cmd_refresh(multi_screen: bool = False) -> bytes:
    """Refresh the panel. multi_screen selects the 03 03 payload for tags with more than one screen."""
    return cmd_frame(0x04, b"\x03\x03" if multi_screen else b"\x00")


def cmd_ota() -> bytes:
    # The vendor app builds an 8-byte array whose LEN byte says 7. Reproduce exactly.
    return cmd_frame(0x05) + b"\x00"


# ---- data packets -----------------------------------------------------------

def data_packet(chunk: bytes, idx: int, total: int) -> bytes:
    if len(chunk) > SUB_PACKET:
        raise XTEError(f"data packet carries {len(chunk)} bytes, limit {SUB_PACKET}")
    if not 0 <= idx < total <= 255:
        raise XTEError(f"packet index {idx} of {total} out of range")
    hdr = bytearray(MAGIC + b"\x02" + struct.pack(">H", 9 + len(chunk)) + bytes([0, total, idx]))
    hdr[6] = (total + idx + sum(chunk)) & 0xFF
    return bytes(hdr) + chunk


def packet_count(n: int) -> int:
    return -(-n // SUB_PACKET)


def data_packets(payload: bytes) -> list:
    """All data packets of a single-batch container, in index order.

    Containers larger than BATCH need the multi-batch procedure (spec 8.4),
    which this codec does not implement. No PSJ-213 image approaches it.
    """
    if len(payload) == 0:
        raise XTEError("empty payload")
    if len(payload) > BATCH:
        raise XTEError(f"container is {len(payload)} bytes; single-batch limit is {BATCH} (spec 8.4 not implemented)")
    total = packet_count(len(payload))
    return [data_packet(payload[i * SUB_PACKET:(i + 1) * SUB_PACKET], i, total) for i in range(total)]


def ble_chunks(packet: bytes, size: int = BLE_WRITE) -> list:
    if not 1 <= size <= BLE_WRITE:
        raise XTEError(f"write size {size} outside 1..{BLE_WRITE}")
    return [packet[i:i + size] for i in range(0, len(packet), size)]


# ---- responses --------------------------------------------------------------

STATUS_OK = 0xFF
STATUS_MISSING = 0x68


@dataclass(frozen=True)
class Response:
    """One validated response frame (spec 6.3). extra excludes the padding."""
    cmd: int
    status: int
    extra: bytes
    raw: bytes

    def missing_packets(self, total: int) -> list:
        """Indexes the tag did not receive, from the bitmap (spec 6.4).

        The bitmap starts at byte 7 for a verify (02) reply and at byte 8 for
        a refresh (04/05) reply. Bits the frame does not carry count as missing.
        """
        start = 7 if self.cmd == 0x02 else 8
        length = self.raw[4]
        bits = []
        for b in self.raw[start:length]:
            bits.extend((b >> (7 - i)) & 1 for i in range(8))
        bits = bits[:total] + [0] * max(0, total - len(bits))
        return [i for i, bit in enumerate(bits) if not bit]


def parse_response(r: bytes):
    """Return a Response, or None if r is not a well-formed XTE response.

    Checks magic, frame type 04, the length byte against the notification,
    and the checksum over bytes 6..length-1. Anything else is ignored, as
    the spec says.
    """
    if len(r) < 8 or r[:3] != MAGIC or r[3] != 0x04:
        return None
    length = r[4]
    if length < 8 or length > len(r):
        return None
    if sum(r[6:length]) & 0xFF != r[5]:
        return None
    return Response(cmd=r[6], status=r[7], extra=bytes(r[8:length]), raw=bytes(r))


# ---- pixels -----------------------------------------------------------------

def row_bytes(w: int) -> int:
    """Packed bytes per row: w pixels padded to a multiple of 4, two bits each."""
    return -(-w // 4)


def pack_bwry(pixels, w: int, h: int) -> bytes:
    """Pack w*h row-major (r, g, b) pixels at two bits per pixel (spec 7.2).

    Exact matches for white, yellow and red take codes 1, 2, 3. Any other
    colour, including near-white and anti-aliased edges, packs as black (0).
    Quantise first. Raises XTEError unless exactly w*h pixels are given.
    """
    if w <= 0 or h <= 0:
        raise XTEError(f"image size {w}x{h} must be positive")
    px = list(pixels)
    if len(px) != w * h:
        raise XTEError(f"expected {w * h} pixels for {w}x{h}, got {len(px)}")
    padw = row_bytes(w) * 4
    out = bytearray()
    for y in range(h):
        row = [CODES.get(tuple(p)[:3], CODE_BLACK) for p in px[y * w:(y + 1) * w]]
        row += [0] * (padw - w)
        for i in range(0, padw, 4):
            out.append(row[i] << 6 | row[i + 1] << 4 | row[i + 2] << 2 | row[i + 3])
    return bytes(out)


def _runs(out: bytearray, count: int, value: int) -> None:
    while count > 0:                       # greedy: 300 -> (255, v), (45, v)
        k = min(count, 255)
        out += bytes([k, value])
        count -= k


def rle(data: bytes) -> bytes:
    """Vendor RLE (spec 7.3): two halves encoded independently as (count, value) pairs.

    The first half is floor(n/2) bytes; an empty half produces no output.
    """
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


@dataclass(frozen=True)
class ImageRecord:
    """One image inside a container. data must be exactly row_bytes(w) * h packed bytes."""
    x: int
    y: int
    w: int
    h: int
    data: bytes

    def __post_init__(self):
        for name in ("x", "y", "w", "h"):
            _u32(name, getattr(self, name))
        want = row_bytes(self.w) * self.h
        if len(self.data) != want:
            raise XTEError(f"image {self.w}x{self.h} needs {want} packed bytes, got {len(self.data)} "
                           f"(rows must be {row_bytes(self.w)} bytes; see spec 7.2 and 8.1)")


def container(images, compress: bool = True) -> bytes:
    """Build the XTEK container (spec 7.1) from ImageRecords."""
    images = [im if isinstance(im, ImageRecord) else ImageRecord(*im) for im in images]
    n = len(images)
    if not 1 <= n <= 255:
        raise XTEError(f"container holds 1..255 images, got {n}")
    buf = bytearray(b"XTEK" + bytes(8) + bytes([n]) + bytes(4 * n))
    offsets = []
    for im in images:
        offsets.append(len(buf))
        enc = rle(im.data) if compress else im.data
        ctype = 1 if compress and len(enc) <= len(im.data) else 0   # tie: RLE wins
        if ctype == 0:
            enc = im.data
        buf += struct.pack(">IIIIBI", im.x, im.y, im.w, im.h, ctype, len(enc)) + enc
    if len(buf) > U32:
        raise XTEError("container too large")
    struct.pack_into(">I", buf, 8, len(buf))
    for i, off in enumerate(offsets):
        struct.pack_into(">I", buf, 13 + 4 * i, off)
    struct.pack_into(">I", buf, 4, sum(buf[12:]) & U32)
    return bytes(buf)


def container_info(payload: bytes) -> dict:
    """Header facts of a container: total length, image count, and each record's geometry and compression."""
    if payload[:4] != b"XTEK" or len(payload) < 13:
        raise XTEError("not an XTEK container")
    n = payload[12]
    recs = []
    for i in range(n):
        off = struct.unpack_from(">I", payload, 13 + 4 * i)[0]
        x, y, w, h, ctype, dlen = struct.unpack_from(">IIIIBI", payload, off)
        recs.append({"x": x, "y": y, "w": w, "h": h, "compressed": bool(ctype), "data_len": dlen})
    return {"length": struct.unpack_from(">I", payload, 8)[0], "images": recs}


def image_payload(pixels, w: int, h: int, compress: bool = True) -> bytes:
    """Pixels in, container out. One full-screen image record at (0, 0)."""
    return container([ImageRecord(0, 0, w, h, pack_bwry(pixels, w, h))], compress)


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

    def expect_error(name, fn):
        nonlocal fails
        try:
            fn()
        except XTEError:
            print(f"ok   {name} raises XTEError")
            return
        fails += 1
        print(f"FAIL {name} did not raise")

    # vendor-generated vectors (first generation)
    noise = _pixels(ref, "pixels")
    payload = image_payload(noise, w, h)
    check("image container (noise, falls back to raw)", payload, ref["container"])
    check("image container (noise, raw forced)", image_payload(noise, w, h, compress=False), ref["container_raw"])
    bands = image_payload(_pixels(ref, "pixels_bands"), w, h)
    check("image container (bands, RLE)", bands, ref["container_bands"])
    assert container_info(bands)["images"][0]["compressed"], "bands image should have chosen RLE"
    check("cmd alloc", cmd_alloc(len(payload)), ref["alloc"])
    check("cmd alloc batch", cmd_alloc_batch(300000, 204800, 95200), ref["alloc_batch"])
    check("cmd verify", cmd_verify(), ref["verify"])
    check("cmd refresh 1", cmd_refresh(False), ref["refresh1"])
    check("cmd refresh 2", cmd_refresh(True), ref["refresh2"])
    check("cmd ota", cmd_ota(), ref["ota"])
    pk = data_packets(payload)
    for idx in ref["packets"]:
        chunks = ble_chunks(pk[int(idx)])
        check(f"data packet {idx} ({len(chunks)} writes)", b"".join(chunks), "".join(ref["packets"][idx]))
        assert [len(c) for c in chunks] == [len(bytes.fromhex(c)) for c in ref["packets"][idx]]

    # second-generation vectors (this codec, hardware-verified shapes)
    if "portrait" in ref:
        p = ref["portrait"]
        check(f"portrait container {p['w']}x{p['h']} (real push shape)",
              image_payload(_pixels(p, "pixels"), p["w"], p["h"]), p["container"])
    if "rle_tie" in ref:
        t = ref["rle_tie"]
        check("RLE tie chooses RLE", container([ImageRecord(0, 0, t["w"], t["h"], bytes.fromhex(t["packed"]))]), t["container"])
    for name, hexs in ref.get("responses", {}).items():
        r = parse_response(bytes.fromhex(hexs))
        ok = r is not None and (r.cmd, r.status) == tuple(ref["responses_decoded"][name])
        fails += not ok
        print(f"{'ok  ' if ok else 'FAIL'} response {name} -> {(r.cmd, r.status) if r else None}")

    # preconditions
    expect_error("short pixel list", lambda: pack_bwry(noise[:-1], w, h))
    expect_error("stride invariant", lambda: container([ImageRecord(0, 0, 122, 250, bytes(63 * 122))]))
    expect_error("oversized batch", lambda: data_packets(bytes(BATCH + 1)))
    expect_error("u32 range", lambda: cmd_alloc(-1))
    expect_error("payload limit", lambda: cmd_frame(1, bytes(249)))
    assert parse_response(b"XTE\x04\x08\x00\x04\xff") is None, "bad checksum must be rejected"
    resp = parse_response(bytes.fromhex("58544504080304ff0000000000000000"))
    assert resp and resp.status == STATUS_OK and resp.extra == b"", "FF reply has no extra bytes"
    short = parse_response(bytes.fromhex("5854450409" + "%02x" % ((0x04 + 0x68 + 0xFF) & 0xFF) + "0468ff"))
    assert short and short.missing_packets(12) == list(range(8, 12)), "bits the frame lacks count as missing"
    resp68 = parse_response(bytes.fromhex("5854450409" + "%02x" % ((0x04 + 0x68 + 0xA0) & 0xFF) + "0468a0"))
    assert resp68 and resp68.missing_packets(4) == [1, 3], "bitmap 1010 -> packets 1 and 3 missing"
    print("ok   preconditions and response parsing")

    print(f"{'ALL OK' if not fails else f'{fails} FAILED'}: {w}x{h}, payload {len(payload)} B, {packet_count(len(payload))} packets")
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(selftest())
