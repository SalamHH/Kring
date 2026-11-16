/**
 * Hendelse (F5, §7.3, D12): what the screen says. No React here, so jest covers it.
 *
 * - The precision card explains the `geocode_method` in plain words (§9.1), and says when a long
 *   street or a large place makes the ring wide.
 * - «Hvorfor fikk jeg dette?» says whether this place got a push, and why or why not, from
 *   `for_place` (§8.6) and the push rules (§6.2). It never guesses a reason the API doesn't give.
 * - «Del med familien» shares the title, time and police text with «Kilde: Politiloggen» (D12).
 */
import { radiusShort, type Relation, type Tier } from './home';
import type { Place } from './places';
import { t } from './strings';

/** GET /v1/events/{id} (§8.6). */
export interface EventDetail {
  id: string;
  title: string;
  category: string;
  police_category: string;
  severity: 'severe' | 'normal';
  scope: 'kommune' | 'distrikt';
  district: string | null;
  municipality: string | null;
  kommunenummer: string | null;
  area: string | null;
  is_active: boolean | null;
  is_control: boolean;
  first_message_at: string;
  last_message_at: string;
  lat: number | null;
  lon: number | null;
  uncertainty_m: number | null;
  precision_tier: Tier | null;
  geocode_method: string | null;
  geocode_match: string | null;
  messages: { seq: number; created_at: string; text: string }[];
  for_place?: ForPlace | null;
}

/** With `?place_id=`: how the event relates to that place. */
export interface ForPlace {
  place_id: string;
  distance_m: number | null;
  /** null: neither a match nor imprecise nearby. */
  relation: Relation | null;
  category_followed: boolean;
  pushed: boolean;
}

export function isNotice(e: Pick<EventDetail, 'scope'>): boolean {
  return e.scope === 'distrikt';
}

/** The category on the chip and in texts: the police category for Andre (D5). */
export function categoryName(e: Pick<EventDetail, 'category' | 'police_category'>): string {
  return e.category === 'Andre' ? e.police_category : e.category;
}

/** «Pågår» / «Avsluttet» from `is_active`; null when Politiloggen doesn't say. */
export function statusText(isActive: boolean | null): string | null {
  if (isActive === null) return null;
  return isActive ? t('event.active') : t('event.ended');
}

// --- times -----------------------------------------------------------------------------------

const WEEKDAYS = ['søn.', 'man.', 'tir.', 'ons.', 'tor.', 'fre.', 'lør.'];
const MONTHS = ['jan.', 'feb.', 'mars', 'apr.', 'mai', 'juni', 'juli', 'aug.', 'sep.', 'okt.', 'nov.', 'des.'];

function hhmm(d: Date): string {
  return `${String(d.getHours()).padStart(2, '0')}:${String(d.getMinutes()).padStart(2, '0')}`;
}

function sameDay(a: Date, b: Date): boolean {
  return a.getFullYear() === b.getFullYear() && a.getMonth() === b.getMonth() && a.getDate() === b.getDate();
}

/** «man. 2. nov. 08:23», in the device's time zone. */
export function dateTimeText(iso: string): string {
  const d = new Date(iso);
  return `${WEEKDAYS[d.getDay()]} ${d.getDate()}. ${MONTHS[d.getMonth()]} ${hhmm(d)}`;
}

/** A police update's time: «08:44» on the first message's day, «3. nov. 08:44» after it. */
export function messageTime(iso: string, firstIso: string): string {
  const d = new Date(iso);
  return sameDay(d, new Date(firstIso)) ? hhmm(d) : `${d.getDate()}. ${MONTHS[d.getMonth()]} ${hhmm(d)}`;
}

// --- where -----------------------------------------------------------------------------------

/** «Hølandsgata, Kampen»: the matched street or place, then the police area or municipality. */
export function whereText(e: EventDetail): string {
  if (isNotice(e)) return e.district ?? e.municipality ?? '';
  const parts: string[] = [];
  for (const p of [e.geocode_match, e.area ?? e.municipality]) {
    const v = p?.trim();
    if (!v) continue;
    // «Kampen» after «Kampen», or «Hølandsgata» inside «Hølandsgata 4, Kampen», is said once.
    if (parts.some((q) => q.toLowerCase().includes(v.toLowerCase()))) continue;
    parts.push(v);
  }
  return parts.join(', ');
}

/** «Hølandsgata, Kampen · man. 2. nov. 08:23». */
export function subtitle(e: EventDetail): string {
  return [whereText(e), dateTimeText(e.first_message_at)].filter(Boolean).join(' · ');
}

/** «±150 m», «±1,2 km». */
export function uncertaintyText(m: number): string {
  if (m < 1000) return `±${m} m`;
  const km = Math.round(m / 100) / 10;
  return `±${Number.isInteger(km) ? km : km.toFixed(1).replace('.', ',')} km`;
}

/** Whether the map can show the incident: a point, always with its ring (§5, honest precision). */
export function hasPoint(e: EventDetail): e is EventDetail & { lat: number; lon: number } {
  return e.lat !== null && e.lon !== null;
}

