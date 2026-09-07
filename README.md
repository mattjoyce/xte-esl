# xte-esl

Host-side SDK for XTE electronic shelf labels: the BLE e-paper price tags
sold as **Poshiji PSJ-213** (and the ESL-15/21/26/29/35/37 BWRY family). It
puts an image on the tag from a laptop in about 2.5 seconds, no base station,
no cloud account.

The protocol was recovered from the vendor's own app and is documented
clean-room in [`docs/protocol.md`](docs/protocol.md). Every language port is
checked byte for byte against [`testdata/reference.json`](testdata/README.md).
A long-form explainer, including how the e-ink refresh works and why it
flickers, is in [`docs/explainer.html`](docs/explainer.html).

## Quick start (Python)

```sh
python3 -m venv .venv && .venv/bin/pip install bleak pillow
.venv/bin/python python/xte.py                       # codec self-test
.venv/bin/python python/push.py 9F:1D:00:0B:33:36 label.png --no-dither
```

Draw the label at 250x122 using only pure white, black, red (`FF0000`) and
yellow (`FFFF00`). `push.py` rotates it into the tag's portrait buffer, packs,
connects, and pushes. Use `--no-dither` for flat graphics; dithering only
helps photographs and looks poor on a four-ink panel.

Other tools: `python/scan.py` watches the advertisement, `python/probe.py`
is an interactive GATT shell.

## Layout

| path | what |
|---|---|
| `docs/protocol.md` | the wire format and procedures, the single source for ports |
| `docs/explainer.html` | the illustrated guide |
| `testdata/` | conformance vectors and how to use them |
| `python/` | reference codec, BLE pusher, scan and probe tools |
| `go/`, `ts/` | ports, each with the same self-test contract |
| `hardware/` | SWD findings, NFC dump, ESP32 bit-bang probe sketch |
| `NOTES.md` | the reconnaissance log, from unboxing to first image |
| `references/` | gitignored. APK, unpacked bundle, manual. Not needed by ports. |

## Status

| | |
|---|---|
| Codec | verified against vendor vectors |
| Push | verified on PSJ-213, firmware 4.0.2 |
| Geometry | 122x250 portrait buffer, rotate 90 |
| Large images, OTA | specified, not exercised |
| Go, TypeScript | not started |

## What it is not

Not the Bluetooth SIG ESL profile, not OpenEPaperLink, not Gicisky. Those
tags use different radios or services. The XTE service UUID is the Arm
Cordio proprietary data pipe (`...2760-08C2-11E1-9073-0E8AC72E...`), so the
UUID identifies the BLE stack, not the product.
