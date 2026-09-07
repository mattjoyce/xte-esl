import { test, expect } from 'bun:test';
import { encodeContainer, uploadContainer, type BleTransport } from '../dist/index.js';

function response(command: number, payload: number[]) {
  const body = [command, ...payload];
  return Uint8Array.of(0x58,0x54,0x45,4,6 + body.length,body.reduce((a,b) => a+b,0) & 255,...body);
}
function container(large = false) {
  return encodeContainer([{ image: {
    width: large ? 1024 : 250, height: large ? 1000 : 122, channels: 3,
    data: new Uint8Array((large ? 1024000 : 30500) * 3),
  } }], { compress: false });
}
class Tag implements BleTransport {
  writeSize = 20;
  frames: Uint8Array[] = [];
  input: number[] = [];
  disconnected = 0;
  received: (data: Uint8Array) => void = () => {};
  lost: (error?: Error) => void = () => {};
  packetCount = 0;
  patchRefresh = 0;
  patchVerify = 0;
  allocStatus = 255;
  silent = false;
  malformed = false;
  disconnectOnData = false;
  hangWrites = false;
  async connect(received: (data: Uint8Array) => void, lost: (error?: Error) => void) {
    this.received = received; this.lost = lost;
  }
  async write(data: Uint8Array) {
    if (this.hangWrites) return new Promise<void>(() => {});
    this.input.push(...data);
    if (this.input.length < 6) return;
    const size = this.input[3] === 1 ? this.input[4] : this.input[4] * 256 + this.input[5];
    if (this.input.length < size) return;
    expect(this.input.length).toBe(size);
    const frame = Uint8Array.from(this.input); this.input = []; this.frames.push(frame);
    if (frame[3] === 2) {
      this.packetCount = frame[7];
      if (this.disconnectOnData) this.lost();
      return;
    }
    if (this.silent) return;
    const command = frame[6];
    // Noise and unrelated responses must not consume the pending command.
    this.received(Uint8Array.of(1,2,3));
    this.received(response(5, [255]));
    let payload: number[];
    if (command === 1) payload = [this.allocStatus, 0xbd];
    else {
      const bitmap = Array(Math.ceil(this.packetCount / 8)).fill(255);
      const patch = command === 2 ? this.patchVerify-- > 0 : this.patchRefresh-- > 0;
      if (patch) bitmap[0] &= ~0x20; // Packet 2 missing.
      payload = command === 2 ? bitmap : patch ? [0x68, ...bitmap] : [255];
    }
    const reply = response(command, payload);
    if (this.malformed) reply[5] ^= 1;
    this.received(reply); // Synchronous reply exercises notification-before-write-resolution.
  }
  disconnect() { this.disconnected++; }
}
const fast = { writeDelayMs: 0 };

test('small upload recovers a missing packet and disconnects after refresh', async () => {
  const tag = new Tag(); tag.patchRefresh = 1;
  const data = container(); await uploadContainer(tag, data, fast);
  const commands = tag.frames.filter(f => f[3] === 1).map(f => f[6]);
  expect(commands).toEqual([1,4,4]);
  const packets = tag.frames.filter(f => f[3] === 2);
  expect(packets.at(-1)![8]).toBe(2);
  const original = packets.slice(0,-1).flatMap(f => [...f.subarray(9)]);
  expect(Uint8Array.from(original)).toEqual(data);
  expect(tag.disconnected).toBe(1);
});
test('large upload batches, verifies, patches and restarts packet indices', async () => {
  const tag = new Tag(); tag.writeSize = 244; tag.patchVerify = 1;
  await uploadContainer(tag, container(true), fast);
  const commands = tag.frames.filter(f => f[3] === 1);
  expect(commands.map(f => f[6])).toEqual([1,2,2,1,4]);
  const allocations = commands.filter(f => f[6] === 1);
  expect(allocations.every(f => f.length === 19)).toBe(true);
  const view = new DataView(allocations[1].buffer);
  expect(view.getUint32(11)).toBe(204800);
  expect(view.getUint32(15)).toBe(51238);
  for (let i = 0; i < tag.frames.length; i++) {
    if (tag.frames[i][3] === 1 && tag.frames[i][6] === 1) expect(tag.frames[i+1][8]).toBe(0);
  }
  expect(tag.disconnected).toBe(1);
});
test('allocation failure stops before data and disconnects', async () => {
  const tag = new Tag(); tag.allocStatus = 1;
  await expect(uploadContainer(tag, container(), fast)).rejects.toThrow('Allocation failed');
  expect(tag.frames.length).toBe(1); expect(tag.disconnected).toBe(1);
});
test('recovery is limited to three retransmissions', async () => {
  const tag = new Tag(); tag.patchRefresh = 20;
  await expect(uploadContainer(tag, container(), fast)).rejects.toThrow('3 patch rounds');
  expect(tag.frames.filter(f => f[3] === 1 && f[6] === 4).length).toBe(4);
  expect(tag.disconnected).toBe(1);
});
test('missing/invalid replies and hung writes time out with cleanup', async () => {
  for (const field of ['silent', 'malformed', 'hangWrites'] as const) {
    const tag = new Tag(); tag[field] = true;
    await expect(uploadContainer(tag, container(), { ...fast, commandTimeoutMs: 20 })).rejects.toThrow('timed out');
    expect(tag.disconnected).toBe(1);
  }
});
test('unexpected disconnect interrupts the upload', async () => {
  const tag = new Tag(); tag.disconnectOnData = true;
  await expect(uploadContainer(tag, container(), fast)).rejects.toThrow('disconnected');
  expect(tag.disconnected).toBe(1);
});
test('abort and concurrent use are handled without disconnecting another upload', async () => {
  const tag = new Tag(); tag.silent = true;
  const controller = new AbortController();
  const first = uploadContainer(tag, container(), { ...fast, signal: controller.signal });
  const rejection = first.catch(error => error);
  await expect(uploadContainer(tag, container(), fast)).rejects.toThrow('already');
  expect(tag.disconnected).toBe(0);
  controller.abort(new Error('cancelled'));
  expect((await rejection).message).toBe('cancelled'); expect(tag.disconnected).toBe(1);
});
test('recovery has a wall-clock deadline', async () => {
  const tag = new Tag(); tag.patchRefresh = 10;
  await expect(uploadContainer(tag, container(), { ...fast, patchTimeoutMs: 10 })).rejects.toThrow('timed out');
  expect(tag.disconnected).toBe(1);
});
