/** Codec implemented from docs/protocol.md; no vendor code dependencies. */
export const SERVICE_UUID = '00002760-08c2-11e1-9073-0e8ac72e1001';
export const WRITE_UUID = '00002760-08c2-11e1-9073-0e8ac72e0001';
export const NOTIFY_UUID = '00002760-08c2-11e1-9073-0e8ac72e0002';
export const BATCH_SIZE = 204800;
export const PACKET_DATA_SIZE = 1211;

function uint(value: number, max: number, name: string): void {
  if (!Number.isInteger(value) || value < 0 || value > max) {
    throw new RangeError(`${name} must be an integer from 0 to ${max}`);
  }
}
function u32(value: number): Uint8Array {
  uint(value, 0xffffffff, 'u32');
  const out = new Uint8Array(4);
  new DataView(out.buffer).setUint32(0, value);
  return out;
}
function sum(bytes: Uint8Array): number {
  return bytes.reduce((a, b) => (a + b) >>> 0, 0);
}
function join(...parts: Uint8Array[]): Uint8Array {
  const out = new Uint8Array(parts.reduce((n, p) => n + p.length, 0));
  let offset = 0;
  for (const part of parts) { out.set(part, offset); offset += part.length; }
  return out;
}
function command(code: number, payload: Uint8Array = new Uint8Array()): Uint8Array {
  const body = Uint8Array.of(code, ...payload);
  return Uint8Array.of(0x58, 0x54, 0x45, 1, 6 + body.length, sum(body) & 255, ...body);
}
export function allocate(totalSize: number, batch?: { offset: number; length: number }): Uint8Array {
  uint(totalSize, 0xffffffff, 'totalSize');
  if (!totalSize) throw new RangeError('Container must not be empty');
  if (batch) {
    uint(batch.offset, totalSize, 'batch offset');
    uint(batch.length, BATCH_SIZE, 'batch length');
    if (!batch.length || batch.offset + batch.length > totalSize) throw new RangeError('Invalid batch bounds');
    return command(1, join(u32(totalSize), u32(batch.offset), u32(batch.length)));
  }
  if (totalSize > BATCH_SIZE) throw new RangeError('Large containers require batch allocation');
  return command(1, u32(totalSize));
}
export const verify = (): Uint8Array => command(2);
export function refresh(screens = 1): Uint8Array {
  uint(screens, 255, 'screens');
  if (!screens) throw new RangeError('At least one screen is required');
  return command(4, screens === 1 ? Uint8Array.of(0) : Uint8Array.of(3, 3));
}
/** Frame only; this SDK does not implement firmware updates. */
export const applyFirmware = (): Uint8Array => join(command(5), Uint8Array.of(0));

export function dataPackets(batch: Uint8Array): Uint8Array[] {
  if (!batch.length || batch.length > BATCH_SIZE) throw new RangeError('Batch must contain 1–204800 bytes');
  const total = Math.ceil(batch.length / PACKET_DATA_SIZE);
  return Array.from({ length: total }, (_, index) => {
    const data = batch.subarray(index * PACKET_DATA_SIZE, (index + 1) * PACKET_DATA_SIZE);
    const packet = new Uint8Array(9 + data.length);
    packet.set([0x58, 0x54, 0x45, 2]);
    new DataView(packet.buffer).setUint16(4, packet.length);
    packet.set([total, index], 7);
    packet.set(data, 9);
    packet[6] = sum(packet.subarray(7)) & 255;
    return packet;
  });
}
export function splitWrites(frame: Uint8Array, writeSize = 244): Uint8Array[] {
  uint(writeSize, 244, 'writeSize');
  if (!writeSize) throw new RangeError('writeSize must be positive');
  const writes: Uint8Array[] = [];
  for (let i = 0; i < frame.length; i += writeSize) writes.push(frame.slice(i, i + writeSize));
  return writes;
}

