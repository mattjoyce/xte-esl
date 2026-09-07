# Solar tracker

Generation now as the hero with today's kWh beneath, battery and grid tiles
with sparklines, and a kWh-by-hour column chart with the current hour
highlighted. Grid import above a threshold turns the grid tile red; battery
under 20% turns its tile red.

The recipe does not talk to any inverter itself. It reads one JSON snapshot
from a file, a URL or a command, so whatever already collects your solar
data (a GoodWe poller, an RRD export, Home Assistant, a spreadsheet) only
has to write this:

```json
{
  "now_w": 3200,
  "battery_pct": 82,
  "battery_series": [61, 64, 68, 70, 74, 77, 79, 80, 81, 82],
  "grid_w": -1100,
  "grid_series": [400, 300, 100, -200, -500, -800, -900, -1000, -1100],
  "hourly_kwh": [0, 0, 0.1, 0.6, 1.4, 2.2, 2.9, 3.3, 3.5, 3.2, 2.6, 1.7, 0.8, 0.2, 0],
  "hour_start": 6,
  "day_kwh": 22.5
}
```

Every key is optional; missing ones leave their region empty. `grid_w` is
negative when exporting.

```sh
.venv/bin/python cookbook/solar-tracker/solar.py --demo --push 9F:1D:00:0B:33:36
.venv/bin/python cookbook/solar-tracker/solar.py --file /var/lib/solar/latest.json --push 9F:1D:00:0B:33:36 --if-changed
.venv/bin/python cookbook/solar-tracker/solar.py --url http://inverter.local/snapshot.json --spec-only
.venv/bin/python cookbook/solar-tracker/solar.py --command "rrdtool xport ... | jq '...'" --push ...
```

Cron every 10 minutes during daylight is plenty; `--if-changed` keeps the
panel still overnight when nothing moves.
