# Solar tracker on the 250x122 tag, through Tufte × Knaflic

Stage: before, design review. Axis: evidence × message.

Reviewed: `docs/images/solar-day.png` (live, 09:55) and `docs/images/solar-night.png` (demo), `cookbook/solar-tracker/README.md`, `cookbook/solar-tracker/solar.py`, `python/dashboard.py`, `python/push.py` (quantisation only), and `ZK/structure/MOC-goodwe.md` for the domain claim that irradiance is the primary diagnostic.

## Two facts about the medium that shape every finding

The panel is 48.5 x 23.7 mm, so one pixel is 0.194 mm. At one metre, DejaVu cap heights subtend:

| font | cap height | at 1 m | reads as |
|---|---|---|---|
| 48 px bold (night hero "4.5") | 6.8 mm | 23 arcmin | glance |
| 31 px bold (day hero "2.8kW", after `fit()` shrank it) | 4.5 mm | 15 arcmin | glance |
| 22 px bold (tile values) | 3.1 mm | 11 arcmin | glance, just |
| 12 px bold ("Solar") | 1.75 mm | 6 arcmin | lean in |
| 11 px regular (hero delta line) | 1.55 mm | 5.3 arcmin | 20/20 threshold |
| 9 px regular (labels) | 1.36 mm | 4.7 arcmin | below threshold |
| 8 px regular (ticks, night delta) | 1.16 mm | 4 arcmin | below threshold |

So the panel has exactly two tiers. The glance tier is the hero, the two tile values, the chart silhouette, and colour. Everything else is lean-in detail. A two-second message has to live entirely in the first tier.

Second fact. The preview PNGs are not what the panel shows. `dashboard.py` renders into an RGB image and PIL's `d.text` anti-aliases, so `solar-day.png` contains about 250 grey levels. `push.py` line 62 then snaps every pixel to the nearest of the four inks (`dither=Image.NONE`). Re-quantising the previews the same way, "Generating now" becomes "Gereratirg row", "Generated today" becomes "Generatec tocay", and the night hero's unit line "kWh · peak 3.0kW @12:40" (shrunk to 8 px by `fit()`) becomes unreadable. Both lenses audit the rendered output, and the rendered output is the quantised one.

## Tufte: is the evidence honest and dense?

### 🔴 T1. The review artifact is not the artifact

Locus: `dashboard.py` line 245-246 (`Image.new("RGB", ...)`, `ImageDraw.Draw(im)`); `push.py` line 62; both docs images.

Anti-aliased text thresholded to bilevel loses strokes. On the night panel the unit of the largest number on the display does not survive to the glass. Change: set `d.fontmode = "1"` right after `ImageDraw.Draw(im)` so PIL rasterises hinted bilevel glyphs (these are far cleaner than thresholded anti-aliasing at 8-11 px), and make `--scale` write the quantised image so the docs show what the tag shows. Then re-check every label under 12 px on the real output.

### 🔴 T2. The highlighted bar is the least honest bar

Locus: `solar.py` line 103 (`"highlight": cur`); README "Known gaps", second bullet; `dashboard.py` `columns()` lines 183-188.

The README admits the current hour's bar is energy so far and "always short until the hour ends". The spec then paints that bar yellow, the only accent on the panel. At 09:05 the eye is sent to a 1 px stub; at 09:55 to a full bar. The lie factor of the highlighted column cycles from near zero to one every hour on a display that refreshes every ten minutes. Change: draw the current hour as a full-height yellow band (`plot.y` to `base_y`, `bw` wide) with the so-far energy as a black bar on top of it. Yellow then means "this hour is in progress", black means "measured", and the honest short bar stops being the focal point. A 1 px black tick at the projected end-of-hour value (`so_far / elapsed_fraction`) is optional and cheap.

### 🟠 T3. Scales move under the reader

Locus: `columns()` line 166 `hi = max(values) or 1.0`; `sparkline()` lines 122-123 and the baseline at line 130.

