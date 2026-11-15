/**
 * @jest-environment node
 *
 * The API client and device session against a mock API server (a real HTTP server on a
 * random port), which behaves like the backend's /v1/devices (§8.6).
 */
import { randomUUID } from 'crypto';
import { createServer, request, type IncomingMessage, type Server, type ServerResponse } from 'http';
import type { AddressInfo } from 'net';

import { ApiClient, ApiError } from '@/lib/api';
import { DEVICE_ID_KEY, DeviceSession, SECRET_KEY, type SecretStore } from '@/lib/device';

interface Device {
  id: string;
  platform: string | null;
  tz: string;
  push_token: string | null;
}

/** A minimal stand-in for the backend: devices by secret, the error shape and the 429 header. */
class MockApi {
  server: Server;
  devices = new Map<string, Device>();
  registrations = 0;
  requests: { method: string; url: string; auth?: string; body?: unknown }[] = [];
  /** Set to make the next request fail with this status and body. */
  failNext: { status: number; body: string; headers?: Record<string, string> } | null = null;

  constructor() {
    this.server = createServer((req, res) => this.handle(req, res));
  }

  get url(): string {
    return `http://127.0.0.1:${(this.server.address() as AddressInfo).port}`;
  }

  start(): Promise<void> {
    return new Promise((ok) => this.server.listen(0, '127.0.0.1', ok));
  }

  stop(): Promise<void> {
    return new Promise((ok) => this.server.close(() => ok()));
  }

  private async handle(req: IncomingMessage, res: ServerResponse) {
    let raw = '';
    for await (const chunk of req) raw += chunk;
    const body = raw ? JSON.parse(raw) : undefined;
    this.requests.push({ method: req.method!, url: req.url!, auth: req.headers.authorization, body });

    const send = (status: number, json?: unknown, headers: Record<string, string> = {}) => {
      res.writeHead(status, { 'Content-Type': 'application/json', ...headers });
      res.end(json === undefined ? undefined : JSON.stringify(json));
    };

    if (this.failNext) {
      const { status, body: text, headers } = this.failNext;
      this.failNext = null;
      res.writeHead(status, headers);
      res.end(text);
      return;
    }

    if (req.method === 'POST' && req.url === '/v1/devices') {
      this.registrations++;
      const secret = `secret-${randomUUID()}`;
      const device = { id: randomUUID(), platform: body?.platform ?? null, tz: body?.tz ?? 'Europe/Oslo', push_token: null };
      this.devices.set(secret, device);
      return send(201, { device_id: device.id, secret });
    }

    const secret = req.headers.authorization?.replace(/^Bearer /, '');
    const device = secret ? this.devices.get(secret) : undefined;
    if (!device) {
      return send(401, { error: 'unauthorized', message: 'Missing or invalid device secret' }, { 'WWW-Authenticate': 'Bearer' });
    }
    if (req.method === 'PUT' && req.url === '/v1/devices/me') {
      Object.assign(device, body);
      return send(200, {
        device_id: device.id,
        platform: device.platform,
        tz: device.tz,
        has_push_token: device.push_token !== null,
      });
    }
    if (req.method === 'DELETE' && req.url === '/v1/devices/me') {
      this.devices.delete(secret!);
      return send(204);
    }
    send(404, { error: 'not_found', message: 'Not found' });
  }
}

/**
 * A fetch over node:http with just what ApiClient uses. The jest-expo preset replaces the
 * global fetch with React Native's, which can't reach a local server from jest.
 */
const nodeFetch: typeof fetch = (input, init = {}) =>
  new Promise((resolve, reject) => {
    const req = request(
      String(input),
      { method: init.method, headers: init.headers as Record<string, string> },
      (res) => {
        let text = '';
        res.setEncoding('utf8');
        res.on('data', (c: string) => (text += c));
        res.on('end', () => {
          const status = res.statusCode ?? 0;
          resolve({
            status,
            ok: status >= 200 && status < 300,
            headers: { get: (name: string) => (res.headers[name.toLowerCase()] as string | undefined) ?? null },
            text: async () => text,
          } as unknown as Response);
        });
      },
    );
    req.on('error', reject);
    init.signal?.addEventListener('abort', () => req.destroy(new Error('aborted')));
    if (init.body) req.write(init.body);
    req.end();
  });

class MemoryStore implements SecretStore {
  data = new Map<string, string>();
  async get(k: string) {
    return this.data.get(k) ?? null;
  }
  async set(k: string, v: string) {
    this.data.set(k, v);
  }
  async delete(k: string) {
    this.data.delete(k);
  }
}

let mock: MockApi;

beforeEach(async () => {
  mock = new MockApi();
  await mock.start();
});

afterEach(() => mock.stop());

function newSession(store = new MemoryStore()) {
  return {
    store,
    session: new DeviceSession({
      baseUrl: mock.url,
      store,
      registration: () => ({ platform: 'ios', tz: 'Europe/Oslo' }),
      fetch: nodeFetch,
    }),
  };
}

