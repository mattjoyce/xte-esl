# Go port

Not started. Reading order for whoever picks it up:

1. Run `python/xte.py` and read its output; that is the target.
2. Read `testdata/README.md`, then `docs/protocol.md` §7 (container, packing, RLE).
3. Implement §7 as a package with one error type, and a `selftest` command
   that loads `../testdata/reference.json` and reproduces every field byte for
   byte, exiting non-zero on any mismatch.
4. Then §6 (frames, response parsing with validation) and §6.4.
5. Only then the transport, via `tinygo.org/x/bluetooth`, following §8.2.

The Python module's public surface (listed in its docstring) is the shape to
mirror: `ImagePayload`, `DataPackets`, `BLEChunks`, the `Cmd*` builders,
`ParseResponse` returning a validated record with `MissingPackets(total)`.
