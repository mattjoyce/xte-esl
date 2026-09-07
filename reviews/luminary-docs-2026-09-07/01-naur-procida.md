# Naur × Procida on the xte-esl documentation

Lens: theory × need, subject documentation. Two passes. Reconciliation (Naur): are the docs true to the code and the vectors as they stand today, and would the theory survive if only the docs did? Authoring (Procida): does a stranger arriving with one of four needs get served by exactly one page?

Reviewed: README.md, docs/protocol.md, docs/explainer.html (source), testdata/README.md, examples/README.md, go/README.md, ts/README.md, NOTES.md. Reconciled against python/xte.py, python/push.py, examples/qr_label.py, testdata/reference.json (keys), and live runs of the self-test, `push.py --help` and a dry-run push of examples/github-qr.png.

## What verifies

Before the findings, the ledger of what I recomputed and found correct, because the spec earns credit for it.

- Every hex example in protocol.md §6.1 (six command frames): checksum, length byte and bytes all recomputed from the rule "sum of bytes 6 to end, mod 256" and all match. The OTA frame's length byte says 7 while the frame is 8 bytes; the doc says so plainly.
- §6.2 data-packet example: length field 0x000E = 9 + 5, checksum 0x13 = 07 + 02 + 00 + 01 + 02 + 03 + 04. Matches `xte.data_packet(b"\x00\x01\x02\x03\x04", 2, 7)`.
- §7.1 container example: 42 bytes, length field 0x2A, checksum 0xCF = sum of bytes 12..41. Byte-identical to `xte.container([(0,0,8,2,b"\x55"*4)])`. Note the RLE inside it (`02 55 02 55`, not `04 55`) is the only example in the spec that proves the two-half rule (see R5).
- §7.2 packing example `6c 10` matches `pack_bwry` on the six listed pixels, including the black pad.
- §7.3 RLE example matches `xte.rle`.
- §6.3 both observed responses: checksum over bytes 6..(len-1) inclusive gives BD and 03 as shown.
- §8.1 arithmetic: ceil(122/4) = 31 bytes per row, 31 × 250 = 7750.
- `python/xte.py` passes all twelve vectors; `reference.json` has exactly the keys testdata/README lists (`packets` = 0, 3, 6, i.e. first, middle, last of 7).
- `push.py --help` shows every flag the docs mention; the dry run of examples/github-qr.png produces a 122x250 buffer, 6892 bytes, RLE chosen, 6 packets.
- The rotation description is self-consistent: "90° counter-clockwise" = PIL `rotate(90)`, and the two stated invariants (buffer row 0 = right-hand edge as viewed, first pixel of a row = top) match both PIL's result and the explainer's stride widget (`vx = 249 - r; vy = c`).

So the wire format in the spec is not a fossil. The findings below are about what the spec does not say, what it claims beyond what was seen, and the places where the surrounding pages have started to drift from it.

## Reconciliation findings (Naur)

The program text here is unusually honest residue. The theory that matters most, "the panel is portrait and reads 31-byte rows, and here are the two wrong strides and what they look like", survived into §8.1 and into the explainer's stride widget. That is the part most projects lose. What has not survived into the spec is the boundary between what the author saw the tag do and what the author read in the vendor's JavaScript.

🟠 R1. The spec claims hardware verification for paths that were never exercised. Locus: docs/protocol.md:3 ("Status: verified on hardware"), plus §6.3 rows for `02` and `68`, §6.4, §8.3, §8.4, and the 19-byte `01` form. NOTES.md:13-36 and README.md:70-76 record what actually ran: one batch, no packet loss, 244-byte writes, refresh `FF`. The `02` response, the `68` status, the bitmap offsets 7 and 8, the batch loop, and OTA all come from `references/dataSender.js` and friends, which are gitignored. A port author debugging a `68` response two years from now needs to know the offset 8 was transcribed, not observed. Fix: replace line 3 with what was verified ("§4, §5, §6.1 alloc and refresh, §6.3 `01`/`04` `FF`, §7, §8.1, §8.2 without patching, observed on PSJ-213 firmware 4.0.2"), and mark each remaining section or table row "from vendor code, not exercised" in one short sentence. This is the single most valuable sentence the spec is missing.

🟠 R2. Broken cross-reference sends the reader to the wrong section for the packing rule. Locus: docs/protocol.md:109, "The device number selects the pixel packing. Section 6.3 gives the rule." §6.3 is the response frame. The rule is §7.2:284. Fix: "Section 7.2".

