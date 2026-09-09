// Package bluez provides an optional Linux BLE transport for the XTE SDK.
// It uses BlueZ's D-Bus API and requires a powered Bluetooth adapter.
package bluez

import (
	"bytes"
	"context"
	"errors"
	"fmt"
	"net"
	"sort"
	"strings"
	"sync"
	"time"

	"github.com/godbus/dbus/v5"
	xte "github.com/mattjoyce/xte-esl/go"
)

const (
	deviceInterface         = "org.bluez.Device1"
	serviceInterface        = "org.bluez.GattService1"
	characteristicInterface = "org.bluez.GattCharacteristic1"
	propertiesChanged       = "org.freedesktop.DBus.Properties.PropertiesChanged"
)

type objects map[dbus.ObjectPath]map[string]map[string]dbus.Variant

// bus isolates D-Bus I/O so lifecycle behavior can be tested without a radio.
type bus interface {
	call(context.Context, dbus.ObjectPath, string, any, ...any) error
	signals() <-chan *dbus.Signal
	close() error
}
type systemBus struct {
	conn   *dbus.Conn
	events chan *dbus.Signal
	cancel context.CancelFunc
}

func (b *systemBus) call(ctx context.Context, path dbus.ObjectPath, method string, result any, args ...any) error {
	call := b.conn.Object("org.bluez", path).CallWithContext(ctx, method, 0, args...)
	if result != nil {
		return call.Store(result)
	}
	return call.Err
}
func (b *systemBus) signals() <-chan *dbus.Signal { return b.events }
func (b *systemBus) close() error                 { b.conn.RemoveSignal(b.events); b.cancel(); return b.conn.Close() }
func openBus(ctx context.Context) (bus, error) {
	lifetime, cancel := context.WithCancel(context.Background())
	type result struct {
		conn *dbus.Conn
		err  error
	}
	ready := make(chan result)
	go func() {
		conn, err := dbus.ConnectSystemBus(dbus.WithContext(lifetime))
		select {
		case ready <- result{conn, err}:
		case <-ctx.Done():
			if conn != nil {
				_ = conn.Close()
			}
			cancel()
		}
	}()
	var conn *dbus.Conn
	select {
	case <-ctx.Done():
		cancel()
		return nil, ctx.Err()
	case r := <-ready:
		if r.err != nil {
			cancel()
			return nil, r.err
		}
		conn = r.conn
	}
	events := make(chan *dbus.Signal, 64)
	conn.Signal(events)
	err := conn.AddMatchSignalContext(ctx, dbus.WithMatchSender("org.bluez"), dbus.WithMatchInterface("org.freedesktop.DBus.Properties"), dbus.WithMatchMember("PropertiesChanged"))
	if err != nil {
		conn.RemoveSignal(events)
		cancel()
		_ = conn.Close()
		return nil, err
	}
	return &systemBus{conn: conn, events: events, cancel: cancel}, nil
}

// Transport is single-use. Construct a fresh one for each upload, including
// retries. Its private D-Bus connection isolates cleanup from other clients.
type Transport struct {
	mu                            sync.Mutex
	address                       string
	adapter                       dbus.ObjectPath
	device, writer, notifier      dbus.ObjectPath
	writeType                     string
	size                          int
	used, closed, ready, scanning bool
	bus                           bus
	stop                          chan struct{}
	done                          chan struct{}
	dial                          func(context.Context) (bus, error)
}

var _ xte.Transport = (*Transport)(nil)

