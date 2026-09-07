#!/usr/bin/env python3
"""Token weather: this week's LLM token usage from ccusage, as a tag dashboard.

    ./examples/token_weather.py --push 9F:1D:00:0B:33:36
    ./examples/token_weather.py --budget 500M -o tokens.png --scale 3     # preview only
    */15 * * * *  cd ~/Projects/xte-esl && .venv/bin/python examples/token_weather.py --push 9F:1D:00:0B:33:36

Reads `bunx ccusage daily --json --offline` for Monday to today, builds a
dashboard spec and hands it to python/dashboard.py. Nothing is stored; the
usage figures never leave this machine unless you push them to the tag.

Layout: hero = week-to-date tokens, with estimated cost and output tokens
beneath; chart = daily totals Mon..Sun in millions with today highlighted and
the cache-hit rate in its label; meter = share of --budget used (omit
--budget for no meter). The hero turns red if the cache-hit rate drops
below 50%.
"""

import argparse
import datetime as dt
import json
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
DASHBOARD = HERE.parent / "python" / "dashboard.py"


def compact(n: float) -> str:
    for unit, div in (("B", 1e9), ("M", 1e6), ("K", 1e3)):
        if n >= div:
            v = n / div
            return f"{v:.1f}{unit}" if v < 10 else f"{v:.0f}{unit}"
    return f"{n:.0f}"


def parse_budget(s: str) -> float:
    s = s.strip().upper()
    mult = {"K": 1e3, "M": 1e6, "B": 1e9}.get(s[-1], 1)
    return float(s.rstrip("KMB")) * mult


def ccusage(since: dt.date, until: dt.date) -> dict:
    cmd = ["bunx", "ccusage", "daily", "--since", since.strftime("%Y%m%d"),
           "--until", until.strftime("%Y%m%d"), "--json", "--offline"]
    out = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
    if out.returncode != 0:
        sys.exit(f"ccusage failed: {out.stderr.strip()[:300]}")
    return json.loads(out.stdout)


def build_spec(data: dict, monday: dt.date, today: dt.date, budget: float | None) -> dict:
    by_day = {d["period"]: d for d in data.get("daily", [])}
    days = [monday + dt.timedelta(days=i) for i in range(7)]
    totals = [by_day.get(d.isoformat(), {}).get("totalTokens", 0) for d in days]
    week_total = sum(totals)
    out_tokens = sum(by_day.get(d.isoformat(), {}).get("outputTokens", 0) for d in days)
    cache_read = sum(by_day.get(d.isoformat(), {}).get("cacheReadTokens", 0) for d in days)
    cost = sum(by_day.get(d.isoformat(), {}).get("totalCost", 0.0) for d in days)
    hit = (cache_read / week_total * 100) if week_total else 0.0
    today_idx = (today - monday).days
    spec = {
        "title": f"Tokens wk {monday.isocalendar()[1]}",
        "updated": today.strftime("%a %H:%M") if isinstance(today, dt.datetime) else dt.datetime.now().strftime("%a %H:%M"),
        "hero": {"label": "Week to date", "value": compact(week_total),
                 "delta": f"${cost:,.0f} est. · {compact(out_tokens)} out", "alert": hit < 50 and week_total > 0},
        "chart": {"type": "columns", "label": f"Daily, M · {hit:.0f}% cached",
                  "values": [round(t / 1e6, 1) for t in totals],
                  "highlight": today_idx, "ticks": [[i, "MTWTFSS"[i]] for i in range(7)]},
    }
    if budget:
        spec["meter"] = {"label": "Budget", "value": min(1.0, week_total / budget), "warn": 0.8}
    return spec


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--budget", help="weekly token budget for the meter, e.g. 500M")
    ap.add_argument("-o", "--out", default="tokens.png")
    ap.add_argument("--scale", type=int, default=1)
    ap.add_argument("--push", metavar="ADDRESS")
    ap.add_argument("--spec-only", action="store_true", help="print the spec JSON and exit")
    a = ap.parse_args()

    today = dt.date.today()
    monday = today - dt.timedelta(days=today.weekday())
    spec = build_spec(ccusage(monday, today), monday, today, parse_budget(a.budget) if a.budget else None)
    if a.spec_only:
        print(json.dumps(spec, indent=2))
        return 0
    cmd = [sys.executable, str(DASHBOARD), "-", "-o", a.out, "--scale", str(a.scale)]
    if a.push:
        cmd += ["--push", a.push]
    return subprocess.run(cmd, input=json.dumps(spec), text=True).returncode


if __name__ == "__main__":
    sys.exit(main())
