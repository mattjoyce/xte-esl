# Cookbook

Recipes that turn a data source into a picture on the tag. Each one is a
small script that builds a dashboard spec and hands it to
`python/dashboard.py`, which renders in the four inks and pushes.

| recipe | shows | source |
|---|---|---|
| [`token-tracker/`](token-tracker/) | this week's LLM token usage, cost, cache hit, daily columns | `ccusage` |
| [`solar-tracker/`](solar-tracker/) | generation now, battery, grid, kWh by hour | a JSON snapshot from a file, URL or command |

## The shape of a recipe

```
source  ->  spec (dict)  ->  python/dashboard.py -  ->  push.py --if-changed
```

- Keep the script free of rendering code. Build the spec (keys in the
  `dashboard.py` docstring) and pipe it in on stdin.
- Use `--if-changed` on the push. Every refresh is a 20-second full-panel
  waveform and costs battery; a dashboard that has not changed should not
  be redrawn. The pusher remembers a hash of the last image per tag in
  `~/.cache/xte-esl/`.
- Cadence: every 5 to 15 minutes is plenty on coin cells for a few weeks,
  hourly for months. `docs/power.md` has the table and the USB option.
- Nothing personal in the repo. Recipes fetch at run time and store nothing;
  the values only leave the machine if they go to the tag.

## Running on a schedule

```
*/15 * * * *  cd /path/to/xte-esl && .venv/bin/python cookbook/token-tracker/token_weather.py --push 9F:1D:00:0B:33:36 --if-changed
```

The tag has to be within Bluetooth range of the machine running the cron,
and not connected to anything else at that moment.

## Ideas not yet written

- Weather: today's forecast as a line, rain hours in red.
- Calendar: next three events as a plain list.
- CI: last ten builds as columns, failures red, current in yellow.
- Room sensor: temperature sparkline with a comfort band.
