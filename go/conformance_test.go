package xte_test

import (
	"github.com/mattjoyce/xte-esl/go/internal/conformance"
	"os"
	"testing"
)

func TestReferenceVectors(t *testing.T) {
	f, err := os.Open("../testdata/reference.json")
	if err != nil {
		t.Fatal(err)
	}
	defer f.Close()
	n, err := conformance.Run(f)
	if err != nil {
		t.Fatal(err)
	}
	if n == 0 {
		t.Fatal("no checks")
	}
	t.Logf("%d reference checks", n)
}
