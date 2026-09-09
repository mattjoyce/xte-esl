#!/usr/bin/env python3
"""Render a mini dashboard for the 250x122 four-ink tag from a JSON spec, optionally push it.

    ./python/dashboard.py examples/dashboard-solar.json -o dash.png
    ./python/dashboard.py examples/dashboard-solar.json --push 9F:1D:00:0B:33:36
    ./python/dashboard.py --demo --push 9F:1D:00:0B:33:36
    some-script | ./python/dashboard.py - --push 9F:1D:00:0B:33:36

Spec (every key optional, order of regions is fixed):

    {
      "title": "Solar",              header, left
      "updated": "14:32",            header, right
      "hero":  {"label": "Now", "value": "3.2 kW", "delta": "+0.4 vs 1h", "alert": false},
      "tiles": [{"label": "Battery", "value": "82%", "spark": [..], "alert": false}, ...],  up to 3
      "chart": {"type": "columns" | "line", "label": "kWh by hour",
                "values": [..], "highlight": 5, "alert_above": 4.0},
      "meter": {"label": "Tank", "value": 0.62, "warn": 0.8}
    }

Layout: header band if title/updated; hero takes the left column if present;
tiles form one row; the chart takes what is left; a meter sits at the bottom.
Inks: text and marks are black, the current/highlighted point is red only
when "alert" is true (otherwise a black marker), yellow is the emphasis band.
Everything is drawn in hard pixels of the four inks; push with --no-dither
(dashboard.py passes it for you).
"""

import argparse
import json
import subprocess
import sys
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

W, H = 250, 122
BLACK, WHITE, RED, YELLOW = (0, 0, 0), (255, 255, 255), (255, 0, 0), (255, 255, 0)
FONT_DIR = Path("/usr/share/fonts/truetype/dejavu")
BOLD, REGULAR = FONT_DIR / "DejaVuSans-Bold.ttf", FONT_DIR / "DejaVuSans.ttf"
_fonts: dict = {}


def font(path: Path, size: int) -> ImageFont.FreeTypeFont:
    key = (path, size)
    if key not in _fonts:
        try:
            _fonts[key] = ImageFont.truetype(str(path), size)
        except OSError:
            sys.exit(f"font not found: {path}. Install fonts-dejavu-core or edit FONT_DIR.")
    return _fonts[key]


def fit(d, text, path, max_px, min_px, width):
    for px in range(max_px, min_px - 1, -1):
        f = font(path, px)
        if d.textlength(text, font=f) <= width:
            return f
    return font(path, min_px)


def text_h(f) -> int:
    asc, desc = f.getmetrics()
    return asc + desc


def label_line(d, x, y, text, width, size=9):
    """Draw a small label truncated with an ellipsis to fit width. Returns its height."""
    f = font(REGULAR, size)
    while len(text) > 3 and d.textlength(text, font=f) > width:
        text = text[:-2].rstrip() + "…"
    d.text((x, y), text, fill=BLACK, font=f)
    return text_h(f)


class Box:
    def __init__(self, x, y, w, h):
        self.x, self.y, self.w, self.h = int(x), int(y), int(w), int(h)

    @property
    def x2(self): return self.x + self.w - 1

    @property
    def y2(self): return self.y + self.h - 1


# ---- components -------------------------------------------------------------

def header(d, box: Box, title: str, updated: str) -> None:
    f = font(BOLD, 12)
    if title:
        d.text((box.x, box.y), title, fill=BLACK, font=f)
    if updated:
        fr = font(REGULAR, 10)
        d.text((box.x2 - d.textlength(updated, font=fr), box.y + 1), updated, fill=BLACK, font=fr)
    d.line([box.x, box.y2, box.x2, box.y2], fill=BLACK, width=1)


def hero(d, box: Box, spec: dict) -> None:
    label, value, delta = spec.get("label", ""), str(spec.get("value", "")), spec.get("delta", "")
    alert = bool(spec.get("alert"))
    y = box.y
    if label:
        fl = font(REGULAR, 10)
        d.text((box.x, y), label, fill=BLACK, font=fl)
        y += text_h(fl) + 1
    room = box.h - (y - box.y) - (14 if delta else 0)
    fv = fit(d, value, BOLD, min(48, room), 18, box.w)
    d.text((box.x - 1, y - 4), value, fill=RED if alert else BLACK, font=fv)
    y += text_h(fv) - 6
    if delta:
        fd = fit(d, delta, REGULAR, 11, 8, box.w)
        while len(delta) > 3 and d.textlength(delta, font=fd) > box.w:   # never spill into the next column
            delta = delta[:-2].rstrip() + "…"
        d.text((box.x, y), delta, fill=RED if alert else BLACK, font=fd)