/** A point without a stored uncertainty is drawn with the widest gate-tier ring, never as a pin. */
export const FALLBACK_UNCERTAINTY_M = 500;

// --- «Hvor presist er dette?» ----------------------------------------------------------------

/** Above this, a street or place covers a whole area, and the explanation says so. */
const WIDE_M = 1500;

/** The explanation of how the incident was placed (§9.1, §9.2). */
export function methodText(method: string | null, uncertaintyM: number | null): string {
  const wide = uncertaintyM !== null && uncertaintyM > WIDE_M;
  switch (method) {
    case 'adresse':
      return t('precision.adresse');
    case 'kryss':
      return t('precision.kryss');
    case 'gate_area':
    case 'gate_tekst':
      return wide ? `${t('precision.gate')} ${t('precision.longStreet')}` : t('precision.gate');
    case 'gate_omrade':
      return t('precision.gateOmrade');
    case 'stedsnavn':
    case 'stedsnavn_utvidet':
      return wide ? t('precision.stedsnavnWide') : t('precision.stedsnavn');
    case 'stedsnavn_tekst':
      return t('precision.stedsnavnTekst');
    case 'kommunenavn':
      return t('precision.kommunenavn');
    case 'kommune':
      return t('precision.kommune');
    case null:
      return t('precision.none');
    default:
      // A method the app doesn't know yet: say what the ring means.
      return t('precision.other');
  }
}

/** The badge: «Gatenivå · ±150 m», or «Bydel» when there is no point. */
export function badgeText(tier: Tier, uncertaintyM: number | null): string {
  return uncertaintyM === null ? t(`tier.${tier}`) : `${t(`tier.${tier}`)} · ${uncertaintyText(uncertaintyM)}`;
}

// --- «Hvorfor fikk jeg dette?» ---------------------------------------------------------------

/** A piece of the «Hvorfor» text; the place's label is bold, as in the mockup. */
export interface WhyPart {
  text: string;
  bold?: boolean;
}

/** The parts as one string, for screen readers and tests. */
export function plain(parts: WhyPart[]): string {
  return parts.map((p) => p.text).join('');
}

/** «brann», «ro og orden», «andre hendelser»: a category inside a sentence. */
function followed(category: string): string {
  return category === 'Andre' ? 'andre hendelser' : category.toLowerCase();
}

/** Splits a string at «{label}» so the label can be bold. */
function withLabel(text: string, label: string): WhyPart[] {
  const [before, after = ''] = text.split('{label}');
  return [{ text: before }, { text: label, bold: true }, { text: after }].filter((p) => p.text);
}

type WhyPlace = Pick<Place, 'label' | 'radius_m' | 'push'>;

/**
 * The «Hvorfor fikk jeg dette?» text, or null when the screen was opened without a place
 * (an incident has no «why» on its own; a district notice still does).
 */
export function whyText(e: EventDetail, place: WhyPlace | null): WhyPart[] | null {
  const fp = e.for_place ?? null;

  if (isNotice(e)) {
    const district = e.district ?? e.municipality ?? '';
    const parts: WhyPart[] = [{ text: t('why.notice', { district }) }];
    if (place && fp?.pushed) parts.push({ text: ' ' }, ...withLabel(t('why.noticePushed', { category: followed(e.category) }), place.label));
    return parts;
  }
  if (!place || !fp) return null;

  const r = radiusShort(place.radius_m);
  const cat = followed(e.category);

  if (fp.relation === 'match') {
    const parts = withLabel(t('why.match', { radius: r, category: cat }), place.label);
    let reason: string;
    if (fp.pushed) reason = t('why.pushed');
    else if (!place.push) reason = t('why.pushOff');
    else if (e.severity !== 'severe') reason = t('why.notSevere');
    else reason = t('why.notPushed');
    return [...parts, { text: ` ${reason}` }];
  }
  if (fp.relation === 'imprecise_nearby') {
    return withLabel(t('why.imprecise', { radius: r }), place.label);
  }
  // Neither: opened from an old list, or the place or its categories changed since.
  if (!fp.category_followed) return withLabel(t('why.notFollowed', { category: cat }), place.label);
  if (!hasPoint(e)) return withLabel(t('why.noPoint'), place.label);
  if (fp.distance_m !== null && fp.distance_m <= place.radius_m && e.precision_tier !== 'gate') {
    return withLabel(t('why.tooImprecise', { radius: r }), place.label);
  }
  return withLabel(t('why.outside', { radius: r }), place.label);
}

// --- «Del med familien» (D12) ----------------------------------------------------------------

/** The title, time and place, every police update with its time, and the source. No app link. */
export function shareText(e: EventDetail): string {
  const updates = e.messages.map((m) => `${messageTime(m.created_at, e.first_message_at)} ${m.text}`);
  return [e.title, subtitle(e), '', ...updates, '', t('event.shareSource')].join('\n');
}