export interface Raster {
  width: number;
  height: number;
  /** Row-major RGB or RGBA bytes. Alpha is ignored; composite before encoding. */
  data: Uint8Array | Uint8ClampedArray;
  channels: 3 | 4;
}
function validateRaster(image: Raster): void {
  uint(image.width, 0xffffffff, 'width'); uint(image.height, 0xffffffff, 'height');
  if (!image.width || !image.height || ![3, 4].includes(image.channels) ||
      image.data.length !== image.width * image.height * image.channels) {
    throw new RangeError('Raster dimensions/channels must match its data length');
  }
}
export function packPixels(image: Raster, deviceNumber = 140): Uint8Array {
  validateRaster(image);
  uint(deviceNumber, 65535, 'deviceNumber');
  if ([97, 102, 106, 109, 119, 122].includes(deviceNumber)) {
    throw new Error(`Device ${deviceNumber} uses unsupported pixel packing`);
  }
  const stride = Math.ceil(image.width / 4);
  const out = new Uint8Array(stride * image.height);
  for (let y = 0; y < image.height; y++) {
    for (let x = 0; x < image.width; x++) {
      const p = (y * image.width + x) * image.channels;
      const r = image.data[p], g = image.data[p + 1], b = image.data[p + 2];
      const code = r === 255 && g === 255 && b === 255 ? 1 :
        r === 255 && g === 255 && b === 0 ? 2 : r === 255 && g === 0 && b === 0 ? 3 : 0;
      out[y * stride + (x >> 2)] |= code << (6 - 2 * (x % 4));
    }
  }
  return out;
}
export function rotateCounterClockwise(image: Raster): Raster {
  validateRaster(image);
  const data = new Uint8Array(image.data.length);
  for (let y = 0; y < image.height; y++) {
    for (let x = 0; x < image.width; x++) {
      const src = (y * image.width + x) * image.channels;
      const dst = ((image.width - 1 - x) * image.height + y) * image.channels;
      data.set(image.data.subarray(src, src + image.channels), dst);
    }
  }
  return { width: image.height, height: image.width, channels: image.channels, data };
}
export function encodeRle(data: Uint8Array): Uint8Array {
  const out: number[] = [];
  const half = Math.floor(data.length / 2);
  for (const [start, end] of [[0, half], [half, data.length]]) {
    for (let i = start; i < end;) {
      let count = 1;
      while (i + count < end && count < 255 && data[i + count] === data[i]) count++;
      out.push(count, data[i]); i += count;
    }
  }
  return Uint8Array.from(out);
}
export interface ImageRecord {
  image: Raster;
  x?: number;
  y?: number;
}
export interface EncodeOptions { compress?: boolean; deviceNumber?: number }
/** Images must already have native buffer orientation and four-colour RGB values. */
export function encodeContainer(images: readonly ImageRecord[], options: EncodeOptions = {}): Uint8Array {
  if (!images.length || images.length > 255) throw new RangeError('Expected 1–255 images');
  const records = images.map(({ image, x = 0, y = 0 }) => {
    const raw = packPixels(image, options.deviceNumber);
    const rle = options.compress === false ? undefined : encodeRle(raw);
    const compressed = rle !== undefined && rle.length <= raw.length;
    const data = compressed ? rle : raw;
    return join(u32(x), u32(y), u32(image.width), u32(image.height),
      Uint8Array.of(compressed ? 1 : 0), u32(data.length), data);
  });
  let offset = 13 + 4 * records.length;
  const offsets = records.map(record => { const value = u32(offset); offset += record.length; return value; });
  const body = join(Uint8Array.of(records.length), ...offsets, ...records);
  return join(Uint8Array.of(0x58, 0x54, 0x45, 0x4b), u32(sum(body)), u32(12 + body.length), body);
}
/** Prepare a 250×122 landscape PSJ-213 image, including its required CCW rotation. */
export function encodePsj213(image: Raster, options: EncodeOptions = {}): Uint8Array {
  if (image.width !== 250 || image.height !== 122) throw new RangeError('PSJ-213 source must be 250×122');
  return encodeContainer([{ image: rotateCounterClockwise(image) }], options);
}

export interface ResponseFrame {
  command: number;
  status: number;
  /** Declared frame bytes only, excluding notification padding. */
  bytes: Uint8Array;
}
export function parseResponse(notification: Uint8Array): ResponseFrame | undefined {
  if (notification.length < 8 || notification[0] !== 0x58 || notification[1] !== 0x54 ||
      notification[2] !== 0x45 || notification[3] !== 4) return undefined;
  const length = notification[4];
  if (length < 8 || length > notification.length) return undefined;
  const bytes = notification.slice(0, length);
  if ((sum(bytes.subarray(6)) & 255) !== bytes[5]) return undefined;
  return { command: bytes[6], status: bytes[7], bytes };
}
export function missingPackets(response: ResponseFrame, total: number): number[] {
  uint(total, 255, 'packet count');
  const offset = response.command === 2 ? 7 :
    [4, 5].includes(response.command) && response.status === 0x68 ? 8 : -1;
  if (offset < 0) throw new Error('Response does not contain a packet bitmap');
  const bitmap = response.bytes.subarray(offset);
  // Bits absent from the declared frame are missing too; never use padding.
  return Array.from({ length: total }, (_, i) => i).filter(i => !((bitmap[i >> 3] ?? 0) & (0x80 >> (i % 8))));
}
export function parseAdvertisement(data: Uint8Array) {
  if (data.length < 15 || data[0] !== 0x58 || ![0x54, 0x52].includes(data[1]) ||
      ![0xfd, 0xfe, 0xfc, 4].includes(data[2])) return undefined;
  return {
    recordType: data[2], hardwareRevision: data[3],
    firmware: `${data[4] >> 4}.${data[4] & 15}.${data[5]}`,
    deviceNumber: (data[6] << 8) | data[7], batteryPercent: data[8],
    chipType: data[9] >> 4, transmitPower: data[9] & 15,
  };
}
export function addressFromName(name: string): string {
  if (!/^[\da-f]{12}$/i.test(name)) throw new Error('Label name must be twelve hex digits');
  return name.match(/../g)!.reverse().join(':').toUpperCase();
}
