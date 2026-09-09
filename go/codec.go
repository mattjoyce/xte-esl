// Package xte encodes images and uploads them to XTE electronic shelf labels.
// It uses only the Go standard library. Wire formats follow docs/protocol.md.
package xte

import (
	"bytes"
	"encoding/binary"
	"encoding/hex"
	"fmt"
	"image"
	"image/color"
	"image/draw"
	"strings"
)

const (
	ServiceUUID    = "00002760-08c2-11e1-9073-0e8ac72e1001"
	WriteUUID      = "00002760-08c2-11e1-9073-0e8ac72e0001"
	NotifyUUID     = "00002760-08c2-11e1-9073-0e8ac72e0002"
	BatchSize      = 204800
	PacketDataSize = 1211
	MaxWriteSize   = 244
	maxU32         = 1<<32 - 1
)

// Error reports invalid SDK input or an unsupported protocol operation.
// Transport and context errors retain their original types.
type Error struct{ Message string }

func (e *Error) Error() string                 { return "xte: " + e.Message }
func invalid(format string, args ...any) error { return &Error{fmt.Sprintf(format, args...)} }
func checksum(b []byte) (s uint32) {
	for _, v := range b {
		s += uint32(v)
	}
	return
}
func put32(b []byte, v int) { binary.BigEndian.PutUint32(b, uint32(v)) }

// Raster holds tightly packed, row-major RGB or RGBA pixels. Alpha is ignored;
// composite transparent images first, or use RasterFromImage.
type Raster struct {
	Width, Height int
	Channels      int // 3 or 4
	Data          []byte
}

func (r Raster) validate() error {
	if r.Width <= 0 || r.Height <= 0 || uint64(r.Width) > maxU32 || uint64(r.Height) > maxU32 {
		return invalid("image dimensions must be positive u32 values")
	}
	if r.Channels != 3 && r.Channels != 4 {
		return invalid("channels must be 3 or 4")
	}
	// Divide before multiplying so even malicious dimensions cannot overflow.
	if r.Width > int(^uint(0)>>1)/r.Channels/r.Height || len(r.Data) != r.Width*r.Height*r.Channels {
		return invalid("raster dimensions/channels must match data length")
	}
	return nil
}

// RasterFromImage composites onto white, preserving non-zero image bounds.
// It does not quantise colours: all off-palette RGB values pack as black.
func RasterFromImage(src image.Image) (Raster, error) {
	if src == nil {
		return Raster{}, invalid("image is nil")
	}
	b := src.Bounds()
	w, h := b.Dx(), b.Dy()
	if w <= 0 || h <= 0 || uint64(w) > maxU32 || uint64(h) > maxU32 || w > int(^uint(0)>>1)/4/h {
		return Raster{}, invalid("invalid image dimensions")
	}
	dst := image.NewRGBA(image.Rect(0, 0, w, h))
	draw.Draw(dst, dst.Bounds(), image.NewUniform(color.White), image.Point{}, draw.Src)
	draw.Draw(dst, dst.Bounds(), src, b.Min, draw.Over)
	return Raster{Width: w, Height: h, Channels: 4, Data: dst.Pix}, nil
}

// PackPixels packs four exact BWRY colour codes per byte, padding every row.
// Only the verified device number 140 is supported.
func PackPixels(r Raster, deviceNumber uint16) ([]byte, error) {
	if err := r.validate(); err != nil {
		return nil, err
	}
	if deviceNumber != 140 {
		return nil, invalid("unsupported device number %d", deviceNumber)
	}
	stride := r.Width / 4
	if r.Width%4 != 0 {
		stride++
	}
	out := make([]byte, stride*r.Height)
	for y := 0; y < r.Height; y++ {
		for x := 0; x < r.Width; x++ {
			p := (y*r.Width + x) * r.Channels
			red, green, blue := r.Data[p], r.Data[p+1], r.Data[p+2]
			var code byte
			switch {
			case red == 255 && green == 255 && blue == 255:
				code = 1
			case red == 255 && green == 255 && blue == 0:
				code = 2
			case red == 255 && green == 0 && blue == 0:
				code = 3
			}
			out[y*stride+x/4] |= code << (6 - 2*(x%4))
		}
	}
	return out, nil
}

