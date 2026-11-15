/**
 * Places as the app sees them (spec §6, §6.1, §8.6): categories, templates, radius and time
 * windows, and the texts Nytt sted builds from them. No React here, so Jest can cover it.
 *
 * The server also fills in template defaults (§6.1), but Nytt sted must show them before saving,
 * so they live here too. `__tests__/places.test.ts` checks both tables against the spec.
 */

/** App categories (Appendix B), in the order the app shows them. */
export const APP_CATEGORIES = [
  'Vold',
  'Brann',
  'Savnet',
  'Ro og orden',
  'Innbrudd',
  'Tyveri',
  'Trafikk',
  'Andre',
] as const;
export type AppCategory = (typeof APP_CATEGORIES)[number];

export type Template = 'skole' | 'hjem' | 'hytte' | 'jobb' | 'annet';
export const TEMPLATE_ORDER: readonly Template[] = ['skole', 'hjem', 'hytte', 'jobb', 'annet'];

/** ISO weekdays 1 (Monday) to 7, and HH:MM times; `from` is before `to` (§8.6). */
export type TimeWindow = { all: true } | { days: number[]; from: string; to: string };

export const ALL_DAY: TimeWindow = { all: true };
const WEEKDAYS = [1, 2, 3, 4, 5];

export interface TemplateInfo {
  /** The chip text. */
  name: string;
  /** The label a new place gets, as on Hjem («Skolen», «Hjemme»). null: the search result's name. */
  defaultLabel: string | null;
  categories: readonly AppCategory[];
  window: TimeWindow;
}

/** §6.1. «Annet» is all categories except Trafikk, so it includes Andre (decided 2026-11-14, §8.6). */
export const TEMPLATES: Record<Template, TemplateInfo> = {
  skole: {
    name: 'Skole',
    defaultLabel: 'Skolen',
    categories: ['Vold', 'Brann', 'Savnet', 'Ro og orden'],
    window: { days: WEEKDAYS, from: '08:00', to: '16:00' },
  },
  hjem: {
    name: 'Hjem',
    defaultLabel: 'Hjemme',
    categories: ['Vold', 'Brann', 'Ro og orden', 'Innbrudd'],
    window: ALL_DAY,
  },
  hytte: { name: 'Hytte', defaultLabel: 'Hytta', categories: ['Brann', 'Innbrudd'], window: ALL_DAY },
  jobb: {
    name: 'Jobb',
    defaultLabel: 'Jobben',
    categories: ['Vold', 'Brann'],
    window: { days: WEEKDAYS, from: '07:00', to: '17:00' },
  },
  annet: {
    name: 'Annet',
    defaultLabel: null,
    categories: APP_CATEGORIES.filter((c) => c !== 'Trafikk'),
    window: ALL_DAY,
  },
};

/** The default template of a new place, as in the prototype (§7.6). */
export const DEFAULT_TEMPLATE: Template = 'skole';

export const LABEL_MAX = 40;
export const PLACE_NAME_MAX = 100;

/** The label a new place gets for this template and search result, cut to 40 characters. */
export function defaultLabel(template: Template, placeName: string | null): string {
  return (TEMPLATES[template].defaultLabel ?? placeName ?? '').slice(0, LABEL_MAX).trim();
}

/** Categories in Appendix B order, without duplicates. */
export function canonical(categories: Iterable<string>): AppCategory[] {
  const set = new Set(categories);
  return APP_CATEGORIES.filter((c) => set.has(c));
}

// --- radius (F3, §7.2 RadiusSlider) ---------------------------------------------------------

export const RADIUS_MIN = 300;
export const RADIUS_MAX = 2000;
export const RADIUS_STEP = 100;
export const RADIUS_DEFAULT = 1000;
/** Below this radius only gate-tier incidents count (§6.2 rule 3), so Nytt sted shows the InfoNote. */
export const SMALL_RADIUS_BELOW = 1000;

/** The nearest allowed radius. */
export function snapRadius(m: number): number {
  const stepped = Math.round(m / RADIUS_STEP) * RADIUS_STEP;
  return Math.min(RADIUS_MAX, Math.max(RADIUS_MIN, stepped));
}

/** «700 m» below 1 km, «1,0 km» from 1 km (§7.2). */
export function radiusLabel(m: number): string {
  if (m < 1000) return `${m} m`;
  return `${(m / 1000).toFixed(1).replace('.', ',')} km`;
}

export function showsSmallRadiusNote(m: number): boolean {
  return m < SMALL_RADIUS_BELOW;
}

// --- time windows ----------------------------------------------------------------------------

const DAY_SHORT = ['man', 'tir', 'ons', 'tor', 'fre', 'lør', 'søn'];

function hours(from: string, to: string): string {
  const short = (t: string) => (t.endsWith(':00') ? t.slice(0, 2) : t);
  return `${short(from)}–${short(to)}`;
}