// New selects a MAC address and adapter (empty means hci0). It performs no I/O.
func New(address, adapter string) (*Transport, error) {
	mac, err := net.ParseMAC(address)
	if err != nil || len(mac) != 6 {
		return nil, &xte.Error{Message: "expected a six-byte Bluetooth MAC address"}
	}
	if adapter == "" {
		adapter = "hci0"
	}
	if !strings.HasPrefix(adapter, "hci") || len(adapter) == 3 || strings.Trim(adapter[3:], "0123456789") != "" {
		return nil, &xte.Error{Message: "adapter must be hci followed by digits"}
	}
	return &Transport{address: strings.ToUpper(mac.String()), adapter: dbus.ObjectPath("/org/bluez/" + adapter), size: 20, dial: openBus}, nil
}
func (t *Transport) WriteSize() int { t.mu.Lock(); defer t.mu.Unlock(); return t.size }
func (t *Transport) Connect(ctx context.Context, notify func([]byte), disconnected func(error)) error {
	t.mu.Lock()
	if t.used || t.closed {
		t.mu.Unlock()
		return errors.New("bluez: transport is single-use")
	}
	t.used = true
	t.mu.Unlock()
	b, err := t.dial(ctx)
	if err != nil {
		return err
	}
	t.mu.Lock()
	if t.closed {
		t.mu.Unlock()
		_ = b.close()
		return context.Canceled
	}
	t.bus = b
	t.mu.Unlock()
	// Poll managed objects during discovery; notifications have a separate reader
	// once the characteristic is known, so no reply can be consumed by discovery.
	var all objects
	if err = b.call(ctx, "/", "org.freedesktop.DBus.ObjectManager.GetManagedObjects", &all); err != nil {
		return err
	}
	path := findDevice(all, t.adapter, t.address)
	if path == "" {
		if err = b.call(ctx, t.adapter, "org.bluez.Adapter1.SetDiscoveryFilter", nil, map[string]dbus.Variant{"Transport": dbus.MakeVariant("le")}); err != nil {
			return err
		}
		// Mark before issuing the call, so even an ambiguous timeout is cleaned up.
		t.mu.Lock()
		t.scanning = true
		t.mu.Unlock()
		if err = b.call(ctx, t.adapter, "org.bluez.Adapter1.StartDiscovery", nil); err != nil {
			return err
		}
		for path == "" {
			if err = wait(ctx, 50*time.Millisecond); err != nil {
				return err
			}
			if err = b.call(ctx, "/", "org.freedesktop.DBus.ObjectManager.GetManagedObjects", &all); err != nil {
				return err
			}
			path = findDevice(all, t.adapter, t.address)
		}
		if err = b.call(ctx, t.adapter, "org.bluez.Adapter1.StopDiscovery", nil); err != nil {
			return err
		}
		t.mu.Lock()
		t.scanning = false
		t.mu.Unlock()
	}
	t.mu.Lock()
	t.device = path
	t.mu.Unlock()
	if err = b.call(ctx, path, deviceInterface+".Connect", nil); err != nil {
		return err
	}
	for {
		if err = b.call(ctx, "/", "org.freedesktop.DBus.ObjectManager.GetManagedObjects", &all); err != nil {
			return err
		}
		if resolved, _ := all[path][deviceInterface]["ServicesResolved"].Value().(bool); resolved {
			break
		}
		if err = wait(ctx, 20*time.Millisecond); err != nil {
			return err
		}
	}
	writer, notifier, writeType, size, err := characteristics(all, path)
	if err != nil {
		return err
	}
	t.mu.Lock()
	if t.closed {
		t.mu.Unlock()
		return context.Canceled
	}
	t.writer = writer
	t.notifier = notifier
	t.writeType = writeType
	t.size = size
	t.stop = make(chan struct{})
	t.done = make(chan struct{})
	stop, done := t.stop, t.done
	t.mu.Unlock()
	go func() {
		defer close(done)
		for {
			select {
			case <-stop:
				return
			case sig, ok := <-b.signals():
				if !ok {
					disconnected(errors.New("bluez: D-Bus connection closed"))
					return
				}
				value, lost := decodeSignal(sig, path, notifier)
				if lost {
					disconnected(errors.New("bluez: BLE device disconnected"))
					return
				}
				if value != nil {
					notify(value)
				}
			}
		}
	}()
	if err = b.call(ctx, notifier, characteristicInterface+".StartNotify", nil); err != nil {
		return err
	}
	t.mu.Lock()
	if t.closed {
		t.mu.Unlock()
		return context.Canceled
	}
	t.ready = true
	t.mu.Unlock()
	return ctx.Err()
}
func (t *Transport) Write(ctx context.Context, data []byte) error {
	if err := ctx.Err(); err != nil {
		return err
	}
	t.mu.Lock()
	b, writer, kind, size, ready := t.bus, t.writer, t.writeType, t.size, t.ready && !t.closed
	t.mu.Unlock()
	if !ready {
		return errors.New("bluez: transport is not connected")
	}
	if len(data) > size {
		return &xte.Error{Message: "write exceeds negotiated BLE payload"}
	}
	return b.call(ctx, writer, characteristicInterface+".WriteValue", nil, bytes.Clone(data), map[string]dbus.Variant{"type": dbus.MakeVariant(kind)})
}
func (t *Transport) Disconnect(ctx context.Context) error {
	t.mu.Lock()
	if t.closed {
		t.mu.Unlock()
		return nil
	}
	t.closed = true
	t.ready = false
	b, device, scanning, stop, done := t.bus, t.device, t.scanning, t.stop, t.done
	if stop != nil {
		close(stop)
	}
	t.mu.Unlock()
	if b == nil {
		return nil
	}
	// Closing the private bus releases discovery and notification sessions too.
	defer b.close()
	var errs []error
	if device != "" {
		if err := b.call(ctx, device, deviceInterface+".Disconnect", nil); err != nil {
			errs = append(errs, err)
		}
	}
	if scanning {
		if err := b.call(ctx, t.adapter, "org.bluez.Adapter1.StopDiscovery", nil); err != nil {
			errs = append(errs, err)
		}
	}
	if done != nil {
		select {
		case <-done:
		case <-ctx.Done():
			errs = append(errs, ctx.Err())
		}
	}
	return errors.Join(errs...)
}
func wait(ctx context.Context, d time.Duration) error {
	timer := time.NewTimer(d)
	defer timer.Stop()
	select {
	case <-ctx.Done():
		return ctx.Err()
	case <-timer.C:
		return ctx.Err()
	}
}
func findDevice(all objects, adapter dbus.ObjectPath, address string) dbus.ObjectPath {
	for path, interfaces := range all {
		props := interfaces[deviceInterface]
		addr, _ := props["Address"].Value().(string)
		if strings.HasPrefix(string(path), string(adapter)+"/") && strings.EqualFold(addr, address) {
			return path
		}
	}
	return ""
}
func characteristics(all objects, device dbus.ObjectPath) (writer, notifier dbus.ObjectPath, kind string, size int, err error) {
	// BlueZ object paths give deterministic discovery order, as in the protocol.
	paths := make([]string, 0, len(all))
	for p := range all {
		paths = append(paths, string(p))
	}
	sort.Strings(paths)
	service := dbus.ObjectPath("")
	for _, p := range paths {
		props := all[dbus.ObjectPath(p)][serviceInterface]
		uuid, _ := props["UUID"].Value().(string)
		owner, _ := props["Device"].Value().(dbus.ObjectPath)
		if owner == device && strings.EqualFold(uuid, xte.ServiceUUID) {
			service = dbus.ObjectPath(p)
			break
		}
	}
	if service == "" {
		return "", "", "", 0, errors.New("bluez: XTE service not found")
	}
	size = 20
	for _, p := range paths {
		props := all[dbus.ObjectPath(p)][characteristicInterface]
		owner, _ := props["Service"].Value().(dbus.ObjectPath)
		if owner != service {
			continue
		}
		flags, _ := props["Flags"].Value().([]string)
		has := func(s string) bool {
			for _, f := range flags {
				if f == s {
					return true
				}
			}
			return false
		}
		if writer == "" && (has("write-without-response") || has("write")) {
			writer = dbus.ObjectPath(p)
			kind = "request"
			if has("write-without-response") {
				kind = "command"
			}
			if mtu, ok := props["MTU"].Value().(uint16); ok && mtu >= 23 {
				size = min(int(mtu)-3, xte.MaxWriteSize)
			}
		}
		if notifier == "" && (has("notify") || has("indicate")) {
			notifier = dbus.ObjectPath(p)
		}
	}
	if writer == "" || notifier == "" {
		err = fmt.Errorf("bluez: XTE write/notify characteristics not found")
	}
	return
}
func decodeSignal(sig *dbus.Signal, device, notifier dbus.ObjectPath) ([]byte, bool) {
	if sig == nil || sig.Name != propertiesChanged || len(sig.Body) < 2 {
		return nil, false
	}
	iface, ok := sig.Body[0].(string)
	if !ok {
		return nil, false
	}
	props, ok := sig.Body[1].(map[string]dbus.Variant)
	if !ok {
		return nil, false
	}
	if sig.Path == device && iface == deviceInterface {
		connected, present := props["Connected"].Value().(bool)
		return nil, present && !connected
	}
	if sig.Path == notifier && iface == characteristicInterface {
		value, _ := props["Value"].Value().([]byte)
		return bytes.Clone(value), false
	}
	return nil, false
}