The hourly chart re-scales to the tallest bar so far, so the 08:00 bar shrinks through the day as later hours beat it; the same quantity changes height between refreshes, which breaks the only comparison a slow display offers (memory of the last glance). The sparkline normalises to its own min and max and draws a baseline at the minimum, so a 101 to 622 W/m² morning ramp and a 590 to 622 wobble both fill the 12 px and both appear to rise from zero. Change: a `max` key on `chart` (rated kWp, or best hour of the last 30 days from the exporter) and `min`/`max` on `spark`; draw the sparkline baseline only when `lo == 0`. Fixed scales make the bar silhouette comparable across refreshes and across days.

### 🟠 T4. The primary diagnostic is left for the reader to compute

Locus: README "Design" paragraph ("the irradiance-to-output ratio is the primary diagnostic"); MOC-goodwe; day view tiles at x 124-183 and the hero.

The panel shows 632 W/m² and 2.8 kW in different units 50 px apart and leaves the division to a reader who does not know the array's kWp. The comparison the README says matters most is the one comparison not drawn. Change: `solar.py` takes `--kwp` (or reads `kwp` from the snapshot), computes `expected = kwp * irradiance / 1000`, and the tile becomes "vs sun 89%", red below a threshold when irradiance is high enough to judge (say under 60% with irradiance over 300). If the sparkline stays, plot the ratio series, which is the shade and soiling trace, rather than raw irradiance.

### 🟠 T5. The night view states 4.5 three times

Locus: night hero "4.5"; yellow W bar (drawn against 22.5); meter "vs best 19%"; tile "Best, 30d 24.1".

One datum, three encodings, plus the meter's denominator stated separately as a tile. Change: draw best-30d as a 1 px dashed reference line across the 7-day chart at 24.1, labelled "best 24.1" (a `reference` key; `columns()` already direct-labels the extreme at line 191-195). Drop the meter and the Best tile. That returns 15 px (meter) and 34 px (tile row) to the chart, taking `bar_h` from 20 px to about 45 px (1.1 kWh per pixel becomes 0.5), or hosts the forecast from K4.

### 🟡 T6. Structural ink

Locus: header rule at y=17 (242 px) and divider at x=119 (100 px), `dashboard.py` lines 96 and 261.

342 px of ink carries no data. The tiles already separate by 4 px of whitespace without a rule. Try removing the divider (the 8 px gap at line 262 remains) and see whether the columns still read. Low priority; on this medium a 1 px rule is nearly free, and hard pixels make whitespace do less work than on paper.

### 🟡 T7. A label that mixes units

Locus: `solar.py` line 101, `"kWh by hour · peak 09:54"`.

The chart is kWh per hour; the peak is a kW instant; at 09:55 "peak 09:54" means "a minute ago". The hero delta already says "peak 2.8kW". Either mark the peak moment as a 1 px tick on the chart's x-axis (data at the resolution the panel allows) or drop it from the label.

### 🟡 T8. Density unused where it would carry the most

Locus: day chart, plot box (124..245, 80..119); 12 of 16 bars are zero at 09:55.

The empty hours are fine, they show time remaining. What is missing is any shape to compare today against. Yesterday's hourly profile, or a clear-sky expected profile, as a 1 px outline behind the bars, gives comparison and causality in about sixteen line segments. Needs the exporter to emit `hourly_kwh_yesterday` (the same RRD query shifted a day) or `expected_hourly_kwh` from the OpenMeteo work already in the goodwe project.

### 🟡 T9. The day hero shrinks with its own value

Locus: `hero()` line 108, `fit(d, value, BOLD, min(48, room), 18, box.w)`.

"2.8kW" fits at 31 px, "12.3kW" would fit at 26 px, the night "4.5" gets 48 px. The number gets smaller as the system makes more. Consider "2.8" at 48 px with the unit in the label ("Generating now, kW") so size stops depending on glyph count.

## Knaflic: does the reader get the message?

### 🔴 K1. The day view has no reference, so "how is today going" cannot be answered at a glance

