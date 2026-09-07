# Ousterhout × Liskov, code audit of the XTE codec boundary

Axis: surface × substitution. Subject: the module boundary between `python/xte.py` (the codec other ports will mirror) and its callers (`python/push.py`, `examples/qr_label.py`, and the future Go and TypeScript ports).

Reviewed 2026-09-07 against `docs/protocol.md` v1.0 and `testdata/reference.json`. The self-test passes (12 vectors, ALL OK). Every finding below is off the vector path; the wire format on the happy path is correct and I did not find a byte-level bug in it.

No 🔴. The codec is right where the conformance suite looks. The problems are in the shape of the boundary and in what happens when a caller steps off the vectors.

---

## Ousterhout: is the boundary deep, and does it hide or relocate?

The one deep function is `image_payload` (`python/xte.py:154`). Pixels in, XTEK container out, three internal stages hidden. That is the interface a port should mirror first. Everything below it is thinner than it looks.

### 🟠 O1. `parse_response` is shallow enough that its only caller parses again

Locus: `python/xte.py:80-84`, used at `python/push.py:82-84`, then bypassed at `python/push.py:107`, `python/push.py:121`, `python/push.py:124`, `python/push.py:126`.

`parse_response` returns `(cmd, status)` and hides a 3-byte magic check and a length check. `expect()` uses the tuple only to match `cmd`, then returns the raw `r` so the caller can do `r[7]` for status and `xte.bitmap_bits(r, 8)` for the bitmap. The caller has to know offsets 7 and 8 from the spec. The abstraction pays interface cost (a function, a `None` case, a tuple) without removing a single protocol detail from the caller.

Fix. Return a small record and put the bitmap behind it:

```python
@dataclass(frozen=True)
class Response:
    cmd: int
    status: int
    extra: bytes          # bytes 8..length-1, padding excluded

    def missing_packets(self, total: int) -> list[int]: ...   # knows 02 -> byte 7, 04/05 -> byte 8
```

Then `push.py` never indexes a notification. A Go port mirrors a struct with a method, not two loose offsets.

### 🟠 O2. `bitmap_bits(r, start)` makes the caller supply a protocol constant

Locus: `python/xte.py:87-92`, caller `python/push.py:126`.

`start` is 7 for command `02` and 8 for `04`/`05` (spec 6.3). The codec knows this and the caller does not, yet the parameter shape puts the decision on the caller, hard-coded as `8` in `push.py`. A port mirroring `bitmapBits(r, start)` reproduces the leak. The function also reads to the end of the notification, not to the frame length at byte 4 (spec 6.4 step 1), so padding bytes come back as "missing" bits and the caller has to truncate with `[:len(packets)]`. Two facts the codec should own are being relocated to the caller.

Fix. Fold into O1: `missing_packets(total)` dispatches on `cmd`, bounds by the length byte, and truncates to `total`.

### 🟠 O3. Errors leak the implementation, and there is no error type to mirror

Loci and the messages a caller sees:

| call | line | error surfaced |
|---|---|---|
| `pack_bwry` with fewer than `w*h` pixels | `python/xte.py:103` | bare `StopIteration` |
| `pack_bwry` with a non-iterable pixel | `python/xte.py:103` | `TypeError: 'int' object is not iterable` |
| `container` with 256 images | `python/xte.py:138` | `ValueError: bytes must be in range(0, 256)` |
| `container` with negative or >u32 geometry | `python/xte.py:146` | `struct.error: 'I' format requires 0 <= number <= 4294967295` |
| `cmd_frame` with a 249-byte payload | `python/xte.py:28` | `ValueError: bytes must be in range(0, 256)` |
| `cmd_alloc(-1)` | `python/xte.py:34` | `struct.error` |

Only `data_packets` (`python/xte.py:69`) raises a deliberate error. Every other precondition is enforced by whichever Python builtin happens to trip first, with a message about Python internals rather than the protocol. A Go port cannot mirror `struct.error`; it has to invent error semantics the Python never wrote down.

