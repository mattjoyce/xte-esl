// Label editor + Web Bluetooth push for XTE tags. Bundled by `bun run web:build`.
import { encodePsj213, addressFromName, type Raster } from '../ts/src/index.js';
import { requestWebBluetoothTransport } from '../ts/src/web-bluetooth.js';
import { uploadContainer } from '../ts/src/upload.js';

const W = 250, H = 122;
const INK = { white: [255, 255, 255], black: [0, 0, 0], red: [255, 0, 0], yellow: [255, 255, 0] } as const;
type InkName = keyof typeof INK;
const CSS: Record<InkName, string> = { white: '#ffffff', black: '#000000', red: '#ff0000', yellow: '#ffff00' };

const $ = <T extends HTMLElement>(id: string) => document.getElementById(id) as T;
const canvas = $<HTMLCanvasElement>('label');
const ctx = canvas.getContext('2d', { willReadFrequently: true })!;
const fields = {
  name: $<HTMLInputElement>('name'), price: $<HTMLInputElement>('price'), note: $<HTMLInputElement>('note'),
  priceInk: $<HTMLSelectElement>('priceInk'), bandInk: $<HTMLSelectElement>('bandInk'),
  tag: $<HTMLInputElement>('tag'),
};
const status = $<HTMLDivElement>('status');
const pushBtn = $<HTMLButtonElement>('push');
const imageInput = $<HTMLInputElement>('image');
let imported: ImageBitmap | undefined;

function log(line: string, cls = '') {
  const p = document.createElement('div');
  p.textContent = line; if (cls) p.className = cls;
  status.appendChild(p); status.scrollTop = status.scrollHeight;
}

/** Snap every canvas pixel to the nearest of the four inks, in place. */
function quantise() {
  const img = ctx.getImageData(0, 0, W, H), d = img.data;
  const inks = Object.values(INK);
  for (let i = 0; i < d.length; i += 4) {
    let best = 0, bd = Infinity;
    for (let k = 0; k < inks.length; k++) {
      const [r, g, b] = inks[k];
      const dist = (d[i] - r) ** 2 + (d[i + 1] - g) ** 2 + (d[i + 2] - b) ** 2;
      if (dist < bd) { bd = dist; best = k; }
    }
    [d[i], d[i + 1], d[i + 2]] = inks[best]; d[i + 3] = 255;
  }
  ctx.putImageData(img, 0, 0);
}

function fit(text: string, family: string, maxPx: number, minPx: number, width: number, weight = 'bold') {
  for (let px = maxPx; px >= minPx; px -= 1) {
    ctx.font = `${weight} ${px}px ${family}`;
    if (ctx.measureText(text).width <= width) return px;
  }
  return minPx;
}

function draw() {
  ctx.fillStyle = CSS.white; ctx.fillRect(0, 0, W, H);
  if (imported) {
    ctx.drawImage(imported, 0, 0, W, H);
    quantise();
    return;
  }
  ctx.textBaseline = 'top';
  const name = fields.name.value.trim() || 'Product name';
  const price = fields.price.value.trim() || '0.00';
  const note = fields.note.value.trim();
  const priceInk = fields.priceInk.value as InkName;
  const bandInk = fields.bandInk.value as InkName;
  // name, top
  ctx.fillStyle = CSS.black;
  const namePx = fit(name, 'sans-serif', 22, 12, W - 16);
  ctx.font = `bold ${namePx}px sans-serif`; ctx.fillText(name, 8, 6);
  // price, large
  const pricePx = fit(price, 'sans-serif', 60, 24, W - 16);
  ctx.fillStyle = CSS[priceInk]; ctx.font = `bold ${pricePx}px sans-serif`;
  ctx.fillText(price, 8, 34);
  // band + note at bottom
  ctx.fillStyle = CSS[bandInk]; ctx.fillRect(0, H - 22, W, 22);
  if (note) {
    ctx.fillStyle = bandInk === 'black' ? CSS.white : CSS.black;
    const notePx = fit(note, 'sans-serif', 14, 9, W - 16, 'normal');
    ctx.font = `${notePx}px sans-serif`; ctx.fillText(note, 8, H - 20 + (14 - notePx) / 2);
  }
  quantise();
  try { localStorage.setItem('xte-label', JSON.stringify({ name: fields.name.value, price: fields.price.value, note: fields.note.value, priceInk, bandInk, tag: fields.tag.value })); } catch { /* storage unavailable */ }
}

function raster(): Raster {
  const img = ctx.getImageData(0, 0, W, H);
  return { width: W, height: H, channels: 4, data: img.data };
}

async function push() {
  const container = encodePsj213(raster());
  const name = fields.tag.value.trim().replace(/[^0-9a-f]/gi, '');
  pushBtn.disabled = true;
  status.textContent = '';
  log(`container ${container.length} B, ${Math.ceil(container.length / 1211)} packets`);
  try {
    if (!('bluetooth' in navigator)) throw new Error('This browser has no Web Bluetooth. Use Chrome or Edge on Android, Windows, macOS, Linux or ChromeOS.');
    log(name ? `choose tag ${name.toUpperCase()} (${addressFromName(name)})` : 'choose a tag in the picker');
    const transport = await requestWebBluetoothTransport(name || undefined);
    log(`connecting to ${transport.device.name ?? 'tag'} ...`);
    const t0 = performance.now();
    await uploadContainer(transport, container);
    log(`refresh accepted after ${Math.round(performance.now() - t0)} ms. The panel now flickers for about 20 s; that is the refresh.`, 'ok');
  } catch (e) {
    log(`failed: ${(e as Error).message}`, 'err');
  } finally {
    pushBtn.disabled = false;
  }
}

for (const el of Object.values(fields)) el.addEventListener('input', () => { imported = undefined; imageInput.value = ''; draw(); });
imageInput.addEventListener('change', async () => {
  const file = imageInput.files?.[0]; if (!file) return;
  imported = await createImageBitmap(file); draw();
});
$<HTMLButtonElement>('clear').addEventListener('click', () => { imported = undefined; imageInput.value = ''; draw(); });
pushBtn.addEventListener('click', push);
$<HTMLButtonElement>('download').addEventListener('click', () => {
  const a = document.createElement('a'); a.download = 'label.png'; a.href = canvas.toDataURL('image/png'); a.click();
});

try {
  const saved = JSON.parse(localStorage.getItem('xte-label') ?? 'null');
  if (saved) { fields.name.value = saved.name ?? ''; fields.price.value = saved.price ?? ''; fields.note.value = saved.note ?? ''; fields.priceInk.value = saved.priceInk ?? 'red'; fields.bandInk.value = saved.bandInk ?? 'yellow'; fields.tag.value = saved.tag ?? ''; }
} catch { /* ignore */ }
if (!('bluetooth' in navigator)) log('No Web Bluetooth in this browser. The editor works; pushing needs Chrome or Edge.', 'err');
if (!window.isSecureContext) log('Not a secure context. Web Bluetooth needs HTTPS or localhost.', 'err');
draw();