Locus: day hero and delta; the whole day spec in `solar.py` lines 79-104.

The Big Idea for this one reader is "today is a good or bad solar day, and now is or is not a good time to run things". The panel says 2.8 kW now and, in 11 px at the acuity limit, 4.5 kWh so far. Against what? 4.5 kWh by 09:55 is excellent in June and poor in December; nothing on the panel lets the reader tell. Change: put the comparison in words at the glance tier. Cheapest with existing data is yesterday's total at this hour ("4.5 kWh · yesterday 3.9 by now"); better is the forecast the goodwe pipeline already fetches ("4.5 of ~18 expected"). The chart then gives the shape, the sentence gives the verdict.

### 🔴 K2. The hierarchy puts the two least actionable numbers in the second glance

Locus: tiles "Sun W/m² 632" and "Grid V 247" at 22 px bold; delta "4.5 kWh" at 11 px regular.

The two-second read of the day view is "2.8kW, 632, 247". Grid voltage is meaningful only outside 216 to 253 V (README); 632 W/m² needs a conversion the homeowner does not have. Today's accumulating total, the actual answer, sits in the tier that quantises to noise. Change: tile values regular weight at 16 px unless alert (bold red at 22 px when tripped), so the glance tier is hero, chart, and one sentence. Promote today's kWh into the glance tier (hero label or a tile). Replace the raw irradiance tile with the ratio from T4. Show grid V only when out of range.

### 🟠 K3. "Solar" is a topic label spending 13% of the panel

Locus: `header()` lines 89-96; 16 px of 122.

The reader knows what the panel on the bench is. Keep "09:55" (on a display that can silently stop refreshing, staleness is information). Replace "Solar" with the computed sentence from K1 ("Ahead of yesterday", "Behind, cloudy", "On track for ~18"). If no reference data exists yet, "4.5 kWh so far" is still a better title than "Solar".

### 🟠 K4. The night view answers last night's question, then sits there until breakfast with the wrong tiles

Locus: night tiles "Best, 30d" and "Inverter °C"; README "the one number worth a glance at breakfast".

At 22:00 the reader wants "how did today go", and the view answers it (4.5, 19% of best, worst day of the week). At 07:00 the same image is still up and the question is "what about today". "Inverter °C 39" is a daytime diagnostic shown while the inverter is idle. "Best, 30d" is the meter's denominator. Change: night tiles become "vs sun" for the day just finished (was it weather or the panels, the "so what" of a 4.5 kWh day) and "Tomorrow ~N kWh" from the forecast. Temperature stays in the day view as an alert-only red value.

### 🟠 K5. The accent colour vanishes exactly when the reader needs it

Locus: day render, yellow interior 3 x 18 px (0.6 x 3.5 mm) at x 159-161, y 92-109; night render, yellow interior 13 x 3 px (2.5 x 0.6 mm) at x 229-241, y 92-94; `columns()` lines 187-188.

Yellow is the only "you are here" ink. In the day view the 5 px bar loses two of those pixels to a black outline; in the night view a 4.5 kWh day on a 22.5 scale is 4 px tall. At one metre both read as black. On a bad solar day the "today" marker disappears when the reader most wants to find it. Change: the same fix as T2, a full-height yellow band behind the highlighted column, black bar on top, no outline. Yellow then always covers `bw x bar_h` and means "now" or "today" identically in both views.

### 🟠 K6. Words that cannot be read are clutter

Locus: night hero delta "kWh · peak 3.0kW @12:40", `hero()` lines 111-115, `fit()` minimum 8 px.

Cross-reference T1. This line carries the hero's unit and is illegible on the panel. Words are part of the graph; a word the reader cannot resolve costs attention and returns nothing. Change: `fontmode = "1"`, and never set information below 10 px regular. The peak belongs on the chart as a tick, or nowhere at night.

### 🟡 K7. The meter measures against a goal the reader did not set

Locus: `solar.py` line 121, `min(1.0, e_day / best)`; meter "vs best 19%".