🟠 R3. The bitmap length is under-specified and the code does something the spec does not say. Locus: docs/protocol.md:217 ("to the end of the frame") vs python/xte.py:87-92 and python/push.py:126, which read to the end of the *notification*. A 16-byte notification holds 8 bitmap bytes from offset 8, so 64 packets; a full 204800-byte batch has 170 packets and needs 22 bytes. Whether the tag emits a longer notification, a longer frame across several notifications, or something else is unknown, and the spec does not admit that. Also unstated: §8.2 says nothing for "status `68` with no bits missing", which push.py:128-129 handles by sending refresh again. Fix: say the frame length byte governs; say the notification may exceed 16 bytes for large bitmaps and that this is unobserved; add "if the bitmap shows nothing missing, send `04` again" to §8.3.

🟠 R4. "As viewed" has no orientation anchor. Locus: docs/protocol.md:313-323 and docs/explainer.html:217-220. The rotation and the two invariants are unambiguous relative to a landscape image, but a landscape tag has two ways up and nothing in the repo prose says which. The author knows because they held it; a port author will push, see the image upside down, and be unable to tell whether the doc or their code is wrong. Fix: one sentence, e.g. "As viewed means the factory test-screen text reads upright" (hardware/self-test-screen.jpg exists and can be cited), or anchor to the NFC coil or the battery door. Also change "Byte 0 of a row is the top edge" to "pixel 0 of a row (bits 7-6 of byte 0) is the top edge", since a byte is four pixels.

🟡 R5. The RLE example does not test the rule it illustrates. Locus: docs/protocol.md:298-304. The input `09 09 09 09 01 01 02 02 02 02 02 02` has its run boundary at the half boundary, so plain RLE gives the identical `04 09 02 01 06 02`. An implementer who skipped the halving would pass this example and fail the vectors, then hunt. The §7.1 container example does prove it (`02 55 02 55`) but nobody looks there for RLE. Fix: use `09 09 09 09 09 09 01 01` → first half `04 09`, second half `02 09 02 01`, result `04 09 02 09 02 01`, and add "plain RLE would give `06 09 02 01`; that is wrong". Two more gaps in the same section: step 4 "Split longer runs" does not say greedy (300 must be `FF v 2D v`, not `96 v 96 v`; `_runs` in xte.py:110-114 is greedy and the band vectors exercise it), and n = 1 gives an empty first half, which the code skips silently (xte.py:122-123); say "an empty half produces no bytes".

🟡 R6. The device-number exceptions are honest but unactionable. Locus: docs/protocol.md:284-286. The spec says six device numbers use a packing that is out of scope and "all other four-colour tags" use this one. Two problems for a port: nothing tells it to refuse those numbers, and nothing in §5 tells it whether the tag is four-colour at all (the ink set is in the NFC record, not the advertisement; docs/explainer.html:180). Fix: "A port must refuse a device number it does not know. Verified: 140. Believed from vendor code: other BWRY numbers except 97, 102, 106, 109, 119, 122." and add to §5 that the advertisement does not carry the ink set.

🟡 R7. A timeout with no implementation behind it. Locus: docs/protocol.md:81, "a patch round 300 s". push.py:75 and :120 wait `CMD_TIMEOUT` = 5 s for every response including the post-patch refresh. Either the 300 s is the vendor's number (say so, per R1) or it is a placeholder. Fix: attribute it or delete it.

🟡 R8. The spec omits the second advertisement payload. Locus: docs/protocol.md §5. NOTES.md:172-173 records that the tag alternates `ff 01` and the 13-byte record under the same company ID. The accept rule at line 106 does reject it (byte 2 would be `FF`), but an implementer watching a scanner will see it and wonder if their parser is broken. Fix: one line, "The tag also broadcasts a two-byte payload `FF 01` under the same ID. Ignore it."

🟡 R9. The explainer has started to drift from the spec. Locus: docs/explainer.html:306, the data-packet rail shows checksum `12` beside a header (`04 C4`, total 07, index 00) that is reference packet 0, whose checksum is `CE`. :614, the frame builder emits data-packet headers with checksum `00` and the note does not say it is a placeholder. :174, the model table gives the 2.13" a nominal 250 × 128 with no note that the panel is 250 × 122 everywhere else. :555, the stride widget pads rows with code 1 (white) where the spec pads with 0 (black); invisible on screen, but a reader cross-checking the JS against §7.2 will trip. Fix: compute the checksum in the rail from the shown bytes, make the builder compute it or label it "checksum omitted", annotate the 128, pad with 0.

