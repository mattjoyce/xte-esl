import { test, expect } from 'bun:test';
import * as sdk from '../dist/index.js';
const bytes = (hex: string) => Uint8Array.from(Buffer.from(hex.replaceAll(' ', ''), 'hex'));

test('packs exact colours, black fallback and per-row padding', () => {
  const image = { width: 6, height: 1, channels: 3 as const,
    data: Uint8Array.of(255,255,255, 255,255,0, 255,0,0, 0,0,0, 255,255,254, 255,255,255) };
  expect(sdk.packPixels(image)).toEqual(bytes('6c10'));
  expect(() => sdk.packPixels(image, 97)).toThrow('unsupported');
  expect(() => sdk.packPixels({ ...image, height: 2 })).toThrow();
});
test('CCW orientation puts the right edge in the first buffer row', () => {
  const image = { width: 3, height: 2, channels: 3 as const,
    data: Uint8Array.from([1,2,3,4,5,6].flatMap(n => [n,n,n])) };
  const rotated = sdk.rotateCounterClockwise(image);
  expect(rotated.width).toBe(2); expect(rotated.height).toBe(3);
  expect([...rotated.data].filter((_, i) => i % 3 === 0)).toEqual([3,6,2,5,1,4]);
  const container = sdk.encodePsj213({ width: 250, height: 122, channels: 4,
    data: new Uint8ClampedArray(250 * 122 * 4).fill(255) }, { compress: false });
  const view = new DataView(container.buffer);
  expect(view.getUint32(25)).toBe(122);
  expect(view.getUint32(29)).toBe(250);
  expect(view.getUint32(34)).toBe(7750);
});
test('RLE handles odd halves, long runs and equality', () => {
  expect(sdk.encodeRle(Uint8Array.of(9,9,9,9,1,1,2,2,2,2,2,2))).toEqual(bytes('040902010602'));
  expect(sdk.encodeRle(new Uint8Array(513).fill(7))).toEqual(bytes('ff070107ff070207'));
  expect(sdk.encodeRle(Uint8Array.of(1))).toEqual(bytes('0101'));
  const image = { width: 8, height: 2, channels: 3 as const, data: new Uint8Array(48).fill(255) };
  expect(sdk.encodeContainer([{ image }])).toEqual(bytes(
    '5854454b000000cf0000002a010000001100000000000000000000000800000002010000000402550255'));
});
test('multiple image offsets, coordinates and checksum', () => {
  const image = { width: 1, height: 1, channels: 3 as const, data: Uint8Array.of(255,0,0) };
  const container = sdk.encodeContainer([{ image }, { image, x: 10, y: 20 }], { compress: false });
  const view = new DataView(container.buffer);
  expect(container[12]).toBe(2);
  expect(view.getUint32(13)).toBe(21); expect(view.getUint32(17)).toBe(43);
  expect(view.getUint32(43)).toBe(10); expect(view.getUint32(47)).toBe(20);
  expect(view.getUint32(4)).toBe(container.subarray(12).reduce((a,b) => a+b, 0));
});
test('observed responses, notification padding, checksums and bitmap offsets', () => {
  const alloc = sdk.parseResponse(bytes('5854450409bd01ffbd0000000000000000'))!;
  expect(alloc.command).toBe(1); expect(alloc.status).toBe(255); expect(alloc.bytes.length).toBe(9);
  expect(sdk.parseResponse(bytes('58544504080304ff0000000000000000'))?.status).toBe(255);
  expect(sdk.parseResponse(bytes('58544504080204ff'))).toBeUndefined();
  expect(sdk.parseResponse(bytes('58544504100304ff'))).toBeUndefined();
  expect(sdk.parseResponse(bytes('58544502080304ff'))).toBeUndefined();
  expect(sdk.missingPackets(sdk.parseResponse(bytes('5854450409490468dd'))!, 8)).toEqual([2,6]);
  expect(sdk.missingPackets(sdk.parseResponse(bytes('5854450408df02dd'))!, 8)).toEqual([2,6]);
  expect(sdk.missingPackets(sdk.parseResponse(bytes('5854450408df02dd'))!, 9)).toEqual([2,6,8]);
  expect(sdk.missingPackets(sdk.parseResponse(bytes('5854450409490468ddffff'))!, 10)).toEqual([2,6,8,9]);
  expect(sdk.missingPackets(sdk.parseResponse(bytes('58544504086c0468'))!, 3)).toEqual([0,1,2]);
});
test('advertisement decoding and input bounds', () => {
  expect(sdk.parseAdvertisement(bytes('5852fd024002008c63060102ffff1c'))).toMatchObject({
    firmware: '4.0.2', hardwareRevision: 2, deviceNumber: 140, batteryPercent: 99, chipType: 0, transmitPower: 6,
  });
  expect(sdk.parseAdvertisement(bytes('5852ff01'))).toBeUndefined();
  expect(sdk.addressFromName('36330b001d9f')).toBe('9F:1D:00:0B:33:36');
  expect(() => sdk.allocate(204801)).toThrow();
  expect(() => sdk.allocate(10, { offset: 9, length: 2 })).toThrow();
  expect(() => sdk.dataPackets(new Uint8Array(204801))).toThrow();
  expect(() => sdk.splitWrites(bytes('01'), 0)).toThrow();
});
test('invalid codec inputs share an SDK error type and unknown devices are refused', () => {
  const image = { width: 1, height: 1, channels: 3 as const, data: Uint8Array.of(255,255,255) };
  for (const device of [0, 97, 102, 106, 109, 119, 122, 141, 65535]) {
    expect(() => sdk.packPixels(image, device)).toThrow(sdk.XteError);
  }
  for (const invalid of [
    () => sdk.packPixels({ ...image, width: 2 }),
    () => sdk.encodeContainer([]),
    () => sdk.encodeContainer([{ image, x: -1 }]),
    () => sdk.encodePsj213(image),
    () => sdk.allocate(204801),
    () => sdk.dataPackets(new Uint8Array()),
    () => sdk.splitWrites(Uint8Array.of(1), 0),
    () => sdk.refresh(0),
    () => sdk.addressFromName('bad'),
  ]) expect(invalid).toThrow(sdk.XteError);
});
