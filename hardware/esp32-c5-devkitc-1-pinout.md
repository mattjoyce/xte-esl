# ESP32-C5-DevKitC-1 pin headers

Source: Espressif esp-dev-kits user guides —
[v1.2 (current)](https://docs.espressif.com/projects/esp-dev-kits/en/latest/esp32c5/esp32-c5-devkitc-1/user_guide.html) ·
[v1.1](https://docs.espressif.com/projects/esp-dev-kits/en/latest/esp32c5/esp32-c5-devkitc-1/user_guide_v1.1.html)

## The trap: GPIO4 and GPIO5 moved between revisions

Espressif changed the header assignments. Their note:

> For boards with the PW number of and after PW-2025-04-0446, J1 and J3
> functions are updated.

| | v1.1 | v1.2 |
|---|---|---|
| GPIO4 | **J1 pin 5** | **J3 pin 8** |
| GPIO5 | **J1 pin 6** | **J3 pin 9** |

Different header, opposite side of the board. Pinout images found by search
are frequently for the wrong revision.

**The silkscreen is authoritative** — the DevKitC-1 prints the GPIO number
next to each pin. Read the board, not a diagram.

## v1.2 (PW-2025-04-0446 and later)

| J1 | Name | | J3 | Name |
|---|---|---|---|---|
| 1 | 3V3 | | 1 | GND |
| 2 | RST | | 2 | TX / GPIO11 |
| 3 | GPIO2 *(strap)* | | 3 | RX / GPIO12 |
| 4 | GPIO3 | | 4 | GPIO24 |
| 5 | GPIO0 | | 5 | GPIO23 |
| 6 | GPIO1 | | 6 | NC / GPIO15 |
| 7 | GPIO6 | | 7 | GPIO27 *(strap)* |
| 8 | GPIO7 *(strap)* | | 8 | **GPIO4** |
| 9 | GPIO8 | | 9 | **GPIO5** |
| 10 | GPIO9 | | 10 | NC |
| 11 | GPIO10 | | 11 | GPIO28 *(strap)* |
| 12 | GPIO26 | | 12 | GND |
| 13 | GPIO25 *(strap)* | | 13 | GPIO14 *(USB D+)* |
| 14 | 5V | | 14 | GPIO13 *(USB D-)* |
| 15 | GND | | 15 | GND |
| 16 | NC | | 16 | NC |

## v1.1

| J1 | Name | | J3 | Name |
|---|---|---|---|---|
| 1 | 3V3 | | 1 | GND |
| 2 | RST | | 2 | TX / GPIO11 |
| 3 | GPIO2 *(strap)* | | 3 | RX / GPIO12 |
| 4 | GPIO3 | | 4 | GPIO24 |
| 5 | **GPIO4** | | 5 | GPIO23 |
| 6 | **GPIO5** | | 6 | NC / GPIO15 |
| 7 | GPIO0 | | 7 | GPIO10 |
| 8 | GPIO1 | | 8 | GPIO9 |
| 9 | GPIO27 *(strap)* | | 9 | GPIO8 |
| 10 | GPIO6 | | 10 | NC |
| 11 | GPIO7 *(strap)* | | 11 | GPIO28 *(strap)* |
| 12 | GPIO26 | | 12 | GND |
| 13 | GPIO25 *(strap)* | | 13 | GPIO14 *(USB D+)* |
| 14 | 5V | | 14 | GPIO13 *(USB D-)* |
| 15 | GND | | 15 | GND |
| 16 | NC | | 16 | NC |

## Pins to avoid

- **Strapping:** GPIO2, GPIO7, GPIO25, GPIO27, GPIO28 — sampled at reset;
  driving them can stop the board booting.
- **SPI flash / PSRAM:** GPIO16-22 — not broken out anyway.
- **USB-JTAG:** GPIO13, GPIO14 — repurposing these kills the USB console.

**Safe for arbitrary I/O:** 0, 1, 3, 4, 5, 6, 8, 9, 10, 11, 12, 15, 23, 24, 26
(11 and 12 are the UART console; fine if you are using USB CDC, which we are).

## Ground pins

Plenty available: J1 pin 15, and J3 pins 1, 12 and 15. Any of them works as
the common ground back to the tag — and a common ground is **required**, not
optional; SWD signals need a shared reference.