// RotateCounterClockwise rotates a raster by 90 degrees into a new allocation.
func RotateCounterClockwise(r Raster) (Raster, error) {
	if err := r.validate(); err != nil {
		return Raster{}, err
	}
	out := Raster{Width: r.Height, Height: r.Width, Channels: r.Channels, Data: make([]byte, len(r.Data))}
	for y := 0; y < r.Height; y++ {
		for x := 0; x < r.Width; x++ {
			src := (y*r.Width + x) * r.Channels
			dst := ((r.Width-1-x)*r.Height + y) * r.Channels
			copy(out.Data[dst:dst+r.Channels], r.Data[src:src+r.Channels])
		}
	}
	return out, nil
}

// EncodeRLE encodes each half separately, with greedy runs of at most 255.
func EncodeRLE(data []byte) []byte {
	out := []byte{}
	for _, part := range [][]byte{data[:len(data)/2], data[len(data)/2:]} {
		for i := 0; i < len(part); {
			n := 1
			for i+n < len(part) && n < 255 && part[i+n] == part[i] {
				n++
			}
			out = append(out, byte(n), part[i])
			i += n
		}
	}
	return out
}

type ImageRecord struct {
	Image Raster
	X, Y  int64
}
type EncodeOptions struct {
	DisableCompression bool
	DeviceNumber       uint16 // Zero selects the verified device 140.
}

// EncodeContainer builds an XTEK container. Records use native buffer orientation.
func EncodeContainer(images []ImageRecord, options EncodeOptions) ([]byte, error) {
	if len(images) < 1 || len(images) > 255 {
		return nil, invalid("expected 1–255 images")
	}
	device := options.DeviceNumber
	if device == 0 {
		device = 140
	}
	records := make([][]byte, 0, len(images))
	total := uint64(13 + 4*len(images))
	for _, record := range images {
		if record.X < 0 || record.Y < 0 || record.X > maxU32 || record.Y > maxU32 {
			return nil, invalid("coordinates must fit u32")
		}
		raw, err := PackPixels(record.Image, device)
		if err != nil {
			return nil, err
		}
		payload := raw
		var compressed byte
		if !options.DisableCompression {
			if rle := EncodeRLE(raw); len(rle) <= len(raw) {
				payload = rle
				compressed = 1
			}
		}
		total += 21 + uint64(len(payload))
		if total > maxU32 || total > uint64(^uint(0)>>1) {
			return nil, invalid("container too large")
		}
		b := make([]byte, 21+len(payload))
		binary.BigEndian.PutUint32(b, uint32(record.X))
		binary.BigEndian.PutUint32(b[4:], uint32(record.Y))
		put32(b[8:], record.Image.Width)
		put32(b[12:], record.Image.Height)
		b[16] = compressed
		put32(b[17:], len(payload))
		copy(b[21:], payload)
		records = append(records, b)
	}
	out := make([]byte, int(total))
	copy(out, "XTEK")
	put32(out[8:], len(out))
	out[12] = byte(len(images))
	offset := 13 + 4*len(images)
	for i, record := range records {
		put32(out[13+4*i:], offset)
		copy(out[offset:], record)
		offset += len(record)
	}
	binary.BigEndian.PutUint32(out[4:], checksum(out[12:]))
	return out, nil
}

// EncodePSJ213 accepts a 250×122 landscape raster and includes the required rotation.
func EncodePSJ213(r Raster, options EncodeOptions) ([]byte, error) {
	if r.Width != 250 || r.Height != 122 {
		return nil, invalid("PSJ-213 source must be 250×122")
	}
	rotated, err := RotateCounterClockwise(r)
	if err != nil {
		return nil, err
	}
	return EncodeContainer([]ImageRecord{{Image: rotated}}, options)
}

func command(code byte, payload ...byte) []byte {
	out := append([]byte{'X', 'T', 'E', 1, byte(7 + len(payload)), 0, code}, payload...)
	out[5] = byte(checksum(out[6:]))
	return out
}
func Allocate(total uint32) ([]byte, error) {
	if total == 0 || total > BatchSize {
		return nil, invalid("single allocation requires 1–%d bytes", BatchSize)
	}
	b := make([]byte, 4)
	binary.BigEndian.PutUint32(b, total)
	return command(1, b...), nil
}
func AllocateBatch(total, offset, length uint32) ([]byte, error) {
	if length == 0 || length > BatchSize || uint64(offset)+uint64(length) > uint64(total) {
		return nil, invalid("invalid batch bounds")
	}
	b := make([]byte, 12)
	binary.BigEndian.PutUint32(b, total)
	binary.BigEndian.PutUint32(b[4:], offset)
	binary.BigEndian.PutUint32(b[8:], length)
	return command(1, b...), nil
}
func Verify() []byte { return command(2) }
func Refresh(multiScreen bool) []byte {
	if multiScreen {
		return command(4, 3, 3)
	}
	return command(4, 0)
}

