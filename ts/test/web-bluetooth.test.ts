import { test, expect } from 'bun:test';
import { SERVICE_UUID } from '../dist/index.js';
import { WebBluetoothTransport } from '../dist/web-bluetooth.js';

class Characteristic extends EventTarget {
  properties = { write: false, writeWithoutResponse: false, notify: false, indicate: false };
  value?: DataView;
  writes: ArrayBuffer[] = [];
  async startNotifications() {}
  async writeValueWithoutResponse(data: ArrayBuffer) { this.writes.push(data); }
  async writeValueWithResponse(data: ArrayBuffer) { this.writes.push(data); }
}
function device() {
  const writer = new Characteristic(); writer.properties.writeWithoutResponse = true;
  const notifier = new Characteristic(); notifier.properties.notify = true;
  const peripheral = new EventTarget();
  let disconnects = 0;
  const gatt = {
    async connect() { return gatt; },
    disconnect() { disconnects++; },
    async getPrimaryService(uuid: string) {
      expect(uuid).toBe(SERVICE_UUID);
      return { async getCharacteristics() { return [notifier, writer]; } };
    },
  };
  return { device: Object.assign(peripheral, { gatt }), gatt, writer, notifier,
    disconnects: () => disconnects };
}
test('browser transport selects properties, copies DataView slices and removes listeners', async () => {
  const fixture = device(); const adapter = new WebBluetoothTransport(fixture.device);
  const readings: Uint8Array[] = []; let lost = 0;
  await adapter.connect(data => readings.push(data), () => lost++);
  const buffer = Uint8Array.of(99,1,2,88);
  fixture.notifier.value = new DataView(buffer.buffer, 1, 2);
  fixture.notifier.dispatchEvent(new Event('characteristicvaluechanged'));
  buffer[1] = 7;
  expect(readings).toEqual([Uint8Array.of(1,2)]);
  await adapter.write(Uint8Array.of(3,4));
  expect(new Uint8Array(fixture.writer.writes[0])).toEqual(Uint8Array.of(3,4));
  fixture.device.dispatchEvent(new Event('gattserverdisconnected'));
  expect(lost).toBe(1);
  await expect(adapter.write(Uint8Array.of(1))).rejects.toThrow('not connected');
  fixture.notifier.dispatchEvent(new Event('characteristicvaluechanged'));
  expect(readings.length).toBe(1);
  adapter.disconnect();
  fixture.device.dispatchEvent(new Event('gattserverdisconnected'));
  expect(lost).toBe(1);
});
test('late connection after cancellation is closed and cannot overlap a new connect', async () => {
  const fixture = device();
  let finish!: (server: typeof fixture.gatt) => void;
  fixture.gatt.connect = () => new Promise(resolve => { finish = resolve; });
  const adapter = new WebBluetoothTransport(fixture.device);
  const first = adapter.connect(() => {}, () => {}).catch(error => error);
  adapter.disconnect();
  await expect(adapter.connect(() => {}, () => {})).rejects.toThrow('already');
  finish(fixture.gatt);
  expect((await first).message).toBe('Connection cancelled');
  expect(fixture.disconnects()).toBe(2);
});
test('notification setup failure cleans up the connection', async () => {
  const fixture = device();
  fixture.notifier.startNotifications = async () => { throw new Error('notifications failed'); };
  const adapter = new WebBluetoothTransport(fixture.device);
  await expect(adapter.connect(() => {}, () => {})).rejects.toThrow('notifications failed');
  expect(fixture.disconnects()).toBe(1);
  await expect(adapter.write(Uint8Array.of(1))).rejects.toThrow('not connected');
});