🟡 R10. Fossils and stale arithmetic in the smaller pages. python/probe.py:10 says `./tools/probe.py`; it lives in python/. README.md:19 pushes `label.png`, a file that does not exist (examples/github-qr.png does). README.md:17 installs bleak and pillow; examples/qr_label.py:7 and examples/README.md:9 need `qrcode`, which is in this venv but not in any install line. NOTES.md:152 "7625 bytes of framebuffer" is 250 × 122 / 4 from before the shear was understood; the buffer is 7750. NOTES.md is a log, so strike it through rather than rewrite it, but do strike it, because README routes readers there.

🟡 R11. The vectors' theory lives in a gitignored file. Locus: testdata/README.md:6-8 and NOTES.md:11 (`references/mkref.js`). The provenance disclosure is honest. But no one can regenerate or extend reference.json, and the two inputs (a noise image, a band image) are described by adjective only. If the vendor file is lost the vectors become unrepeatable ground truth. Fix: describe the inputs in testdata/README in enough detail to regenerate them (seed or generator, band layout), and add one 122x250 portrait vector produced by the Python codec, labelled second-generation, since every real push is that shape and no vector is (testdata/README.md:14 says this in a table cell; see A6).

🟡 R12. Family claim outruns evidence. Locus: README.md:3-4, "sold as Poshiji PSJ-213 (and the ESL-15/21/26/29/35/37 BWRY family)". Only the 21 has been driven. The explainer's table (:172-179) marks the others "not tested", which is the right posture. Fix: "verified on the PSJ-213 / ESL-21BWRY; the same firmware family lists five other sizes, untested".

Two smaller notes. §4.2 says "request an MTU of 247" while push.py requests nothing and reads BlueZ's negotiated 517 (push.py:88-94); the outcome is the same and §10 records the 517, so this is fine as written, but a line saying "on BlueZ the stack negotiates; the port only needs writes of at most 244 bytes" would save a port author a detour. And §6.3's "checksum of bytes 6 to (length - 1)" should say "inclusive" and "frame length" should say "excluding the padding"; both are inferable from the examples, neither is stated.

## Authoring findings (Procida)

The docs tree is closer to Diátaxis than most: there is a reference (protocol.md), an explanation (explainer.html), a conformance page (testdata/README) and a log kept separate (NOTES.md). The failures are the usual two: the tutorial does not take responsibility for the beginner, and the explanation has swallowed a second copy of the reference.

🔴 A1. The 60-second path does not complete. Locus: README.md:14-25. A stranger with a tag and this README hits three walls in order. They have no way to learn the tag's address (scan.py is introduced at :27 as "watches the advertisement", which is what it does, not what they need it for). Step 3 pushes `label.png`, which they do not have, while examples/github-qr.png sits unmentioned. And nothing says what success looks like: push.py prints "done, image on screen" 60 ms in and the panel then flashes black and white for 20 seconds, which a first-timer reads as failure and retries into. Fix, as the whole tutorial:

```
python3 -m venv .venv && .venv/bin/pip install bleak pillow
.venv/bin/python python/xte.py                      # codec self-test, no tag needed
.venv/bin/python python/scan.py -t 10               # note your tag's address
.venv/bin/python python/push.py <address> examples/github-qr.png --no-dither
```

followed by one sentence: "The tag acknowledges in about a second and then flickers for 20 seconds. That is the refresh. The QR appears when it stops." The self-test line is a real first proof for the reader with no tag; keep it first.

🟠 A2. The explainer is two quadrants. Locus: docs/explainer.html. Sections 2, 3 (intro), 8 (last paragraph) and 11 are explanation and good. Sections 4 through 7 restate every table in protocol.md (GATT, advertisement layout, all three frame layouts, the command table, the response table, the container layout, RLE). Section 10 is a tool. The lede at :147 promises "everything you need to drive a four-colour Bluetooth shelf label from your own code", which is the reference's promise. Two copies of every table is a drift engine and R9 shows it has started. Fix: keep every widget and every "why"; reduce each restated table to a one-paragraph summary ending "layout in protocol.md §N"; move "Build a frame" to a small tools page or an appendix of protocol.md; rewrite the lede as "why it works the way it does, with the parts you can poke".

🟠 A3. README does not route by need. Locus: README.md, whole. Four readers arrive. "I want to push an image": quick start (A1). "I want to write the Go/TS port": go/README and ts/README state a contract but nobody states the order of work, which is run python/xte.py, read testdata/README, implement §7 against the vectors, then §6, then transport (protocol.md §9 says "codec before BLE" but the README does not point there). "I want to look up a byte": protocol.md, correctly named "the single source". "I want to understand": explainer, correctly named. Fix: a "Start here" block of four lines under the intro, one per need, before the quick start.

