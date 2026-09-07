#!/usr/bin/env python3
"""Render a four-ink 250x122 label from a few fields, then optionally push it.

    ./python/label.py --name "Flat white" --price "$4.20" --note "regular" -o label.png
    ./python/label.py --name "Flat white" --price "$4.20" --push 9F:1D:00:0B:33:36
    ./python/label.py --qr https://example.com --name "Scan me" --push 9F:1D:00:0B:33:36
    ./python/label.py --text "Back in 5 min" --push 9F:1D:00:0B:33:36

Layout: name across the top in black, price large (red by default), a
coloured band along the bottom carrying the note. --qr puts a QR code on the
left and shifts the text right. --text is a single centred message instead.
Only the four inks are used, so the push never dithers.
"""

import argparse
import subprocess
import sys
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

W, H = 250, 122
INK = {"white": (255, 255, 255), "black": (0, 0, 0), "red": (255, 0, 0), "yellow": (255, 255, 0)}
FONT_DIR = Path("/usr/share/fonts/truetype/dejavu")
BOLD, REGULAR = FONT_DIR / "DejaVuSans-Bold.ttf", FONT_DIR / "DejaVuSans.ttf"


def font(path: Path, size: int) -> ImageFont.FreeTypeFont:
    try:
        return ImageFont.truetype(str(path), size)
    except OSError:
        sys.exit(f"font not found: {path}. Install fonts-dejavu-core or edit FONT_DIR.")


def fit(d: ImageDraw.ImageDraw, text: str, path: Path, max_px: int, min_px: int, width: int) -> ImageFont.FreeTypeFont:
    for px in range(max_px, min_px - 1, -1):
        f = font(path, px)
        if d.textlength(text, font=f) <= width:
            return f
    return font(path, min_px)


def render(a: argparse.Namespace) -> Image.Image:
    im = Image.new("RGB", (W, H), INK["white"])
    d = ImageDraw.Draw(im)
    x0, text_w = 8, W - 16

    if a.qr:
        import qrcode
        qr = qrcode.QRCode(error_correction=qrcode.constants.ERROR_CORRECT_M, box_size=3, border=2)
        qr.add_data(a.qr)
        qr.make(fit=True)
        code = qr.make_image(fill_color=INK["black"], back_color=INK["white"]).convert("RGB")
        if code.size[1] > H:
            sys.exit(f"QR is {code.size[1]} px tall, panel is {H}: shorten the URL")
        im.paste(code, (4, (H - code.size[1]) // 2))
        x0 = code.size[0] + 12
        text_w = W - x0 - 8

    if a.text:
        f = fit(d, a.text, BOLD, 40, 14, text_w)
        tw = d.textlength(a.text, font=f)
        d.text((x0 + (text_w - tw) / 2, (H - f.size) / 2 - 4), a.text, fill=INK[a.price_ink], font=f)
        return im

    if a.name:
        f = fit(d, a.name, BOLD, 22, 12, text_w)
        d.text((x0, 6), a.name, fill=INK["black"], font=f)
    if a.price:
        f = fit(d, a.price, BOLD, 60, 24, text_w)
        d.text((x0, 32), a.price, fill=INK[a.price_ink], font=f)
    if a.band_ink != "white":
        d.rectangle([0 if not a.qr else x0 - 4, H - 22, W, H], fill=INK[a.band_ink])
    if a.note:
        f = fit(d, a.note, REGULAR, 14, 9, text_w)
        d.text((x0, H - 20 + (14 - f.size) / 2), a.note,
               fill=INK["white"] if a.band_ink == "black" else INK["black"], font=f)
    return im


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--name", default="", help="product name, top line")
    ap.add_argument("--price", default="", help="price, large")
    ap.add_argument("--note", default="", help="small text in the bottom band")
    ap.add_argument("--text", default="", help="single centred message instead of name/price/note")
    ap.add_argument("--qr", default="", help="URL or text for a QR code on the left")
    ap.add_argument("--price-ink", default="red", choices=list(INK), help="ink for the price or --text")
    ap.add_argument("--band-ink", default="yellow", choices=list(INK), help="bottom band colour; white = no band")
    ap.add_argument("-o", "--out", default="label.png", help="PNG to write")
    ap.add_argument("--push", metavar="ADDRESS", help="also push to this tag with push.py --no-dither")
    a = ap.parse_args()
    if not (a.name or a.price or a.note or a.text or a.qr):
        ap.error("nothing to draw: give --name/--price/--note, --text, or --qr")

    im = render(a)
    im.save(a.out)
    print(f"wrote {a.out}")
    if a.push:
        push = Path(__file__).with_name("push.py")
        return subprocess.call([sys.executable, str(push), a.push, a.out, "--no-dither"])
    return 0


if __name__ == "__main__":
    sys.exit(main())
