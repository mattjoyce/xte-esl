import { SERVICE_UUID } from './codec.js';
import type { BleTransport } from './upload.js';

// Minimal structural interfaces keep the SDK independent of ambient Web Bluetooth
// declarations. Native BluetoothDevice objects satisfy this interface.
export interface WebBluetoothCharacteristic extends EventTarget {
  readonly properties: { write: boolean; writeWithoutResponse: boolean; notify: boolean; indicate: boolean };
  readonly value?: DataView;
  startNotifications(): Promise<unknown>;
  writeValueWithoutResponse(value: ArrayBuffer): Promise<void>;
  writeValueWithResponse(value: ArrayBuffer): Promise<void>;
}
export interface WebBluetoothServer {
  connect(): Promise<WebBluetoothServer>;
  disconnect(): void;
  getPrimaryService(uuid: string): Promise<{ getCharacteristics(): Promise<WebBluetoothCharacteristic[]> }>;
}
export interface WebBluetoothDevice extends EventTarget {
  readonly name?: string;
  readonly gatt?: WebBluetoothServer;
}
interface BrowserBluetooth {
  requestDevice(options: {
    filters: ({ name: string } | { manufacturerData: { companyIdentifier: number }[] })[];
    optionalServices: string[];
  }): Promise<WebBluetoothDevice>;
}

/** Call from a user gesture on a secure page. Uses the name when supplied,
 * since the vendor service need not appear in advertisements.
 */
export async function requestWebBluetoothTransport(name?: string): Promise<WebBluetoothTransport> {
  const bluetooth = (globalThis.navigator as Navigator & { bluetooth?: BrowserBluetooth })?.bluetooth;
  if (!bluetooth) throw new Error('Web Bluetooth is unavailable in this browser');
  if (name !== undefined && !/^[\da-f]{12}$/i.test(name)) throw new Error('Expected a twelve-digit label name');
  const device = await bluetooth.requestDevice({
    filters: name ? [{ name: name.toUpperCase() }] : [{ manufacturerData: [{ companyIdentifier: 0x5258 }] }],
    optionalServices: [SERVICE_UUID],
  });
  return new WebBluetoothTransport(device);
}

export class WebBluetoothTransport implements BleTransport {
  /** Web Bluetooth cannot request/read the negotiated MTU. Default to safe 20-byte writes. */
  constructor(readonly device: WebBluetoothDevice, readonly writeSize = 20) {
    if (!Number.isInteger(writeSize) || writeSize < 1 || writeSize > 244) throw new RangeError('Invalid write size');
  }
  private writer?: WebBluetoothCharacteristic;
  private notify?: WebBluetoothCharacteristic;
  private notificationListener?: EventListener;
  private disconnectListener?: EventListener;
  private generation = 0;
  private connecting = false;

  async connect(onNotification: (data: Uint8Array) => void, onDisconnect: (error?: Error) => void): Promise<void> {
    if (this.connecting || this.writer) throw new Error('Transport already connected or connecting');
    const gatt = this.device.gatt;
    if (!gatt) throw new Error('Device has no GATT server');
    this.connecting = true;
    const generation = ++this.generation;
    const check = () => {
      if (generation !== this.generation) {
        gatt.disconnect();
        throw new Error('Connection cancelled');
      }
    };
    this.disconnectListener = () => {
      this.disconnect();
      onDisconnect(new Error('BLE device disconnected'));
    };
    this.device.addEventListener('gattserverdisconnected', this.disconnectListener);
    try {
      const server = await gatt.connect(); check();
      const service = await server.getPrimaryService(SERVICE_UUID); check();
      const characteristics = await service.getCharacteristics(); check();
      this.writer = characteristics.find(c => c.properties.writeWithoutResponse || c.properties.write);
      this.notify = characteristics.find(c => c.properties.notify || c.properties.indicate);
      if (!this.writer || !this.notify) throw new Error('XTE write/notify characteristics not found');
      const notify = this.notify;
      this.notificationListener = () => {
        const value = notify.value;
        if (value) onNotification(new Uint8Array(value.buffer, value.byteOffset, value.byteLength).slice());
      };
      notify.addEventListener('characteristicvaluechanged', this.notificationListener);
      await notify.startNotifications(); check();
    } catch (error) {
      if (generation === this.generation) this.disconnect();
      throw error;
    } finally {
      this.connecting = false;
    }
  }
  async write(data: Uint8Array): Promise<void> {
    const writer = this.writer;
    if (!writer || this.connecting) throw new Error('Transport is not connected');
    if (data.length > this.writeSize) throw new RangeError('BLE write exceeds configured size');
    const buffer = new Uint8Array(data).buffer;
    if (writer.properties.writeWithoutResponse) await writer.writeValueWithoutResponse(buffer);
    else await writer.writeValueWithResponse(buffer);
  }
  disconnect(): void {
    ++this.generation;
    if (this.notify && this.notificationListener) this.notify.removeEventListener('characteristicvaluechanged', this.notificationListener);
    if (this.disconnectListener) this.device.removeEventListener('gattserverdisconnected', this.disconnectListener);
    this.writer = undefined; this.notify = undefined;
    this.notificationListener = undefined; this.disconnectListener = undefined;
    this.device.gatt?.disconnect();
  }
}
