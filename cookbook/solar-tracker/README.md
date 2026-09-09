# Solar tracker

A grid-tied inverter's day on the tag, with a different view after dark.

<p><img src="../../docs/images/solar-day.png" width="375" alt="Day view"> <img src="../../docs/images/solar-night.png" width="375" alt="Night view"></p>

## Design

The panel has room for one sentence, one hero figure, two small tiles and
one chart, in four inks, read at a glance from a metre. Two views share
that frame. The design went through a Tufte × Knaflic review
(`reviews/luminary-solar-2026-09-09/`); its three changes are in.

**The title is the message.** Not "Solar" but "4.5 kWh, +0.9 vs
yesterday", or at night "17.3 kWh today, ~18 tomorrow". It is the one
line the reader should get in two seconds.

**Day** (sun up). Generation now is the hero, with the peak beneath. The
tiles are the diagnostic and the constraint: "vs sun", the share of the
sun's offer (irradiance × array kWp) the inverter turned into power, which
is what reveals shade, soiling and clipping; and grid voltage, at regular
weight until it leaves 216 to 253 V, when it goes red. The chart is kWh by
hour on a fixed scale (one hour at full array power is the top), with
yesterday's profile as a 1-pixel outline behind the bars and a full-height
yellow band on the current hour, so the marker is legible however short
the in-progress bar is.

**Night** (no generation, after 18:00 or before 06:00). Today's total is
the hero. Tiles are "vs sun" for the whole day and tomorrow's forecast
from OpenMeteo. The chart is the last seven days on a fixed scale, today
banded, with a dotted line at the best day of the month. No meter: the
chart against the dotted line already says it.

Red is reserved for alerts (grid voltage out of range, conversion below
40%, battery under 20% on systems that have one). Everything else is black
on white, drawn in hard pixels with no anti-aliasing.

## Data path

The recipe reads one JSON snapshot and never talks to an inverter itself.
For a GoodWe monitored with the rrdtool stack, `snapshot.py` in that
project's `src/` builds the snapshot inside the `solar-monitor` container:
hourly energy and today's peak from the one-minute archive, yesterday's
profile from the hourly archive, the last seven days and best-of-month
from the daily archive, irradiance and today's insolation from the weather
RRD, the live values from `rrdtool lastupdate`, and tomorrow's forecast
from OpenMeteo. The "vs sun" ratio uses `ARRAY_KWP` (13 × 400 W = 5.2 by
default) and the forecast a performance ratio of 0.8; set both as
environment variables on the container if they differ.

```sh
# ad hoc, no deploy: run the exporter in the container over SSH, render locally
unraid_cmd.sh "docker exec -i solar-monitor python3 -" < /path/to/goodwe/src/snapshot.py > snap.json
.venv/bin/python cookbook/solar-tracker/solar.py --file snap.json --push 9F:1D:00:0B:33:36 --if-changed

# deployed: the grapher writes /data/graphs/snapshot.json every 15 min and nginx serves it
.venv/bin/python cookbook/solar-tracker/solar.py --url http://192.168.20.4:8095/graphs/snapshot.json --push 9F:1D:00:0B:33:36 --if-changed
```

Any other source works if it emits the keys in the script's docstring.
`--demo` renders sample data; `--day` and `--night` force a view.

## Cron

```
*/10 5-21 * * *  cd /path/to/xte-esl && .venv/bin/python cookbook/solar-tracker/solar.py --url http://HOST:8095/graphs/snapshot.json --push 9F:1D:00:0B:33:36 --if-changed
0 22 * * *       cd /path/to/xte-esl && .venv/bin/python cookbook/solar-tracker/solar.py --url http://HOST:8095/graphs/snapshot.json --push 9F:1D:00:0B:33:36 --night
```

Ten minutes in daylight is plenty; `--if-changed` keeps the panel still when
nothing moves. The 22:00 line switches to the night view once and leaves it
there until morning.

## Known gaps

- `daily_kwh` is derived from the average power per day, so a day with an
  RRD gap under-reports; the exporter emits `null` for days with no data and
  the recipe draws them as zero.
- The current hour's bar is energy so far this hour, so it is always short
  until the hour ends.
