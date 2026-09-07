# Go port

Not started. Contract:

- Implement the codec from `docs/protocol.md` only. Do not read vendor code.
- Ship a `selftest` that loads `../testdata/reference.json` and reproduces
  every vector byte for byte.
- BLE transport comes after the codec passes, via `tinygo.org/x/bluetooth`.
