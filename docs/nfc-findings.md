# NFC findings — Poshiji PSJ-213

Investigation: 2026-09-07, including the phone test at approximately
21:30–21:44 Sydney time. Source session:

NFC identification works with NFC Tools on the phone. The existing BLE
uploader can update the display. Combining those into **tap → identify →
BLE upload → refresh** is supported by the evidence, but has not yet been
implemented or tested end to end. Sending an image or triggering a refresh
directly through NFC remains unproven.

## Confirmed observations

| Observation | Evidence and limit |
|---|---|
| The phone detects the tag | User reported vibration near the label and detection in NFC Tools. Vibration alone does not establish a successful NDEF read. |
| NFC Tools reads the identity | User pasted the complete text below, matching the saved memory dump. |
| Chrome starts scanning but shows no label | User reported the page remained at “Scanning — hold your phone…”. No exported event log was received, so the exact browser/OS failure is unknown. |
| BLE image upload and refresh work | Recorded successful pushes in [NOTES.md](../NOTES.md); transport and commands are in [protocol.md](protocol.md). This was established separately from the NFC test. |

The phone returned this 40-byte ASCII string:

```text
36330B001D9F,140,122,250,BWRY,0,0,0,0,CN
```

| Field | Interpretation |
|---|---|
| `36330B001D9F` | Label identity/BLE advertised name; reverse its byte pairs for BLE address `9F:1D:00:0B:33:36` |
| `140` | Vendor label type code |
| `122,250` | Height and width: 250 × 122 landscape display |
| `BWRY` | Black, white, red and yellow |
| `0,0,0,0` | Meaning not established |
| `CN` | Region field |

The label identity in the text is distinct from the NFC chip's UID.

## Memory dump and malformed Text record

The saved [Intel HEX export](../hardware/nfc-export.hex) contains 1576 bytes,
at addresses `0x000–0x627`. Its record checksums validate. At offset `0x010`:

```text
03 2c       NDEF TLV, 44-byte message
d1 01 28 54 single short Well Known record, type T, 40-byte payload
33 36 ...  payload begins with ASCII "36330B001D9F,..."
```

The payload lacks the Text record's status byte and language code. Treating
the first character `3` (`0x33`) as status gives a language length of
`0x33 & 0x3f = 51`, exceeding the entire 40-byte payload. This cannot be
decoded as a valid NFC Text payload. The NDEF record framing still identifies
the raw payload, which a tolerant/native reader can expose. NFC Tools' exact
decoding method was not inspected. The Text layout is described in the
[Web NFC specification](https://w3c-cg.github.io/web-nfc/#text-record).

Other dump evidence needs qualification:

- Capability Container `e1 10 ea 00` advertises `0xea × 8 = 1872` bytes of
  data area. This suggests a larger tag and makes NTAG I2C plus 2K a candidate;
  it does not identify the part or prove a connection to the label MCU.
- The first 64 bytes repeat at `0x400`. An export/sector-wrap artifact is
  plausible, but not demonstrated.
- The apparent UID check bytes disagree with the expected XORs: BCC0 is
  `0x0a` versus calculated `0x6f`; BCC1 is `0x44` versus calculated `0x2f`.
  The export's provenance for those pages is uncertain, so its apparent
  `ff ff` static lock bytes do not establish the tag's actual write protection.

The [NXP NTAG I2C plus datasheet](https://www.nxp.com/docs/en/data-sheet/NT3H2111_2211.pdf)
describes an I2C interface, field detection and a 64-byte SRAM pass-through
buffer. Those are possible investigation paths **if this is that chip and
the board and firmware use those features**. No such wiring or firmware
support has been established. A factory-programmed identity string does not
prove that the MCU updates NFC memory.

## Browser experiment

[nfc.html](nfc.html) is a read-only diagnostic page with identity parsing,
record data, timestamped events, a downloadable log and an example mode.
The previous session served it over Tailscale HTTPS at
a private HTTPS origin. This records the test address, not a
guarantee that the server is still running.

The prior session reported successful HTTPS delivery and simulated scans.
On the real phone, Chrome stayed at scanning while NFC Tools could read the
same label. No visible reading reached the page's identity display. There
is no captured browser log, phone model, Android version or Chrome version
with which to establish the precise failing layer.

Malformed Text decoding is a leading hypothesis, not a confirmed cause.
Other dispatch or browser conditions have not been ruled out. Changing the
page's label parser cannot fix a reading event that never reaches it.

Web NFC exposes NDEF rather than raw chip commands, so the page cannot
bypass that boundary with a memory read. Scanning requires suitable Android
hardware, permission and a secure page; the page must remain visible and the
phone unlocked. See [Chrome's Web NFC documentation](https://developer.chrome.com/docs/capabilities/nfc).

## What the vendor app suggests

The previous session's inspection of the recovered vendor mini-program
reported that its NFC refresh flow reads the serial number from the NFC
record, looks up the device and opens an update screen containing the
Bluetooth sending component `refBlueTosend`.

The local APK extraction is under `references/miniapp/` (gitignored).
Its routes include `report/pages/nfcchange/nfc` and
`report/pages/nfcchange/nfc-change`. The recovery chain is documented in
[NOTES.md](../NOTES.md#the-vendor-app).

This supports the interpretation that NFC selects a label and Bluetooth
delivers the update. It is a static-code inference, not a captured vendor
transaction or proof that every vendor update mode uses BLE.

## Next experiments

1. **Establish the browser boundary.** Record phone/OS/Chrome versions and
   download the page log after a scan. With competing NFC apps closed,
   compare this label against a known-good NDEF Text tag under the same
   conditions. This distinguishes a general scanning problem from a
   label-specific problem; it still needs further evidence to isolate the
   malformed payload as the cause.
2. **Test tap-to-BLE.** Build a small native Android reader that obtains the
   identity payload and sends the resolved label address to a laptop service
   running the existing uploader. The phone supplies NFC; the laptop needs
   Bluetooth. Verify one tap selects the correct label and completes a push.
   Neither the bridge nor this end-to-end test exists yet.
3. **Observe possible wake-up.** With the vendor app closed, record baseline
   BLE advertisements, repeat timestamped NFC taps and watch the display.
   Use `.venv/bin/python python/scan.py -a 9F:1D:00:0B:33:36 -t 120`.
   This scanner reports payload changes, so silence does not establish that
   advertisement timing or internal MCU activity stayed unchanged. Use a
   timestamped every-advertisement capture if testing wake-up timing.
4. **Investigate direct NFC separately.** Identify the chip using native tag
   information, supported identification reads or a part marking; verify
   memory sectors and any MCU connection. Then look for firmware support
   for field detection or data transfer. A chip capability alone does not
   establish a usable display-update protocol.

No NFC memory rewrite, direct NFC image transfer, or NFC-triggered display
refresh was demonstrated in this session.
