# Token tracker

This week's LLM token usage on the tag: week-to-date total as the hero,
estimated cost and output tokens beneath, daily columns Monday to Sunday
with today highlighted, cache-hit rate in the chart label, and an optional
budget meter.

Source: [`ccusage`](https://github.com/ryoppippi/ccusage) via `bunx`, reading
the local Claude Code and Codex logs offline. Nothing is uploaded and
nothing is stored; the figures only leave the machine if they go to the tag.

```sh
.venv/bin/python cookbook/token-tracker/token_weather.py --spec-only            # see the numbers
.venv/bin/python cookbook/token-tracker/token_weather.py --budget 500M -o t.png --scale 3
.venv/bin/python cookbook/token-tracker/token_weather.py --budget 500M --push 9F:1D:00:0B:33:36 --if-changed
```

Cron, every 15 minutes, redrawing only when the picture changed:

```
*/15 * * * *  cd /path/to/xte-esl && .venv/bin/python cookbook/token-tracker/token_weather.py --budget 500M --push 9F:1D:00:0B:33:36 --if-changed
```

The hero turns red when the weekly cache-hit rate drops below 50%, which on
Claude Code usually means long sessions are being restarted cold.
