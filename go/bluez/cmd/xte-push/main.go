// xte-push uploads an XTEK container using the optional Linux BlueZ transport.
package main

import (
	"context"
	"flag"
	"fmt"
	"os"
	"os/signal"
	"time"

	xte "github.com/mattjoyce/xte-esl/go"
	"github.com/mattjoyce/xte-esl/go/bluez"
)

func main() {
	adapter := flag.String("adapter", "hci0", "Linux Bluetooth adapter")
	timeout := flag.Duration("timeout", 60*time.Second, "overall upload timeout")
	commandTimeout := flag.Duration("command-timeout", 5*time.Second, "connection and command timeout")
	flag.Parse()
	if flag.NArg() != 2 {
		fmt.Fprintln(os.Stderr, "usage: xte-push [flags] MAC image.xtek")
		os.Exit(2)
	}
	if *timeout <= 0 || *commandTimeout <= 0 {
		fmt.Fprintln(os.Stderr, "timeouts must be positive")
		os.Exit(2)
	}
	if err := run(flag.Arg(0), flag.Arg(1), *adapter, *timeout, *commandTimeout); err != nil {
		fmt.Fprintln(os.Stderr, err)
		os.Exit(1)
	}
}
func run(address, path, adapter string, timeout, commandTimeout time.Duration) error {
	data, err := os.ReadFile(path)
	if err != nil {
		return err
	}
	transport, err := bluez.New(address, adapter)
	if err != nil {
		return err
	}
	uploader, err := xte.NewUploader(transport)
	if err != nil {
		return err
	}
	interrupt, stop := signal.NotifyContext(context.Background(), os.Interrupt)
	defer stop()
	ctx, cancel := context.WithTimeout(interrupt, timeout)
	defer cancel()
	start := time.Now()
	if err = uploader.Upload(ctx, data, xte.UploadOptions{CommandTimeout: commandTimeout}); err != nil {
		return err
	}
	fmt.Printf("Refresh accepted in %s; allow about 20 seconds for the panel to settle.\n", time.Since(start).Round(time.Millisecond))
	return nil
}