Fix. One `class XTEError(ValueError)` and explicit checks at the three public entry points (`image_payload`/`container`, `data_packets`, `cmd_frame`): `n <= 255`, `0 <= x,y,w,h < 2**32`, `len(payload) <= 248`, `len(pixels) == w*h`. Message in protocol vocabulary ("container holds at most 255 images"). Ports mirror the check list, not the Python.

### 🟠 O4. `data_packets` guards the wrong bound, and the batch story is relocated to nowhere

Locus: `python/xte.py:66-71`, `python/xte.py:16` (`BATCH`), `python/xte.py:37` (`cmd_alloc_batch`), `python/push.py:103-105`.

The guard is `total > 255` packets. The spec's binding limit is the batch size, 204800 bytes, which is 170 packets; the 255 check never fires first under the spec. So `data_packets(b"\x00" * 300000)` succeeds (248 packets) and `push.py:105` sends the 11-byte single alloc for a container the spec says needs the 19-byte batch form (spec 6.1, 8.4). Reachable from the CLI with `--width 1000 --height 1000 --rotate 0`. The error message says "split into batches" but the library provides no batching; it exports `BATCH` and `cmd_alloc_batch` and leaves the 8.4 procedure to each caller. That is complexity relocated, not hidden.

Fix. Either check `len(payload) <= BATCH` in `data_packets` and add `batches(payload) -> list[tuple[offset, length, packets]]` so the 8.4 procedure has a codec-side shape, or state in the docstring that the codec is single-batch only and have `push.py` refuse anything over `BATCH`.

### 🟡 O5. `container`'s record is a positional 5-tuple

Locus: `python/xte.py:135-136`, `python/xte.py:140`.

`(x, y, w, h, packed_bytes)` is the wire record's field order exposed as the API's parameter shape. Fine in Python, but the docstring is the only place the order lives, and it is the shape the ports will copy. A named record (`ImageRecord`) costs nothing and gives Go and TS an obvious struct to mirror.

### 🟡 O6. Two callers reach into the opaque container with a hand-computed offset

Locus: `python/push.py:157` (`payload[13 + 4 + 16]`) and `python/xte.py:191` (`bands[13 + 4 + 16]`).

The container is supposed to be opaque bytes. Both readers compute "compression byte of image 0" by hand, and the literal is only right for `N == 1`. The self-test doing it is forgivable; the pusher doing it means the codec did not give callers what they needed.

Fix. Have `image_payload` return (or expose via a tiny `container_info(payload)`) the chosen compression, or drop the print.

### 🟡 O7. `load_pixels` is a seven-parameter function, and three of the knobs produce output the spec forbids

Locus: `python/push.py:36`, `python/push.py:145-149`.

`--pad-width`, `--flip-v`, and `--rotate 0` all exist so the user can produce exactly the shear the spec warns against (8.1: "Do not send 63-byte rows and do not pad the width to 128"). These are debugging leftovers now on the user surface. Ousterhout's move is to define the error out of existence: remove the knobs, or move them behind a `--geometry-experiment` flag with the warning attached.

### 🟡 O8. Name collisions across the two vocabularies

Locus: `python/xte.py:20-22`, `examples/qr_label.py:16`.

`xte.WHITE` is the code `1`; `qr_label.WHITE` is the RGB `(255,255,255)`. Same four names, different types, and `PALETTE[3]` is black while `BLACK == 0`, so palette index and code disagree. Nothing breaks, but a reader holding both files pays for it.

Fix. Rename the codes `CODE_WHITE` etc., or make `PALETTE` a dict keyed by code so index and code cannot drift.

### 🟡 O9. `cmd_refresh(screens: int)` is an int with two behaviours

Locus: `python/xte.py:45-46`.

`0`, `-3`, `1`, `True` all give `00`; anything above `1` gives `03 03`. The parameter type promises a range the function does not honour. `multi_screen: bool` says what the wire actually distinguishes.

