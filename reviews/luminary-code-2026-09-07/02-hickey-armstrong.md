# Hickey × Armstrong code audit: push.py, xte.py, qr_label.py

Pair: Rich Hickey × Joe Armstrong. Axis: structure × runtime. Stage: after, code audit.
Subject: the BLE pusher in `python/push.py`, the codec in `python/xte.py`, and `examples/qr_label.py`, read against `docs/protocol.md` sections 4, 6 and 8. Hardware was not exercised; every finding is reasoned from the code and the spec.

Severity key. 🔴 must-fix, a real defect. 🟠 should-fix, wrong under a plausible fault or a spec deviation. 🟡 consider, structural or ergonomic.

Overall verdict first. `xte.py` is the good part of this codebase. Frames are built as immutable byte values, packets are materialised once (`push.py:103`) and resent as the same value in the patch loop, and the codec has a reference self-test. The problems concentrate in `push()`, where the protocol state machine, the transport, the response parsing, the logging and process termination are braided into one coroutine, and where the two terminal failure paths that matter most (a silent success and a blank timeout) are the ones least well handled.

## Hickey: what is complected, where state hides, where simple became easy

### H1 🟠 The response is never reified as a value; callers re-parse raw bytes with magic offsets

`xte.parse_response` (`python/xte.py:80-84`) returns a bare `(cmd, status)` tuple and throws away the rest of the frame. `expect()` uses that tuple only to filter (`python/push.py:83`) and then returns the raw `bytes` (`python/push.py:84`). Every caller then reaches back into the raw frame by offset:

```python
# python/push.py:107
if r[7] != 0xFF:
# python/push.py:121, 124
if r[7] == 0xFF:
if r[7] != 0x68:
# python/push.py:126
missing = [i for i, bit in enumerate(xte.bitmap_bits(r, 8)[:len(packets)]) if not bit]
```

The layout knowledge that `docs/protocol.md` §6.3 assigns to the codec (status at byte 7, bitmap from byte 8 for `04`, from byte 7 for `02`) has leaked into the pusher as literals. The "response frame" concept exists in the spec and in the tag but nowhere in the code. That is data-and-process complected, and it is why the `02` verify response (bitmap at byte 7, §6.3) would need a second copy of line 126 with a different literal if §8.4 batching were ever implemented.

Fix. Make `parse_response` return a small immutable value, e.g. `Response(cmd, status, extra: bytes)` with `extra = r[8:length]`, and add `xte.missing_packets(resp, total) -> list[int]` that knows the per-command bitmap offset. `expect()` returns the `Response`; `push()` never indexes bytes.

### H2 🟠 Process termination is complected with protocol outcome

`sys.exit(...)` is called from inside the coroutine at `python/push.py:67, 108, 125, 131`. `push()` therefore cannot be called from anything but this CLI, cannot be tested for its failure outcomes without catching `SystemExit`, and cannot report *which* failure happened except as a string on stderr. The "outcome" of a push (allocated, refused, refresh accepted, missing packets, gave up) is a value; here it is a side effect on the interpreter.

Fix. Define `class PushError(Exception)` (or a small enum-tagged exception) in `push.py`, raise it at those four sites, and let `main()` catch it once at `python/push.py:164` and translate to an exit code and a one-line message. `qr_label.py:33` has the same smell (`raise SystemExit` from `render()`); the fix is the same, raise `ValueError` and let `main` exit.

### H3 🟡 The session state machine is implicit in control flow, and it has an unhandled terminal state

`push()` (`python/push.py:61-132`) implements §8.2 and §8.3 as an imperative sequence with closures over `client`, `chunk`, `packets`, `inbox`. The states (allocated, sent, refresh-pending, patch round n) are never named; they are positions in the source. The consequence is a state nobody wrote down: the loop at `python/push.py:116-132` can exhaust without either `return` or `sys.exit` (see A1 below for the runtime consequence). A state machine expressed as data, even a tiny one, cannot fall off the end.

Fix. Pull the procedure into a pure `next_step(state, response) -> (state', action)` or, less ambitiously, end the loop with an explicit `raise PushError("refresh never accepted after N rounds")` so every exit from the function is named.

### H4 🟡 The inbox is a mutable place that discards history

