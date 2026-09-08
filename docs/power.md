# Power

What the tag draws, how long cells last at a given refresh cadence, and how
to run it from USB. Everything here is an estimate from the panel type and
the measurements in NOTES.md unless marked *measured*.

## What is known

- *Measured:* two CR2450 cells in **parallel**, 3 V nominal, about 1200 mAh
  together. The rail holds 3 V with one cell fitted, which a series pair
  could not do.
- *Measured:* logic level 3 V on the debug pads.
- *Measured:* the advertisement carries a battery percentage (byte 8); it
  read 99 on fresh cells. The factory screen printed 80%.
- *Measured:* the refresh command is acknowledged in about 60 ms, and the
  panel then runs its waveform for 15 to 25 seconds.
- *Not measured:* the current during a refresh, the sleep current, and the
  firmware's low-voltage cutoff.

## Where the energy goes

E-paper holds an image with no power. Everything is spent in two places:

| state | typical draw for this class of tag | cost |
|---|---|---|
| sleeping, advertising about once a second | 5 to 15 µA | 0.2 to 0.4 mAh per day |
| one refresh: booster, panel drive, BLE session | 10 to 20 mA for about 20 s | 0.1 to 0.2 mAh |

So the refresh count decides the battery life, and nothing else matters
much.

## Cell life against cadence

Assuming 0.15 mAh per refresh and 0.3 mAh per day at rest:

| refreshes per day | cadence | mAh per day | 2x CR2450 (usable ~800 mAh) | 2x AAA lithium (~1200 mAh) |
|---|---|---|---|---|
| 4 | a shop | 0.9 | years | years |
| 24 | hourly | 3.9 | about 7 months | about 10 months |
| 96 | every 15 min | 14.7 | 7 to 9 weeks | 11 to 12 weeks |
| 288 | every 5 min | 43.5 | under 3 weeks | under 4 weeks |

**Why the coin cells get less than their rated capacity.** A CR2450 has an
internal resistance of tens of ohms that rises as it drains. The 20-second
refresh pulse sags the rail, and the firmware's low-voltage cutoff will
trip well before the cell is chemically empty. Wiring the two cells in
parallel halves that sag, which is presumably why the vendor did it. AAA
cells have a fraction of the resistance; lithium AAAs also hold a flat
3 V until the end. Alkaline AAAs fade and can leak if left for a year.

`--if-changed` on the pusher removes every refresh where the picture did
not change, which for most dashboards means the whole night.

## Running from USB

USB is 5 V. The tag is a 3 V design and must not be fed 5 V directly.

- **3.3 V LDO regulator.** The simple answer. Prefer a low-quiescent part
  (HT7333, MCP1700, a few µA idle) over an AMS1117 (about 5 mA idle, which
  is more than the tag). 3.3 V is fine: fresh coin cells sit near 3.2 V and
  the battery byte will read full.
- **A buck converter** is not worth it here. Its idle current exceeds the
  tag's and it adds switching noise next to a BLE radio.
- **An ESP32 devkit's 3V3 pin** works and is what accidentally powered the
  tag during the SWD work. Fine on a bench, wasteful as a fixture.

Wiring: regulator output to the battery holder's positive contact, ground to
its negative, cells removed. Put 10 to 100 µF across the supply at the
holder; the refresh pulse is exactly the load that makes a long USB lead sag.

On mains power the cadence no longer costs anything, but the ink does have
a cycle life, on the order of a million refreshes for panels of this type.
A 5-minute cron is years of that.

## Measuring instead of estimating

Two cheap measurements would replace this whole page:

1. **Per-refresh cost.** Power the tag from a bench supply or USB meter
   with current logging, push once, integrate the pulse. Or put a 10 Ω
   resistor in the battery lead and watch it on a scope.
2. **The battery byte over time.** `python/scan.py` prints the
   advertisement; log byte 8 against the number of pushes and the curve
   appears within a couple of weeks of dashboard use. The number the
   firmware reports is what its cutoff will act on, so it is the one that
   matters.

When either number exists, replace the estimates above and say so.