🟡 A4. A how-to for a side tool sits inside the README's front matter. Locus: README.md:30-52, the Phone NFC reader. Twenty-three lines including Tailscale serve instructions and a browser caveat, longer than the quick start, between the tutorial and the layout table. Fix: move it to docs/nfc.md (or a header comment in docs/nfc.html) and leave one line in the layout table.

🟡 A5. The spec's procedures section leans into how-to and warning. Locus: docs/protocol.md §8.1:325-326 ("Do not send 63-byte rows ... Both display as diagonal shear"). Procida would say warnings and war stories belong in explanation. I would keep these two sentences, because they are normative negatives and the explainer already carries the story (§3). Consider adding "See explainer §3 for why" and nothing more.

🟡 A6. Prose that assumes theory the reader lacks. Three loci. testdata/README.md:14 tells the port author, in a table cell, that the vectors are landscape 250-wide while a real push is portrait 122-wide; a port that passes the vectors and then pushes will shear, and the sentence that prevents it is the least prominent on the page. Make it a paragraph under "Fields" headed "The vectors are not a real push". docs/protocol.md §2 defines "batch" nine sections before the reader learns why batches exist (§8.4); add "used only for containers over 204800 bytes, section 8.4" to the term. docs/explainer.html:190-192 states pigment mobility and waveform branching as fact where :193 hedges with "very likely"; the whole of §2 is inference from watching the panel and should say so once at the top, the way :162 does for the simulator.

🟡 A7. The port READMEs say what not to read instead of what to read. Locus: go/README.md:5, ts/README.md:5, "Do not read vendor code." It is gitignored, so this is moot and slightly odd to a stranger. Replace with the reading order from A3 and the target of `selftest` (which fields, which exit code).

🟡 A8. NOTES.md is routed as a narrative but is a log. Locus: README.md:65 ("from unboxing to first image"). The "Where this stands" block at the top is exactly right. Below it, the Ambiq hypothesis sits under the section that supersedes it, and the NFC framebuffer arithmetic is pre-shear (R10). A log is allowed all of that. Either date the section headings or change the README line to "reconnaissance log; read 'Where this stands', the rest is history".

## Where they converge

- R1 and A2 are one fault from two sides. protocol.md claims verified status for text transcribed from vendor JS; explainer.html claims to be "everything you need" while being an explanation. Both are documents asserting a status they have not earned, and both fixes are one honest sentence at the top.
- R10 and A1 are the same broken quick start. Naur sees a fossil path and a missing dependency; Procida sees a tutorial that abandons the beginner. Same four lines fix both.
- R11 and A6 are the same missing vector. The port author needs a 122x250 vector both for correctness (there is no ground truth for the real shape) and for the tutorial-shaped reason that passing the suite should mean the tag shows a straight image.
- Both agree §8.1 is the best paragraph in the repo. It is where the theory of the shear survived.

## Where they pull apart

- §8.1's warnings. Naur wants them in the spec because they are the residue of the one hard-won discovery and a spec without them invites the regression. Procida wants a reference that describes and does not warn. Resolution taken above (A5): keep them, they are normative, cross-link the story.
- The explainer's tables. Naur would keep mechanism next to why, since the theory is transmitted by seeing both at once. Procida wants one source of truth and links. The drift in R9 settles it in Procida's favour, provided the explainer keeps enough of each layout to make the "why" legible without a tab switch.
- NOTES.md. Naur would keep it as the only place the theory of the reconnaissance is written, contradictions and all. Procida would say it serves no reader need and should be mined into the explainer and archived. Keep it; fix the routing line (A8).
- Provenance marking. Naur wants "observed" versus "transcribed" on every claim. Procida would keep such marks out of a reference's body. The compromise is a status line per section, not per row.

## Verdict: could a port be written from protocol.md alone?

The codec, yes. Every layout, checksum rule and example in §6 and §7 recomputes correctly; the container example verifies to the byte; the vectors catch the two things the prose under-specifies (halved RLE and greedy run splitting). A competent stranger would produce a conforming codec from §6, §7 and testdata/ without reading Python.

The pusher, yes for the path that has been seen. §8.2 without patching is complete, the observed responses are given with checksums, the timeouts are stated. A port would put a straight image on a PSJ-213, subject to R4: it might be upside down on the first try and the doc gives no way to know which side is up.

The recovery paths, no, and the doc does not say so. §6.4, §8.3 and §8.4 are faithful transcriptions of vendor behaviour that no one has watched the tag perform. A port written from them would be plausible, untested code, and the reader would believe it verified because line 3 says so. That is Naur's exact failure mode, mimicry of a surface that the author was careful about but never marked as surface. Fix R1 and the verdict becomes "yes, with the unobserved parts labelled", which is the most any clean-room spec can honestly offer.
