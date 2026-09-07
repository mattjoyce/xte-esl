# Web label push

A single page that draws a 250x122 four-ink label and pushes it to a tag
with the TypeScript port's Web Bluetooth transport. No server-side code.

```sh
cd ts
bun run web:build          # bundles web/app.ts -> web/app.js
python3 -m http.server 8765 --directory ../web   # or any static server
```

Open http://localhost:8765 in Chrome or Edge. For a phone, serve over
HTTPS from any origin you control, because Web Bluetooth refuses plain HTTP
off localhost. Safari, iOS and Firefox cannot do Web Bluetooth.

`app.js` is a build product; rebuild after editing `app.ts` or the port.
