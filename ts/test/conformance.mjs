import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import * as sdk from '../dist/index.js';
const ref = JSON.parse(await readFile(new URL('../../testdata/reference.json', import.meta.url), 'utf8'));
const hex = bytes => Buffer.from(bytes).toString('hex');
const image = pixels => ({ width: ref.w, height: ref.h, channels: 3,
  data: Uint8Array.from([...pixels].flatMap(index => ref.palette[Number(index)])) });
let checks = 0;
function check(name, actual, expected) { assert.deepEqual(actual, expected, name); checks++; }
const container = sdk.encodeContainer([{ image: image(ref.pixels) }]);
check('container', hex(container), ref.container);
check('container_raw', hex(sdk.encodeContainer([{ image: image(ref.pixels) }], { compress: false })), ref.container_raw);
check('container_bands', hex(sdk.encodeContainer([{ image: image(ref.pixels_bands) }])), ref.container_bands);
check('alloc', hex(sdk.allocate(container.length)), ref.alloc);
check('alloc_batch', hex(sdk.allocate(300000, { offset: 204800, length: 95200 })), ref.alloc_batch);
check('verify', hex(sdk.verify()), ref.verify);
check('refresh1', hex(sdk.refresh()), ref.refresh1);
check('refresh2', hex(sdk.refresh(2)), ref.refresh2);
check('ota', hex(sdk.applyFirmware()), ref.ota);
const packets = sdk.dataPackets(container);
for (const [index, writes] of Object.entries(ref.packets)) {
  check(`packet ${index}`, sdk.splitWrites(packets[Number(index)]).map(hex), writes);
}
// second generation: the real PSJ-213 push shape and observed response frames
const portrait = ref.portrait;
check('portrait', hex(sdk.encodeContainer([{ image: { width: portrait.w, height: portrait.h, channels: 3,
  data: Uint8Array.from([...portrait.pixels].flatMap(index => portrait.palette[Number(index)])) } }])), portrait.container);
for (const [name, frame] of Object.entries(ref.responses)) {
  const parsed = sdk.parseResponse(Buffer.from(frame, 'hex'));
  check(`response ${name}`, [parsed?.command, parsed?.status], ref.responses_decoded[name]);
}
console.log(`All ${checks} conformance checks passed (12 vendor, ${checks - 12} second generation).`);
