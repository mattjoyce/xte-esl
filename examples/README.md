# Examples

| file | what |
|---|---|
| `qr_label.py` | renders a QR code plus three lines of text in the four inks |
| `github-qr.png` | its output for `https://github.com/mattjoyce`, a good first test image |

```sh
../.venv/bin/python qr_label.py https://example.com "example.com" "/path" "scan me" -o label.png
../.venv/bin/python ../python/push.py 9F:1D:00:0B:33:36 label.png --no-dither
```
