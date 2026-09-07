# TypeScript SDK

Dependency-free ESM codec and BLE image uploader for XTE shelf labels.
The codec runs in Node, Bun, and browsers. The browser transport uses Web
Bluetooth; other environments supply a `BleTransport`.

## Build and install locally

From the repository root:

```sh
cd ts
bun install --frozen-lockfile
bun run test        # TypeScript build, reference vectors, unit tests
npm pack           # creates xte-esl-sdk-0.1.0.tgz
```

Install that tarball in your application with
`npm install /path/to/xte-esl/ts/xte-esl-sdk-0.1.0.tgz`.
The package includes JavaScript, TypeScript declarations, and source maps.
Bun is needed for development, not by SDK consumers.

## Encode an image

```ts
import { encodePsj213 } from '@xte-esl/sdk';

// A white 250×122 landscape image, in row-major RGB order.
const data = new Uint8Array(250 * 122 * 3).fill(255);
const container = encodePsj213({ width: 250, height: 122, channels: 3, data });
```

Draw using exact white, black, red (`FF0000`), and yellow (`FFFF00`).
Other RGB values become black. Quantise photographs and antialiased text
before encoding. RGBA input is supported with `channels: 4`, but alpha is
ignored: composite transparent images onto a background first.
`encodePsj213` handles the required counter-clockwise rotation and chooses
RLE only when it is no larger than the raw pixels. Pass `{ compress: false }`
as its second argument to disable compression.

For native buffer orientation, other geometries, or multiple image records,
use `encodeContainer([{ image, x: 0, y: 0 }])`. Four-colour packing is verified
on device 140; all other device numbers are rejected until their packing is
verified. Invalid codec inputs throw the exported `XteError` type.

## Push from a browser

Call device selection directly from a click on a secure page. This example
assumes a button with ID `push` and the `container` created above:

```ts
import { uploadContainer } from '@xte-esl/sdk';
import { requestWebBluetoothTransport } from '@xte-esl/sdk/web-bluetooth';

document.querySelector<HTMLButtonElement>('#push')!.onclick = async () => {
  try {
    const transport = await requestWebBluetoothTransport();
    await uploadContainer(transport, container);
    console.log('Image accepted; allow about 20 seconds for the panel to settle.');
  } catch (error) {
    console.error('Upload failed', error);
  }
};
```

An optional twelve-digit advertised name, such as `36330B001D9F`, narrows
the chooser to one tag. The default chooser filters manufacturer ID `0x5258`.
`WebBluetoothTransport` also accepts an already-selected device. It uses
20-byte writes by default because Web Bluetooth does not expose the MTU.
The working label editor in [`../web/`](../web/) is a complete example:

```sh
bun run web:serve   # from ts/; localhost:8765
```

## Upload lifecycle and custom transports

`uploadContainer(transport, container, options?)` allocates flash, sends
packets, patches missing packets, and requests refresh. It resolves when
the tag accepts refresh, before the display has settled. It disconnects on
success, failure, or cancellation and rejects concurrent uploads on the
same transport. Whole uploads are not retried automatically.

| Option | Default | Meaning |
|---|---|---|
| `signal` | none | `AbortSignal` for cancellation |
| `screens` | `1` | Screen count; values above one use the multi-screen command |
| `commandTimeoutMs` | `5000` | Bounds command replies, connection, writes, and cleanup |
| `patchTimeoutMs` | `300000` | Deadline for each recovery phase |
| `writeDelayMs` | `5` | Delay after each BLE write; use `0` for simulations |

Cancellation example: pass `{ signal: controller.signal }` where
`controller` is an `AbortController`, then call `controller.abort()`.
Each recovery phase allows at most three retransmissions. Missing bitmap
bits count as missing packets; a refresh reporting missing data with a
complete bitmap fails immediately.

To supply another BLE adapter, implement the exported `BleTransport`:

- `writeSize`: maximum write payload, from 1 to 244 bytes.
- `connect(onNotification, onDisconnect)`: resolve after enabling
  notifications; deliver each notification as a `Uint8Array` and report
  unexpected disconnects through the callback.
- `write(data)`: resolve when the adapter has accepted a write.
- `disconnect()`: close the connection, including one still being established.
  Ensure old writes cannot continue into a subsequent connection.

The codec also exports `packPixels`, `rotateCounterClockwise`, `encodeRle`,
`allocate`, `verify`, `refresh`, `dataPackets`, `splitWrites`, `parseResponse`,
`missingPackets`, `parseAdvertisement`, and `addressFromName`.
`parseAdvertisement` expects manufacturer data including the two company-ID
bytes. `applyFirmware` builds a command frame only; firmware updates are
not implemented.

## Validation and hardware status

Every vector in [`../testdata/reference.json`](../testdata/reference.json)
is checked byte for byte. Unit tests cover multi-batch transfers, recovery,
timeouts, cancellation, and browser transport cleanup. CI also runs the
conformance runner under Node and builds the browser example.

On 2026-09-07, `uploadContainer` drove a PSJ-213 end to end through the bleak
bridge below, and the browser transport was verified from Android Chrome
using `web/index.html`. Large transfers and packet recovery remain tested
with simulated transports only.

```sh
# From ts/, after building; requires repo-root .venv with bleak installed.
node tools/push-hardware.mjs 9F:1D:00:0B:33:36 image.rgb
# image.rgb: exactly 250×122×3 raw RGB bytes
```

Protocol reference: [`../docs/protocol.md`](../docs/protocol.md).
