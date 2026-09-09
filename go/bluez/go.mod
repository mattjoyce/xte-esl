module github.com/mattjoyce/xte-esl/go/bluez

go 1.22

require (
	github.com/godbus/dbus/v5 v5.2.2
	github.com/mattjoyce/xte-esl/go v0.0.0
)

require golang.org/x/sys v0.27.0 // indirect

replace github.com/mattjoyce/xte-esl/go => ..
