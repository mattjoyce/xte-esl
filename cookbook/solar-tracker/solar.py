#!/usr/bin/env python3
"""Solar tracker: a grid-tied inverter's day on the tag, with a night view.

    ./cookbook/solar-tracker/solar.py --demo --push 9F:1D:00:0B:33:36
    ./cookbook/solar-tracker/solar.py --url http://192.168.20.4:8095/graphs/snapshot.json --push ... --if-changed
    ./cookbook/solar-tracker/solar.py --file snap.json -o solar.png --scale 3
    ./cookbook/solar-tracker/solar.py --command "ssh host 'docker exec -i solar-monitor python3 -' < snapshot.py" --push ...

Source JSON (every key optional; missing ones leave their region empty):

    now_w            generating now, W                 e_day_kwh        today so far
    peak_w           today's peak, W                   peak_time        "12:40"
    irradiance       W/m² now                          irradiance_series  recent values for the sparkline
    vgrid            grid voltage, V                   temp_c           inverter temperature
    hourly_kwh       today's energy per hour           hour_start       hour of hourly_kwh[0]
    daily_kwh        last 7 days, oldest first, today last; null where unknown
    best_kwh_30d     best day in the last 30           updated          "HH:MM" local
    battery_pct, battery_series, grid_w, grid_series    for systems that have them

Day view (sun up, now_w > 0): hero = now, with today's kWh and the peak beneath;
tiles = irradiance with sparkline, grid voltage (red outside 216..253 V);
chart = kWh by hour with the current hour highlighted and the peak in its
label.

Night view: hero = today's total; chart = last 7 days with today
highlighted; tiles = best of the month and inverter temperature; meter =
today against the best day.
"""

import argparse
import datetime as dt
import json
import subprocess
import sys
import urllib.request
from pathlib import Path

DASHBOARD = Path(__file__).resolve().parents[2] / "python" / "dashboard.py"

DEMO = {
    "now_w": 2800, "e_day_kwh": 4.5, "peak_w": 3050, "peak_time": "12:40", "temp_c": 39.2, "vgrid": 247.6,
    "irradiance": 632, "irradiance_series": [101, 147, 199, 250, 301, 351, 400, 448, 496, 542, 585, 622],
    "hourly_kwh": [0, 0.19, 0.56, 1.68, 2.1, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0], "hour_start": 5,
    "daily_kwh": [18.2, 21.7, 9.4, 16.0, 22.5, 19.8, 4.5], "best_kwh_30d": 24.1, "updated": "09:53",
}


def kw(w: float) -> str:
    return f"{w / 1000:.1f}kW" if abs(w) >= 1000 else f"{w:.0f}W"


def load(a: argparse.Namespace) -> dict:
    if a.demo:
        return DEMO
    if a.file:
        return json.loads(Path(a.file).read_text())
    if a.url:
        with urllib.request.urlopen(a.url, timeout=20) as r:
            return json.load(r)
    if a.command:
        out = subprocess.run(a.command, shell=True, capture_output=True, text=True, timeout=120)
        if out.returncode != 0:
            sys.exit(f"source command failed: {out.stderr.strip()[:300]}")
        return json.loads(out.stdout)
    sys.exit("give --demo, --file, --url or --command")