`inbox` (`python/push.py:69`) is drained by `expect()` and every non-matching frame is printed and dropped (`python/push.py:85`). The spec says to ignore them, so the behaviour is right, but the queue-as-place means that after a failure the program has no record of what the tag actually said. When a push fails on real hardware, the sequence of frames *is* the diagnostic. A list of `(t, frame)` appended to and never mutated is simpler than a queue that forgets.

Fix. Keep `inbox` for waiting, but also append every received frame to a `log: list[tuple[float, bytes]]` that `main()` prints on failure. Cheap, and it makes A4 (disconnect misdiagnosis) visible after the fact.

### H5 🟡 Runtime policy lives in the "pure codec"

`CMD_TIMEOUT` and `MAX_PATCH_ROUNDS` (`python/xte.py:17-18`) are not byte-layout facts; they are §4.3 and §8.3 host policy. `xte.py` says of itself "Pure Python, no BLE" (`python/xte.py:2`), and it is, but policy is now imported by the pusher from the codec. Small, but it is the beginning of the codec becoming the place everything gets put.

Fix. Move both constants to `push.py`, or into a `PROCEDURE` dict in `xte.py` explicitly labelled as §4.3/§8.3 policy, separate from the layout section.

### H6 🟡 Exploration knobs shipped in the verified tool, and one docstring example contradicts the spec

`--rotate`, `--pad-width` and `--flip-v` (`python/push.py:145-149`) survive from the geometry hunt. `docs/protocol.md` §8.1 now says explicitly: "Do not flip the image vertically" and "do not pad the width to 128. Both display as diagonal shear." The docstring example `--height 128` at `python/push.py:5` produces a 128-wide buffer, which §8.1 says shears. These knobs complect "the way that works" with "the ways we tried". A user reading `--help` cannot tell which is which.

Fix. Delete `--flip-v` and `--pad-width`, fix the docstring example, and keep `--rotate` only if some other tag needs it (then say so in the help string).

### H7 🟡 `pack_bwry` silently maps any off-palette pixel to black

`python/xte.py:103`: `CODES.get(tuple(next(it))[:3], BLACK)`. The docstring says "exact palette colours only", but the function enforces that contract by quietly substituting black. Today `load_pixels` quantises first, so it never triggers, but the codec's own self-test could not catch a future caller that skips quantisation; the image would just come out mostly black. Easy (a default) chosen over simple (a contract).

Fix. `CODES[...]` with a `KeyError` wrapped into `ValueError(f"pixel {rgb} not in palette")`, or accept a pre-coded `bytes` of 0..3 and move the RGB→code map to the caller. Also the pixel round-trip `bytes -> list of 3-tuples -> tuple(...)[:3]` (`python/push.py:58`, `python/xte.py:103`) is value churn; `raw` bytes with a stride of 3 would do.

## Armstrong: every external call, what crashes, who notices, message contract

### A1 🔴 A refresh that never succeeds can exit 0 with no message

`python/push.py:116-132`:

```python
for attempt in range(xte.MAX_PATCH_ROUNDS + 1):
    ...
    r = await expect(0x04)
    if r[7] == 0xFF:
        ...
        return
    if r[7] != 0x68:
        sys.exit(...)
    missing = [i for i, bit in enumerate(xte.bitmap_bits(r, 8)[:len(packets)]) if not bit]
    ...
    if not missing:
        continue
    if attempt == xte.MAX_PATCH_ROUNDS:
        sys.exit("gave up patching")
    await send(missing)
```

If every round returns status `68` with an empty `missing` list, the loop `continue`s four times, runs out, `push()` returns `None`, `asyncio.run` returns, `main()` returns, and the process exits 0 without printing "done". The tag has not refreshed. The caller (a script, a cron job, a human glancing at `$?`) is told the image is on screen.

When does `68` come with an empty bitmap? Two concrete ways from this code alone. First, a `68` response of exactly 8 bytes: `bitmap_bits(r, 8)` returns `[]`, so `missing` is `[]`. Second, any firmware or frame variant where the bitmap sits at byte 7 rather than 8 (the spec itself has both layouts, §6.3), which makes the slice land on the wrong bytes. Neither is exotic. The fix is one line and it turns a silent lie into a crash.

Fix. After the loop, `raise PushError(f"refresh returned 0x68 with no missing packets, {attempt + 1} times")`. Better, treat `68` with an empty bitmap as its own error immediately, because it means the host and tag disagree about the frame layout and another round will not help.

### A2 🟠 The command timeout crashes with an empty message

`python/push.py:75-85`:

```python
async def expect(cmd: int, timeout: float = xte.CMD_TIMEOUT) -> bytes:
    deadline = time.monotonic() + timeout
    while True:
        left = deadline - time.monotonic()
        if left <= 0:
            raise TimeoutError(f"no response to cmd {cmd:#04x}")
        r = await asyncio.wait_for(inbox.get(), left)
```

`asyncio.wait_for` raises `TimeoutError` itself when `left` elapses, and on Python 3.12 that exception carries an empty message (verified: `TimeoutError('')`). The `left <= 0` branch only runs if a *non-matching* frame arrives in the last instant before the deadline, so the informative message at line 80 is effectively dead code. What the user sees for the most common failure on real hardware (tag busy, tag asleep, tag out of range after connect) is a bare traceback ending in `TimeoutError` with no command named, and no exit path in `main()` catches it (`python/push.py:164`).

Fix. Wrap the `wait_for` in `try/except TimeoutError: raise PushError(f"no response to cmd {cmd:#04x} within {timeout}s") from None`, and drop the `left <= 0` check (keep `left` for the wait). Then catch `PushError` in `main()`.

### A3 🟠 Response frames are accepted without the checks the spec defines

`python/xte.py:80-84` accepts any notification that is at least 8 bytes and starts with `XTE`. §6.3 defines three more fields that this code never reads: frame type `04` at byte 3, frame length at byte 4, and checksum at byte 5 over bytes 6 to length-1. So the message contract with the tag is enforced only on the magic; a frame with a matching command byte and garbage after it is treated as a response, and `r[7]` is trusted. The BLE link layer has its own CRC, so random corruption is unlikely; the realistic case is a frame of a *different type* (data echo, or a future firmware sending a longer status) being read as a response and steering the state machine.

Fix. In `parse_response`, require `r[3] == 0x04`, require `8 <= r[4] <= len(r)`, verify `sum(r[6:r[4]]) & 0xFF == r[5]`, return `None` otherwise (the spec says ignore), and expose `extra = r[8:r[4]]` so the bitmap never reads into the `00` padding.

### A4 🟠 A disconnect mid-push is not observed; it surfaces as a misleading timeout or a raw bleak traceback

`BleakClient(dev)` at `python/push.py:87` registers no `disconnected_callback`. Two cases:

- Disconnect while writing (`python/push.py:100`): `write_gatt_char` raises a `BleakError`, which propagates out of `push()`, out of `asyncio.run`, and prints a bleak traceback. That is "let it crash", which is fine, but nothing translates it into "tag disconnected after packet N of M".
- Disconnect while waiting (`python/push.py:81`): nothing will ever arrive in `inbox`. `expect` waits the full 5 s and raises the empty `TimeoutError` from A2. The diagnosis on screen ("no response") is wrong; the tag left.

The `async with` block does clean up the host side in both cases, so the host is not left in a bad state. The tag has an accepted alloc and partial flash contents, but §8.2 step 4 re-allocates on the next push, so the tag is not left in a bad state either. The defect is purely that the operator is told the wrong thing.

Fix. `BleakClient(dev, disconnected_callback=lambda c: inbox.put_nowait(DISCONNECTED))` with a sentinel object, and in `expect()`, `if r is DISCONNECTED: raise PushError("tag disconnected")`. Wrap `write()` in a `try/except BleakError as e: raise PushError(f"write failed at packet {i}: {e}")` in `send()`.

### A5 🟡 Every other external call has a timeout or a clean crash; the list, for the record

- `BleakScanner.find_device_by_address(address, timeout=15.0)` (`python/push.py:65`). Timeout explicit, fallback is a clear message with a `bluetoothctl disconnect` hint. Good. The hint reveals a real host failure mode though: a stale BlueZ connection from a killed process makes the tag stop advertising, and this code cannot recover because it insists on scanning first. Consider falling back to `BleakClient(address)` directly when the scan finds nothing; BlueZ will reuse the existing connection.
- `BleakClient(dev)` connect (`python/push.py:87`). Uses bleak's default 10 s connect timeout; not stated in the code. Make it explicit: `BleakClient(dev, timeout=10.0)`.
- `client._backend._acquire_mtu()` (`python/push.py:88-92`). Private API, guarded by `hasattr` and a broad `except Exception`. The fallback (`mtu 23`, `chunk 20`) is correct per §4.2, so this is a well-supervised call; the only risk is that a bleak upgrade removes the private method and every push silently drops to 20-byte writes (slower, still correct). Log the fallback loudly, which line 92 already does for the exception case but not for the `hasattr` false case.
- `client.start_notify(DATA_OUT, on_notify)` (`python/push.py:96`). No timeout available in bleak; a failure raises and propagates. Acceptable.
- `client.write_gatt_char(..., response=False)` (`python/push.py:100`). Fire-and-forget by design, no timeout, no acknowledgement; the tag's bitmap in the `04` response is the acknowledgement, which is the right supervisor for lost writes. Good.
- `asyncio.sleep(0.1)` before refresh (`python/push.py:117`) matches §8.2 step 7; `interval` default `0.005` (`python/push.py:143`) matches §4.2 step 3.

