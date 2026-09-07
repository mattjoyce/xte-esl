# Poshiji PSJ-213 BLE price tag — reconnaissance

## Where this stands

**The application protocol is recovered.** On 2026-09-07 the supplier's own
operation manual turned up (`references/poshiji-esl-operation-manual.pdf`). Its
download QR code led to the Android APK, which is a WeChat mini-program in a
wrapper, which means the BLE code is plain JavaScript. Everything the tag
speaks is now written down in [`docs/protocol.md`](docs/protocol.md), and
`python/xte.py` reproduces the vendor's frames byte for byte (verified against
the vendor JS itself, `references/mkref.js`).

**Image push works.** First run of `python/push.py`, 2026-09-07, 250x122,
RLE, unbound tag, straight from a cold advertise:

```
[  2.514s] -> alloc 4242 B, 4 packets
[  2.603s] <- 58 54 45 04 09 bd 01 ff ...     alloc OK
[  4.026s] sent 4 packets
[  4.126s] -> refresh
[  5.888s] <- 58 54 45 04 08 03 04 ff ...     refresh OK
```

So the tag accepts a push while unprovisioned; no binding handshake needed.
The response frames carry `04` at byte 3 and a length at byte 4, i.e. the
tag's own frame type for replies. Bleak reported MTU 23 on that run and
pushed with 20-byte writes, which the tag tolerated; the script now asks
BlueZ for the negotiated MTU. Second run: MTU 517, 244-byte writes, all four
packets in 0.1 s, refresh acknowledged 60 ms later, 2.5 s connect-to-done.

First two pushes came out as diagonal shear: the tag wants a portrait
122x250 buffer (31-byte rows), not landscape 250x122 (63-byte rows). Solved
from the shear slopes in two photos, then confirmed: `--rotate 90` (now the
default) puts a landscape picture on the screen the right way up. Details in
`docs/protocol.md`. The flicker during refresh is the four-colour waveform,
normal.

SWD work is parked. It is no longer on the critical path; keep it for owning
the hardware later. **Standing rule still applies: do not mass-erase.**

---

## The vendor app

Chain of custody, so it can be repeated:

| step | where |
|---|---|
| Manual | `references/poshiji-esl-operation-manual.pdf`, "POSHIJI ESL Management System", V1.0, March 2026, author "Eva", WPS |
| Web admin | https://esl.pos.cn/#/account/login |
| App download page (QR on p.27) | https://esl.ttdh.cc/esl_download_app.html |
| APK | http://down.app.jsjpos.com/softupdate/android-phone-esl.apk (110 MB, kept at `references/android-phone-esl.apk`) |
| iOS | App Store, "POSHIJI ESL Management System" |
| Integration | "Kemai Yunfan" backend (科脉云帆, a large Chinese POS software vendor) |

The APK is Tencent's Donut / WMPF runtime (`com.tencent.luggage`,
`com.tencent.wmpf`) carrying an embedded mini-program,
`assets/SaaA_embed/release_2_wxbfaacbea03c4b388_(__APP__).wxapkg`, built
2026-09-03. `references/unwxapkg.py` unpacks it; `references/miniapp/` is the result,
`references/src/` the beautified modules that matter:

- `utils/bluetoothUtil.js` — transport, advert parser, service/char selection
- `utils/commandManager.js` — command and data frames
- `utils/dataSender.js` — the push state machine, batches, patch loop
- `utils/picUtils.js` — pixel packing and RLE, the `XTEK` container
- `utils/chromaink.js` — the SDK facade; `chromaink` is the vendor SDK's name

The advert parser reads our tag exactly and settles two of the unknown bytes:
`06` is `chipType 0` (high nibble) and `sendPower 6` (low nibble). Hardware
rev, firmware 4.0.2, type 140 and battery decode as the notes already had
them. Bytes `01 02 ff ff 1c` are not read by the app at all.

