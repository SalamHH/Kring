/**
 * lib/places.ts: templates (§6.1), the radius slider (§7.2, F3), time windows and the preview
 * text. The template table and the category list are checked against the spec itself.
 */
import { readFileSync } from 'fs';
import { join } from 'path';

import { radiusAt } from '@/components/RadiusSlider';
import {
  ALL_DAY,
  APP_CATEGORIES,
  canonical,
  DEFAULT_TEMPLATE,
  defaultLabel,
  type PlaceFields,
  placeChanges,
  previewText,
  RADIUS_DEFAULT,
  RADIUS_MAX,
  RADIUS_MIN,
  radiusLabel,
  sameWindow,
  showsSmallRadiusNote,
  snapRadius,
  type Template,
  TEMPLATE_ORDER,
  TEMPLATES,
  windowChoices,
  windowLabel,
} from '@/lib/places';

const spec = readFileSync(join(__dirname, '..', '..', 'docs', 'kring-spec.md'), 'utf8');

function section(start: string, end: string): string {
  const from = spec.indexOf(start);
  return spec.slice(from, spec.indexOf(end, from));
}

/** Rows of the §6.1 table: template → [categories, window text]. */
function templateTable(): Record<string, [string[], string]> {
  const out: Record<string, [string[], string]> = {};
  for (const line of section('## 6.1 Templates', '## 6.2').split('\n')) {
    const cells = line.split('|').map((c) => c.trim());
    if (cells.length < 4 || cells[1] === 'Template' || cells[1].startsWith('-')) continue;
    out[cells[1]] = [cells[2].split(',').map((c) => c.trim()), cells[3]];
  }
  return out;
}

describe('templates (§6.1)', () => {
  const table = templateTable();

  it('has the same five templates as the spec', () => {
    expect(Object.keys(table)).toEqual(TEMPLATE_ORDER.map((t) => TEMPLATES[t].name));
  });

  it.each(TEMPLATE_ORDER.filter((t) => t !== 'annet'))('%s has the spec categories', (t) => {
    const [cats] = table[TEMPLATES[t].name];
    expect(canonical(TEMPLATES[t].categories)).toEqual(canonical(cats));
  });

  it('Annet is all categories except Trafikk', () => {
    expect(table.Annet[0]).toEqual(['All except Trafikk']);
    expect(TEMPLATES.annet.categories).toEqual(APP_CATEGORIES.filter((c) => c !== 'Trafikk'));
  });

  it.each([
    ['skole', 'Weekdays 08:00–16:00', 'Hverdager 08–16'],
    ['hjem', 'All day', 'Hele døgnet'],
    ['hytte', 'All day', 'Hele døgnet'],
    ['jobb', 'Weekdays 07:00–17:00', 'Hverdager 07–17'],
    ['annet', 'All day', 'Hele døgnet'],
  ] as [Template, string, string][])('%s window is «%s»', (t, specText, label) => {
    expect(table[TEMPLATES[t].name][1]).toBe(specText);
    expect(windowLabel(TEMPLATES[t].window)).toBe(label);
  });

  it('the categories are Appendix B', () => {
    const appendix = section('# Appendix B', '| Key |');
    const fromSpec = [...appendix.matchAll(/^\| ([A-ZÆØÅ][^|]*?)(?: \(off by default\))? \|/gm)]
      .map((m) => m[1])
      .filter((c) => c !== 'App category (UI)');
    expect([...APP_CATEGORIES]).toEqual(fromSpec);
  });

  it('a new place starts as Skole, as in the prototype', () => {
    expect(DEFAULT_TEMPLATE).toBe('skole');
  });

  it('labels come from the template, or the search result for Annet', () => {
    expect(defaultLabel('skole', 'Tøyen skole')).toBe('Skolen');
    expect(defaultLabel('hjem', null)).toBe('Hjemme');
    expect(defaultLabel('annet', 'Tøyen skole')).toBe('Tøyen skole');
    expect(defaultLabel('annet', null)).toBe('');
    expect(defaultLabel('annet', 'x'.repeat(60))).toHaveLength(40);
  });
});

describe('radius (F3, §7.2 RadiusSlider)', () => {
  it('runs 300–2 000 m and starts at 1 000', () => {
    expect([RADIUS_MIN, RADIUS_MAX, RADIUS_DEFAULT]).toEqual([300, 2000, 1000]);
  });

  it.each([
    [300, '300 m'],
    [700, '700 m'],
    [900, '900 m'],
    [1000, '1,0 km'],
    [1500, '1,5 km'],
    [2000, '2,0 km'],
  ])('%i m is «%s»', (m, label) => {
    expect(radiusLabel(m)).toBe(label);
  });

  it('shows the small-radius InfoNote only below 1 000 m', () => {
    expect(showsSmallRadiusNote(300)).toBe(true);
    expect(showsSmallRadiusNote(900)).toBe(true);
    expect(showsSmallRadiusNote(1000)).toBe(false);
    expect(showsSmallRadiusNote(2000)).toBe(false);
  });

  it('snaps to steps of 100 inside the range', () => {
    expect(snapRadius(649)).toBe(600);
    expect(snapRadius(650)).toBe(700);
    expect(snapRadius(120)).toBe(300);
    expect(snapRadius(2600)).toBe(2000);
  });

  it('maps a touch on the slider to a radius', () => {
    // 26 pt thumb: the track runs from x = 13 to x = width − 13.
    expect(radiusAt(0, 366)).toBe(300);
    expect(radiusAt(13, 366)).toBe(300);
    expect(radiusAt(366, 366)).toBe(2000);
    expect(radiusAt(13 + 340 / 2, 366)).toBe(1200); // the middle: 1 150 rounds to 1 200
    expect(radiusAt(13 + (340 * 400) / 1700, 366)).toBe(700);
    expect(radiusAt(50, 0)).toBe(2000); // before layout: never NaN
  });
});