def build_spec(d: dict, night: bool | None, import_alert: float) -> dict:
    now = dt.datetime.now()
    now_w = d.get("now_w")
    if night is None:
        night = (now_w == 0 or now_w is None) and (now.hour >= 18 or now.hour < 6)
    spec = {"title": "Solar", "updated": d.get("updated") or now.strftime("%H:%M")}
    e_day = d.get("e_day_kwh")
    best = d.get("best_kwh_30d")
    peak = d.get("peak_w")
    peak_s = (kw(peak) + (f" @{d['peak_time']}" if d.get("peak_time") else "")) if peak else ""

    if not night:
        if now_w is not None:
            under = ([f"{e_day:.1f} kWh"] if e_day is not None else []) + ([f"peak {kw(peak)}"] if peak else [])
            spec["hero"] = {"label": "Generating now", "value": kw(now_w), "delta": " · ".join(under)}
        tiles = []
        if "irradiance" in d:
            tiles.append({"label": "Sun W/m²", "value": f"{d['irradiance']:.0f}", "spark": d.get("irradiance_series") or []})
        if "battery_pct" in d:
            tiles.append({"label": "Battery", "value": f"{d['battery_pct']:.0f}%",
                          "spark": d.get("battery_series") or [], "alert": d["battery_pct"] < 20})
        if "grid_w" in d:
            g = d["grid_w"]
            tiles.append({"label": "Grid " + ("import" if g > 0 else "export"), "value": kw(abs(g)),
                          "spark": d.get("grid_series") or [], "alert": g > import_alert})
        elif "vgrid" in d:
            tiles.append({"label": "Grid V", "value": f"{d['vgrid']:.0f}", "alert": not 216 <= d["vgrid"] <= 253})
        if tiles:
            spec["tiles"] = tiles[:2]
        hourly = list(d.get("hourly_kwh") or [])
        if hourly:
            start = int(d.get("hour_start", 0))
            cur = now.hour - start
            spec["chart"] = {"type": "columns", "label": "kWh by hour" + (f" · peak {d['peak_time']}" if d.get("peak_time") else ""),
                             "values": [v or 0 for v in hourly],
                             "highlight": cur if 0 <= cur < len(hourly) else None,
                             "ticks": [[i, str((start + i) % 24)] for i in range(0, len(hourly), 3)]}
    else:
        if e_day is not None:
            spec["hero"] = {"label": "Generated today", "value": f"{e_day:.1f}", "delta": "kWh" + (f" · peak {peak_s}" if peak_s else "")}
        tiles = []
        if best is not None:
            tiles.append({"label": "Best, 30d", "value": f"{best:.1f}"})
        if "temp_c" in d:
            tiles.append({"label": "Inverter °C", "value": f"{d['temp_c']:.0f}"})
        if tiles:
            spec["tiles"] = tiles
        daily = d.get("daily_kwh")
        if daily:
            spec["chart"] = {"type": "columns", "label": "kWh, last 7 days",
                             "values": [v or 0 for v in daily], "highlight": len(daily) - 1,
                             "ticks": [[i, (now - dt.timedelta(days=len(daily) - 1 - i)).strftime("%a")[0]] for i in range(len(daily))]}
    if night and e_day is not None and best:
        spec["meter"] = {"label": "vs best", "value": min(1.0, e_day / best)}
    return spec


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    src = ap.add_mutually_exclusive_group()
    src.add_argument("--demo", action="store_true")
    src.add_argument("--file")
    src.add_argument("--url")
    src.add_argument("--command", help="shell command that prints the JSON")
    view = ap.add_mutually_exclusive_group()
    view.add_argument("--day", action="store_true", help="force the day view")
    view.add_argument("--night", action="store_true", help="force the night view")
    ap.add_argument("--import-alert", type=float, default=2000, help="watts of grid import that turns the tile red")
    ap.add_argument("-o", "--out", default="solar.png")
    ap.add_argument("--scale", type=int, default=1)
    ap.add_argument("--push", metavar="ADDRESS")
    ap.add_argument("--if-changed", action="store_true", help="skip the push when the image is unchanged")
    ap.add_argument("--spec-only", action="store_true")
    a = ap.parse_args()

    night = True if a.night else False if a.day else None
    spec = build_spec(load(a), night, a.import_alert)
    if a.spec_only:
        print(json.dumps(spec, indent=2))
        return 0
    cmd = [sys.executable, str(DASHBOARD), "-", "-o", a.out, "--scale", str(a.scale)]
    if a.push:
        cmd += ["--push", a.push]
    if a.if_changed:
        cmd.append("--if-changed")
    return subprocess.run(cmd, input=json.dumps(spec), text=True).returncode


if __name__ == "__main__":
    sys.exit(main())
