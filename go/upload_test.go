package xte

import (
	"bytes"
	"context"
	"encoding/binary"
	"errors"
	"reflect"
	"strings"
	"testing"
	"time"
)

type fakeTag struct {
	size                                             int
	notify                                           func([]byte)
	lost                                             func(error)
	input                                            []byte
	frames                                           [][]byte
	disconnected                                     int
	count                                            int
	patchVerify, patchRefresh                        int
	shortBitmap, completeBitmap                      bool
	allocStatus                                      byte
	silent, hangWrite, hangConnect, disconnectOnData bool
	lateConnectSuccess                               bool
	onData                                           func()
	connected                                        chan struct{}
	cleanupError                                     error
}

func (f *fakeTag) WriteSize() int {
	if f.size == 0 {
		return 20
	}
	return f.size
}
func (f *fakeTag) Connect(ctx context.Context, notify func([]byte), lost func(error)) error {
	f.notify = notify
	f.lost = lost
	if f.connected != nil {
		close(f.connected)
	}
	if f.hangConnect {
		<-ctx.Done()
		if f.lateConnectSuccess {
			return nil
		}
		return ctx.Err()
	}
	return nil
}
func response(cmd byte, payload ...byte) []byte {
	b := append([]byte{'X', 'T', 'E', 4, byte(7 + len(payload)), 0, cmd}, payload...)
	b[5] = byte(checksum(b[6:]))
	return b
}
func (f *fakeTag) Write(ctx context.Context, b []byte) error {
	if f.hangWrite {
		<-ctx.Done()
		return ctx.Err()
	}
	f.input = append(f.input, b...)
	if len(f.input) < 6 {
		return nil
	}
	n := int(f.input[4])
	if f.input[3] == 2 {
		n = int(binary.BigEndian.Uint16(f.input[4:]))
	}
	if len(f.input) < n {
		return nil
	}
	if len(f.input) != n {
		return errors.New("overlapping frames")
	}
	frame := bytes.Clone(f.input)
	f.input = nil
	f.frames = append(f.frames, frame)
	if frame[3] == 2 {
		f.count = int(frame[7])
		if f.disconnectOnData {
			f.lost(nil)
		}
		if f.onData != nil {
			f.onData()
		}
		return nil
	}
	if f.silent {
		return nil
	}
	f.notify([]byte{1, 2, 3})
	f.notify(response(5, 255))
	cmd := frame[6]
	payload := []byte{f.allocStatus, 0xbd}
	if cmd != 1 {
		bitmap := bytes.Repeat([]byte{255}, (f.count+7)/8)
		patch := false
		if cmd == 2 {
			patch = f.patchVerify > 0
			f.patchVerify--
		} else {
			patch = f.patchRefresh > 0
			f.patchRefresh--
		}
		if patch && !f.completeBitmap {
			bitmap[0] &= ^byte(0x20)
		}
		if patch && f.shortBitmap {
			bitmap = bitmap[:1]
		}
		if cmd == 2 {
			payload = bitmap
		} else if patch {
			payload = append([]byte{0x68}, bitmap...)
		} else {
			payload = []byte{255}
		}
	}
	f.notify(response(cmd, payload...))
	return nil
}
func (f *fakeTag) Disconnect(context.Context) error { f.disconnected++; return f.cleanupError }
func uploadFixture(t *testing.T, large bool) []byte {
	t.Helper()
	w, h := 250, 122
	if large {
		w, h = 1024, 1000
	}
	b, e := EncodeContainer([]ImageRecord{{Image: Raster{Width: w, Height: h, Channels: 3, Data: make([]byte, w*h*3)}}}, EncodeOptions{DisableCompression: true})
	if e != nil {
		t.Fatal(e)
	}
	return b
}
func fastOptions() UploadOptions { zero := time.Duration(0); return UploadOptions{WriteDelay: &zero} }
func doUpload(t *testing.T, f *fakeTag, b []byte, options UploadOptions) error {
	t.Helper()
	u, e := NewUploader(f)
	if e != nil {
		t.Fatal(e)
	}
	return u.Upload(context.Background(), b, options)
}
func commands(f *fakeTag) []byte {
	var out []byte
	for _, b := range f.frames {
		if b[3] == 1 {
			out = append(out, b[6])
		}
	}
	return out
}
func TestUploadRecovery(t *testing.T) {
	f := &fakeTag{allocStatus: 255, patchRefresh: 1}
	b := uploadFixture(t, false)
	if e := doUpload(t, f, b, fastOptions()); e != nil {
		t.Fatal(e)
	}
	if !bytes.Equal(commands(f), []byte{1, 4, 4}) || f.disconnected != 1 {
		t.Fatal(commands(f), f.disconnected)
	}
	var packets [][]byte
	for _, frame := range f.frames {
		if frame[3] == 2 {
			packets = append(packets, frame)
		}
	}
	var data []byte
	for _, p := range packets[:len(packets)-1] {
		data = append(data, p[9:]...)
	}
	if !bytes.Equal(data, b) || packets[len(packets)-1][8] != 2 {
		t.Fatal("wrong retransmission/data")
	}
}
func TestUploadBatchesAndShortBitmap(t *testing.T) {
	f := &fakeTag{allocStatus: 255, size: 244, patchVerify: 1, shortBitmap: true}
	if e := doUpload(t, f, uploadFixture(t, true), fastOptions()); e != nil {
		t.Fatal(e)
	}
	if !bytes.Equal(commands(f), []byte{1, 2, 2, 1, 4}) {
		t.Fatal(commands(f))
	}
	var indexes []int
	record := false
	for i, frame := range f.frames {
		if frame[3] == 1 && frame[6] == 1 {
			if f.frames[i+1][8] != 0 || len(frame) != 19 {
				t.Fatal("batch framing")
			}
			if binary.BigEndian.Uint32(frame[11:]) != 0 && binary.BigEndian.Uint32(frame[11:]) != BatchSize {
				t.Fatal("batch offset")
			}
		}
		if frame[3] == 1 && frame[6] == 2 {
			if record {
				break
			}
			record = true
			continue
		}
		if record {
			indexes = append(indexes, int(frame[8]))
		}
	}
	want := []int{2}
	for i := 8; i < 170; i++ {
		want = append(want, i)
	}
	if !reflect.DeepEqual(indexes, want) {
		t.Fatal(indexes)
	}
}
func TestUploadFailures(t *testing.T) {
	for _, tc := range []struct {
		name string
		f    *fakeTag
		want string
	}{
		{"allocation", &fakeTag{allocStatus: 1}, "allocation failed"},
		{"round limit", &fakeTag{allocStatus: 255, patchRefresh: 10}, "3 patch rounds"},
		{"complete bitmap", &fakeTag{allocStatus: 255, patchRefresh: 1, completeBitmap: true}, "bitmap is complete"},
		{"disconnect", &fakeTag{allocStatus: 255, disconnectOnData: true}, "disconnected"},
	} {
		t.Run(tc.name, func(t *testing.T) {
			e := doUpload(t, tc.f, uploadFixture(t, false), fastOptions())
			if e == nil || !strings.Contains(e.Error(), tc.want) || tc.f.disconnected != 1 {
				t.Fatal(e, tc.f.disconnected)
			}
			if tc.f.disconnectOnData && len(tc.f.input) != 0 {
				t.Fatal("writes continued after disconnect")
			}
		})
	}
}
func TestUploadTimeouts(t *testing.T) {
	for _, f := range []*fakeTag{{silent: true}, {hangWrite: true}, {hangConnect: true}, {hangConnect: true, lateConnectSuccess: true}} {
		options := fastOptions()
		options.CommandTimeout = 10 * time.Millisecond
		e := doUpload(t, f, uploadFixture(t, false), options)
		if !errors.Is(e, context.DeadlineExceeded) || f.disconnected != 1 {
			t.Fatal(e, f.disconnected)
		}
	}
	f := &fakeTag{allocStatus: 255, patchRefresh: 10}
	options := fastOptions()
	options.PatchTimeout = 10 * time.Millisecond
	if e := doUpload(t, f, uploadFixture(t, false), options); !errors.Is(e, context.DeadlineExceeded) {
		t.Fatal(e)
	}
}
func TestCancellationAndConcurrentUse(t *testing.T) {
	f := &fakeTag{allocStatus: 255, silent: true, connected: make(chan struct{})}
	u, _ := NewUploader(f)
	b := uploadFixture(t, false)
	ctx, cancel := context.WithCancel(context.Background())
	done := make(chan error, 1)
	go func() { done <- u.Upload(ctx, b, fastOptions()) }()
	<-f.connected
	if e := u.Upload(context.Background(), b, fastOptions()); e == nil || !strings.Contains(e.Error(), "already") {
		t.Fatal(e)
	}
	cancel()
	if e := <-done; !errors.Is(e, context.Canceled) || f.disconnected != 1 {
		t.Fatal(e, f.disconnected)
	}
	// The same uploader is usable again after cleanup.
	f.connected = nil
	f.silent = false
	f.input = nil
	if e := u.Upload(context.Background(), b, fastOptions()); e != nil {
		t.Fatal(e)
	}
}
func TestAbortDuringWriteStopsImmediately(t *testing.T) {
	ctx, cancel := context.WithCancel(context.Background())
	defer cancel()
	f := &fakeTag{allocStatus: 255, onData: cancel}
	u, _ := NewUploader(f)
	e := u.Upload(ctx, uploadFixture(t, false), fastOptions())
	if !errors.Is(e, context.Canceled) || len(f.input) != 0 || len(f.frames) != 2 || f.disconnected != 1 {
		t.Fatal(e, len(f.frames), f.input)
	}
}
func TestInputAndCleanup(t *testing.T) {
	f := &fakeTag{allocStatus: 255}
	b := uploadFixture(t, false)
	b[4] ^= 1
	if e := doUpload(t, f, b, fastOptions()); e == nil || f.disconnected != 0 {
		t.Fatal(e)
	}
	failure := errors.New("cleanup failure")
	f = &fakeTag{allocStatus: 255, cleanupError: failure}
	if e := doUpload(t, f, uploadFixture(t, false), fastOptions()); !errors.Is(e, failure) {
		t.Fatal(e)
	}
	f = &fakeTag{allocStatus: 1, cleanupError: failure}
	if e := doUpload(t, f, uploadFixture(t, false), fastOptions()); e == nil || !strings.Contains(e.Error(), "allocation failed") {
		t.Fatal(e)
	}
}
