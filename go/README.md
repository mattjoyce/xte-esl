# Go SDK

A standard-library-only XTE image codec and BLE upload state machine, for
Go 1.22 or newer. Module: `github.com/mattjoyce/xte-esl/go`; package: `xte`.

The optional [`bluez/`](bluez/) module provides actual Bluetooth uploads on
Linux. Keeping it in a separate module means the core SDK has **zero
external dependencies**. BlueZ adds one direct external dependency,
`github.com/godbus/dbus/v5`, and one transitive dependency, `golang.org/x/sys`.
No Python, CGo, or TinyGo toolchain is required.

## Build and check

From the repository root:

```sh
cd go
go test -race ./...
go run ./cmd/selftest
```

The self-test loads `../testdata/reference.json` and checks all supplied
vectors, including portrait geometry, the RLE tie, and observed replies.
It reports 25 checks because each BLE write in the packet vectors is
compared separately. `-vectors /path/to/reference.json` overrides the path.

Use the local SDK in another Go project before a version is published:

```sh
go mod edit -require=github.com/mattjoyce/xte-esl/go@v0.0.0
go mod edit -replace=github.com/mattjoyce/xte-esl/go=/absolute/path/to/xte-esl/go
go mod tidy
```

## Encode a prepared image

The CLI accepts a 250×122 PNG or JPEG and writes an XTEK container:

```sh
# From go/:
go run ./cmd/xte-encode -out /tmp/label.xtek ../examples/github-qr.png
```

Draw using pure white, black, red (`FF0000`), and yellow (`FFFF00`). Other
colours become black. The encoder does not resize, quantise, or dither.
`RasterFromImage` composites transparent pixels onto white before encoding.

```go
package main

import (
    "image"
    _ "image/png"
    "log"
    "os"

    xte "github.com/mattjoyce/xte-esl/go"
)

func main() {
    file, err := os.Open("label.png")
    if err != nil { log.Fatal(err) }
    defer file.Close()
    src, _, err := image.Decode(file)
    if err != nil { log.Fatal(err) }
    raster, err := xte.RasterFromImage(src)
    if err != nil { log.Fatal(err) }
    data, err := xte.EncodePSJ213(raster, xte.EncodeOptions{})
    if err != nil { log.Fatal(err) }
    if err := os.WriteFile("label.xtek", data, 0644); err != nil { log.Fatal(err) }
}
```

`EncodePSJ213` rotates landscape input counter-clockwise into the 122×250
native buffer. RLE is selected when its size is equal to or smaller than
raw pixels. Set `DisableCompression: true` to force raw data.

Raw RGB/RGBA data can be supplied as `Raster{Width, Height, Channels, Data}`.
`Channels` is 3 or 4, with tightly packed row-major pixels. For raw RGBA,
alpha is ignored: composite it yourself or use `RasterFromImage`.
`EncodeContainer` accepts 1–255 `ImageRecord` values in native buffer
orientation, with optional `X` and `Y` coordinates.

Only device 140 has verified packing. `EncodeOptions.DeviceNumber == 0`
selects 140; other nonzero values are rejected. Low-level `PackPixels`
requires the explicit device number 140. Validation failures return `*xte.Error`,
which can be inspected with `errors.As`.

## Upload

For a ready-to-run Linux command, see [the BlueZ quick start](bluez/README.md).
For other transports:

```go
uploader, err := xte.NewUploader(transport) // transport implements xte.Transport
if err != nil { return err }
return uploader.Upload(ctx, container, xte.UploadOptions{})
```

Use one `Uploader` per transport and give it exclusive ownership of that
transport. Concurrent calls on the same uploader are rejected. Upload
snapshots the container, enables notifications, allocates flash, transmits
packets, patches losses, and requests refresh. It disconnects on success,
failure, and cancellation. It does not retry whole uploads.

An accepted refresh means the upload is complete; the e-paper panel takes
about another 20 seconds to settle.

| Option | Zero/default behavior |
|---|---|
| `MultiScreen` | `false`: single-screen refresh |
| `CommandTimeout` | `0`: 5 seconds for connect, commands, writes, cleanup |
| `PatchTimeout` | `0`: 300 seconds per recovery phase |
| `WriteDelay` | `nil`: 5 ms; pointer to zero disables pacing |

Cancel with a Go context. Context and transport errors retain their types,
so `errors.Is(err, context.DeadlineExceeded)` works. Cleanup errors are
returned when the upload otherwise succeeded; original failures take
precedence. Every recovery phase permits at most three patch rounds.
Short bitmaps mark unreported packets as missing. A refresh claiming loss
with a complete bitmap fails immediately.

A `Transport` implements `WriteSize`, `Connect`, `Write`, and `Disconnect`.
Its I/O methods must respect context cancellation and clean up in-flight
operations. Notifications and disconnect callbacks may run concurrently;
they should return promptly. The supplied BlueZ transport is single-use,
so create a new transport and uploader for each whole-upload retry.

## Other codec functions

`PackPixels`, `RotateCounterClockwise`, `EncodeRLE`, `Allocate`,
`AllocateBatch`, `Verify`, `Refresh`, `DataPackets`, `SplitWrites`,
`ParseResponse`, `Response.MissingPackets`, `ParseAdvertisement`, and
`AddressFromName` are available independently of BLE. Advertisement data
must include the two manufacturer-ID bytes. `ApplyFirmware` only builds
the command; firmware updates are not implemented.

## Verification status

Codec: verified byte for byte against the shared reference vectors.
Uploader: simulated tests cover large batches, recovery, deadlines,
cancellation, concurrent use, and cleanup, including race-detector runs.
BlueZ: simulated D-Bus tests; **the Go implementation has not been exercised
on a physical tag**. Prior Python/TypeScript hardware verification does not
count as Go hardware verification.

Protocol reference: [`../docs/protocol.md`](../docs/protocol.md).