A progress bar toward the best day of the month reads as failure on every cloudy day. If a meter survives T5, label it against the forecast ("vs forecast 91%"), the number that separates weather from fault.

### 🟡 K8. The demo image contradicts its own rationale

Locus: `docs/images/solar-night.png`, updated "09:53"; `solar.py` DEMO line 44.

The README says the night view runs from 22:00; the night image says 09:53 with a peak at 12:40. Re-render the demo with `"updated": "22:00"` so the picture tells the story the text tells.

### 🟡 K9. What would the reader do differently?

Locus: `solar.py` lines 90-94 (`grid_w` optional, falls back to `vgrid`).

The homeowner's only lever is load shifting. The day view shows generation and nothing about export or import, so it informs but cannot prompt. If the meter can supply `grid_w`, "export 1.9kW" (red on import) is the number that triggers "run the dishwasher now". Without it, the "now" hero is half an answer.

## Where they converge

1. The preview is not the panel (T1, K6). Both lenses audit the rendered output; the rendered output is the quantised one, and it loses the night hero's unit.
2. The current-hour and today markers (T2, K5). Honesty and attention want the same thing: a yellow band that marks the column regardless of the bar's height, with the measured energy in black on top.
3. A reference for today (T8, K1, K3). Tufte wants the comparison adjacent as an outline profile; Knaflic wants it stated in a sentence. Both need the same exporter key (yesterday's hourly profile, or the forecast).
4. Night redundancy (T5, K4). One 7-day chart with the best-30d reference line does the work of the tile, the meter, and the chart, and the space it frees is where the forecast goes.
5. Fixed scales and consistent colour (T3, K5). On a display the reader sees once every ten minutes, the same mark must mean the same thing across refreshes.

## Where they pull apart

1. Grid voltage. Tufte keeps it; it is measured, it is causal (voltage rise from export leads to curtailment), and he would sparkline it. Knaflic cuts it; the reader cannot act on 247 and it steals the second glance. Resolution: keep the number at regular weight in the lean-in tier, and let an alert promote it to bold red in the glance tier.
2. The title. Tufte would give the 16 px to the chart; Knaflic wants the sentence. Resolution: the sentence, because the hourly chart is already at the resolution its data supports (0.1 kWh per pixel) and the panel has no sentence anywhere.
3. The sparkline. Tufte wants more of them, scaled (the ratio, the voltage). Knaflic says a 55 x 12 px unscaled wiggle says nothing to this reader at one metre; cut it or replace it with the number. Resolution: replace raw irradiance with the ratio number (T4); a scaled ratio sparkline can stay as lean-in detail.
4. Density. Tufte wants yesterday's outline, a 30-day strip at night, hourly ticks. Knaflic wants three glanceable things and no more. Resolution through the two tiers: additions must sit below 5 arcmin and must not change the silhouette the glance reads.
5. Which number is the hero. Tufte is indifferent; Knaflic asks which number drives the action. "Now" is right for load shifting only if there is something to compare it with (K9). Without export data, "today so far against a reference" is the hero and "now" is a tile. The README chose "now"; that choice should be tied to whether `grid_w` is available.

## Verdict

The design is already disciplined for the medium: two views, one accent, red reserved for faults, direct labels instead of axes, no gauges. What it lacks is a reference for the day and a rendering path that survives the panel. Three changes:

1. Make the pixels honest. `d.fontmode = "1"` in `render()`, a full-height yellow band for the current or today column with the measured bar in black on top, and fixed scales (`max` on the chart, `min`/`max` on the spark). Fixes T1, T2, T3, K5, K6.
2. Give the day a reference and say it. The exporter emits yesterday's hourly profile or the forecast; the header becomes the sentence ("4.5 kWh, ahead of yesterday"); the profile goes behind the bars as a 1 px outline. Fixes K1, K3, T8.
3. Rebuild the night view around one chart. Best-30d as a reference line on the 7-day columns, drop the meter and the Best tile, and use the space for "vs sun" and "Tomorrow ~N kWh". Fixes T5, K4, K7.
