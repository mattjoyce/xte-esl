# Reference vectors

`reference.json` is the conformance suite for every codec port. A port that
reproduces these bytes exactly is correct; nothing else needs the vendor app.

Provenance: the vectors were produced by running the vendor's own encoder
(from the Android app) on two synthetic images, so they are ground truth for
the wire format. The vendor code itself is not in this repository.

## Fields

| field | what |
|---|---|
| `w`, `h` | 250, 122. Landscape source size used for the vectors. Note the vectors pack rows of `w` pixels; a real PSJ-213 push rotates to 122x250 first (see `docs/protocol.md`). |
| `palette` | six RGB triples |
| `pixels` | `w*h` characters, each a palette index, row-major. Noisy image, incompressible |
| `pixels_bands` | same shape, flat bands, compresses well |
| `container` | XTEK container for `pixels` (RLE attempted, falls back to raw) |
| `container_raw` | XTEK container for `pixels` with compression forced off |
| `container_bands` | XTEK container for `pixels_bands`, RLE chosen |
| `alloc` | command 0x01 for `len(container)` bytes |
| `alloc_batch` | command 0x01 batch form for total 300000, offset 204800, length 95200 |
| `verify`, `refresh1`, `refresh2`, `ota` | commands 0x02, 0x04 (1 screen), 0x04 (2 screens), 0x05 |
| `packets` | data packets `0`, `3` and the last one for `container`, each as the list of ≤244-byte BLE writes |

Palette indices 4 and 5 are off-palette colours (dark grey, near-white).
The codec must map them to black; near-white is *not* white.

## Running

```
python/xte.py            # Python port
```

Go and TypeScript ports should ship an equivalent `selftest` that loads this
file and checks the same fields.