---

## Liskov: what does each function promise, and who depends on more than that?

The spec is the supertype. `xte.py` is one implementation of it, and the Go and TS ports will be others. Substitution holds only where the promise is written down and kept off the happy path.

### 🟠 L1. `pack_bwry` has an unstated precondition and violating it can fail silently

Locus: `python/xte.py:97-103`.

Precondition (unstated): the iterable yields at least `w*h` pixels. Violation surfaces as a bare `StopIteration` escaping a non-generator function. That exception is special. Inside `map()` or any iterator protocol it is treated as end-of-sequence, not as an error:

```python
list(map(lambda p: xte.pack_bwry(p, 4, 2), [good, short, good]))   # -> 1 result, no exception
```

Three frames in, one out, nothing raised. This is the one place the codec can produce a wrong answer without telling anyone. Also unstated and silently accepted: extra pixels beyond `w*h` are dropped, and a 4-tuple's alpha is discarded (`[:3]`), so transparent white packs as white.

Fix. `pixels = list(pixels)` (or check `len`) and raise `XTEError("expected w*h pixels")`. State the alpha rule in the docstring or reject 4-tuples.

### 🟠 L2. `container` does not hold the invariant that makes the tag draw correctly

Locus: `python/xte.py:135-146`.

The container is a well-formed frame for any `(w, h, data)` triple. The tag additionally requires `len(data) == ceil(w/4) * h`. `container([(0, 0, 122, 250, b"\x00" * 63 * 122)])` returns a valid-looking 7,7xx-byte payload with a correct checksum that displays as diagonal shear (spec 8.1). `image_payload` satisfies the invariant by construction; `container` is public and does not. A port that mirrors `container` inherits the hole.

Fix. Check the invariant in `container` and raise `XTEError`. If non-BWRY packings are ever in scope, pass the bytes-per-pixel rule in rather than dropping the check.

### 🟠 L3. `push.py`'s patch loop can exit 0 without success or failure

Locus: `python/push.py:116-132`.

Trace the path where status is `0x68` and the bitmap has no zero bits: `missing == []` hits `continue` at line 129. After the fourth such refresh the `for` ends, `push()` returns `None`, and the process exits 0 with no "done" line and no error. The protocol's postcondition for a push is "status `FF` received" (spec 8.2 step 10); the function's implicit postcondition is "returned without raising", which is weaker. Unlikely on hardware, but this is exactly the case the spec calls "unknown result, disconnect".

Fix. After the loop, `sys.exit("refresh never acknowledged")`.

### 🟠 L4. `parse_response` promises "None if not an XTE response" and returns tuples for non-responses

Locus: `python/xte.py:80-84`, docstring line 81.

Postcondition stated: `None` unless the frame is an XTE response. Postcondition delivered: `None` unless the first three bytes are `XTE` and the length is at least 8. `parse_response(xte.cmd_alloc(10))` returns `(1, 0)`; a command frame is not a response. The type byte (`04`, spec 6.3) and the checksum are both available and both ignored. The spec only mandates the two checks the code makes, so this is not wrong against the spec, but the docstring promises more than the code keeps, and `push.py:83` matches on `parsed[0] == cmd` alone, so a stray frame with the right byte at offset 6 would be accepted as the answer.

Fix. Check `r[3] == 0x04`, and either verify the checksum or say in the docstring that it is not verified.

### 🟠 L5. `data_packets` defers its precondition check to first iteration

Locus: `python/xte.py:66-71`.

It is a generator, so `data_packets(oversized)` returns without error and the `ValueError` fires on the first `next()`. `push.py:103` happens to call `list()` immediately, so it works. A caller that stores the generator, or a port that mirrors "returns an iterator" and then checks lazily, gets the failure at a different time than the Python docstring implies (there is no docstring). Precondition checks belong at the call, not at first use.

