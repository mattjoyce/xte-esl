# Optional Linux BlueZ transport

Native BLE for the Go XTE SDK. Requires Linux, a running BlueZ service, a
powered Bluetooth adapter, and permission to use BlueZ over the system
D-Bus. No pairing is required. This module has one direct external dependency
(`godbus/dbus/v5`) and one transitive dependency (`x/sys`); neither is added
to the core SDK module.

## Push from the checkout

```sh
# From the repository root:
cd go
go run ./cmd/xte-encode -out /tmp/label.xtek ../examples/github-qr.png
cd bluez
go test -race ./...
go run ./cmd/xte-push 9F:1D:00:0B:33:36 /tmp/label.xtek
```

Replace the example MAC with your own tag's address. The command scans when
BlueZ has not seen that device, connects, discovers the XTE service,
subscribes to notifications, and uploads. It selects the first write and
notify characteristics by their properties, as the protocol specifies.
BlueZ negotiates the MTU; payloads use up to 244 bytes, or the safe 20-byte
fallback when BlueZ does not expose the MTU.

`-adapter hci1` selects another adapter. `-timeout 90s` changes the overall
limit; `-command-timeout 15s` allows more time for initial discovery and for
each command. Ctrl-C cancels and disconnects. Success is reported when
refresh is accepted; allow about 20 more seconds for the display to settle.

## Library usage

```go
transport, err := bluez.New(address, "hci0")
if err != nil { return err }
uploader, err := xte.NewUploader(transport)
if err != nil { return err }
return uploader.Upload(ctx, container, xte.UploadOptions{})
```

Imports are `github.com/mattjoyce/xte-esl/go` (as `xte`) and
`github.com/mattjoyce/xte-esl/go/bluez`. Each transport has its own D-Bus
connection and is single-use. Create a fresh one for each retry. If calling
`Connect` directly, always call `Disconnect` afterwards, including on error;
`Uploader` already handles this.

For use from another local project, add local replacements for **both**
modules; dependency modules' replacement directives do not propagate:

```sh
go mod edit -require=github.com/mattjoyce/xte-esl/go/bluez@v0.0.0
go mod edit -replace=github.com/mattjoyce/xte-esl/go=/absolute/path/to/xte-esl/go
go mod edit -replace=github.com/mattjoyce/xte-esl/go/bluez=/absolute/path/to/xte-esl/go/bluez
go mod tidy
```

This adapter targets Linux only. Core encoding and the transport interface
are portable. It has been tested with simulated D-Bus calls and signals,
not yet with a physical tag.

The implementation follows the official BlueZ
[Device API](https://github.com/bluez/bluez/blob/master/doc/org.bluez.Device.rst)
and [GATT characteristic API](https://github.com/bluez/bluez/blob/master/doc/org.bluez.GattCharacteristic.rst).