// ApplyFirmware builds a frame only. Firmware uploading is not implemented.
func ApplyFirmware() []byte { return append(command(5), 0) }

func DataPackets(batch []byte) ([][]byte, error) {
	if len(batch) == 0 || len(batch) > BatchSize {
		return nil, invalid("batch must contain 1–%d bytes", BatchSize)
	}
	total := (len(batch) + PacketDataSize - 1) / PacketDataSize
	packets := make([][]byte, total)
	for i := range packets {
		start := i * PacketDataSize
		end := min(start+PacketDataSize, len(batch))
		b := make([]byte, 9+end-start)
		copy(b, "XTE")
		b[3] = 2
		binary.BigEndian.PutUint16(b[4:], uint16(len(b)))
		b[7] = byte(total)
		b[8] = byte(i)
		copy(b[9:], batch[start:end])
		b[6] = byte(checksum(b[7:]))
		packets[i] = b
	}
	return packets, nil
}

// SplitWrites returns owned chunks, at most writeSize bytes each.
func SplitWrites(frame []byte, writeSize int) ([][]byte, error) {
	if writeSize < 1 || writeSize > MaxWriteSize {
		return nil, invalid("write size must be 1–244")
	}
	var chunks [][]byte
	for i := 0; i < len(frame); i += writeSize {
		chunks = append(chunks, bytes.Clone(frame[i:min(i+writeSize, len(frame))]))
	}
	return chunks, nil
}

// Response is a validated response; its byte storage is private and excludes padding.
type Response struct {
	Command, Status byte
	raw             []byte
}

func (r Response) Bytes() []byte { return bytes.Clone(r.raw) }
func ParseResponse(notification []byte) (Response, bool) {
	if len(notification) < 8 || string(notification[:3]) != "XTE" || notification[3] != 4 {
		return Response{}, false
	}
	n := int(notification[4])
	if n < 8 || n > len(notification) || byte(checksum(notification[6:n])) != notification[5] {
		return Response{}, false
	}
	return Response{Command: notification[6], Status: notification[7], raw: bytes.Clone(notification[:n])}, true
}
func (r Response) MissingPackets(total int) ([]int, error) {
	if total < 0 || total > 255 {
		return nil, invalid("packet count must be 0–255")
	}
	// Revalidate the exported metadata as callers can modify those fields.
	if len(r.raw) < 8 || r.Command != r.raw[6] || r.Status != r.raw[7] {
		return nil, invalid("invalid response")
	}
	offset := 8
	if r.Command == 2 {
		offset = 7
	} else if (r.Command != 4 && r.Command != 5) || r.Status != 0x68 {
		return nil, invalid("response has no packet bitmap")
	}
	bitmap := r.raw[offset:]
	missing := []int{}
	for i := 0; i < total; i++ {
		if i/8 >= len(bitmap) || bitmap[i/8]&(0x80>>uint(i%8)) == 0 {
			missing = append(missing, i)
		}
	}
	return missing, nil
}

type Advertisement struct {
	RecordType, HardwareRevision            byte
	Firmware                                string
	DeviceNumber                            uint16
	BatteryPercent, ChipType, TransmitPower byte
}

// ParseAdvertisement expects manufacturer data INCLUDING its two company-ID bytes.
func ParseAdvertisement(data []byte) (Advertisement, bool) {
	if len(data) < 15 || data[0] != 0x58 || (data[1] != 0x54 && data[1] != 0x52) {
		return Advertisement{}, false
	}
	switch data[2] {
	case 0xfd, 0xfe, 0xfc, 4:
	default:
		return Advertisement{}, false
	}
	return Advertisement{data[2], data[3], fmt.Sprintf("%d.%d.%d", data[4]>>4, data[4]&15, data[5]), binary.BigEndian.Uint16(data[6:]), data[8], data[9] >> 4, data[9] & 15}, true
}
func AddressFromName(name string) (string, error) {
	if len(name) != 12 {
		return "", invalid("label name must be twelve hex digits")
	}
	b, err := hex.DecodeString(name)
	if err != nil {
		return "", invalid("label name must be twelve hex digits")
	}
	parts := make([]string, len(b))
	for i, v := range b {
		parts[len(b)-1-i] = fmt.Sprintf("%02X", v)
	}
	return strings.Join(parts, ":"), nil
}
