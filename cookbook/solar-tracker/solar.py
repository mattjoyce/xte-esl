#!/usr/bin/env python3
"""Solar tracker: generation, battery, grid and kWh by hour on the tag.

    ./cookbook/solar-tracker/solar.py --demo --push 9F:1D:00:0B:33:36
    ./cookbook/solar-tracker/solar.py --file /var/lib/solar/latest.json --push 9F:1D:00:0B:33:36 --if-changed
    ./cookbook/solar-tracker/solar.py --url http://inverter.local/snapshot.json --push ...
    ./cookbook/solar-tracker/solar.py --command "rrdtool-export.sh" --push ...

The source must produce this JSON (every key optional):

    {
      "now_w": 3200,            generating now, watts
      "battery_pct": 82,        state of charge
      "battery_series": [..],   recent SoC values for the sparkline
      "grid_w": -1100,          negative = exporting, positive = importing
      "grid_series": [..],
      "hourly_kwh": [0, 0, 0.1, 0.6, ...],   one value per hour from "hour_start"
      "hour_start": 6,          hour of the first hourly value
      "day_kwh": 18.4,          total today, shown under the hero
      "updated": "14:32"        optional; defaults to now
    }

Grid import above --import-alert watts (default 2000) turns the grid tile
red. Nothing is stored.
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
    "now_w": 3200, "battery_pct": 82, "battery_series": [61, 64, 68, 70, 74, 77, 79, 80, 81, 82],
    "grid_w": -1100, "grid_series": [400, 300, 100, -200, -500, -800, -900, -1000, -1100],
    "hourly_kwh": [0, 0, 0.1, 0.6, 1.4, 2.2, 2.9, 3.3, 3.5, 3.2, 2.6, 1.7, 0.8, 0.2, 0],
    "hour_start": 6, "day_kwh": 22.5,
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
        out = subprocess.run(a.command, shell=True, capture_output=True, text=True, timeout=60)
        if out.returncode != 0:
            sys.exit(f"source command failed: {out.stderr.strip()[:300]}")
        return json.loads(out.stdout)
    sys.exit("give --demo, --file, --url or --command")


def build_spec(d: dict, import_alert: float) -> dict:
    now = dt.datetime.now()
    hourly = list(d.get("hourly_kwh") or [])
    start = int(d.get("hour_start", 0))
    spec = {"title": "Solar", "updated": d.get("updated") or now.strftime("%H:%M")}
    if "now_w" in d:
        spec["hero"] = {"label": "Generating now", "value": kw(d["now_w"]),
                        "delta": f"{d['day_kwh']:.1f} kWh today" if "day_kwh" in d else ""}
    tiles = []
    if "battery_pct" in d:
        tiles.append({"label": "Battery", "value": f"{d['battery_pct']:.0f}%",
                      "spark": d.get("battery_series") or [], "alert": d["battery_pct"] < 20})
    if "grid_w" in d:
        g = d["grid_w"]
        tiles.append({"label": "Grid " + ("import" if g > 0 else "export"), "value": kw(abs(g)),
                      "spark": d.get("grid_series") or [], "alert": g > import_alert})
    if tiles:
        spec["tiles"] = tiles
    if hourly:
        cur = now.hour - start
        ticks = [[i, str((start + i) % 24)] for i in range(0, len(hourly), 4)]
        spec["chart"] = {"type": "columns", "label": "kWh by hour", "values": hourly,
                         "highlight": cur if 0 <= cur < len(hourly) else None, "ticks": ticks}
    return spec


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    src = ap.add_mutually_exclusive_group()
    src.add_argument("--demo", action="store_true")
    src.add_argument("--file")
    src.add_argument("--url")
    src.add_argument("--command", help="shell command that prints the JSON")
    ap.add_argument("--import-alert", type=float, default=2000, help="watts of grid import that turns the tile red")
    ap.add_argument("-o", "--out", default="solar.png")
    ap.add_argument("--scale", type=int, default=1)
    ap.add_argument("--push", metavar="ADDRESS")
    ap.add_argument("--if-changed", action="store_true", help="skip the push when the image is unchanged")
    ap.add_argument("--spec-only", action="store_true")
    a = ap.parse_args()

    spec = build_spec(load(a), a.import_alert)
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
