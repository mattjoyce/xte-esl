package bluez

import (
	"bytes"
	"context"
	"errors"
	"reflect"
	"sync"
	"testing"
	"time"

	"github.com/godbus/dbus/v5"
	xte "github.com/mattjoyce/xte-esl/go"
)

const testDevice dbus.ObjectPath = "/org/bluez/hci0/dev_9F_1D_00_0B_33_36"
const testService dbus.ObjectPath = testDevice + "/service0001"
const testWriter dbus.ObjectPath = testService + "/char0002"
const testNotifier dbus.ObjectPath = testService + "/char0003"

func props(values map[string]any) map[string]dbus.Variant {
	out := map[string]dbus.Variant{}
	for k, v := range values {
		out[k] = dbus.MakeVariant(v)
	}
	return out
}
func fixtureObjects() objects {
	return objects{
		testDevice:   {deviceInterface: props(map[string]any{"Address": "9F:1D:00:0B:33:36", "ServicesResolved": true})},
		testService:  {serviceInterface: props(map[string]any{"UUID": xte.ServiceUUID, "Device": testDevice})},
		testWriter:   {characteristicInterface: props(map[string]any{"Service": testService, "Flags": []string{"write-without-response"}, "MTU": uint16(517)})},
		testNotifier: {characteristicInterface: props(map[string]any{"Service": testService, "Flags": []string{"notify"}})},
	}
}

type fakeBus struct {
	mu                     sync.Mutex
	events                 chan *dbus.Signal
	all                    objects
	methods                []string
	write                  []byte
	writeType              string
	failMethod, hangMethod string
	closed                 bool
	discover               bool
	notifyOnStart          bool
}