def sparkline(d, box: Box, values, alert=False) -> None:
    """1px line, hairline baseline, current point marked."""
    if len(values) < 2 or box.w < 8 or box.h < 4:
        return
    lo, hi = min(values), max(values)
    span = (hi - lo) or 1.0
    n = len(values)
    pts = []
    for i, v in enumerate(values):
        x = box.x + round(i * (box.w - 1) / (n - 1))
        y = box.y2 - round((v - lo) / span * (box.h - 1))
        pts.append((x, y))
    d.line([box.x, box.y2, box.x2, box.y2], fill=BLACK, width=1)     # baseline, recessive by being 1px
    d.line(pts, fill=BLACK, width=1)
    cx, cy = pts[-1]
    d.rectangle([cx - 1, cy - 1, cx + 1, cy + 1], fill=RED if alert else BLACK)


def tile(d, box: Box, spec: dict) -> None:
    label, value = spec.get("label", ""), str(spec.get("value", ""))
    alert = bool(spec.get("alert"))
    spark = spec.get("spark") or []
    y = box.y
    if label:
        y += label_line(d, box.x, y, label, box.w)
    spark_h = 12 if spark else 0
    room = box.h - (y - box.y) - spark_h - 2
    fv = fit(d, value, BOLD, min(22, room), 12, box.w - 2)
    d.text((box.x - 1, y - 3), value, fill=RED if alert else BLACK, font=fv)
    if spark:
        sparkline(d, Box(box.x, box.y2 - spark_h + 1, box.w - 4, spark_h), spark, alert)


