// Selftest verifies every field in the shared reference vectors, without BLE.
package main

import (
	"flag"
	"fmt"
	"os"

	"github.com/mattjoyce/xte-esl/go/internal/conformance"
)

func main() {
	path := flag.String("vectors", "../testdata/reference.json", "path to shared reference vectors")
	flag.Parse()
	if err := run(*path); err != nil {
		fmt.Fprintln(os.Stderr, err)
		os.Exit(1)
	}
}
func run(path string) error {
	f, err := os.Open(path)
	if err != nil {
		return err
	}
	defer f.Close()
	n, err := conformance.Run(f)
	if err != nil {
		return err
	}
	fmt.Printf("All %d conformance checks passed (including portrait, RLE tie, and observed responses).\n", n)
	return nil
}
