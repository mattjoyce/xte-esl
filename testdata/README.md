# Reference vectors

`reference.json` is the conformance suite for every codec port. A port that
reproduces these bytes exactly is correct. Nothing else needs the vendor app.

## The vectors are not a real push

The first-generation vectors pack rows of 250 pixels, because they were
made from landscape images before the panel geometry was known. A real
PSJ-213 push packs rows of 122 pixels in a 122x250 portrait buffer
(protocol.md §8.1). A port that passes only the first-generation vectors
and then sends a landscape image will display diagonal shear. The
`portrait` vector exists to catch that: pass it too.

## Provenance

| generation | vectors | produced by |
|---|---|---|
| first | `container`, `container_raw`, `container_bands`, `alloc`, `alloc_batch`, `verify`, `refresh1`, `refresh2`, `ota`, `packets` | the vendor application's own encoder, run on the two synthetic images below. Ground truth for the wire format. |
| second | `portrait`, `rle_tie`, `responses` | `python/xte.py` (itself verified against the first generation) and frames observed from a PSJ-213. |

The vendor code is not in this repository and cannot be re-run from it. The
inputs are described below well enough to regenerate them; a port that
matches the stored bytes has matched the vendor.

## Fields

| field | what |
|---|---|
| `w`, `h` | 250, 122. Source size of the first-generation images. |
| `palette` | six RGB triples: white, yellow, red, black, dark grey `(17,34,51)`, near-white `(255,255,254)` |
| `pixels` | `w*h` characters, each a palette index, row-major. The noise image. |
| `pixels_bands` | same shape. The bands image. |
| `container` | XTEK container for `pixels`. RLE attempted, falls back to raw. |
| `container_raw` | XTEK container for `pixels` with compression forced off |
| `container_bands` | XTEK container for `pixels_bands`. RLE chosen. |
| `alloc` | command `01` for `len(container)` bytes |
| `alloc_batch` | command `01`, 19-byte form, total 300000, offset 204800, length 95200 |
| `verify`, `refresh1`, `refresh2`, `ota` | commands `02`, `04` single screen, `04` multi-screen, `05` |
| `packets` | data packets `0`, `3` and the last one for `container`, each as its list of ≤244-byte BLE writes |
| `portrait` | `{w: 122, h: 250, palette, pixels, container}`. The real push shape. |
| `rle_tie` | `{w: 16, h: 1, packed, container}`. RLE output equals raw length; RLE must win. |
| `responses` | observed notifications, hex: `alloc_ok`, `refresh_ok`. `responses_decoded` gives `[cmd, status]` for each. |

Palette indices 4 and 5 are off-palette colours. The codec must pack them
as black. Near-white is not white.

## How the inputs were made

Noise image (`pixels`): for each pixel in row-major order, a linear
congruential generator `seed = (seed * 1103515245 + 12345) mod 2^31`,
starting at 12345, picks palette index `(seed >> 16) mod 6`. Every seventh
row (row index divisible by 7) is overwritten with white. The RLE output
for this image is longer than raw, so the encoder falls back.

Bands image (`pixels_bands`): white background; rows 20 to 39 red; rows 60
to 69 yellow for columns 0 to 99; otherwise every column divisible by 50 is
black.

Portrait image (`portrait.pixels`): 122 wide, 250 tall, in buffer
coordinates. White background; rows 10 to 39 red; rows 200 to 239 yellow for
columns 0 to 59; otherwise every column divisible by 30 and every row
divisible by 50 is black; column 121 on odd rows is the off-palette dark
grey, which must pack as black.

## Running

```
python/xte.py            # Python port: 12 first-generation vectors, then the second generation, then precondition checks
```

Go and TypeScript ports should ship an equivalent `selftest` that loads this
file, checks every field above, and exits non-zero on any mismatch.