def columns(d, box: Box, spec: dict) -> None:
    values = list(spec.get("values") or [])
    if not values:
        return
    label = spec.get("label", "")
    y = box.y
    if label:
        y += label_line(d, box.x, y, label, box.w)
    ticks = [t for t in (spec.get("ticks") or []) if isinstance(t, (list, tuple)) and len(t) == 2]
    plot = Box(box.x, y, box.w, box.h - (y - box.y) - (9 if ticks else 0))
    n = len(values)
    gap = 1 if n > 25 else 2
    bw = max(1, (plot.w - gap * (n - 1)) // n)
    used = bw * n + gap * (n - 1)
    x0 = plot.x + (plot.w - used) // 2
    hi = max(values) or 1.0
    lo = min(0.0, min(values))
    span = (hi - lo) or 1.0
    label_room = 10                                   # one row above the tallest bar for its value
    bar_h = max(1, plot.h - label_room)
    scale = lambda v: round((v - lo) / span * (bar_h - 1))
    base_y = plot.y2 - scale(0)
    highlight = spec.get("highlight")
    alert_above = spec.get("alert_above")
    fl = font(REGULAR, 8)
    extreme = max(range(n), key=lambda i: values[i])
    for i, v in enumerate(values):
        x = x0 + i * (bw + gap)
        top = plot.y2 - scale(v)
        ink = BLACK
        if alert_above is not None and v > alert_above:
            ink = RED
        elif highlight is not None and i == highlight:
            ink = YELLOW
        if v >= 0:
            d.rectangle([x, top, x + bw - 1, base_y], fill=ink)
            if ink == YELLOW:
                d.rectangle([x, top, x + bw - 1, base_y], outline=BLACK, width=1)
        else:
            d.rectangle([x, base_y, x + bw - 1, top], fill=ink)
        if i == extreme and bw >= 6 and top - label_room >= plot.y:   # direct-label the extreme only
            s = f"{v:g}"
            tw = d.textlength(s, font=fl)
            lx = min(max(plot.x, x + (bw - tw) / 2), plot.x2 - tw)
            d.text((lx, top - label_room), s, fill=BLACK, font=fl)
    d.line([plot.x, base_y, plot.x2, base_y], fill=BLACK, width=1)
    for i, t in ticks:
        if 0 <= int(i) < n:
            x = x0 + int(i) * (bw + gap)
            d.line([x, base_y + 1, x, base_y + 2], fill=BLACK, width=1)
            d.text((x, base_y + 2), str(t), fill=BLACK, font=fl)


def line_chart(d, box: Box, spec: dict) -> None:
    values = list(spec.get("values") or [])
    if len(values) < 2:
        return
    label = spec.get("label", "")
    y = box.y
    if label:
        y += label_line(d, box.x, y, label, box.w)
    plot = Box(box.x, y, box.w - 28, box.h - (y - box.y) - 2)
    alert = spec.get("alert_above") is not None and values[-1] > spec["alert_above"]
    sparkline(d, plot, values, alert)
    fl = font(BOLD, 10)
    s = f"{values[-1]:g}"
    lo, hi = min(values), max(values)
    ly = plot.y2 - round((values[-1] - lo) / ((hi - lo) or 1) * (plot.h - 1)) - 6
    d.text((plot.x2 + 4, max(plot.y, min(ly, plot.y2 - 10))), s, fill=RED if alert else BLACK, font=fl)


def meter(d, box: Box, spec: dict) -> None:
    value = max(0.0, min(1.0, float(spec.get("value", 0))))
    warn = spec.get("warn")
    label = spec.get("label", "")
    fl = font(REGULAR, 9)
    lw = d.textlength(label, font=fl) + 6 if label else 0
    if label:
        d.text((box.x, box.y), label, fill=BLACK, font=fl)
    track = Box(box.x + lw, box.y + 1, box.w - lw - 30, max(6, box.h - 2))
    d.rectangle([track.x, track.y, track.x2, track.y2], outline=BLACK, width=1)
    fill_w = round((track.w - 2) * value)
    ink = RED if (warn is not None and value >= warn) else BLACK
    if fill_w > 0:
        d.rectangle([track.x + 1, track.y + 1, track.x + fill_w, track.y2 - 1], fill=ink)
    if warn is not None:
        wx = track.x + 1 + round((track.w - 2) * float(warn))
        d.line([wx, track.y - 1, wx, track.y2 + 1], fill=BLACK, width=1)
    d.text((track.x2 + 4, box.y), f"{round(value * 100)}%", fill=ink, font=font(BOLD, 10))


# ---- layout -----------------------------------------------------------------

def render(spec: dict) -> Image.Image:
    im = Image.new("RGB", (W, H), WHITE)
    d = ImageDraw.Draw(im)
    d.fontmode = "1"     # no anti-aliasing: the panel has no greys, and snapped edges mangle small text
    top, bottom, left, right = 2, H - 2, 4, W - 4

    if spec.get("title") or spec.get("updated"):
        header(d, Box(left, top, right - left, 16), spec.get("title", ""), spec.get("updated", ""))
        top += 19

    if spec.get("meter"):
        meter(d, Box(left, bottom - 11, right - left, 11), spec["meter"])
        bottom -= 15

    if spec.get("hero"):
        hw = 112 if (spec.get("tiles") or spec.get("chart")) else right - left
        hero(d, Box(left, top, hw, bottom - top), spec["hero"])
        if hw < right - left:
            d.line([left + hw + 3, top, left + hw + 3, bottom], fill=BLACK, width=1)
            left += hw + 8

    tiles = (spec.get("tiles") or [])[:3]
    chart = spec.get("chart")
    if tiles:
        has_spark = any(t.get("spark") for t in tiles)
        th = (44 if has_spark else 30) if chart else bottom - top
        n = len(tiles)
        tw = (right - left - 4 * (n - 1)) // n
        for i, t in enumerate(tiles):
            tile(d, Box(left + i * (tw + 4), top, tw, th), t)
        top += th + 4
    if chart:
        (line_chart if chart.get("type") == "line" else columns)(d, Box(left, top, right - left, bottom - top), chart)
    return im


DEMO = {
    "title": "Solar", "updated": "14:32",
    "hero": {"label": "Generating now", "value": "3.2kW", "delta": "+0.4 vs 1h ago"},
    "tiles": [
        {"label": "Battery", "value": "82%", "spark": [61, 64, 68, 70, 74, 77, 79, 80, 81, 82]},
        {"label": "Grid", "value": "-1.1kW", "spark": [0.4, 0.3, 0.1, -0.2, -0.5, -0.8, -0.9, -1.0, -1.1], "alert": True},
    ],
    "chart": {"type": "columns", "label": "kWh by hour", "values": [0, 0, 0.1, 0.6, 1.4, 2.2, 2.9, 3.3, 3.5, 3.2, 2.6, 1.7, 0.8, 0.2, 0],
              "highlight": 8, "ticks": [[0, "6"], [4, "10"], [8, "14"], [12, "18"]]},
}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("spec", nargs="?", help="JSON file, or - for stdin")
    ap.add_argument("--demo", action="store_true", help="render the built-in solar example")
    ap.add_argument("-o", "--out", default="dashboard.png")
    ap.add_argument("--scale", type=int, default=1, help="also write a scaled preview, e.g. 3")
    ap.add_argument("--push", metavar="ADDRESS", help="push to this tag after rendering")
    ap.add_argument("--if-changed", action="store_true", help="with --push: skip if the image is unchanged since the last push")
    a = ap.parse_args()
    if a.demo:
        spec = DEMO
    elif a.spec == "-":
        spec = json.load(sys.stdin)
    elif a.spec:
        spec = json.loads(Path(a.spec).read_text())
    else:
        ap.error("give a spec file, -, or --demo")

    im = render(spec)
    im.save(a.out)
    print(f"wrote {a.out}")
    if a.scale > 1:
        p = Path(a.out).with_suffix(f".x{a.scale}.png")
        im.resize((W * a.scale, H * a.scale), Image.NEAREST).save(p)
        print(f"wrote {p}")
    if a.push:
        cmd = [sys.executable, str(Path(__file__).with_name("push.py")), a.push, a.out, "--no-dither"]
        if a.if_changed:
            cmd.append("--if-changed")
        return subprocess.call(cmd)
    return 0


if __name__ == "__main__":
    sys.exit(main())
