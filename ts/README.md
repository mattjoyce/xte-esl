# TypeScript port

Codec and BLE uploader for XTE shelf labels, written from `docs/protocol.md`.
Passes every vector in `testdata/reference.json`: the 12 vendor-generated
ones plus the portrait push shape and the observed response frames.

```sh
bun install
bun run test        # build, conformance against ../testdata, unit tests
```

Exports (`@xte-esl/sdk`): `encodePsj213` (250x122 landscape in, container
out, rotation included), `encodeContainer`, `packPixels`, `encodeRle`,
`allocate`, `verify`, `refresh`, `applyFirmware`, `dataPackets`,
`splitWrites`, `parseResponse`, `missingPackets`, `parseAdvertisement`,
`addressFromName`, and `uploadContainer` over a `BleTransport`.
`@xte-esl/sdk/web-bluetooth` provides that transport for Chrome.

Known divergence from the spec: `missingPackets` throws on a bitmap shorter
than the packet count (spec 6.4 step 5 says count those packets as
missing). Both behaviours are loud; the Python port pads.

Hardware check, 2026-09-07: `uploadContainer` drove a PSJ-213 end to end
(alloc `FF`, refresh `FF`, image correct) through `tools/push-hardware.mjs`,
which implements `BleTransport` over `tools/bleak-bridge.py` so the radio is
bleak and everything protocol-level is this code:

```sh
node tools/push-hardware.mjs 9F:1D:00:0B:33:36 image.rgb   # raw 250x122 RGB bytes
```

The Web Bluetooth transport was verified the same day from Chrome on an
Android phone through `web/index.html`.