describe('ApiClient', () => {
  it('registers without a secret and sends JSON', async () => {
    const api = new ApiClient({ baseUrl: `${mock.url}/`, fetch: nodeFetch });
    const reg = await api.registerDevice({ platform: 'android', tz: 'Europe/Oslo' });
    expect(reg.secret).toMatch(/^secret-/);
    expect(mock.requests[0]).toMatchObject({
      method: 'POST',
      url: '/v1/devices',
      auth: undefined,
      body: { platform: 'android', tz: 'Europe/Oslo' },
    });
  });

  it('sends the bearer secret', async () => {
    const { secret } = await new ApiClient({ baseUrl: mock.url, fetch: nodeFetch }).registerDevice();
    const api = new ApiClient({ baseUrl: mock.url, fetch: nodeFetch, getSecret: async () => secret });
    const out = await api.updateDevice({ push_token: 'ExponentPushToken[abc]' });
    expect(out.has_push_token).toBe(true);
    expect(mock.requests[1].auth).toBe(`Bearer ${secret}`);
  });

  it('refuses an authenticated call before registration, without a request', async () => {
    const api = new ApiClient({ baseUrl: mock.url, fetch: nodeFetch });
    await expect(api.updateDevice({})).rejects.toMatchObject({ status: 401, code: 'no_device' });
    expect(mock.requests).toHaveLength(0);
  });

  it('turns the error shape into ApiError', async () => {
    const api = new ApiClient({ baseUrl: mock.url, fetch: nodeFetch, getSecret: async () => 'wrong' });
    const err = await api.updateDevice({}).catch((e) => e);
    expect(err).toBeInstanceOf(ApiError);
    expect(err).toMatchObject({ status: 401, code: 'unauthorized', message: 'Missing or invalid device secret' });
  });

  it('reads Retry-After on a 429', async () => {
    mock.failNext = {
      status: 429,
      body: JSON.stringify({ error: 'rate_limited', message: 'Too many registrations' }),
      headers: { 'Content-Type': 'application/json', 'Retry-After': '42' },
    };
    const err = await new ApiClient({ baseUrl: mock.url, fetch: nodeFetch }).registerDevice().catch((e) => e);
    expect(err).toMatchObject({ status: 429, code: 'rate_limited', retryAfter: 42 });
  });

  it('survives an error page that is not JSON', async () => {
    mock.failNext = { status: 502, body: '<html>Bad gateway</html>', headers: { 'Content-Type': 'text/html' } };
    const err = await new ApiClient({ baseUrl: mock.url, fetch: nodeFetch }).registerDevice().catch((e) => e);
    expect(err).toMatchObject({ status: 502, code: 'http_502' });
  });

  it('reports a server that cannot be reached as a network error', async () => {
    const url = mock.url;
    await mock.stop();
    const err = await new ApiClient({ baseUrl: url, fetch: nodeFetch }).registerDevice().catch((e) => e);
    expect(err).toMatchObject({ status: 0, code: 'network' });
    await mock.start(); // for afterEach
  });

  it('times out', async () => {
    // A fetch that never answers, and gives up only when aborted.
    const hang: typeof fetch = (_input, init) =>
      new Promise((_, reject) => init?.signal?.addEventListener('abort', () => reject(new Error('aborted'))));
    const err = await new ApiClient({ baseUrl: mock.url, fetch: hang, timeoutMs: 20 }).registerDevice().catch((e) => e);
    expect(err).toMatchObject({ status: 0, code: 'network' });
    expect(err.message).toContain('timed out');
  });
});

describe('DeviceSession', () => {
  it('registers on first use and stores the secret', async () => {
    const { session, store } = newSession();
    const out = await session.call((api) => api.updateDevice({ tz: 'Europe/Oslo' }));
    expect(mock.registrations).toBe(1);
    expect(mock.requests[0].body).toEqual({ platform: 'ios', tz: 'Europe/Oslo' });
    expect(store.data.get(SECRET_KEY)).toMatch(/^secret-/);
    expect(store.data.get(DEVICE_ID_KEY)).toBe(out.device_id);
    expect(await session.deviceId()).toBe(out.device_id);
  });

  it('registers once for concurrent calls', async () => {
    const { session } = newSession();
    await Promise.all([session.ensure(), session.ensure(), session.call((api) => api.updateDevice({}))]);
    expect(mock.registrations).toBe(1);
  });

  it('reuses a stored secret across launches', async () => {
    const store = new MemoryStore();
    await newSession(store).session.ensure();
    await newSession(store).session.call((api) => api.updateDevice({}));
    expect(mock.registrations).toBe(1);
  });

  it('registers again when the server no longer knows the device', async () => {
    const { session, store } = newSession();
    await session.ensure();
    const first = store.data.get(DEVICE_ID_KEY);
    mock.devices.clear(); // deleted on the server, for example after 12 months inactive
    const out = await session.call((api) => api.updateDevice({}));
    expect(mock.registrations).toBe(2);
    expect(out.device_id).not.toBe(first);
    expect(store.data.get(DEVICE_ID_KEY)).toBe(out.device_id);
  });

  it('does not retry other errors', async () => {
    const { session } = newSession();
    await session.ensure();
    mock.failNext = { status: 500, body: JSON.stringify({ error: 'internal', message: 'boom' }) };
    await expect(session.call((api) => api.updateDevice({}))).rejects.toMatchObject({ status: 500 });
    expect(mock.registrations).toBe(1);
  });

  it('does not store anything when registration fails', async () => {
    const { session, store } = newSession();
    mock.failNext = { status: 503, body: '' };
    await expect(session.ensure()).rejects.toMatchObject({ status: 503 });
    expect(store.data.size).toBe(0);
    await session.ensure(); // and recovers on the next try
    expect(store.data.get(SECRET_KEY)).toMatch(/^secret-/);
  });
});
