/** lib/home.ts (Hjem's texts and status row) and lib/opened.ts («N ny» on the device). */
import {
  distanceText,
  districtNotices,
  type EventSummary,
  impreciseText,
  newCount,
  type Notice,
  placeMeta,
  placeStatus,
  type PlaceEvents,
  radiusShort,
  timeText,
  updatedText,
} from '@/lib/home';
import { OpenedStore, type TextFile } from '@/lib/opened';
import { ALL_DAY, TEMPLATES } from '@/lib/places';

const NOW = new Date(2026, 10, 15, 14, 0); // 15 Nov 2026 14:00, local time
const hoursAgo = (h: number) => new Date(NOW.getTime() - h * 3600_000).toISOString();

function ev(id: string, h: number, over: Partial<EventSummary> = {}): EventSummary {
  return {
    id,
    title: `Brann · ${id}`,
    category: 'Brann',
    police_category: 'Brann',
    severity: 'severe',
    first_message_at: hoursAgo(h),
    last_message_at: hoursAgo(h),
    is_active: false,
    area: null,
    municipality: 'Oslo',
    lat: 59.9,
    lon: 10.7,
    uncertainty_m: 100,
    precision_tier: 'gate',
    geocode_method: 'adresse',
    distance_m: 150,
    relation: 'match',
    pushed: false,
    ...over,
  };
}

function pe(events: EventSummary[], municipality_only = 0, district_notices: Notice[] = []): PlaceEvents {
  return { place_id: 'p', days: 7, events, municipality_only, district_notices };
}

describe('status row', () => {
  it('shows the newest matched incident of the last 7 days', () => {
    const s = placeStatus({ radius_m: 1000 }, pe([ev('a', 30), ev('b', 2), ev('n', 1, { relation: 'imprecise_nearby' })]), NOW);
    expect(s).toEqual({ kind: 'incident', event: expect.objectContaining({ id: 'b' }) });
  });

  it('is calm without matches, also with imprecise events, at 1 km and more', () => {
    expect(placeStatus({ radius_m: 1000 }, pe([]), NOW)).toEqual({ kind: 'calm' });
    expect(placeStatus({ radius_m: 1000 }, pe([ev('n', 3, { relation: 'imprecise_nearby' })], 4), NOW)).toEqual({
      kind: 'calm',
    });
  });

  it('ignores matches older than 7 days', () => {
    expect(placeStatus({ radius_m: 1000 }, pe([ev('old', 7 * 24 + 1)]), NOW)).toEqual({ kind: 'calm' });
  });

  it('under 1 km, counts district- and municipality-only incidents in the note (D1)', () => {
    const s = placeStatus({ radius_m: 500 }, pe([ev('n', 3, { relation: 'imprecise_nearby' })], 2), NOW);
    expect(s).toEqual({ kind: 'imprecise', count: 3 });
    expect(impreciseText(3)).toBe(
      'Ingen gatepresise hendelser denne uken. 3 hendelser er bare oppgitt med bydel eller kommune og vises ikke i et så lite område.',
    );
    expect(impreciseText(1)).toContain('1 hendelse er');
    expect(placeStatus({ radius_m: 500 }, pe([]), NOW)).toEqual({ kind: 'calm' });
  });
});

describe('«N ny»', () => {
  it('counts matched incidents of the last 7 days not opened on this device', () => {
    const data = pe([
      ev('a', 1),
      ev('b', 5),
      ev('c', 200), // older than 7 days
      ev('d', 2, { relation: 'imprecise_nearby' }),
    ]);
    expect(newCount(data, () => false, NOW)).toBe(2);
    expect(newCount(data, (id) => id === 'a', NOW)).toBe(1);
    expect(newCount(pe([]), () => false, NOW)).toBe(0);
  });
});

