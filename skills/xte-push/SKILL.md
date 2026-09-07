---
name: xte-push
description: Put text, a price label, a QR code, or an image on the Poshiji PSJ-213 e-paper shelf tag over Bluetooth. Use when the user asks to update, show, display, or push something to the tag, the shelf label, the price tag, or the e-paper screen.
---

# Push to the shelf tag

The tag is a 250x122 four-ink (black, white, red, yellow) e-paper label
driven over BLE by this repo's Python tools. One command renders and
pushes; do not write Pillow or BLE code by hand.

## Facts you need

- Tag address: `9F:1D:00:0B:33:36` (advertised name `36330B001D9F`). If a
  different tag is meant, find it with `.venv/bin/python python/scan.py -t 10`.
- Run everything from the repo root with `.venv/bin/python`.
- Success is the line `refresh acknowledged; panel now redraws for ~20 s`
  and exit status 0. The panel then flickers black and white for about
  20 seconds. That is the refresh, not a fault. Do not retry during it.
- Only the four inks exist. Anything else becomes black. Never dither flat
  graphics; `label.py` and `--no-dither` already handle this.

## Commands

Price label (name top, price large, note in a coloured band):

```sh
.venv/bin/python python/label.py --name "Flat white" --price "$4.20" --note "regular" --push 9F:1D:00:0B:33:36
```

A single message:

```sh
.venv/bin/python python/label.py --text "Back in 5 min" --price-ink black --push 9F:1D:00:0B:33:36
```

QR code with a caption:

```sh
.venv/bin/python python/label.py --qr https://example.com --name "Scan me" --push 9F:1D:00:0B:33:36
```

A dashboard from a JSON spec (hero figure, up to three stat tiles with
sparklines, a `columns` or `line` chart, a meter; see the docstring in
`python/dashboard.py` for the keys, `examples/dashboard-*.json` for shapes):

```sh
.venv/bin/python python/dashboard.py spec.json --push 9F:1D:00:0B:33:36
echo '{"title":"Rack 1","tiles":[{"label":"CPU","value":"41%","spark":[30,35,40,41]}]}' | .venv/bin/python python/dashboard.py - --push 9F:1D:00:0B:33:36
```

Use `"alert": true` on a tile or hero, or `"alert_above"` on a chart, to
draw that value in red; leave everything else black. Push a dashboard no
more often than every few minutes: each refresh is a 20-second full-panel
waveform.

This week's token usage (from ccusage, needs bun):

```sh
.venv/bin/python cookbook/token-tracker/token_weather.py --budget 500M --push 9F:1D:00:0B:33:36 --if-changed
```

Other live-data recipes are in `cookbook/`; add `--if-changed` to any
scheduled push so an unchanged picture is not redrawn.

An existing image (resized to 250x122; add `--no-dither` for flat graphics,
omit it for photos):

```sh
.venv/bin/python python/push.py 9F:1D:00:0B:33:36 picture.png --no-dither
```

Options on `label.py`: `--price-ink red|black|yellow`, `--band-ink
yellow|red|black|white` (white means no band), `-o file.png` to keep the
render. Text that is too long is shrunk automatically; keep names under
about 25 characters and notes under about 40 for legibility.

## If it fails

| output | do |
|---|---|
| `not advertising within 15s` | the tag is connected elsewhere or asleep: run `bluetoothctl disconnect 9F:1D:00:0B:33:36`, then retry once |
| `no response to command` | retry once; if it repeats, report it, the tag may need its cells reseated |
| `tag disconnected while waiting` | retry once |
| `FAILED: ... XTEError` | the image is malformed; report the message, do not work around it |
| font not found | `sudo apt install fonts-dejavu-core` |

Never send more than one push at a time, and never push again while the
panel is still flickering from the last one.

## What not to do

- Do not use `--flip-v`, `--pad-width`, or `--rotate` other than the
  default; the geometry is solved and those produce diagonal shear.
- Do not touch `hardware/`, SWD, or NFC for a display update.
- Do not mass-erase or reflash anything.
