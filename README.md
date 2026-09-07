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

## Phone NFC reader

[`docs/nfc.html`](docs/nfc.html) is a standalone, read-only Web NFC page for
Chrome on an NFC-equipped Android phone. Serve it over HTTPS, open it directly
on the phone, and tap **Start scanning**. It shows XTE identity fields, the
record bytes exposed by the browser, and an exportable timestamped log.
**Show example** works without NFC hardware. iPhone browsers do not support
Web NFC. The page does not upload images or refresh the display.

For private HTTPS access with Tailscale on both devices:

```sh
sudo tailscale serve --bg --https=443 "$PWD/docs/nfc.html"
```

Open the HTTPS URL printed by that command on your phone with Tailscale
connected. To stop serving: `sudo tailscale serve --https=443 off`.
This requires an available Tailscale Serve HTTPS port; check existing Serve
configuration before using it on a machine already serving another app.

The PSJ-213's malformed NDEF Text record may be rejected or partly stripped
by the browser. In that case use a native NFC reader app; Web NFC cannot
issue raw chip commands or read the full tag memory.

## Layout

| path | what |
|---|---|
| `docs/protocol.md` | the wire format and procedures, the single source for ports |
| `docs/explainer.html` | the illustrated guide |
| `testdata/` | conformance vectors and how to use them |
| `python/` | reference codec, BLE pusher, scan and probe tools |
| `go/`, `ts/` | ports, each with the same self-test contract |
| `examples/` | label renderers and test images |
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
