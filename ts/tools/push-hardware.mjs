// Push a raw 250x122 RGB image to a real tag through the TypeScript uploader,
// using tools/bleak-bridge.py for the radio.
//   node tools/push-hardware.mjs <address> <image.rgb>
import { spawn } from 'node:child_process';
import { readFile } from 'node:fs/promises';
import readline from 'node:readline';
import { encodePsj213, uploadContainer } from '../dist/index.js';

const [address, path] = process.argv.slice(2);
const data = new Uint8Array(await readFile(path));
const container = encodePsj213({ width: 250, height: 122, channels: 3, data });
console.log(`container ${container.length} B`);

const py = spawn(new URL('../../.venv/bin/python', import.meta.url).pathname,
  [new URL('./bleak-bridge.py', import.meta.url).pathname], { stdio: ['pipe', 'pipe', 'inherit'] });
const lines = readline.createInterface({ input: py.stdout });
const waiters = [];
let onNotify = () => {}, onDisc = () => {};
lines.on('line', line => {
  const ev = JSON.parse(line);
  if (ev.ev === 'notify') { console.log('<-', ev.data.match(/../g).join(' ')); onNotify(Buffer.from(ev.data, 'hex')); return; }
  if (ev.ev === 'disconnected') { onDisc(); return; }
  const w = waiters.shift();
  if (!w) return;
  ev.ev === 'error' ? w.reject(new Error(ev.message)) : w.resolve(ev);
});
const call = msg => new Promise((resolve, reject) => { waiters.push({ resolve, reject }); py.stdin.write(JSON.stringify(msg) + '\n'); });

const transport = {
  writeSize: 20,
  async connect(notify, disconnect) {
    onNotify = notify; onDisc = disconnect;
    const r = await call({ op: 'connect', address });
    this.writeSize = Math.min(244, r.mtu - 3);
    console.log(`connected, mtu ${r.mtu}, write size ${this.writeSize}`);
  },
  write: d => call({ op: 'write', data: Buffer.from(d).toString('hex') }).then(() => {}),
  disconnect: () => call({ op: 'disconnect' }).then(() => {}),
};
const t0 = Date.now();
try {
  await uploadContainer(transport, container);
  console.log(`refresh accepted after ${Date.now() - t0} ms`);
} finally {
  py.stdin.end();
}
