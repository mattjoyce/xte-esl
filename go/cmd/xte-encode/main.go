// xte-encode converts a prepared 250×122 PNG or JPEG to an XTEK container.
package main

import (
	"flag"
	"fmt"
	"image"
	_ "image/jpeg"
	_ "image/png"
	"os"

	xte "github.com/mattjoyce/xte-esl/go"
)

func main() {
	output := flag.String("out", "image.xtek", "output container path")
	raw := flag.Bool("raw", false, "disable RLE compression")
	flag.Parse()
	if flag.NArg() != 1 {
		fmt.Fprintln(os.Stderr, "usage: xte-encode [-out image.xtek] [-raw] image.png")
		os.Exit(2)
	}
	if err := run(flag.Arg(0), *output, *raw); err != nil {
		fmt.Fprintln(os.Stderr, err)
		os.Exit(1)
	}
}
func run(input, output string, raw bool) error {
	file, err := os.Open(input)
	if err != nil {
		return err
	}
	defer file.Close()
	src, _, err := image.Decode(file)
	if err != nil {
		return err
	}
	raster, err := xte.RasterFromImage(src)
	if err != nil {
		return err
	}
	container, err := xte.EncodePSJ213(raster, xte.EncodeOptions{DisableCompression: raw})
	if err != nil {
		return err
	}
	if err = os.WriteFile(output, container, 0644); err != nil {
		return err
	}
	fmt.Printf("Wrote %d bytes to %s\n", len(container), output)
	return nil
}