Fix. Validate, then return a list, or split into `check_batch(payload)` plus the generator.

### 🟡 L6. `push.py` depends on a bleak promise that was never made

Locus: `python/push.py:88-92`.

`client._backend._acquire_mtu()` is a private BlueZ backend method. It is guarded by `hasattr` and `try/except`, so a bleak upgrade degrades to the 23-byte default rather than crashing, and the spec says 20-byte writes are correct. The dependency is contained. It still belongs in a comment naming the bleak version it was observed on, so the next reader knows it is a probe and not an API.

### 🟡 L7. `pack_bwry`'s docstring and its behaviour disagree on off-palette pixels

Locus: `python/xte.py:98` vs `python/xte.py:103` and `testdata/README.md` ("The codec must map them to black").

The docstring says "exact palette colours only", which reads as a precondition. The spec (7.2) and the reference vectors make "any other RGB maps to code 0" a postcondition, and the conformance suite tests it with indices 4 and 5. A port reading the docstring could reasonably raise on off-palette input and fail conformance.

Fix. Docstring: "Any RGB not in CODES packs as black (spec 7.2)."

### 🟡 L8. `rle` and the equal-length tie are correct, and worth pinning

Locus: `python/xte.py:117-132`, `python/xte.py:143`.

Both match the spec (`floor(n/2)` split, `<=` tie chooses RLE, empty half skipped, 1-byte input goes entirely to the second half). None of the edge cases is in `reference.json`, so a port that gets the split or the tie wrong passes conformance. That is a gap in the supertype's test, not in this implementation. Add vectors for odd length, length 1, and the equal-length tie.

---

## Where they converge

1. The response side is the weakest boundary, and both eyes land on it. Ousterhout sees a shallow `parse_response` whose caller re-parses (O1, O2); Liskov sees a docstring promising `None` for non-responses and a caller matching on one byte (L4). One fix serves both: a `Response` record that owns cmd, status, extra bytes, and `missing_packets(total)`.

2. Preconditions are enforced by accident. Ousterhout reads it as leaked internals (O3, six different builtin errors); Liskov reads it as unstated contracts whose violation is sometimes silent (L1, L2, L5). One `XTEError` plus explicit checks at the public entry points closes both.

3. The container invariant `len(data) == ceil(w/4)*h` is the thing the tag actually cares about, and neither the shape (O5, a bare tuple) nor the contract (L2) carries it. Whatever the ports mirror, it should be a record that cannot be built inconsistent.

4. `image_payload` is the model. It is deep (Ousterhout) and its postcondition is exactly the conformance vectors (Liskov). The recommendation to the ports is to mirror `image_payload`, `data_packets`, `cmd_*`, and a `Response` type, and to treat `pack_bwry`, `rle`, and `container` as internals the vectors exercise indirectly.

## Where they pull apart

- Ousterhout would shrink `push.py`'s surface by deleting `--pad-width`, `--flip-v`, `--rotate` (O7). Liskov has no objection to the knobs as long as the spec's postcondition (correct display) is not claimed for them; the docstring at `push.py:8-12` says the default path is verified and the knobs are opt-in. Ousterhout wins on cost, Liskov on principle. I side with Ousterhout here because the knobs are the only way to produce the failure mode the spec spends a paragraph on.

- Ousterhout would fold `bitmap_bits` and `parse_response` into one deep call and stop there. Liskov additionally wants the type byte and checksum checked (L4), which widens the implementation without widening the interface. Both can be had.

- Liskov's L8 asks for more vectors, which is a supertype change (the spec and its suite). Ousterhout is indifferent to test count and cares that the port author has less to know. Adding edge vectors adds nothing to know and removes a way to be wrong, so the tension is small.

- On `data_packets` Liskov wants the check at call time (L5). Ousterhout would rather the 255-packet case not exist (O4): make the codec batch, and there is no oversized single batch to reject. The second is the deeper fix but the larger change; the first is a two-line change and enough for the PSJ-213.
