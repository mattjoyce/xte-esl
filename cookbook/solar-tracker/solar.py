#!/usr/bin/env python3
"""Solar tracker: a grid-tied inverter's day on the tag, with a night view.

    ./cookbook/solar-tracker/solar.py --demo --push 9F:1D:00:0B:33:36
    ./cookbook/solar-tracker/solar.py --url http://192.168.20.4:8095/graphs/snapshot.json --push ... --if-changed
    ./cookbook/solar-tracker/solar.py --file snap.json -o solar.png --scale 3
    ./cookbook/solar-tracker/solar.py --command "ssh host 'docker exec -i solar-monitor python3 -' < snapshot.py" --push ...

Source JSON (every key optional; missing ones leave their region empty):

    now_w                 generating now, W          e_day_kwh            today so far
    peak_w, peak_time     today's peak               vgrid                grid voltage, V
    hourly_kwh, hour_start   today's energy per hour from hour_start
    yesterday_hourly_kwh  same window, yesterday     yesterday_by_now_kwh yesterday's total at this time of day
    vs_sun_now_pct        output / (irradiance x kWp), now
    vs_sun_day_pct        energy / (insolation x kWp), today
    daily_kwh             last 7 days, oldest first, today last; null where unknown
    best_kwh_30d          best day of the last 30    tomorrow_kwh         forecast
    array_kwp             sets the fixed chart scale updated              "HH:MM" local
    irradiance, irradiance_series, battery_pct, battery_series, grid_w, grid_series   also understood

Day view: the title is a sentence about the day ("4.5 kWh, ahead of
yesterday"). Hero = generation now, peak beneath. Tiles = how much of the
sun's offer became power ("vs sun"), and grid voltage at regular weight
unless it is out of 216..253 V, when it goes red. Chart = kWh by hour on a
fixed scale, yesterday's profile as an outline behind the bars, the current
hour marked by a full-height yellow band.

Night view: title = today's total against yesterday or the forecast. Hero =
today's kWh, peak beneath. Tiles = vs sun for the day, and tomorrow's
forecast. Chart = last 7 days on a fixed scale with today's band and a
dotted line at the best day of the month.
"""

import argparse
import datetime as dt
import json
import math
import subprocess
import sys
import urllib.request
from pathlib import Path

DASHBOARD = Path(__file__).resolve().parents[2] / "python" / "dashboard.py"