func (b *fakeBus) call(ctx context.Context, path dbus.ObjectPath, method string, result any, args ...any) error {
	b.mu.Lock()
	defer b.mu.Unlock()
	b.methods = append(b.methods, method)
	if method == b.hangMethod {
		<-ctx.Done()
		return ctx.Err()
	}
	if method == b.failMethod {
		return errors.New("simulated failure")
	}
	if err := ctx.Err(); err != nil {
		return err
	}
	switch method {
	case "org.freedesktop.DBus.ObjectManager.GetManagedObjects":
		if b.discover {
			*result.(*objects) = objects{}
		} else {
			*result.(*objects) = b.all
		}
	case "org.bluez.Adapter1.StartDiscovery":
		b.discover = false
	case characteristicInterface + ".WriteValue":
		b.write = bytes.Clone(args[0].([]byte))
		b.writeType = args[1].(map[string]dbus.Variant)["type"].Value().(string)
	case characteristicInterface + ".StartNotify":
		if b.notifyOnStart {
			b.events <- notification([]byte{1, 2})
		}
	}
	return nil
}
func (b *fakeBus) signals() <-chan *dbus.Signal { return b.events }
func (b *fakeBus) close() error                 { b.mu.Lock(); defer b.mu.Unlock(); b.closed = true; return nil }
func notification(data []byte) *dbus.Signal {
	return &dbus.Signal{Name: propertiesChanged, Path: testNotifier, Body: []any{characteristicInterface, props(map[string]any{"Value": data})}}
}
func fixture(t *testing.T) (*Transport, *fakeBus) {
	t.Helper()
	adapter, e := New("9F:1D:00:0B:33:36", "")
	if e != nil {
		t.Fatal(e)
	}
	b := &fakeBus{events: make(chan *dbus.Signal, 10), all: fixtureObjects()}
	adapter.dial = func(context.Context) (bus, error) { return b, nil }
	return adapter, b
}
func TestConnectWriteNotificationsAndCleanup(t *testing.T) {
	adapter, b := fixture(t)
	b.notifyOnStart = true
	received := make(chan []byte, 2)
	if e := adapter.Connect(context.Background(), func(data []byte) { received <- data }, func(error) {}); e != nil {
		t.Fatal(e)
	}
	select {
	case data := <-received:
		if !bytes.Equal(data, []byte{1, 2}) {
			t.Fatal(data)
		}
	case <-time.After(time.Second):
		t.Fatal("notification lost during setup")
	}
	if adapter.WriteSize() != 244 {
		t.Fatal(adapter.WriteSize())
	}
	if e := adapter.Write(context.Background(), []byte{3, 4}); e != nil {
		t.Fatal(e)
	}
	if !bytes.Equal(b.write, []byte{3, 4}) || b.writeType != "command" {
		t.Fatal(b.write, b.writeType)
	}
	if e := adapter.Disconnect(context.Background()); e != nil {
		t.Fatal(e)
	}
	if !b.closed {
		t.Fatal("bus not closed")
	}
	if e := adapter.Write(context.Background(), nil); e == nil {
		t.Fatal("write after disconnect")
	}
	if e := adapter.Connect(context.Background(), func([]byte) {}, func(error) {}); e == nil {
		t.Fatal("single-use transport reconnected")
	}
}
func TestDiscoveryAndDisconnectSignal(t *testing.T) {
	adapter, b := fixture(t)
	b.discover = true
	lost := make(chan error, 1)
	if e := adapter.Connect(context.Background(), func([]byte) {}, func(e error) { lost <- e }); e != nil {
		t.Fatal(e)
	}
	b.events <- &dbus.Signal{Name: propertiesChanged, Path: testDevice, Body: []any{deviceInterface, props(map[string]any{"Connected": false})}}
	select {
	case <-lost:
	case <-time.After(time.Second):
		t.Fatal("disconnect not reported")
	}
	if e := adapter.Disconnect(context.Background()); e != nil {
		t.Fatal(e)
	}
	found := false
	for _, method := range b.methods {
		if method == "org.bluez.Adapter1.StopDiscovery" {
			found = true
		}
	}
	if !found {
		t.Fatal("discovery not stopped")
	}
}
func TestFailureAndCancellationCleanup(t *testing.T) {
	for _, method := range []string{deviceInterface + ".Connect", characteristicInterface + ".StartNotify"} {
		adapter, b := fixture(t)
		b.hangMethod = method
		ctx, cancel := context.WithTimeout(context.Background(), 10*time.Millisecond)
		e := adapter.Connect(ctx, func([]byte) {}, func(error) {})
		cancel()
		if !errors.Is(e, context.DeadlineExceeded) {
			t.Fatal(e)
		}
		if e = adapter.Disconnect(context.Background()); e != nil {
			t.Fatal(e)
		}
		if !b.closed {
			t.Fatal("leaked bus")
		}
	}
	adapter, b := fixture(t)
	b.discover = true
	b.failMethod = "org.bluez.Adapter1.StartDiscovery"
	if e := adapter.Connect(context.Background(), func([]byte) {}, func(error) {}); e == nil {
		t.Fatal("expected failure")
	}
	if e := adapter.Disconnect(context.Background()); e != nil {
		t.Fatal(e)
	}
	if !b.closed || b.methods[len(b.methods)-1] != "org.bluez.Adapter1.StopDiscovery" {
		t.Fatal(b.methods)
	}
}
func TestCharacteristicSelection(t *testing.T) {
	all := fixtureObjects()
	all[testWriter][characteristicInterface] = props(map[string]any{"Service": testService, "Flags": []string{"write"}})
	writer, notifier, kind, size, e := characteristics(all, testDevice)
	if e != nil || writer != testWriter || notifier != testNotifier || kind != "request" || size != 20 {
		t.Fatal(writer, notifier, kind, size, e)
	}
	delete(all, testNotifier)
	if _, _, _, _, e = characteristics(all, testDevice); e == nil {
		t.Fatal("missing notifier accepted")
	}
}
func TestDecodeSignalAndInputs(t *testing.T) {
	data := []byte{1, 2}
	got, lost := decodeSignal(notification(data), testDevice, testNotifier)
	data[0] = 9
	if lost || !reflect.DeepEqual(got, []byte{1, 2}) {
		t.Fatal(got, lost)
	}
	for _, sig := range []*dbus.Signal{nil, {}, {Name: propertiesChanged, Body: []any{42, "bad"}}} {
		if b, lost := decodeSignal(sig, testDevice, testNotifier); b != nil || lost {
			t.Fatal("malformed signal accepted")
		}
	}
	if _, e := New("bad", ""); e == nil {
		t.Fatal("bad MAC accepted")
	}
	if _, e := New("9F:1D:00:0B:33:36", "../hci0"); e == nil {
		t.Fatal("bad adapter accepted")
	}
}
