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
import { type Place, type PlaceFields, TEMPLATES } from '@/lib/places';

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
  places = new Map<string, { device: string; out: Place }>();
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

    const url = new URL(req.url!, 'http://mock');
    if (req.method === 'GET' && url.pathname === '/v1/geocode/search') {
      return send(200, [
        { kind: 'sted', label: url.searchParams.get('q'), secondary: 'Skole, Oslo', lat: 59.9, lon: 10.7, kommunenummer: '0301', covered: true },
      ]);
    }
    if (req.method === 'GET' && url.pathname === '/v1/preview') {
      return send(200, { days: 30, matched: 5, severe: 5, hidden_traffic: 3, imprecise_nearby: 2 });
    }
    const mine = [...this.places.values()].filter((p) => p.device === device.id);
    if (req.method === 'GET' && url.pathname === '/v1/places') return send(200, mine.map((p) => p.out));
    if (req.method === 'POST' && url.pathname === '/v1/places') {
      if (mine.length >= 10) return send(409, { error: 'place_limit', message: 'A device can have at most 10 places' });
      const out = { id: randomUUID(), ...body, kommunenummer: '0301', covered: true, created_at: '2026-11-15T12:00:00Z' };
      this.places.set(out.id, { device: device.id, out });
      return send(201, out);
    }
    const one = url.pathname.match(/^\/v1\/places\/([^/]+)$/);
    const place = one ? this.places.get(one[1]) : undefined;
    if (one && (!place || place.device !== device.id)) return send(404, { error: 'not_found', message: 'No such place' });
    if (place && req.method === 'PATCH') {
      Object.assign(place.out, body);
      return send(200, place.out);
    }
    if (place && req.method === 'DELETE') {
      this.places.delete(place.out.id);
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

describe('places, search and preview', () => {
  const skole: PlaceFields = {
    label: 'Skolen',
    place_name: 'Tøyen skole',
    template: 'skole',
    lat: 59.91483,
    lon: 10.77318,
    radius_m: 1000,
    categories: [...TEMPLATES.skole.categories],
    time_window: TEMPLATES.skole.window,
    push: true,
  };

  it('encodes the search query', async () => {
    const { session } = newSession();
    const results = await session.call((api) => api.searchPlaces('tøyen skole & co'));
    expect(results[0].label).toBe('tøyen skole & co');
    expect(mock.requests.at(-1)!.url).toBe('/v1/geocode/search?q=t%C3%B8yen%20skole%20%26%20co');
  });

  it('sends the preview query with comma-separated categories', async () => {
    const { session } = newSession();
    const p = await session.call((api) =>
      api.preview({ lat: 59.91483, lon: 10.77318, radius_m: 700, categories: ['Vold', 'Ro og orden'] }),
    );
    expect(p.matched).toBe(5);
    expect(mock.requests.at(-1)!.url).toBe(
      '/v1/preview?lat=59.91483&lon=10.77318&radius_m=700&categories=Vold%2CRo%20og%20orden',
    );
  });

  it('creates, lists, changes and deletes a place', async () => {
    const { session } = newSession();
    const created = await session.call((api) => api.createPlace(skole));
    expect(mock.requests.at(-1)).toMatchObject({ method: 'POST', url: '/v1/places', body: skole });
    expect(await session.call((api) => api.listPlaces())).toEqual([created]);

    const changed = await session.call((api) => api.updatePlace(created.id, { radius_m: 700 }));
    expect(mock.requests.at(-1)).toMatchObject({ method: 'PATCH', url: `/v1/places/${created.id}`, body: { radius_m: 700 } });
    expect(changed.radius_m).toBe(700);

    await session.call((api) => api.deletePlace(created.id));
    expect(mock.requests.at(-1)).toMatchObject({ method: 'DELETE', url: `/v1/places/${created.id}` });
    expect(await session.call((api) => api.listPlaces())).toEqual([]);
  });

  it('reports the 11th place as place_limit', async () => {
    const { session } = newSession();
    for (let i = 0; i < 10; i++) await session.call((api) => api.createPlace(skole));
    await expect(session.call((api) => api.createPlace(skole))).rejects.toMatchObject({
      status: 409,
      code: 'place_limit',
    });
  });

  it('gets 404 for another device\'s place', async () => {
    const a = newSession().session;
    const b = newSession().session;
    const created = await a.call((api) => api.createPlace(skole));
    await expect(b.call((api) => api.deletePlace(created.id))).rejects.toMatchObject({ status: 404 });
  });
});