DEMO = {
    "now_w": 2800, "e_day_kwh": 4.5, "peak_w": 3050, "peak_time": "12:40", "vgrid": 247.6, "array_kwp": 5.2,
    "vs_sun_now_pct": 89, "vs_sun_day_pct": 81,
    "hourly_kwh": [0, 0.19, 0.56, 1.68, 2.1, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0], "hour_start": 5,
    "yesterday_hourly_kwh": [0, 0.1, 0.4, 1.2, 1.9, 2.6, 3.1, 3.4, 3.3, 2.9, 2.2, 1.4, 0.6, 0.1, 0, 0],
    "yesterday_by_now_kwh": 3.6,
    "daily_kwh": [18.2, 21.7, 9.4, 16.0, 22.5, 19.8, 4.5], "best_kwh_30d": 24.1, "tomorrow_kwh": 18.1,
    "updated": "09:53",
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


def sentence(e_day, y_by_now, tomorrow, night: bool) -> str:
    """The one line the reader should take away."""
    if e_day is None:
        return "Solar"
    if y_by_now:
        diff = e_day - y_by_now
        if abs(diff) < 0.3:
            return f"{e_day:.1f} kWh, level with yesterday"
        return f"{e_day:.1f} kWh, {diff:+.1f} vs yesterday"
    if night and tomorrow:
        return f"{e_day:.1f} kWh today, ~{tomorrow:.0f} tomorrow"
    return f"{e_day:.1f} kWh so far today"


def build_spec(d: dict, night: bool | None, import_alert: float) -> dict:
    now = dt.datetime.now()
    now_w = d.get("now_w")
    if night is None:
        night = (not now_w) and (now.hour >= 18 or now.hour < 6)
    e_day, best, peak = d.get("e_day_kwh"), d.get("best_kwh_30d"), d.get("peak_w")
    kwp = float(d.get("array_kwp") or 5.0)
    peak_s = (f"peak {kw(peak)}" + (f" @{d['peak_time']}" if d.get("peak_time") else "")) if peak else ""
    y_hourly = [v or 0 for v in (d.get("yesterday_hourly_kwh") or [])]
    have_yesterday = any(y_hourly)
    spec = {"title": sentence(e_day, d.get("yesterday_by_now_kwh") if have_yesterday else None, d.get("tomorrow_kwh"), night),
            "updated": d.get("updated") or now.strftime("%H:%M")}

    tiles = []
    if not night:
        if now_w is not None:
            spec["hero"] = {"label": "Generating now", "value": kw(now_w), "delta": peak_s}
        if d.get("vs_sun_now_pct") is not None:
            tiles.append({"label": "vs sun", "value": f"{d['vs_sun_now_pct']:.0f}%", "alert": d["vs_sun_now_pct"] < 40})
        elif "irradiance" in d:
            tiles.append({"label": "Sun W/m²", "value": f"{d['irradiance']:.0f}",
                          "spark": d.get("irradiance_series") or [], "spark_range": [0, 1000]})
        if "battery_pct" in d:
            tiles.append({"label": "Battery", "value": f"{d['battery_pct']:.0f}%",
                          "spark": d.get("battery_series") or [], "spark_range": [0, 100], "alert": d["battery_pct"] < 20})
        if "grid_w" in d:
            g = d["grid_w"]
            tiles.append({"label": "Grid " + ("import" if g > 0 else "export"), "value": kw(abs(g)),
                          "spark": d.get("grid_series") or [], "alert": g > import_alert})
        elif "vgrid" in d:
            tiles.append({"label": "Grid V", "value": f"{d['vgrid']:.0f}", "alert": not 216 <= d["vgrid"] <= 253})
        hourly = [v or 0 for v in (d.get("hourly_kwh") or [])]
        if hourly:
            start = int(d.get("hour_start", 0))
            cur = now.hour - start
            spec["chart"] = {"type": "columns", "label": "kWh/h" + (", yesterday outlined" if have_yesterday else " today"),
                             "values": hourly, "max": kwp,          # one hour at full array power is the top of the scale
                             "reference": y_hourly if have_yesterday else [],
                             "highlight": cur if 0 <= cur < len(hourly) else None,
                             "ticks": [[i, str((start + i) % 24)] for i in range(0, len(hourly), 3)]}
    else:
        if e_day is not None:
            spec["hero"] = {"label": "Generated today, kWh", "value": f"{e_day:.1f}", "delta": peak_s}
        if d.get("vs_sun_day_pct") is not None:
            tiles.append({"label": "vs sun", "value": f"{d['vs_sun_day_pct']:.0f}%", "alert": d["vs_sun_day_pct"] < 40})
        if d.get("tomorrow_kwh") is not None:
            tiles.append({"label": "tomorrow kWh", "value": f"~{d['tomorrow_kwh']:.0f}"})
        daily = d.get("daily_kwh")
        if daily:
            top = max([v or 0 for v in daily] + [best or 0, d.get("tomorrow_kwh") or 0])
            spec["chart"] = {"type": "columns", "label": "kWh/day" + (" · best dotted" if best else ""),
                             "values": [v or 0 for v in daily], "highlight": len(daily) - 1,
                             "max": math.ceil(top / 5) * 5 or 5, "reference_line": best,
                             "ticks": [[i, (now - dt.timedelta(days=len(daily) - 1 - i)).strftime("%a")[0]] for i in range(len(daily))]}
    if tiles:
        spec["tiles"] = tiles[:2]
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
