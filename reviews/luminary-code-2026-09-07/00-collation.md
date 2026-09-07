# Collation: luminary panel on the xte-esl Python code, 2026-09-07

Reviewed: `python/xte.py` (the codec other ports will mirror), `python/push.py`
(the BLE pusher), `examples/qr_label.py`. Two pairs ran blind to each other:
Ousterhout × Liskov on the module boundary (surface × substitution) and
Hickey × Armstrong on the running system (structure × runtime). The question
put to the panel: is this code fit to be the reference implementation that
Go and TypeScript ports copy, and is the pusher safe to hand to someone else?

Both lenses confirm the happy path. The self-test passes all 12 vectors and
neither found a byte-level defect in the wire format. Every finding is off
the vector path.

## Verdict table

| Pair | Axis | One-line verdict |
|---|---|---|
| **Ousterhout × Liskov** | surface × substitution | `image_payload` is the one deep function worth mirroring; the response side is shallow, preconditions are enforced by whichever Python builtin trips first, and ports have nothing to copy for errors. |
| **Hickey × Armstrong** | structure × runtime | The pusher can exit 0 without success or failure; the response is never a value, so the message contract is never checked, and a mid-push disconnect is misreported as a timeout. |

## The shared meta-finding

**The tag's reply is never made into a value.** Both pairs, from opposite
directions, land on `parse_response` at `python/xte.py:80-84` and the four
places `push.py` re-indexes raw notification bytes (`r[7]`,
`bitmap_bits(r, 8)`). Ousterhout sees a shallow function whose caller
re-parses. Liskov sees a docstring promising `None` for non-responses while
accepting any 8 bytes with the right magic. Hickey sees data expressed as
offsets. Armstrong sees a message contract (frame type `04`, length,
checksum, spec 6.3) that is never enforced, so a garbled or truncated frame
is treated as a reply. One change resolves O1, O2, L4, H1, A3 and A6: a
`Response` record in `xte.py` with validated `cmd`, `status`, `extra`, and a
`missing_packets(total)` method that owns the 7-versus-8 offset and pads a
short bitmap as missing.

## Where the pairs converge

**C1 🔴 The patch loop can fall off the end and report success.**
Found by Armstrong (A1) as a false exit 0, by Hickey (H3) as an implicit
state machine with an unhandled terminal state, by Liskov (L3) as a
postcondition neither met nor reported. Locus `python/push.py:116-132`.
Fix: after the loop, raise `PushError("refresh never acknowledged after N
rounds")`; treat `68` with an empty missing list as an error immediately,
since it means host and tag disagree about the packet count.

**C2 🟠 The response boundary.** The meta-finding above. Locus
`python/xte.py:80-92`, `python/push.py:82-84, 107, 121-126`. Fix: the
`Response` record with `missing_packets(total)`, checking type byte,
length byte and checksum, returning `None` otherwise per spec.

**C3 🟠 Preconditions are accidental and unmirrorable.** Ousterhout (O3)
lists six different builtin errors leaking from public functions; Liskov
(L1, L2, L5) shows `pack_bwry` can silently truncate on short input (a
`StopIteration` inside `map`), `container` never checks
`len(data) == ceil(w/4)*h`, the exact invariant that produced today's
diagonal shear, and `data_packets` defers its check to first iteration.
Hickey (H7) adds that off-palette pixels going to black is a silent policy.
Fix: one `XTEError(ValueError)`; explicit checks in `pack_bwry` (pixel
count), `container` (row-stride invariant, N ≤ 255, u32 ranges),
`cmd_frame` (payload ≤ 248), `data_packets` (validate before yielding).

**C4 🟠 Every exit from the pusher must be named and diagnosable.**
Hickey (H2) objects to `sys.exit` inside the coroutine on structure;
Armstrong (A2) shows the commonest hardware failure prints an empty
traceback because `asyncio.wait_for` raises a bare `TimeoutError` before
the message is built; Armstrong (A4) shows a disconnect while waiting
surfaces as a 5 s timeout. Fix: `PushError`, raised at the four `sys.exit`
sites and from a wrapped `wait_for`; a `disconnected_callback` that posts a
sentinel into the inbox; `main()` catches once and prints one line.

**C5 🟡 The exploration knobs contradict the spec.** Ousterhout (O7) and
Hickey (H6) both want `--flip-v` and `--pad-width` deleted: they exist only
to produce the geometry section 8.1 forbids, and the wrong setting fails
silently on the panel. `--rotate` stays only if the help string says which
tags need it.

**C6 🟡 Runtime policy lives in the pure codec.** Hickey (H5) on
`CMD_TIMEOUT` and `MAX_PATCH_ROUNDS` in `xte.py:17-18`; Ousterhout (O4) on
`BATCH` being declared but not implemented. Fix: move the timing constants
to `push.py`, and either implement `batches(payload)` or state in the
docstring that batching is out of scope and check `len <= BATCH`.

## The genuine cross-pair tension

**T1 Batching: reject or implement.** Liskov (L5) wants `data_packets` to
validate its 255-packet bound at call time, a two-line fix sufficient for
every PSJ-213 image. Ousterhout (O4) wants the oversized-batch case not to
exist: implement section 8.4 in the codec so there is nothing to reject.
Hickey sides with Ousterhout on structure (policy without mechanism is a
lie), Armstrong is indifferent so long as the failure is loud. The owner
decides: the small fix ships the PSJ-213 correctly today; the large fix
makes the codec honest for the 2.9" and 3.7" tags and for firmware upload,
neither of which can be tested here. Recommendation: do the small fix now
and record the large one as the port contract's known gap.

**T2 The inbox.** Armstrong is content with a queue plus a disconnect
sentinel. Hickey says the queue is a place that forgets and would rather an
append-only event log that `expect` scans. Both work. The sentinel is the
smaller change; the log (H4) is what makes a failed push diagnosable after
the fact. Recommendation: both, they are ten lines together.

## Single-lens signals

- **Ousterhout** O6: two callers reach into the opaque container with the
  hand-computed offset `13 + 4 + 16` to read the compression byte
  (`push.py:157`, `xte.py:191`). Expose it or drop the print. O8: the code
  constants `WHITE=1, RED=3` and `qr_label.py`'s `WHITE=(255,255,255)`
  collide by name. O9: `cmd_refresh(screens: int)` is an int with two
  behaviours.
- **Liskov** L6: `push.py:88-92` calls the private `_backend._acquire_mtu`,
  a bleak promise never made. L8: the RLE equal-length tie (RLE wins) is
  correct but unpinned by a vector; add one.
- **Hickey** H4: the inbox discards history, so a post-mortem has nothing.
- **Armstrong** A5: every other external call (scan, connect, notify,
  write) has a timeout or a clean crash, listed for the record. A7:
  `qr_label.py` falls back to Pillow's default font silently and pastes a
  code wider than the panel without error.

## Build verdict

**Ship with fixes.** The wire format is correct and verified; nothing here
changes a byte on the vectors. Gate on:

1. C1, the false exit 0 (🔴).
2. C2, the `Response` record with validation, because the ports copy it.
3. C3, `XTEError` and the stride invariant in `container`, because the
   invariant is the one bug this project has actually had.
4. C4, `PushError`, wrapped timeout, disconnect sentinel.

Then C5 and C6 as cleanup. T1 is the owner's call; the panel recommends
the small fix now and the batch implementation as a documented gap.
