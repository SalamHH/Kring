/**
 * Kring API client (spec §8.6). Plain fetch, no state: the device secret comes from
 * `getSecret`, so lib/device.ts decides where it lives and when to register.
 */
import type { EventDetail, Health, PlaceEvents } from './home';
import type { Place, PlaceFields, Preview, SearchResult } from './places';

export type Platform = 'ios' | 'android';

function query(params: Record<string, string | number>): string {
  return Object.entries(params)
    .map(([k, v]) => `${encodeURIComponent(k)}=${encodeURIComponent(String(v))}`)
    .join('&');
}

export interface Registered {
  device_id: string;
  secret: string;
}

export interface DeviceIn {
  push_token?: string | null;
  platform?: Platform | null;
  tz?: string;
}

export interface DeviceOut {
  device_id: string;
  platform: Platform | null;
  tz: string;
  has_push_token: boolean;
}

/** An error response from the API, `{error, message}` (§8.6), or a network failure. */
export class ApiError extends Error {
  constructor(
    /** HTTP status, or 0 when the request never got a response. */
    readonly status: number,
    /** The API's error code, such as `unauthorized` or `rate_limited`; `network` for status 0. */
    readonly code: string,
    message: string,
    /** Seconds to wait, from `Retry-After` on a 429. */
    readonly retryAfter?: number,
  ) {
    super(message);
    this.name = 'ApiError';
  }
}

export interface ApiClientOptions {
  baseUrl: string;
  /** The device secret, or null before registration. */
  getSecret?: () => Promise<string | null>;
  fetch?: typeof fetch;
  /** Milliseconds before a request is abandoned. */
  timeoutMs?: number;
}

type Method = 'GET' | 'POST' | 'PUT' | 'PATCH' | 'DELETE';

export class ApiClient {
  private readonly baseUrl: string;
  private readonly getSecret: () => Promise<string | null>;
  private readonly fetchImpl: typeof fetch;
  private readonly timeoutMs: number;

  constructor(opts: ApiClientOptions) {
    this.baseUrl = opts.baseUrl.replace(/\/+$/, '');
    this.getSecret = opts.getSecret ?? (async () => null);
    this.fetchImpl = opts.fetch ?? ((...args) => fetch(...args));
    this.timeoutMs = opts.timeoutMs ?? 15_000;
  }

  /** POST /v1/devices. Needs no secret. */
  registerDevice(body: DeviceIn = {}): Promise<Registered> {
    return this.request('POST', '/v1/devices', { body, auth: false });
  }

  /** PUT /v1/devices/me. Only the fields sent are changed; null clears push_token or platform. */
  updateDevice(body: DeviceIn): Promise<DeviceOut> {
    return this.request('PUT', '/v1/devices/me', { body });
  }

  /** DELETE /v1/devices/me: the device, its places and notifications. */
  deleteDevice(): Promise<void> {
    return this.request('DELETE', '/v1/devices/me');
  }

  /** GET /v1/geocode/search: Kartverket addresses and place names, up to 10. `q` is 2–100 characters. */
  searchPlaces(q: string): Promise<SearchResult[]> {
    return this.request('GET', `/v1/geocode/search?${query({ q })}`);
  }

  /** GET /v1/preview: counts for the last 30 days around a point (F3). */
  preview(p: { lat: number; lon: number; radius_m: number; categories: readonly string[] }): Promise<Preview> {
    return this.request(
      'GET',
      `/v1/preview?${query({ lat: p.lat, lon: p.lon, radius_m: p.radius_m, categories: p.categories.join(',') })}`,
    );
  }

  /** GET /v1/places: this device's places, oldest first. */
  listPlaces(): Promise<Place[]> {
    return this.request('GET', '/v1/places');
  }

  /** POST /v1/places. 409 `place_limit` at 10 places (D10); 502 when Kartverket doesn't answer. */
  createPlace(body: PlaceFields): Promise<Place> {
    return this.request('POST', '/v1/places', { body });
  }

  /** PATCH /v1/places/{id}: only the fields sent are changed. */
  updatePlace(id: string, body: Partial<PlaceFields>): Promise<Place> {
    return this.request('PATCH', `/v1/places/${encodeURIComponent(id)}`, { body });
  }

  /** DELETE /v1/places/{id}. */
  deletePlace(id: string): Promise<void> {
    return this.request('DELETE', `/v1/places/${encodeURIComponent(id)}`);
  }

  /** GET /v1/places/{id}/events: matched and imprecise-nearby events, newest first (1–90 days). */
  placeEvents(id: string, days: number): Promise<PlaceEvents> {
    return this.request('GET', `/v1/places/${encodeURIComponent(id)}/events?${query({ days })}`);
  }

  /** GET /v1/events/{id}, with `for_place` when a place is given. */
  event(id: string, placeId?: string): Promise<EventDetail> {
    const q = placeId ? `?${query({ place_id: placeId })}` : '';
    return this.request('GET', `/v1/events/${encodeURIComponent(id)}${q}`);
  }

  /** GET /v1/health. A stale poll answers 503 with the same body, which is returned too. */
  health(): Promise<Health> {
    return this.request('GET', '/v1/health', { auth: false, acceptStatus: [503] });
  }

  async request<T>(
    method: Method,
    path: string,
    { body, auth = true, acceptStatus = [] }: { body?: unknown; auth?: boolean; acceptStatus?: number[] } = {},
  ): Promise<T> {
    const headers: Record<string, string> = { Accept: 'application/json' };
    if (body !== undefined) headers['Content-Type'] = 'application/json';
    if (auth) {
      const secret = await this.getSecret();
      if (!secret) throw new ApiError(401, 'no_device', 'This device is not registered yet');
      headers.Authorization = `Bearer ${secret}`;
    }

    const controller = new AbortController();
    const timer = setTimeout(() => controller.abort(), this.timeoutMs);
    let res: Response;
    try {
      res = await this.fetchImpl(this.baseUrl + path, {
        method,
        headers,
        body: body === undefined ? undefined : JSON.stringify(body),
        signal: controller.signal,
      });
    } catch (e) {
      const reason = controller.signal.aborted ? 'timed out' : String(e);
      throw new ApiError(0, 'network', `${method} ${path}: ${reason}`);
    } finally {
      clearTimeout(timer);
    }

    if (res.status === 204) return undefined as T;
    const text = await res.text();
    let json: unknown = undefined;
    try {
      json = text ? JSON.parse(text) : undefined;
    } catch {
      // Not JSON: a proxy error page, for example. Handled below.
    }
    if (res.ok || (acceptStatus.includes(res.status) && json !== undefined)) {
      if (json === undefined) throw new ApiError(res.status, 'bad_response', `${method} ${path}: not JSON`);
      return json as T;
    }
    const err = (json ?? {}) as { error?: unknown; message?: unknown };
    const retry = Number(res.headers.get('Retry-After'));
    throw new ApiError(
      res.status,
      typeof err.error === 'string' ? err.error : `http_${res.status}`,
      typeof err.message === 'string' ? err.message : `${method} ${path} failed with ${res.status}`,
      Number.isFinite(retry) && retry > 0 ? retry : undefined,
    );
  }
}