describe('card texts', () => {
  it('writes the radius short', () => {
    expect([300, 500, 1000, 1500, 2000].map(radiusShort)).toEqual(['300 m', '500 m', '1 km', '1,5 km', '2 km']);
  });

  it('writes the meta line as in §7.2', () => {
    expect(placeMeta({ place_name: 'Kampen', radius_m: 1000, time_window: ALL_DAY })).toBe('Kampen · 1 km · hele døgnet');
    expect(placeMeta({ place_name: 'Tøyen skole', radius_m: 1000, time_window: TEMPLATES.skole.window })).toBe(
      'Tøyen skole · 1 km · hverdager 08–16',
    );
    expect(placeMeta({ place_name: null, radius_m: 500, time_window: ALL_DAY })).toBe('500 m · hele døgnet');
  });

  it('rounds distances as the push title does', () => {
    expect(distanceText(12)).toBe('ca. 50 m unna');
    expect(distanceText(149)).toBe('ca. 150 m unna');
    expect(distanceText(974)).toBe('ca. 950 m unna');
    expect(distanceText(1249)).toBe('ca. 1,2 km unna');
    expect(distanceText(2000)).toBe('ca. 2,0 km unna');
  });

  it('writes times as today, yesterday or a date', () => {
    expect(timeText(new Date(2026, 10, 15, 8, 23).toISOString(), NOW)).toBe('08:23');
    expect(timeText(new Date(2026, 10, 14, 22, 5).toISOString(), NOW)).toBe('i går 22:05');
    expect(timeText(new Date(2026, 10, 9, 12, 0).toISOString(), NOW)).toBe('9. nov.');
  });

  it('says how old the last poll is', () => {
    const h = (age_s: number | null) => ({ status: 'ok' as const, last_success_at: null, age_s });
    expect(updatedText(null)).toBeNull();
    expect(updatedText(h(null))).toBeNull();
    expect(updatedText(h(30))).toBe('Oppdatert nå nettopp');
    expect(updatedText(h(70))).toBe('Oppdatert for 1 minutt siden');
    expect(updatedText(h(125))).toBe('Oppdatert for 2 minutter siden');
    expect(updatedText(h(3700))).toBe('Oppdatert for 1 time siden');
    expect(updatedText(h(3 * 3600 + 5))).toBe('Oppdatert for 3 timer siden');
  });
});

describe('district notices (D2)', () => {
  const notice = (id: string, h: number): Notice => ({
    id,
    title: `Savnet · Oslo politidistrikt`,
    category: 'Savnet',
    police_category: 'Savnet',
    district: 'Oslo politidistrikt',
    first_message_at: hoursAgo(h),
    last_message_at: hoursAgo(h),
    is_active: true,
  });

  it('lists each notice once, newest first, across places', () => {
    const all = [pe([], 0, [notice('x', 5), notice('y', 1)]), pe([], 0, [notice('y', 1)])];
    expect(districtNotices(all).map((n) => n.id)).toEqual(['y', 'x']);
    expect(districtNotices([pe([])])).toEqual([]);
  });
});

describe('OpenedStore', () => {
  class Memory implements TextFile {
    text: string | null = null;
    writes = 0;
    read() {
      return this.text;
    }
    write(t: string) {
      this.text = t;
      this.writes++;
    }
  }

  it('remembers opened incidents across launches', () => {
    const file = new Memory();
    const a = new OpenedStore(file, () => NOW.getTime());
    expect(a.isOpened('e1')).toBe(false);
    a.markOpened('e1');
    a.markOpened('e1');
    expect(file.writes).toBe(1);
    expect(new OpenedStore(file, () => NOW.getTime()).isOpened('e1')).toBe(true);
  });

  it('forgets entries older than 30 days, and survives a broken file', () => {
    const file = new Memory();
    file.text = JSON.stringify({ old: NOW.getTime() - 31 * 24 * 3600_000, recent: NOW.getTime() - 1000 });
    const s = new OpenedStore(file, () => NOW.getTime());
    expect(s.isOpened('old')).toBe(false);
    expect(s.isOpened('recent')).toBe(true);

    file.text = '{not json';
    const warn = jest.spyOn(console, 'warn').mockImplementation(() => {});
    expect(new OpenedStore(file).isOpened('recent')).toBe(false);
    warn.mockRestore();
  });

  it('tells subscribers when something is opened', () => {
    const s = new OpenedStore(new Memory());
    const listener = jest.fn();
    const unsubscribe = s.subscribe(listener);
    s.markOpened('e1');
    expect(listener).toHaveBeenCalledTimes(1);
    expect(s.getVersion()).toBe(1);
    unsubscribe();
    s.markOpened('e2');
    expect(listener).toHaveBeenCalledTimes(1);
  });
});