function daysText(days: number[]): string {
  const key = [...days].sort((a, b) => a - b).join(',');
  if (key === '1,2,3,4,5,6,7') return 'Alle dager';
  if (key === '1,2,3,4,5') return 'Hverdager';
  if (key === '6,7') return 'Helg';
  const names = days.map((d) => DAY_SHORT[d - 1]).join(', ');
  return names.charAt(0).toUpperCase() + names.slice(1);
}

/** «Hele døgnet», «Hverdager 08–16», «Helg 10:30–18». Hjem lowercases it in the card meta. */
export function windowLabel(w: TimeWindow): string {
  if ('all' in w) return 'Hele døgnet';
  return `${daysText(w.days)} ${hours(w.from, w.to)}`;
}

export function sameWindow(a: TimeWindow, b: TimeWindow): boolean {
  if ('all' in a || 'all' in b) return 'all' in a && 'all' in b;
  const days = (w: { days: number[] }) => [...w.days].sort((x, y) => x - y).join(',');
  return days(a) === days(b) && a.from === b.from && a.to === b.to;
}

/**
 * The «Når» choices: all day and the templates' windows. A place's own window is added when it
 * is not one of them (made by another client). Custom windows are not offered in M1.
 */
export function windowChoices(current: TimeWindow): TimeWindow[] {
  const out: TimeWindow[] = [ALL_DAY];
  for (const t of TEMPLATE_ORDER) {
    const w = TEMPLATES[t].window;
    if (!out.some((o) => sameWindow(o, w))) out.push(w);
  }
  if (!out.some((o) => sameWindow(o, current))) out.push(current);
  return out;
}

// --- preview (F3, GET /v1/preview) -----------------------------------------------------------

export interface Preview {
  days: number;
  matched: number;
  severe: number;
  hidden_traffic: number;
  imprecise_nearby: number;
}

function count(n: number, one: string, many: string): string {
  return `${n} ${n === 1 ? one : many}`;
}

/** The preview card's number and the line under it. All counts are real (§7.6), so no «ca.». */
export function previewText(p: Preview): { headline: string; detail: string[] } {
  const headline = p.matched === 0 ? 'Ingen hendelser' : count(p.matched, 'hendelse', 'hendelser');
  const detail: string[] = [];
  if (p.matched > 0) {
    if (p.severe === 0) detail.push(p.matched === 1 ? 'Den var ikke alvorlig.' : 'Ingen av dem var alvorlige.');
    else if (p.matched === 1) detail.push('Den var alvorlig.');
    else detail.push(`${p.severe} av dem var ${p.severe === 1 ? 'alvorlig' : 'alvorlige'}.`);
  }
  if (p.hidden_traffic > 0) {
    detail.push(`${count(p.hidden_traffic, 'trafikkhendelse', 'trafikkhendelser')} er skjult.`);
  }
  if (p.imprecise_nearby > 0) {
    detail.push(
      `${count(p.imprecise_nearby, 'hendelse', 'hendelser')} i nærheten er bare oppgitt med bydel og telles ikke.`,
    );
  }
  return { headline, detail };
}

// --- the API's shapes (§8.6) -----------------------------------------------------------------

export interface SearchResult {
  kind: 'adresse' | 'sted';
  label: string;
  secondary: string;
  lat: number;
  lon: number;
  kommunenummer: string | null;
  /** Inside the ingested fylker (D9). */
  covered: boolean;
}

export interface PlaceFields {
  label: string;
  place_name: string | null;
  template: Template;
  lat: number;
  lon: number;
  radius_m: number;
  categories: AppCategory[];
  time_window: TimeWindow;
  push: boolean;
}

export interface Place extends PlaceFields {
  id: string;
  kommunenummer: string | null;
  covered: boolean;
  created_at: string;
}

/**
 * The PATCH body for an edit: only what changed. The coordinates and the place name go
 * together, since they come from the same search result.
 */
export function placeChanges(before: PlaceFields, after: PlaceFields): Partial<PlaceFields> {
  const out: Partial<PlaceFields> = {};
  if (after.label !== before.label) out.label = after.label;
  if (after.template !== before.template) out.template = after.template;
  if (after.radius_m !== before.radius_m) out.radius_m = after.radius_m;
  if (after.push !== before.push) out.push = after.push;
  if (canonical(after.categories).join() !== canonical(before.categories).join()) out.categories = after.categories;
  if (!sameWindow(after.time_window, before.time_window)) out.time_window = after.time_window;
  if (after.lat !== before.lat || after.lon !== before.lon) {
    out.lat = after.lat;
    out.lon = after.lon;
    out.place_name = after.place_name;
  } else if (after.place_name !== before.place_name) {
    out.place_name = after.place_name;
  }
  return out;
}
