import {
  allocate, BATCH_SIZE, dataPackets, missingPackets, parseResponse, refresh,
  splitWrites, verify, type ResponseFrame,
} from './codec.js';

/** One connection per upload. connect must enable notifications before resolving. */
export interface BleTransport {
  /** Maximum BLE write payload, after accounting for MTU. Must be 1–244. */
  readonly writeSize: number;
  connect(onNotification: (data: Uint8Array) => void, onDisconnect: (error?: Error) => void): Promise<void>;
  write(data: Uint8Array): Promise<void>;
  /** Must also cancel any connection still being established. */
  disconnect(): void | Promise<void>;
}
export interface UploadOptions {
  screens?: number;
  signal?: AbortSignal;
  /** Milliseconds; defaults to 5000. Also bounds connect and each write. */
  commandTimeoutMs?: number;
  /** Milliseconds per recovery phase; defaults to 300000. */
  patchTimeoutMs?: number;
  /** Defaults to 5 ms. Set to 0 for simulated transports. */
  writeDelayMs?: number;
}
const active = new WeakSet<BleTransport>();
function duration(value: number, name: string, allowZero = false): number {
  if (!Number.isFinite(value) || value < (allowZero ? 0 : 1) || value > 2147483647) {
    throw new RangeError(`Invalid ${name}`);
  }
  return value;
}

/** Resolves when refresh is accepted, before the e-paper waveform has settled.
 * Disconnects on success, failure or cancellation. Does not retry whole uploads.
 */
export async function uploadContainer(
  transport: BleTransport, container: Uint8Array, options: UploadOptions = {},
): Promise<void> {
  if (active.has(transport)) throw new Error('An upload is already using this transport');
  if (container.length < 13 || container[0] !== 0x58 || container[1] !== 0x54 ||
      container[2] !== 0x45 || container[3] !== 0x4b ||
      new DataView(container.buffer, container.byteOffset, container.byteLength).getUint32(8) !== container.length) {
    throw new Error('Expected an XTEK container with a matching length');
  }
  splitWrites(new Uint8Array(), transport.writeSize); // Validate before connecting.
  const refreshFrame = refresh(options.screens);
  const timeout = duration(options.commandTimeoutMs ?? 5000, 'commandTimeoutMs');
  const patchTimeout = duration(options.patchTimeoutMs ?? 300000, 'patchTimeoutMs');
  const delay = duration(options.writeDelayMs ?? 5, 'writeDelayMs', true);
  options.signal?.throwIfAborted();
  // Own a snapshot so callers cannot change an image halfway through an upload.
  const bytes = container.slice();
  active.add(transport);
  let fail!: (reason: unknown) => void;
  const failed = new Promise<never>((_, reject) => { fail = reject; });
  void failed.catch(() => {});
  const abort = () => fail(options.signal?.reason ?? new Error('Upload cancelled'));
  options.signal?.addEventListener('abort', abort, { once: true });
  let pending: { command: number; resolve: (response: ResponseFrame) => void } | undefined;
  let deadline = Infinity;
  const remaining = () => Math.max(0, Math.min(timeout, deadline - Date.now()));
  async function bounded<T>(operation: Promise<T>, ms = remaining()): Promise<T> {
    let timer: ReturnType<typeof setTimeout> | undefined;
    try {
      return await Promise.race([operation, failed, new Promise<never>((_, reject) => {
        timer = setTimeout(() => reject(new Error('BLE operation timed out')), ms);
      })]);
    } finally { clearTimeout(timer); }
  }
  async function pause(ms: number): Promise<void> {
    let timer: ReturnType<typeof setTimeout> | undefined;
    try {
      await bounded(new Promise<void>(resolve => { timer = setTimeout(resolve, ms); }));
    } finally { clearTimeout(timer); }
  }
  async function send(frame: Uint8Array): Promise<void> {
    for (const write of splitWrites(frame, transport.writeSize)) {
      await bounded(transport.write(write));
      if (delay) await pause(delay);
    }
  }
  async function request(frame: Uint8Array): Promise<ResponseFrame> {
    const response = new Promise<ResponseFrame>(resolve => { pending = { command: frame[6], resolve }; });
    try {
      const [, reply] = await bounded(Promise.all([send(frame), response]));
      return reply;
    } finally { pending = undefined; }
  }
  async function sendSelected(packets: Uint8Array[], indexes: number[]): Promise<void> {
    for (const index of indexes) await send(packets[index]);
  }
  async function recover(packets: Uint8Array[], reply: ResponseFrame, final: boolean): Promise<void> {
    deadline = Date.now() + patchTimeout;
    try {
      for (let round = 0; ; round++) {
        if (final && reply.status === 0xff) return;
        if (final && reply.status !== 0x68) throw new Error(`Refresh failed: status 0x${reply.status.toString(16)}`);
        const missing = missingPackets(reply, packets.length);
        if (!final && !missing.length) return;
        if (round === 3) throw new Error('Packets still missing after 3 patch rounds');
        await sendSelected(packets, missing);
        await pause(100);
        reply = await request(final ? refreshFrame : verify());
      }
    } finally { deadline = Infinity; }
  }
  let successful = false;
  try {
    await bounded(transport.connect(data => {
      const response = parseResponse(data);
      if (response && response.command === pending?.command) pending.resolve(response);
    }, error => fail(error ?? new Error('BLE device disconnected'))));
    for (let offset = 0; offset < bytes.length; offset += BATCH_SIZE) {
      const batch = bytes.subarray(offset, offset + BATCH_SIZE);
      const allocated = await request(allocate(bytes.length,
        bytes.length > BATCH_SIZE ? { offset, length: batch.length } : undefined));
      if (allocated.status !== 0xff) throw new Error(`Allocation failed: status 0x${allocated.status.toString(16)}`);
      const packets = dataPackets(batch);
      await sendSelected(packets, packets.map((_, i) => i));
      const final = offset + batch.length === bytes.length;
      if (final) await pause(100);
      await recover(packets, await request(final ? refreshFrame : verify()), final);
    }
    successful = true;
  } finally {
    // Stop in-flight send loops after an outer command timeout as well.
    fail(new Error('Upload session closed'));
    options.signal?.removeEventListener('abort', abort);
    pending = undefined;
    try {
      // Cleanup cannot wait indefinitely, even for an unresponsive adapter.
      let timer: ReturnType<typeof setTimeout> | undefined;
      try {
        await Promise.race([Promise.resolve(transport.disconnect()), new Promise<never>((_, reject) => {
          timer = setTimeout(() => reject(new Error('BLE disconnect timed out')), timeout);
        })]);
      } finally { clearTimeout(timer); }
    } catch (error) {
      if (successful) throw error; // Preserve the original failure otherwise.
    } finally { active.delete(transport); }
  }
}
