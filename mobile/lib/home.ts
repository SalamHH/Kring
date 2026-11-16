/**
 * Hjem (F4, §7.2–7.3): what each place card shows. No React here, so jest covers it.
 *
 * - The status row is the newest matched incident of the last 7 days; otherwise, for a place
 *   under 1 km, the small-radius note when incidents nearby were given only as a district or
 *   municipality (D1, the *Jobben* card); otherwise «Rolig siste 7 dager».
 * - «N ny» counts matched incidents of the last 7 days not yet opened on this device.
 */
import { type Place, SMALL_RADIUS_BELOW, windowLabel } from './places';
import { t } from './strings';

export const HOME_DAYS = 7;

export type Tier = 'gate' | 'nabolag' | 'bydel';
export type Relation = 'match' | 'imprecise_nearby';

/** One event in GET /v1/places/{id}/events (§8.6). */
export interface EventSummary {
  id: string;
  title: string;
  category: string;
  police_category: string;
  severity: 'severe' | 'normal';
  first_message_at: string;
  last_message_at: string;
  is_active: boolean | null;
  area: string | null;
  municipality: string | null;
  lat: number;
  lon: number;
  uncertainty_m: number | null;
  precision_tier: Tier;
  geocode_method: string | null;
  distance_m: number;
  relation: Relation;
  pushed: boolean;
}

/** A district-wide notice (D2). */
export interface Notice {
  id: string;
  title: string;
  category: string;
  police_category: string;
  district: string;
  first_message_at: string;
  last_message_at: string;
  is_active: boolean | null;
}

export interface PlaceEvents {
  place_id: string;
  days: number;
  events: EventSummary[];
  municipality_only: number;
  district_notices: Notice[];
}

export interface Health {
  status: 'ok' | 'stale' | 'db_unavailable';
  last_success_at: string | null;
  age_s: number | null;
}

export type Status =
  | { kind: 'incident'; event: EventSummary }
  | { kind: 'imprecise'; count: number }
  | { kind: 'calm' };

const DAY_MS = 24 * 3600 * 1000;

function withinDays(e: { first_message_at: string }, now: Date, days = HOME_DAYS): boolean {
  return now.getTime() - new Date(e.first_message_at).getTime() <= days * DAY_MS;
}

/** Matched incidents of the last 7 days, newest first. */
export function recentMatches(pe: PlaceEvents, now: Date): EventSummary[] {
  return pe.events
    .filter((e) => e.relation === 'match' && withinDays(e, now))
    .sort((a, b) => b.first_message_at.localeCompare(a.first_message_at));
}

export function placeStatus(place: Pick<Place, 'radius_m'>, pe: PlaceEvents, now: Date): Status {
  const newest = recentMatches(pe, now)[0];
  if (newest) return { kind: 'incident', event: newest };
  if (place.radius_m < SMALL_RADIUS_BELOW) {
    const imprecise =
      pe.events.filter((e) => e.relation === 'imprecise_nearby' && withinDays(e, now)).length +
      pe.municipality_only;
    if (imprecise > 0) return { kind: 'imprecise', count: imprecise };
  }
  return { kind: 'calm' };
}

/** «N ny»: matched incidents of the last 7 days that haven't been opened on this device. */
export function newCount(pe: PlaceEvents, isOpened: (id: string) => boolean, now: Date): number {
  return recentMatches(pe, now).filter((e) => !isOpened(e.id)).length;
}

/** The text of the small-radius note. */
export function impreciseText(count: number): string {
  return count === 1 ? t('home.impreciseOne') : t('home.imprecise', { n: count });
}

// --- texts on the card ---------------------------------------------------------------------

/** «1 km», «500 m», «1,5 km»: the short radius on a card (§7.2: «Kampen · 1 km · hele døgnet»). */
export function radiusShort(m: number): string {
  if (m < 1000) return `${m} m`;
  const km = m / 1000;
  return `${Number.isInteger(km) ? km : km.toFixed(1).replace('.', ',')} km`;
}

/** «Tøyen skole · 1 km · hverdager 08–16». Places made before place_name have no first part. */
export function placeMeta(place: Pick<Place, 'place_name' | 'radius_m' | 'time_window'>): string {
  const w = windowLabel(place.time_window);
  return [place.place_name, radiusShort(place.radius_m), w.charAt(0).toLowerCase() + w.slice(1)]
    .filter(Boolean)
    .join(' · ');
}

/** «ca. 150 m unna», rounded as in the push title (§8.7): 50 m under 1 km, 100 m above. */
export function distanceText(m: number): string {
  if (m < 1000) return `ca. ${Math.max(50, Math.round(m / 50) * 50)} m unna`;
  const rounded = Math.round(m / 100) / 10;
  return `ca. ${rounded.toFixed(1).replace('.', ',')} km unna`;
}

const MONTHS = ['jan.', 'feb.', 'mars', 'apr.', 'mai', 'juni', 'juli', 'aug.', 'sep.', 'okt.', 'nov.', 'des.'];

function sameDay(a: Date, b: Date): boolean {
  return a.getFullYear() === b.getFullYear() && a.getMonth() === b.getMonth() && a.getDate() === b.getDate();
}

/** «08:23» today, «i går 08:23», «13. nov.» before that; in the device's time zone. */
export function timeText(iso: string, now: Date): string {
  const d = new Date(iso);
  const hhmm = `${String(d.getHours()).padStart(2, '0')}:${String(d.getMinutes()).padStart(2, '0')}`;
  if (sameDay(d, now)) return hhmm;
  const yesterday = new Date(now);
  yesterday.setDate(now.getDate() - 1);
  if (sameDay(d, yesterday)) return `i går ${hhmm}`;
  return `${d.getDate()}. ${MONTHS[d.getMonth()]}`;
}

/** «ca. 150 m unna · 08:23» (§7.2 IncidentRow). */
export function incidentMeta(e: EventSummary, now: Date): string {
  return `${distanceText(e.distance_m)} · ${timeText(e.first_message_at, now)}`;
}

/** «Oppdatert for N minutter siden» (Appendix B), from GET /v1/health. null when unknown. */
export function updatedText(h: Health | null): string | null {
  if (!h || h.age_s === null) return null;
  const min = Math.floor(h.age_s / 60);
  if (min < 1) return t('home.updatedNow');
  if (min === 1) return t('home.updatedOne');
  if (min < 60) return t('home.updated', { n: min });
  const hours = Math.floor(min / 60);
  return hours === 1 ? t('home.updatedHour') : t('home.updatedHours', { n: hours });
}

/** The notices of all places, once each, newest first (D2). */
export function districtNotices(all: PlaceEvents[]): Notice[] {
  const byId = new Map<string, Notice>();
  for (const pe of all) for (const n of pe.district_notices) byId.set(n.id, n);
  return [...byId.values()].sort((a, b) => b.first_message_at.localeCompare(a.first_message_at));
}
