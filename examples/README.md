# Examples

| file | what |
|---|---|
| `qr_label.py` | renders a QR code plus three lines of text in the four inks |
| `github-qr.png` | its output for `https://github.com/mattjoyce`, a good first test image |
| `dashboard-solar.json` | dashboard spec: hero figure, two tiles with sparklines, column chart with highlight and hour ticks |
| `token_weather.py` | this week's LLM token usage from `ccusage` as a dashboard; `--budget 500M` adds the meter, `--push` sends it. Nothing is stored. |
| `dashboard-server.json` | dashboard spec: three tiles, a line chart with an alert threshold, a disk meter |

Needs `pip install qrcode pillow` (both in the quick-start install line).

```sh
../.venv/bin/python qr_label.py https://example.com "example.com" "/path" "scan me" -o label.png
../.venv/bin/python ../python/push.py 9F:1D:00:0B:33:36 label.png --no-dither
```

```sh
../.venv/bin/python ../python/dashboard.py dashboard-solar.json -o dash.png --scale 3   # dash.x3.png is a preview
```
