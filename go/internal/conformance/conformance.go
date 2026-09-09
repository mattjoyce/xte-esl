// Package conformance checks the shared vendor and hardware reference vectors.
package conformance

import (
	"bytes"
	"encoding/hex"
	"encoding/json"
	"fmt"
	"io"
	"sort"
	"strconv"

	xte "github.com/mattjoyce/xte-esl/go"
)

type rasterVector struct {
	W, H              int
	Palette           [][]byte
	Pixels, Container string
}
type vectors struct {
	W, H                            int
	Palette                         [][]byte
	Pixels                          string
	PixelsBands                     string `json:"pixels_bands"`
	Container                       string
	ContainerRaw                    string `json:"container_raw"`
	ContainerBands                  string `json:"container_bands"`
	Alloc                           string
	AllocBatch                      string `json:"alloc_batch"`
	Verify, Refresh1, Refresh2, OTA string
	Packets                         map[string][]string
	Portrait                        rasterVector
	RLETie                          struct {
		W, H              int
		Packed, Container string
	} `json:"rle_tie"`
	Responses        map[string]string
	ResponsesDecoded map[string][]byte `json:"responses_decoded"`
}

func raster(w, h int, palette [][]byte, pixels string) (xte.Raster, error) {
	data := []byte{}
	for _, p := range pixels {
		i := int(p - '0')
		if i < 0 || i >= len(palette) || len(palette[i]) != 3 {
			return xte.Raster{}, fmt.Errorf("invalid palette index")
		}
		data = append(data, palette[i]...)
	}
	return xte.Raster{Width: w, Height: h, Channels: 3, Data: data}, nil
}

// Run checks every vector and returns the number of byte-for-byte checks.
func Run(input io.Reader) (int, error) {
	var v vectors
	if err := json.NewDecoder(input).Decode(&v); err != nil {
		return 0, err
	}
	checks := 0
	check := func(name string, actual []byte, want string) error {
		expected, err := hex.DecodeString(want)
		if err != nil {
			return fmt.Errorf("%s: %w", name, err)
		}
		if !bytes.Equal(actual, expected) {
			return fmt.Errorf("%s differs: got %d bytes, want %d", name, len(actual), len(expected))
		}
		checks++
		return nil
	}
	var container []byte
	for _, c := range []struct {
		name, pixels, want string
		disable            bool
	}{
		{"container", v.Pixels, v.Container, false}, {"container_raw", v.Pixels, v.ContainerRaw, true}, {"container_bands", v.PixelsBands, v.ContainerBands, false},
	} {
		image, err := raster(v.W, v.H, v.Palette, c.pixels)
		if err != nil {
			return checks, err
		}
		encoded, err := xte.EncodeContainer([]xte.ImageRecord{{Image: image}}, xte.EncodeOptions{DisableCompression: c.disable})
		if err != nil {
			return checks, err
		}
		if err = check(c.name, encoded, c.want); err != nil {
			return checks, err
		}
		if c.name == "container" {
			container = encoded
		}
	}
	alloc, err := xte.Allocate(uint32(len(container)))
	if err != nil {
		return checks, err
	}
	batch, err := xte.AllocateBatch(300000, 204800, 95200)
	if err != nil {
		return checks, err
	}
	for _, c := range []struct {
		name   string
		actual []byte
		want   string
	}{
		{"alloc", alloc, v.Alloc}, {"alloc_batch", batch, v.AllocBatch}, {"verify", xte.Verify(), v.Verify},
		{"refresh1", xte.Refresh(false), v.Refresh1}, {"refresh2", xte.Refresh(true), v.Refresh2}, {"ota", xte.ApplyFirmware(), v.OTA},
	} {
		if err := check(c.name, c.actual, c.want); err != nil {
			return checks, err
		}
	}
	packets, err := xte.DataPackets(container)
	if err != nil {
		return checks, err
	}
	keys := make([]string, 0, len(v.Packets))
	for key := range v.Packets {
		keys = append(keys, key)
	}
	sort.Strings(keys)
	for _, key := range keys {
		index, err := strconv.Atoi(key)
		if err != nil || index < 0 || index >= len(packets) {
			return checks, fmt.Errorf("bad packet index %q", key)
		}
		writes, err := xte.SplitWrites(packets[index], 244)
		if err != nil {
			return checks, err
		}
		if len(writes) != len(v.Packets[key]) {
			return checks, fmt.Errorf("packet %s write count differs", key)
		}
		for i, write := range writes {
			if err = check(fmt.Sprintf("packet %s write %d", key, i), write, v.Packets[key][i]); err != nil {
				return checks, err
			}
		}
	}
	portrait, err := raster(v.Portrait.W, v.Portrait.H, v.Portrait.Palette, v.Portrait.Pixels)
	if err != nil {
		return checks, err
	}
	encoded, err := xte.EncodeContainer([]xte.ImageRecord{{Image: portrait}}, xte.EncodeOptions{})
	if err != nil {
		return checks, err
	}
	if err = check("portrait", encoded, v.Portrait.Container); err != nil {
		return checks, err
	}
	packed, err := hex.DecodeString(v.RLETie.Packed)
	if err != nil {
		return checks, err
	}
	palette := [][]byte{{0, 0, 0}, {255, 255, 255}, {255, 255, 0}, {255, 0, 0}}
	pixels := []byte{}
	for _, b := range packed {
		for shift := 6; shift >= 0; shift -= 2 {
			pixels = append(pixels, palette[(b>>uint(shift))&3]...)
		}
	}
	tie := xte.Raster{Width: v.RLETie.W, Height: v.RLETie.H, Channels: 3, Data: pixels}
	encoded, err = xte.EncodeContainer([]xte.ImageRecord{{Image: tie}}, xte.EncodeOptions{})
	if err != nil {
		return checks, err
	}
	if err = check("rle_tie", encoded, v.RLETie.Container); err != nil {
		return checks, err
	}
	for name, wire := range v.Responses {
		data, err := hex.DecodeString(wire)
		if err != nil {
			return checks, err
		}
		response, ok := xte.ParseResponse(data)
		expected := v.ResponsesDecoded[name]
		if !ok || len(expected) != 2 || response.Command != expected[0] || response.Status != expected[1] {
			return checks, fmt.Errorf("response %s differs", name)
		}
		checks++
	}
	return checks, nil
}
