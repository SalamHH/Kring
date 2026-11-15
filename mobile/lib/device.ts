/**
 * The anonymous device (§8.6, §8.8): registered on first launch, its secret kept in a
 * SecretStore (expo-secure-store in the app, a Map in tests).
 */
import { ApiClient, ApiError, type DeviceIn } from './api';

export interface SecretStore {
  get(key: string): Promise<string | null>;
  set(key: string, value: string): Promise<void>;
  delete(key: string): Promise<void>;
}

export const SECRET_KEY = 'kring.device.secret';
export const DEVICE_ID_KEY = 'kring.device.id';

export interface DeviceSessionOptions {
  baseUrl: string;
  store: SecretStore;
  /** Sent with the registration: platform and time zone. */
  registration: () => DeviceIn;
  fetch?: typeof fetch;
}

export class DeviceSession {
  readonly api: ApiClient;
  private readonly store: SecretStore;
  private readonly registration: () => DeviceIn;
  /** undefined until the store has been read. */
  private secret: string | null | undefined;
  private inFlight: Promise<string> | null = null;

  constructor(opts: DeviceSessionOptions) {
    this.store = opts.store;
    this.registration = opts.registration;
    this.api = new ApiClient({ baseUrl: opts.baseUrl, fetch: opts.fetch, getSecret: () => this.ensure() });
  }

  /** The device secret, registering the device first if there is none. Concurrent calls share one registration. */
  ensure(): Promise<string> {
    if (this.secret) return Promise.resolve(this.secret);
    this.inFlight ??= this.loadOrRegister().finally(() => (this.inFlight = null));
    return this.inFlight;
  }

  /**
   * Runs `fn` against the API. If the server no longer knows the secret (401, for example
   * after the 12-month inactive-device deletion, §8.8), registers a new device and tries once more.
   */
  async call<T>(fn: (api: ApiClient) => Promise<T>): Promise<T> {
    try {
      return await fn(this.api);
    } catch (e) {
      if (!(e instanceof ApiError && e.status === 401 && e.code === 'unauthorized')) throw e;
      await this.forget();
      return fn(this.api);
    }
  }

  /** The registered device id, or null before registration. */
  deviceId(): Promise<string | null> {
    return this.store.get(DEVICE_ID_KEY);
  }

  /** Drops the stored secret, so the next call registers a new device. */
  async forget(): Promise<void> {
    this.secret = null;
    await this.store.delete(SECRET_KEY);
    await this.store.delete(DEVICE_ID_KEY);
  }

  private async loadOrRegister(): Promise<string> {
    if (this.secret === undefined) this.secret = await this.store.get(SECRET_KEY);
    if (this.secret) return this.secret;
    const { device_id, secret } = await this.api.registerDevice(this.registration());
    // The secret first: a device id without a secret is useless, the reverse is harmless.
    await this.store.set(SECRET_KEY, secret);
    await this.store.set(DEVICE_ID_KEY, device_id);
    this.secret = secret;
    return secret;
  }
}