describe('time windows', () => {
  it('names day sets', () => {
    expect(windowLabel({ days: [6, 7], from: '10:30', to: '18:00' })).toBe('Helg 10:30–18');
    expect(windowLabel({ days: [1, 2, 3, 4, 5, 6, 7], from: '06:00', to: '22:00' })).toBe('Alle dager 06–22');
    expect(windowLabel({ days: [1, 3], from: '08:00', to: '12:00' })).toBe('Man, ons 08–12');
  });

  it('compares windows by value', () => {
    expect(sameWindow({ days: [5, 1, 2, 3, 4], from: '08:00', to: '16:00' }, TEMPLATES.skole.window)).toBe(true);
    expect(sameWindow(ALL_DAY, { all: true })).toBe(true);
    expect(sameWindow(ALL_DAY, TEMPLATES.skole.window)).toBe(false);
  });

  it('offers all day and the template windows, plus a place’s own', () => {
    expect(windowChoices(ALL_DAY).map(windowLabel)).toEqual(['Hele døgnet', 'Hverdager 08–16', 'Hverdager 07–17']);
    const own = { days: [6, 7], from: '10:00', to: '14:00' };
    expect(windowChoices(own).map(windowLabel)).toContain('Helg 10–14');
  });
});

describe('preview text', () => {
  const p = (matched: number, severe: number, hidden = 0, nearby = 0) => ({
    days: 30,
    matched,
    severe,
    hidden_traffic: hidden,
    imprecise_nearby: nearby,
  });

  it('gives the real count, with no «ca.»', () => {
    expect(previewText(p(5, 5, 3, 2))).toEqual({
      headline: '5 hendelser',
      detail: [
        '5 av dem var alvorlige.',
        '3 trafikkhendelser er skjult.',
        '2 hendelser i nærheten er bare oppgitt med bydel og telles ikke.',
      ],
    });
  });

  it('handles one and none', () => {
    expect(previewText(p(1, 1))).toEqual({ headline: '1 hendelse', detail: ['Den var alvorlig.'] });
    expect(previewText(p(1, 0, 1))).toEqual({
      headline: '1 hendelse',
      detail: ['Den var ikke alvorlig.', '1 trafikkhendelse er skjult.'],
    });
    expect(previewText(p(3, 1)).detail).toEqual(['1 av dem var alvorlig.']);
    expect(previewText(p(4, 0)).detail).toEqual(['Ingen av dem var alvorlige.']);
    expect(previewText(p(0, 0))).toEqual({ headline: 'Ingen hendelser', detail: [] });
  });
});

describe('placeChanges (edit → PATCH body)', () => {
  const before: PlaceFields = {
    label: 'Skolen',
    place_name: 'Tøyen skole',
    template: 'skole',
    lat: 59.91483,
    lon: 10.77318,
    radius_m: 1000,
    categories: ['Vold', 'Brann', 'Savnet', 'Ro og orden'],
    time_window: TEMPLATES.skole.window,
    push: true,
  };

  it('sends nothing when nothing changed', () => {
    expect(placeChanges(before, { ...before, categories: ['Brann', 'Vold', 'Savnet', 'Ro og orden'] })).toEqual({});
  });

  it('sends only the changed fields', () => {
    expect(placeChanges(before, { ...before, radius_m: 700, push: false })).toEqual({ radius_m: 700, push: false });
    expect(placeChanges(before, { ...before, time_window: ALL_DAY })).toEqual({ time_window: ALL_DAY });
  });

  it('sends the place name with new coordinates', () => {
    const moved = { ...before, lat: 59.9089, lon: 10.77923, place_name: 'Hølandsgata 1A' };
    expect(placeChanges(before, moved)).toEqual({ lat: 59.9089, lon: 10.77923, place_name: 'Hølandsgata 1A' });
  });
});

describe('error texts', () => {
  // Imported here so the rest of this file needs no React Native modules.
  // eslint-disable-next-line @typescript-eslint/no-require-imports
  const { errorText } = require('@/lib/errors') as typeof import('@/lib/errors');
  // eslint-disable-next-line @typescript-eslint/no-require-imports
  const { ApiError } = require('@/lib/api') as typeof import('@/lib/api');

  it.each([
    [new ApiError(409, 'place_limit', ''), 'Du kan ha opptil 10 steder. Slett et sted for å legge til et nytt.'],
    [new ApiError(502, 'kartverket_unavailable', ''), 'Kartverket svarer ikke akkurat nå. Prøv igjen om litt.'],
    [new ApiError(0, 'network', ''), 'Ingen forbindelse. Sjekk nettet og prøv igjen.'],
    [new ApiError(429, 'rate_limited', ''), 'For mange forespørsler. Vent litt og prøv igjen.'],
    [new ApiError(404, 'not_found', ''), 'Fant ikke stedet. Det kan være slettet.'],
    [new ApiError(500, 'internal', ''), 'Noe gikk galt. Prøv igjen.'],
    [new Error('x'), 'Noe gikk galt. Prøv igjen.'],
  ])('%s', (e, text) => {
    expect(errorText(e)).toBe(text);
  });
});
