package xte

import (
	"bytes"
	"encoding/binary"
	"encoding/hex"
	"errors"
	"image"
	"image/color"
	"reflect"
	"testing"
)

func unhex(t *testing.T, s string) []byte {
	t.Helper()
	b, e := hex.DecodeString(s)
	if e != nil {
		t.Fatal(e)
	}
	return b
}
func TestPackingAndRotation(t *testing.T) {
	r := Raster{Width: 6, Height: 1, Channels: 3, Data: []byte{255, 255, 255, 255, 255, 0, 255, 0, 0, 0, 0, 0, 255, 255, 254, 255, 255, 255}}
	b, e := PackPixels(r, 140)
	if e != nil || !bytes.Equal(b, []byte{0x6c, 0x10}) {
		t.Fatalf("packing %x %v", b, e)
	}
	r = Raster{Width: 3, Height: 2, Channels: 3}
	for i := byte(1); i <= 6; i++ {
		r.Data = append(r.Data, i, i, i)
	}
	rotated, e := RotateCounterClockwise(r)
	if e != nil {
		t.Fatal(e)
	}
	var values []byte
	for i := 0; i < len(rotated.Data); i += 3 {
		values = append(values, rotated.Data[i])
	}
	if rotated.Width != 2 || rotated.Height != 3 || !bytes.Equal(values, []byte{3, 6, 2, 5, 1, 4}) {
		t.Fatal(rotated, values)
	}
	source := Raster{Width: 250, Height: 122, Channels: 4, Data: bytes.Repeat([]byte{255}, 250*122*4)}
	container, e := EncodePSJ213(source, EncodeOptions{DisableCompression: true})
	if e != nil {
		t.Fatal(e)
	}
	if binary.BigEndian.Uint32(container[25:]) != 122 || binary.BigEndian.Uint32(container[29:]) != 250 || binary.BigEndian.Uint32(container[34:]) != 7750 {
		t.Fatal("wrong native geometry")
	}
}
func TestRasterFromImage(t *testing.T) {
	src := image.NewNRGBA(image.Rect(7, 9, 9, 10))
	src.SetNRGBA(8, 9, color.NRGBA{R: 255, A: 255})
	r, e := RasterFromImage(src)
	if e != nil {
		t.Fatal(e)
	}
	packed, e := PackPixels(r, 140)
	if e != nil || !bytes.Equal(packed, []byte{0x70}) {
		t.Fatalf("white compositing and shifted bounds: %x %v", packed, e)
	}
}
func TestRLEAndRecords(t *testing.T) {
	if got := EncodeRLE(bytes.Repeat([]byte{7}, 513)); !bytes.Equal(got, unhex(t, "ff070107ff070207")) {
		t.Fatalf("%x", got)
	}
	if len(EncodeRLE(nil)) != 0 || !bytes.Equal(EncodeRLE([]byte{1}), []byte{1, 1}) {
		t.Fatal("short RLE")
	}
	r := Raster{Width: 1, Height: 1, Channels: 3, Data: []byte{255, 0, 0}}
	b, e := EncodeContainer([]ImageRecord{{Image: r}, {Image: r, X: 10, Y: 20}}, EncodeOptions{DisableCompression: true})
	if e != nil {
		t.Fatal(e)
	}
	for offset, want := range map[int]uint32{13: 21, 17: 43, 43: 10, 47: 20} {
		if binary.BigEndian.Uint32(b[offset:]) != want {
			t.Fatalf("offset %d", offset)
		}
	}
}
func TestResponses(t *testing.T) {
	r, ok := ParseResponse(unhex(t, "5854450409490468ddffff"))
	if !ok {
		t.Fatal("valid response rejected")
	}
	missing, e := r.MissingPackets(10)
	if e != nil || !reflect.DeepEqual(missing, []int{2, 6, 8, 9}) {
		t.Fatal(missing, e)
	}
	r, ok = ParseResponse(unhex(t, "5854450408df02dd"))
	if !ok {
		t.Fatal("verify rejected")
	}
	missing, e = r.MissingPackets(9)
	if e != nil || !reflect.DeepEqual(missing, []int{2, 6, 8}) {
		t.Fatal(missing, e)
	}
	for _, wire := range []string{"", "58544504080204ff", "58544504100304ff", "58544502080304ff"} {
		if _, ok := ParseResponse(unhex(t, wire)); ok {
			t.Fatal("invalid response accepted")
		}
	}
	raw := unhex(t, "58544504080304ff0000000000000000")
	r, ok = ParseResponse(raw)
	if !ok {
		t.Fatal("refresh")
	}
	raw[7] = 0
	b := r.Bytes()
	b[7] = 0
	if r.Bytes()[7] != 255 || len(r.Bytes()) != 8 {
		t.Fatal("response aliases caller bytes or retains padding")
	}
}
func TestAdvertisements(t *testing.T) {
	a, ok := ParseAdvertisement(unhex(t, "5852fd024002008c63060102ffff1c"))
	if !ok || a.Firmware != "4.0.2" || a.DeviceNumber != 140 || a.BatteryPercent != 99 {
		t.Fatal(a, ok)
	}
	if _, ok = ParseAdvertisement([]byte{255, 1}); ok {
		t.Fatal("noise accepted")
	}
	addr, e := AddressFromName("36330b001d9f")
	if e != nil || addr != "9F:1D:00:0B:33:36" {
		t.Fatal(addr, e)
	}
}
func TestPreconditions(t *testing.T) {
	good := Raster{Width: 1, Height: 1, Channels: 3, Data: []byte{0, 0, 0}}
	for _, r := range []Raster{{}, {Width: 1, Height: 1, Channels: 3}, {Width: 1, Height: 1, Channels: 2, Data: []byte{0, 0}}, {Width: int(^uint(0) >> 1), Height: 2, Channels: 4}} {
		_, e := PackPixels(r, 140)
		var sdkErr *Error
		if !errors.As(e, &sdkErr) {
			t.Fatalf("expected SDK error: %v", e)
		}
	}
	checks := []func() error{
		func() error { _, e := PackPixels(good, 141); return e },
		func() error { _, e := EncodeContainer(nil, EncodeOptions{}); return e },
		func() error { _, e := EncodeContainer([]ImageRecord{{Image: good, X: -1}}, EncodeOptions{}); return e },
		func() error { _, e := EncodeContainer(make([]ImageRecord, 256), EncodeOptions{}); return e },
		func() error { _, e := Allocate(BatchSize + 1); return e },
		func() error { _, e := AllocateBatch(10, 9, 2); return e },
		func() error { _, e := DataPackets(make([]byte, BatchSize+1)); return e },
		func() error { _, e := SplitWrites(nil, 0); return e },
		func() error { _, e := AddressFromName("bad"); return e },
		func() error { _, e := EncodePSJ213(good, EncodeOptions{}); return e },
		func() error { _, e := (Response{}).MissingPackets(1); return e },
	}
	for _, check := range checks {
		var sdkErr *Error
		if e := check(); !errors.As(e, &sdkErr) {
			t.Fatalf("expected SDK error: %v", e)
		}
	}
}
func FuzzParseResponse(f *testing.F) {
	f.Add([]byte{0x58, 0x54, 0x45, 4, 8, 3, 4, 255})
	f.Fuzz(func(t *testing.T, b []byte) {
		r, ok := ParseResponse(b)
		if ok {
			_, _ = r.MissingPackets(170)
			if len(r.Bytes()) < 8 {
				t.Fatal("short accepted frame")
			}
		}
	})
}