No supervisor restarts anything; the supervisor is the human re-running the command. For a CLI that is the honest design and I would not add retry loops. What is missing is that the crash is *informative*, which A1, A2 and A4 address.

### A6 🟡 A bitmap shorter than the packet count silently under-reports missing packets

`python/push.py:126`: `xte.bitmap_bits(r, 8)[:len(packets)]`. If the bitmap carries fewer bits than `len(packets)` (a 16-byte padded notification carries at most 64 bits after byte 8; a 204800-byte batch has 169 packets), `enumerate` stops at the end of the bitmap and every packet beyond it is treated as received. Not reachable on the PSJ-213 (7 packets), but the code claims §8.2 up to 204800 bytes, and `data_packets` (`python/xte.py:68-69`) only rejects at 255.

Fix. In the `missing_packets` helper from H1, pad missing bits as "missing": `bits += [0] * (total - len(bits))`, or raise if the bitmap is too short. Either is loud.

### A7 🟡 `qr_label.py` fails soft in two places where the label comes out wrong

- `font()` (`examples/qr_label.py:20-24`) falls back to `ImageFont.load_default()`, which ignores `size`; on a host without DejaVu the label is rendered with a tiny bitmap font and the script still prints `wrote ... (250x122)`. Print a warning naming the missing font file.
- `render()` (`examples/qr_label.py:41-46`) draws text with no width check; a long second argument runs off the right edge and is clipped. Measure with `d.textlength()` and raise if `x + width > W - 8`, the same way the QR height is checked at line 32.

## Where they converge

1. **The response must be a value.** Hickey wants it because data beats offsets (H1); Armstrong wants it because the message contract cannot be enforced on something that is never parsed (A3, A6). One `Response` type in `xte.py` with a validated `extra` field resolves H1, A3 and A6 together, and the `8`/`7` bitmap offset stops being a literal in `push.py`.
2. **Every exit from `push()` must be named.** Hickey sees an implicit state machine that falls off the end (H3); Armstrong sees the exit-0 false success (A1). `raise PushError` after the loop fixes both, and H2's `PushError` gives `main()` a single place to turn outcomes into exit codes.
3. **The informative message is the deliverable of a crash.** A2 and A4 are both "the tag left / did not answer and the program said something else". Hickey's H4 (keep the frame log as an immutable list) is what makes those crashes diagnosable after the fact. All three want the failure path to carry as much value as the success path.

## Where they pull apart

- **The inbox.** Armstrong is content with a queue plus a disconnect sentinel (A4): processes talk by messages, the queue is the mailbox, add one more message type. Hickey would say the queue is already the wrong shape because it is a place that forgets, and would rather the session be modelled as an accumulating sequence of events that `expect` scans. Both work; the sentinel is the smaller change and the one I would ship first.
- **The bare `write_gatt_char`.** Armstrong endorses the absence of `try/except` around `python/push.py:100`: an unexpected BLE error should crash the push, not be swallowed. Hickey has no opinion on that line. The only reason to touch it (A4) is to name the packet index in the message, not to handle the error.
- **The experimental knobs (H6).** Hickey wants `--flip-v` and `--pad-width` gone because they braid "verified" with "tried". Armstrong does not mind a knob as long as the wrong setting fails loudly, and here it does not fail at all, it shears silently on the panel. So Armstrong would keep them only with a warning, Hickey would delete them. Delete them.
- **`sys.exit` inside the coroutine (H2).** Armstrong could read `sys.exit` as a legitimate crash: the process dies, the `async with` disconnects cleanly, the supervisor (the human) sees stderr. Hickey objects on structure, not runtime: the function's outcome is unavailable to any caller other than the interpreter. Given A1 needs a named exception anyway, Hickey wins this one by default.
