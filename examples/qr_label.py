#!/usr/bin/env python3
"""Render a QR label for the PSJ-213: code on the left, up to three lines on the right.

    ./examples/qr_label.py https://github.com/mattjoyce github.com /mattjoyce "scan me" -o github-qr.png
    ../python/push.py 9F:1D:00:0B:33:36 github-qr.png --no-dither

Uses only the four inks, so push with --no-dither. Needs `pip install qrcode pillow`.
"""

import argparse

import qrcode
from PIL import Image, ImageDraw, ImageFont

W, H = 250, 122
WHITE, BLACK, RED, YELLOW = (255, 255, 255), (0, 0, 0), (255, 0, 0), (255, 255, 0)
FONT_DIR = "/usr/share/fonts/truetype/dejavu/"


def font(name: str, size: int) -> ImageFont.FreeTypeFont:
    try:
        return ImageFont.truetype(FONT_DIR + name, size)
    except OSError:
        return ImageFont.load_default()


def render(url: str, lines: list[str], box: int = 3) -> Image.Image:
    qr = qrcode.QRCode(error_correction=qrcode.constants.ERROR_CORRECT_M, box_size=box, border=2)
    qr.add_data(url)
    qr.make(fit=True)
    code = qr.make_image(fill_color=BLACK, back_color=WHITE).convert("RGB")
    if code.size[1] > H:
        raise SystemExit(f"QR is {code.size[1]} px tall, panel is {H}: shorten the URL or lower --box")

    im = Image.new("RGB", (W, H), WHITE)
    im.paste(code, (6, (H - code.size[1]) // 2))
    d = ImageDraw.Draw(im)
    x = code.size[0] + 16
    bold, plain = font("DejaVuSans-Bold.ttf", 22), font("DejaVuSans.ttf", 15)
    if len(lines) > 0:
        d.text((x, 18), lines[0], fill=BLACK, font=bold)
    if len(lines) > 1:
        d.text((x, 46), lines[1], fill=RED, font=bold)
    d.rectangle([x, 84, W - 8, 88], fill=YELLOW)
    if len(lines) > 2:
        d.text((x, 94), lines[2], fill=BLACK, font=plain)
    return im


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("url")
    ap.add_argument("lines", nargs="*", help="up to three text lines: bold black, bold red, small black")
    ap.add_argument("-o", "--out", default="qr-label.png")
    ap.add_argument("--box", type=int, default=3, help="pixels per QR module")
    a = ap.parse_args()
    im = render(a.url, a.lines[:3], a.box)
    im.save(a.out)
    print(f"wrote {a.out} ({W}x{H})")


if __name__ == "__main__":
    main()
