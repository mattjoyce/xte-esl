# TypeScript port

Not started. Contract:

- Implement the codec from `docs/protocol.md` only. Do not read vendor code.
- Ship a `selftest` that loads `../testdata/reference.json` and reproduces
  every vector byte for byte.
- BLE transport comes after the codec passes: Web Bluetooth in the browser,
  `noble` or similar in Node.