The app talks the same pipe we already had (service `...2760...1001`, first
write char, first notify char, MTU 247, 244-byte writes at 5 ms). No base
station involvement for an image push: the phone does it directly.

Manual's model table names the family: `ESL-21BWRY` for 2.13" BWRY,
alongside 1.54 / 2.66 / 2.9 / 3.5 / 3.7 and an `ESL-21MBW` freezer variant.

---

## Identity

Label reads **Poshiji PSJ-213**, `213` being the panel size in inches.

`"PSJ-213"` and `"poshiji"` return nothing relevant anywhere — not in product
listings, retail sites or ESL vendor catalogues. White-label goods.

### Supplier: Guangzhou Jiashangjia Intelligent Technology Co., Ltd. (JSJ)

Founded 2018, Tianhe District, Guangzhou. Storefronts:
[Alibaba](https://jsjtech.en.alibaba.com/) ·
[Made-in-China](https://jsjpos.en.made-in-china.com/) ·
[LinkedIn](https://www.linkedin.com/company/guangzhou-jiashangjia-intelligent-technology-co-ltd).
Sales contact listed as "Miss Julie", Floor 2-4, No. 25 West Guangtang Road.

They are overwhelmingly a **POS company** — touch terminals, AI POS scales,
kiosks, scanners, cash drawers. ESL appears in their category list but not in
their actual catalogue, and `PSJ-213` appears nowhere. So the tag is a
rebadged OEM product carrying JSJ's "Poshiji" brand, not their design.

The useful consequence: **there is a human to ask.** Chinese suppliers
routinely email an APK on request. This is the highest-probability route to a
reference implementation and costs one message.

*Update 2026-09-07:* it did not even need the message. The manual arrived, and
the APK is on JSJ's own domain (`down.app.jsjpos.com`). See "The vendor app".

### Radio identity

| | |
|---|---|
| Address | `9F:1D:00:0B:33:36` (declared public) |
| Advertised name | `36330B001D9F` — the MAC in reverse byte order |
| Pairing | none; connects open, no bonding |

Two details say "generic firmware, not a serious vendor":

- The address is declared *public*, which should mean IEEE-assigned, but
  `0x9F` = `1001 1111` has both the U/L bit (`0x02`) and the I/G bit (`0x01`)
  set — locally administered *and* group. Not a real OUI, so no vendor to
  look up.
- Manufacturer ID `0x5258` is **not registered**. The Bluetooth SIG's
  [assigned company identifiers](https://bitbucket.org/bluetooth-SIG/public/raw/main/assigned_numbers/company_identifiers/company_identifiers.yaml)
  top out around `0x10FB`; `0x5258` is far outside the allocated range, i.e.
  fabricated. (ASCII `RX`, or `XR` in wire order.)

---

## What the tag says about itself

Three independent self-descriptions — NFC, the display, and the advertisement
— which together break the advertising payload.

### NFC (NDEF Well Known, type `T`, 40 bytes)

```
36330B001D9F,140,122,250,BWRY,0,0,0,0,CN
```

| field | value | meaning |
|---|---|---|
| 1 | `36330B001D9F` | MAC, reversed — same as the BLE name |
| 2 | `140` | tag type code (`0x8C`) |
| 3 | `122` | height, px |
| 4 | `250` | width, px |
| 5 | `BWRY` | 4-colour panel: black / white / red / yellow |
| 6-9 | `0,0,0,0` | unset — provisioning slots? |
| 10 | `CN` | region |

So the panel is **250 x 122, four-colour BWRY** — confirmed, not inferred.
At 2 bpp that is 7625 bytes of framebuffer, which sets the scale of any image
push.

### Self-test screen (`hardware/self-test-screen.jpg`)

The display currently shows a factory test pattern: BWRY colour bars proving
all four inks, a barcode, and

```
36330B001D9F
2.13 H:2 V:4.0.2 B:80%
```

i.e. 2.13", hardware rev 2, firmware 4.0.2, battery 80% at test time.

### Advertising payload, decoded

Two payloads alternate (ADV + scan response) under manufacturer ID `0x5258`:

```
mfr[0x5258] = ff 01
mfr[0x5258] = fd 02 40 02 00 8c 63 06 01 02 ff ff 1c
```

The 13-byte one, using NFC and the screen as cribs:

```
        fd  02  40  02  00  8c  63  06  01  02  ff  ff  1c
        |   |   \___/   \____/   |   \________/  \____/  |
        |   |     |        |     |        |         |    `- 0x1c = 28, temperature?
        |   |     |        |     |        |         `------ unset — store/group ID?
        |   |     |        |     |        `---------------- ?
        |   |     |        |     `------------------------- 0x63 = 99, battery %
        |   |     |        `------------------------------- 0x008c = 140, tag type
        |   |     `---------------------------------------- V:4.0.2 (BCD 0x40 -> "4.0", then .2)
        |   `---------------------------------------------- H:2, hardware rev
        `-------------------------------------------------- record marker
```

Three fields are cross-confirmed rather than guessed: `0x02` matches `H:2` on
screen, `0x40 0x02` reads as BCD `4.0` + `.2` against `V:4.0.2` on screen, and
`0x008c` = 140 matches the NFC tag-type field exactly.

Battery at `0x63` = 99% is a fresh-cells reading; the 80% on screen is stale,
printed at factory test. `ff ff` in an otherwise-populated frame reads like an
unprovisioned store or group ID — the sort of field a base station assigns.

Still unknown: bytes 7-9 (`06 01 02`), and whether `0x1c` is really
temperature. `python/scan.py` across a warm/cold cycle would settle the latter.

### Full NFC memory dump

`hardware/nfc-export.hex`, Intel HEX, 1576 bytes, `0x000-0x627`. Parses as a
standard NFC Forum Type 2 tag:

```
page 0: 04 b1 52 0a     UID0-2 + BCC0
page 1: 44 02 69 00     UID3-6
page 2: 44 00 ff ff     BCC1, internal, lock0, lock1
page 3: e1 10 ea 00     Capability Container
0x010:  03 2c d1 01 28 54 ...  NDEF TLV
```

**1. The NDEF Text record is malformed.** Header `0xD1` = TNF 1 (Well Known),
type `'T'`, payload length `0x28` = 40 — and the payload is 40 bytes of raw
ASCII. A conformant Text record *must* begin with a status byte and a language
code. A standard parser reads the first byte `'3'` (0x33) as the status byte,
takes the low 6 bits as a language length of 51, and overruns the 40-byte
payload immediately. So **no conformant NDEF parser can read this tag** — the
vendor app must pull the payload as a raw string. The firmware rolls its own
NFC encoding.

**2. The tag is 2K-class, which implies NFC-to-MCU wiring.** CC byte 2 is
`0xEA` = 234, so 234x8 = **1872 bytes** of data area — far larger than
NTAG213/215/216 (the 216 tops out at 872), and consistent with an
**NTAG I2C plus 2K**. If so, the NFC chip has an I2C side wired to the MCU,
which is how the firmware writes its own geometry string into NFC memory and
why that string carries live values rather than factory constants. Inferred
from CC arithmetic, not confirmed against a part marking.

**3. The duplicate at 0x400 is a dumping artifact.** Bytes `0x000-0x03F` are
byte-identical to `0x400-0x43F`, and nothing is non-zero past `0x43E`.
NTAG I2C 2K addresses memory as two 1K sectors; reading past sector 0 without
issuing SECTOR SELECT wraps and re-reads sector 0. No hidden second copy.

**4. Treat pages 0-2 with suspicion.** Neither checksum validates: BCC0 should
be `0x88^04^b1^52` = `0x6F` but reads `0x0A`; BCC1 should be `44^02^69^00` =
`0x2F` but reads `0x44`. Likeliest explanation is that the exporting app
synthesised those pages from Android's `getId()` rather than reading them,
since Android does not reliably expose them. Which matters because page 2
appears to show static lock bytes `ff ff` — NDEF locked read-only. **Do not
trust that either way**; test empirically if rewriting NFC ever matters.

---

## BLE interface

```
00001801  Generic Attribute Profile
  00002a05  indicate    Service Changed
  00002b29  read,write  Client Supported Features
  00002b2a  read        Database Hash
00002760-08c2-11e1-9073-0e8ac72e1001   <- vendor service
  ...0001  write-without-response       host -> tag
  ...0002  notify                       tag  -> host
```

No Device Information service, no Battery service. The vendor service is the
whole interface.

### What that UUID means

`xxxx2760-08C2-11E1-9073-0E8AC72Exxxx` is the **Arm Ltd. proprietary UUID
base** from the Arm Cordio / packetcraft BLE host stack
([`att_uuid.h`](https://github.com/packetcraft-inc/stacks/blob/main/ble-host/include/att_uuid.h)):

```c
/*! \brief Base UUID:  E0262760-08C2-11E1-9073-0E8AC72EXXXX */
#define ATT_UUID_ARM_BASE  0x2E, 0xC7, 0x8A, 0x0E, ...
#define ATT_UUID_P1_SERVICE_PART  0x1001   /* proprietary service P1 */
#define ATT_UUID_D1_DATA_PART     0x0001   /* proprietary data char D1 */
```

This tag zeroes the leading `E026`, but is otherwise the stock Cordio
"proprietary service P1" from the `dats`/`datc` data-transfer sample — a
**transparent byte pipe**, the Cordio equivalent of Nordic UART Service.

Consequence: the UUIDs identify the *stack*, not the *product*. No framing, no
command registry, nothing self-describing. The whole application protocol
rides opaquely on those two characteristics and has to be learned from
traffic — which is why a reference implementation matters so much.

---

## Hardware

Back cover pops off. Inside: 2x CR2450 coin cells, no part markings visible,
no further disassembly without force, and 4 exposed pads.

**Battery: the two CR2450s are in parallel.** With only one cell fitted the
rails still sit at 3 V, which a series pair could not do (a missing cell would
open the circuit). So 3 V nominal at roughly 1200 mAh, and **3 V is the logic
level** for anything connected to the pads.

Mechanical note: the second cell physically covers the pad header, so any
cells-in measurement or probe hookup has to run on one cell — which works,
given the parallel wiring.

### Debug header — confirmed SWD

Labelling the pads A-D along the header, measured with one cell fitted, black
probe on A:

| pad | reading | conclusion |
|---|---|---|
| A | 0 V (reference) | **GND** |
| B | **3 V** | **SWDIO** — internal pull-up |
| C | **0 V** | **SWCLK** — internal pull-down |
| D | +3 V | **VCC** |

```
      A       B        C        D
     GND    SWDIO    SWCLK     VCC      3 V logic
```

One line parked high and one parked low is the Cortex-M debug-port signature.
I2C would idle both lines high; UART would idle TX high with RX floating.
Neither matches.

Measurement notes worth keeping, since two of them cost time:

- **Internal pulls only exist under power.** A cells-out resistance test sees
  external components only, and cannot distinguish SWD from UART. Cells out,
  both signal pads read ~2.4 MΩ to GND — meter leakage, i.e. no external
  pull-downs. Useful, but not the answer.
- **Rail-to-rail resistance is meaningless here.** A→D starts near 800 Ω and
  climbs to ~1.2 MΩ: that is the meter charging the board's decoupling
  capacitance, not a resistance. Ignore it.

### SWD works — but only during the power-on window

**`DPIDR = 0x0BB11477`**, captured on the 4th attempt of a hammer loop while
the coin cell was reseated.

| field | value | meaning |
|---|---|---|
| bit 0 | 1 | valid |
| designer `[11:1]` | `0x23B` | **ARM Ltd** (JEP106) |
| partno `[27:12]` | `0xBB11` | Cortex-M0 / M0+ class SW-DP |
| version `[31:28]` | 0 | ADIv5 |

So the pads really are SWD, the bit-bang host works, and the target is a
**Cortex-M0-class** part. Note this sits awkwardly with the Ambiq guess below —
Apollo3/4 are Cortex-M4. Treat the silicon as open until CPUID is read.

**The catch: firmware disables the debug port shortly after boot.** With the
tag running, the port is completely silent — 12500+ connect attempts, no
response, at clock rates from 100 kHz down to 12.5 kHz, in both pin orders.
Immediately after power-on it answers. That is why the first `identify()`
after a successful hammer also failed: it reconnected from scratch and by then
the window had shut.

Consequences for tooling:

1. On a successful DPIDR the session must be used **immediately** — no
   reconnect. `hammer()` now calls `postConnect()` directly.
2. The first thing to do inside the window is **halt the core** (write
   `0xA05F0003` to DHCSR at `0xE000EDF0`). That stops firmware before it can
   shut SWD down and holds the session open. Debug-register write only: no
   flash access, fully undone by a power cycle.
3. Manual cell-reseating is a lottery. The reliable fix is to **power the tag
   from a GPIO** so the ESP32 can cut and restore power in sync with the
   connect attempt — a proper connect-under-reset.

### FULL DEBUG ACCESS ACHIEVED — the target is a Cortex-M0

Complete successful session:

```
DPIDR     = 0x0BB11477   ARM SW-DP (designer 0x23B)
CTRL/STAT = 0xF0000000   debug domain powered
DHCSR     = 0x03030003   C_DEBUGEN|C_HALT set, S_HALT set -> CORE HALTED
AP0 IDR   = 0x04770021   class 8 MEM-AP, type 1 AMBA-AHB, designer 0x23B
CPUID     = 0x410CC200   implementer ARM, partno 0xC20 -> Cortex-M0, r0p0
ROM PID0/PID1 = 0x71/0xB4 -> part 0x471, the Cortex-M0 ROM table
```

**The core halts, and MEM-AP reads work.** Once halted, firmware cannot run
and therefore cannot close the debug window — the session is stable for as
long as power and the probes hold.

**Ambiq is ruled out** (Apollo3/4 are Cortex-M4). A Cortex-M0 running a Cordio
stack points elsewhere; candidates worth checking against the memory map
include Dialog DA1458x and Nordic nRF51, both Cortex-M0 BLE parts. Note the AP
scan found *only* AP0 — an nRF51 would normally also expose AP1 (CTRL-AP),
which is evidence against Nordic. Reading the vector table and probing the
memory map will settle it.

### Reproducing the session — the open problem

Full access has been achieved **once**. Every attempt since has failed, and
the difference is worth understanding before the next session.

**What worked, exactly:** orange (tag VCC) was on a real GPIO. The ESP32 was
reflashed, which left that GPIO as an input for the ~30 s of compile-and-flash
— long enough for the board capacitance to drain completely. The sketch then
booted with auto-probe already hammering, and `v` drove the GPIO high,
producing a clean cold boot into a running clock. Caught on the first dot.

**Why the retries failed:** the tag's rail holds charge for a very long time —
measured **still high after 60 s** against the ESP32's ~45 kΩ internal
pulldown. So briefly tapping the power wire never actually resets the MCU;
it just browses out and keeps running. No cold boot, no window. Repeated fast
taps are strictly worse than one properly dead cycle.

Hand-inserting a wire into a 3V3 hole is also a poor power switch: contact
bounce on insertion gives a ragged brown-out rather than a clean rising edge,
which is not the condition that worked.

**The fix for next time: drive the tag's VCC from a real GPIO again.** That
gives a clean, software-timed edge and lets `p` (power-cycle connect) do the
whole thing unattended. It failed this session only because the hole we used
turned out not to be a GPIO at all.

### Breadboard mapping — do not trust the derived map

The ESP32 board is **not a stock ESP32-C5-DevKitC-1**. It is an
ESP32-C5-WROOM-1 (`16R8` sticker: 16 MB flash, 8 MB PSRAM) on a third-party
carrier that has `vbatt` pins — which no Espressif reference board does. So
`hardware/esp32-c5-devkitc-1-pinout.md` does **not** describe the header order,
and the row arithmetic derived from it produced a wrong answer: `A12` was
predicted to be GPIO23 and measured 3.3 V, silently powering the tag from a
rail for an entire test run.

Only these holes are established by measurement:

| hole | is | how known |
|---|---|---|
| `A8` | GPIO5 | proven — SWDIO, carried a real DPIDR |
| `A9` | GPIO4 | proven — SWCLK |
| `A2`, `A16` | GND | measured |
| `I16` | 3V3 | measured |
| `A12` | 3.3 V (not a GPIO) | measured |

**First job next session:** find a genuine GPIO hole empirically rather than
by arithmetic — drive a known pin as a 1 Hz square wave and probe the header
until a hole swings 0↔3.3 V. The 3V3 pin sits steady, so only the GPIO moves.
Then wire tag VCC to it and `p` should connect unattended.

### The working procedure

What finally worked, and why the earlier attempts did not:

1. **Power the tag from the ESP32** (GPIO23 to the battery holder's positive
   contact, cell removed) so power-on can be synchronised with the connect
   attempt. Hand-reseating a coin cell is a lottery, and the holder clasp
   makes it worse.
2. **Have auto-probe already running**, then bring VCC up. The probe catches
   the debug port within its boot window automatically.
3. **Halt immediately** on connection. That is what makes the session stable
   rather than momentary.

Two traps that cost real time:

- **A negative result is meaningless if the target never booted.** 25 clean
  power cycles returned nothing — because the tag was not actually powering up
  from the GPIO at that point. Verified by BLE scan: no advertisements. Always
  confirm the target is alive before trusting a failure.
- **Contact bounce fabricates plausible garbage.** An early run reported
  `DPIDR = 0x00000002` as a hit. A real ARM DPIDR always has bit 0 set and
  designer `0x23B`; the validator now checks both, requires a matching
  confirming re-read, and rejects any transfer that flagged a parity error.

Mechanically: **jam the GND and VCC wires into the battery holder metal.**
Those contacts are large and forgiving, which leaves only the two signal
probes to hold by hand.

### Silicon hypothesis — Ambiq Apollo (superseded, see above)

The GitHub code search for the Cordio UUID base hit `atc1441/ATCmiBand8fw`
under `Custom_Firmware/ambiq_ble/services/` — Ambiq's BLE SDK, as shipped on
the Mi Band 8. Ambiq licenses Cordio and ships exactly this UUID base and the
same P1/D1 pipe.

So the likely SoC is an **Ambiq Apollo3/4 Blue**, or another Cordio licensee
(NXP, Analog Devices MAX326xx). Hypothesis from the stack fingerprint only.
**The SWD IDCODE read settles it** — that is the point of the next step.

---

## What this is *not*

**Not Gicisky / PICKSMART.** Those advertise GATT service `0xFEF0` with
characteristics `0xFEF1`/`0xFEF2`, and are already reverse-engineered:
[atc1441/ATC_GICISKY_ESL](https://github.com/atc1441/ATC_GICISKY_ESL) +
[web uploader](https://atc1441.github.io/ATC_GICISKY_Paper_Image_Upload.html) ·
[eigger/hass-gicisky](https://github.com/eigger/hass-gicisky) ·
[fpoli/gicisky-tag](https://github.com/fpoli/gicisky-tag).

Their code won't work here, but their *shape* is a good prior: a small command
channel (start / send-size / send-block / refresh), image pushed in chunks,
progress reported over notify.

**Not Realtek.** [`atc1441/ATC_RTL_BLE_OEPL`](https://github.com/atc1441/ATC_RTL_BLE_OEPL)
targets RTL8762ESL / RTL8752HJL BLE ESLs including BWRY panels — a tempting
match. Cloned and grepped the whole tree: no occurrence of `2760`, `08c2` or
`0e8ac72e`. Realtek ships its own BLE stack, not Cordio. Still the closest
prior art for custom firmware on a BWRY BLE tag.

**Not Dahua.** Ruled out by the label. Kept because the architecture was
instructive: their [`DHI-ESL-AP-A`](https://manuals.plus/dahua/dhi-esl-ap-a-electronic-shelf-label-ap-station-manual)
base station is a Bluetooth/WiFi AP with 4 BLE radios running a "BLE Private
Protocol" — which confirms the general principle that an ESL base station is a
**BLE proxy, not a second radio channel**. Whatever a gateway does to a tag
like this, it does over the same pipe we already have. A gateway is a missing
reference implementation, not a missing capability.

Broader prior art on ESL security:
[SEC Consult, "Blackmail Roulette"](https://sec-consult.com/blog/detail/blackmail-roulette-the-risks-of-electronic-shelf-labels-for-retail-and-critical-infrastructure/)
and [furrtek on IR-based ESLs](https://www.furrtek.org/index.php?a=esl).

---

## Tools

```sh
.venv/bin/python python/scan.py -a 9F:1D:00:0B:33:36 -t 120   # watch adv data
.venv/bin/python python/probe.py 9F:1D:00:0B:33:36            # interactive GATT shell
```

`scan.py` prints only when an advertising payload actually changes, so it can
be left running to catch battery decay or a temperature swing. `probe.py`
subscribes to the notify characteristic and takes hex at a prompt to write to
the data-in characteristic, timestamping both directions — a session doubles
as a capture.

Bleak resolves an address through its scan cache, so the tag must be
*disconnected* (and therefore advertising) before either tool can reach it:

```sh
bluetoothctl disconnect 9F:1D:00:0B:33:36
```

`pyocd` 0.45.1 is installed in the venv, ready for the SWD step.

### Getting an SWD probe

No dedicated probe is attached. Currently on USB: an **ESP32 with native USB**
(`303a:1001`, `ttyACM0`) and a CH343-class serial adapter.

- **ESP32-S2 / S3** → flash [`esp-usb-bridge`](https://github.com/espressif/esp-usb-bridge)
  and it enumerates as a CMSIS-DAP probe pyOCD talks to natively. Zero cost.
  *Which ESP32 it is has not been checked* — resetting it would have
  interrupted whatever it is currently doing.
- **C3 / C6 / H2** → not supported by `esp-usb-bridge`. A Raspberry Pi Pico
  with `debugprobe` firmware (~$5) or an ST-Link V2 clone (~$3) is less pain
  than a bit-banged SWD sketch.

Hookup — no level shifting, both sides 3.3 V. Leave one cell in to power the
tag rather than back-feeding from the probe:

```
probe GND   -> pad A
probe SWDIO -> pad B
probe SWCLK -> pad C
```

```sh
.venv/bin/pyocd list                # probe visible?
.venv/bin/pyocd cmd -t cortex_m     # connect, read the DP IDCODE
```

Pure read; touches no flash. Two outcomes, both informative: the port is
locked and we learn readout protection is set, or it enumerates and we get a
part number — and then the question becomes whether flash is readable.

---

## Open questions

- Advertising bytes `01 02 ff ff 1c` — still unexplained; the app ignores them.
- Is `0x1c` temperature? Watch it across a warm/cold cycle.
- Is the NFC memory actually write-locked? The dump says yes but the dump's
  page 2 is untrustworthy.
- What is the SoC? SWD says Cortex-M0; CPUID read once. No longer blocking.

Answered 2026-09-07:

- ~~Does `python/push.py` put an image on the screen?~~ Yes. Portrait 122x250 buffer, rotate 90.
- ~~What is the application protocol?~~ `docs/protocol.md`.
- ~~Does the supplier have an APK?~~ Yes, public download.
- ~~Is the debug port locked?~~ No, it closes shortly after boot; halt-on-connect holds it.
