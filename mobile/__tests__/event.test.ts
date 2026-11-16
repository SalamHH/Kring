/**
 * Hendelse's rules (lib/event.ts) and the push deep link (lib/pushLinks.ts): the explanation for
 * every geocode_method, the «Hvorfor» text in each case, the share text, times and places.
 */
import {
  badgeText,
  categoryName,
  dateTimeText,
  type EventDetail,
  type ForPlace,
  messageTime,
  methodText,
  plain,
  shareText,
  statusText,
  subtitle,
  uncertaintyText,
  whereText,
  whyText,
} from '@/lib/event';
import { eventLink, openResponse, resetHandled } from '@/lib/pushLinks';
import { strings } from '@/lib/strings';

jest.mock('expo-router', () => ({ router: { push: jest.fn() } }));
jest.mock('expo-notifications', () => ({ DEFAULT_ACTION_IDENTIFIER: 'expo.modules.notifications.actions.DEFAULT' }));

const at = (d: number, h: number, m: number) => new Date(2026, 10, d, h, m).toISOString();

const FIRE: EventDetail = {
  id: '26rj6c',
  title: 'Brann · Hølandsgata',
  category: 'Brann',
  police_category: 'Brann',
  severity: 'severe',
  scope: 'kommune',
  district: 'Oslo politidistrikt',
  municipality: 'Oslo',
  kommunenummer: '0301',
  area: 'Kampen',
  is_active: false,
  is_control: false,
  first_message_at: at(2, 8, 23),
  last_message_at: at(2, 9, 2),
  lat: 59.913,
  lon: 10.78,
  uncertainty_m: 150,
  precision_tier: 'gate',
  geocode_method: 'gate_tekst',
  geocode_match: 'Hølandsgata',
  messages: [
    { seq: 1, created_at: at(2, 8, 23), text: 'Nødetatene rykker ut til melding om branntilløp.' },
    { seq: 2, created_at: at(2, 8, 31), text: 'Brannen er slukket.' },
    { seq: 3, created_at: at(3, 7, 5), text: 'Ingen personskader.' },
  ],
};

const NOTICE: EventDetail = {
  ...FIRE,
  id: '26notice',
  title: 'Savnet · Oslo politidistrikt',
  category: 'Savnet',
  police_category: 'Savnet',
  scope: 'distrikt',
  municipality: null,
  kommunenummer: null,
  area: null,
  is_active: true,
  lat: null,
  lon: null,
  uncertainty_m: null,
  precision_tier: null,
  geocode_method: null,
  geocode_match: null,
  messages: [{ seq: 1, created_at: at(2, 8, 23), text: 'Politiet ber om tips om en savnet person.' }],
};

const HJEMME = { label: 'Hjemme', radius_m: 1000, push: true };
const fp = (over: Partial<ForPlace> = {}): ForPlace => ({
  place_id: 'p1',
  distance_m: 148,
  relation: 'match',
  category_followed: true,
  pushed: true,
  ...over,
});
const why = (e: EventDetail, place: typeof HJEMME | null = HJEMME) => {
  const parts = whyText(e, place);
  return parts && plain(parts);
};

describe('the precision card', () => {
  // Every method the backend writes (backend/app/geocode/pipeline.py METHOD_NAMES), and none.
  const METHODS = [
    'adresse',
    'kryss',
    'gate_area',
    'gate_tekst',
    'gate_omrade',
    'stedsnavn',
    'stedsnavn_utvidet',
    'stedsnavn_tekst',
    'kommunenavn',
    'kommune',
  ];

  it.each(METHODS)('explains %s in its own words', (method) => {
    const text = methodText(method, 300);
    expect(text).not.toBe(strings['precision.other']);
    expect(text.length).toBeGreaterThan(20);
  });

  it('gives the methods that differ different texts', () => {
    const texts = new Set(METHODS.map((m) => methodText(m, 300)));
    // gate_area and gate_tekst are both «the street»; stedsnavn and stedsnavn_utvidet both «a place name».
    expect(texts.size).toBe(METHODS.length - 2);
  });

  it('says what the texts say', () => {
    expect(methodText('gate_tekst', 150)).toBe('Politiet oppga gatenavnet. Vi vet hvilken gate, men ikke hvilket hus.');
    expect(methodText('adresse', 25)).toBe('Politiet oppga en adresse med husnummer. Punktet er den adressen.');
    expect(methodText('kommune', null)).toBe('Politiet oppga bare kommunen, så vi kan ikke vise hvor det skjedde.');
  });

  it('says when a long street or a large place makes the ring wide', () => {
    expect(methodText('gate_area', 1800)).toContain('Gaten er lang');
    expect(methodText('gate_area', 1500)).not.toContain('Gaten er lang');
    expect(methodText('stedsnavn', 2500)).toBe(strings['precision.stedsnavnWide']);
    expect(methodText('stedsnavn', 700)).toBe(strings['precision.stedsnavn']);
  });

  it('handles a failed lookup and a method the app does not know', () => {
    expect(methodText(null, null)).toBe(strings['precision.none']);
    expect(methodText('ny_metode', 400)).toBe(strings['precision.other']);
  });

  it('labels the badge with the uncertainty', () => {
    expect(badgeText('gate', 150)).toBe('Gatenivå · ±150 m');
    expect(badgeText('nabolag', 1200)).toBe('Nabolag · ±1,2 km');
    expect(badgeText('bydel', 2500)).toBe('Bydel · ±2,5 km');
    expect(badgeText('bydel', null)).toBe('Bydel');
    expect(uncertaintyText(1000)).toBe('±1 km');
  });
});

describe('«Hvorfor fikk jeg dette?»', () => {
  it('says why a matched incident was pushed', () => {
    expect(why({ ...FIRE, for_place: fp() })).toBe(
      'Hendelsen er innenfor Hjemme (1 km), og du følger brann. Du fikk push fordi den regnes som alvorlig og var ny da Kring fant den.',
    );
  });

  it('makes the place label bold', () => {
    const parts = whyText({ ...FIRE, for_place: fp() }, HJEMME)!;
    expect(parts.filter((p) => p.bold)).toEqual([{ text: 'Hjemme', bold: true }]);
  });

  it('says why a matched incident was not pushed', () => {
    const notPushed = fp({ pushed: false });
    expect(why({ ...FIRE, severity: 'normal', for_place: notPushed })).toContain(
      'Du fikk ikke push, fordi push bare sendes for alvorlige hendelser.',
    );
    expect(why({ ...FIRE, for_place: notPushed }, { ...HJEMME, push: false })).toContain(
      'Push er slått av for dette stedet.',
    );
    // Severe and push on: the API doesn't say which rule held it back, so all are named.
    expect(why({ ...FIRE, for_place: notPushed })).toContain('innenfor tidsrommet du har valgt');
  });

  it('explains an imprecise incident nearby, which is never pushed', () => {
    const e = { ...FIRE, precision_tier: 'bydel' as const, uncertainty_m: 2500, for_place: fp({ relation: 'imprecise_nearby', pushed: false }) };
    expect(why(e)).toBe(
      'Politiet oppga bare et større område, og det overlapper Hjemme (1 km). Hendelser uten gate eller stedsnavn sendes aldri som push.',
    );
  });

  it('explains an incident that does not count for the place', () => {
    const none = fp({ relation: null, pushed: false });
    expect(why({ ...FIRE, category: 'Ro og orden', for_place: { ...none, category_followed: false } })).toBe(
      'Du følger ikke ro og orden for Hjemme, så den teller ikke for stedet.',
    );
    expect(why({ ...FIRE, for_place: { ...none, distance_m: 1400 } })).toBe('Hendelsen er utenfor Hjemme (1 km).');
    expect(
      why({ ...FIRE, precision_tier: 'nabolag', for_place: { ...none, distance_m: 400 } }, { ...HJEMME, radius_m: 500 }),
    ).toContain('I et område under 1 km teller bare hendelser på gatenivå.');
    expect(why({ ...FIRE, lat: null, lon: null, for_place: { ...none, distance_m: null } })).toBe(
      'Politiet oppga bare kommunen, så den teller ikke for Hjemme.',
    );
  });

  it('explains a district notice, with or without a place', () => {
    const base =
      'Politiet meldte dette for hele Oslo politidistrikt, ikke for et bestemt sted. Slike meldinger vises i 24 timer for stedene dine i distriktet.';
    expect(why(NOTICE, null)).toBe(base);
    expect(why({ ...NOTICE, for_place: fp({ relation: null, pushed: false }) })).toBe(base);
    expect(why({ ...NOTICE, for_place: fp({ relation: null, pushed: true }) })).toBe(
      `${base} Du fikk push fordi du følger savnet for Hjemme.`,
    );
  });

  it('is left out for an incident opened without a place', () => {
    expect(whyText(FIRE, null)).toBeNull();
    expect(whyText({ ...FIRE, for_place: null }, HJEMME)).toBeNull();
  });

  it('writes Andre as «andre hendelser»', () => {
    const e = { ...FIRE, category: 'Andre', police_category: 'Ulykke', for_place: fp({ pushed: false }) };
    expect(why(e)).toContain('og du følger andre hendelser.');
  });
});

describe('the heading', () => {
  it('names the category, using the police category for Andre (D5)', () => {
    expect(categoryName(FIRE)).toBe('Brann');
    expect(categoryName({ category: 'Andre', police_category: 'Ulykke' })).toBe('Ulykke');
  });

  it('shows the status from is_active', () => {
    expect(statusText(true)).toBe('Pågår');
    expect(statusText(false)).toBe('Avsluttet');
    expect(statusText(null)).toBeNull();
  });

  it('writes «gate, område · dato tid»', () => {
    expect(dateTimeText(at(2, 8, 23))).toBe('man. 2. nov. 08:23');
    expect(subtitle(FIRE)).toBe('Hølandsgata, Kampen · man. 2. nov. 08:23');
  });

  it('says a place once', () => {
    expect(whereText({ ...FIRE, geocode_match: 'Kampen' })).toBe('Kampen');
    expect(whereText({ ...FIRE, geocode_match: 'Hølandsgata 4', area: 'Hølandsgata' })).toBe('Hølandsgata 4');
    expect(whereText({ ...FIRE, geocode_match: null, area: null })).toBe('Oslo');
  });

  it('uses the district for a notice', () => {
    expect(subtitle(NOTICE)).toBe('Oslo politidistrikt · man. 2. nov. 08:23');
  });

  it('dates updates from a later day', () => {
    expect(messageTime(at(2, 8, 31), FIRE.first_message_at)).toBe('08:31');
    expect(messageTime(at(3, 7, 5), FIRE.first_message_at)).toBe('3. nov. 07:05');
  });
});

describe('«Del med familien» (D12)', () => {
  it('shares the title, time, every update and the source, with no link', () => {
    expect(shareText(FIRE)).toBe(
      [
        'Brann · Hølandsgata',
        'Hølandsgata, Kampen · man. 2. nov. 08:23',
        '',
        '08:23 Nødetatene rykker ut til melding om branntilløp.',
        '08:31 Brannen er slukket.',
        '3. nov. 07:05 Ingen personskader.',
        '',
        'Kilde: Politiloggen',
      ].join('\n'),
    );
    expect(shareText(FIRE)).not.toMatch(/https?:|kring:/);
  });
});

describe('the push deep link (§8.7)', () => {
  const PLACE = '3f2b8c1e-5d4a-4e7b-9c0d-1a2b3c4d5e6f';

  it('opens the incident for the place', () => {
    expect(eventLink({ event_id: '26rj6c', place_id: PLACE })).toEqual({
      pathname: '/event/[id]',
      params: { id: '26rj6c', place: PLACE },
    });
  });

  it('parses defensively', () => {
    expect(eventLink({ event_id: '26rj6c' })).toEqual({ pathname: '/event/[id]', params: { id: '26rj6c' } });
    expect(eventLink({ event_id: '26rj6c', place_id: 'nope' })).toEqual({
      pathname: '/event/[id]',
      params: { id: '26rj6c' },
    });
    expect(eventLink(null)).toBeNull();
    expect(eventLink({})).toBeNull();
    expect(eventLink({ event_id: 42 })).toBeNull();
    expect(eventLink({ event_id: '../place/x' })).toBeNull();
  });

  const response = (id: string, data: unknown, action = 'expo.modules.notifications.actions.DEFAULT') =>
    ({ actionIdentifier: action, notification: { request: { identifier: id, content: { data } } } }) as never;

  beforeEach(() => resetHandled());

  it('opens each tapped notification once', () => {
    const go = jest.fn();
    const r = response('n1', { event_id: '26rj6c', place_id: PLACE });
    expect(openResponse(r, go)).toBe(true);
    // Cold start: the listener and the last response can both report the same tap.
    expect(openResponse(r, go)).toBe(false);
    expect(go).toHaveBeenCalledTimes(1);
    expect(go).toHaveBeenCalledWith({ pathname: '/event/[id]', params: { id: '26rj6c', place: PLACE } });
    expect(openResponse(response('n2', { event_id: '26cwjm' }), go)).toBe(true);
    expect(go).toHaveBeenCalledTimes(2);
  });

  it('ignores no response, other actions and other payloads', () => {
    const go = jest.fn();
    expect(openResponse(null, go)).toBe(false);
    expect(openResponse(response('n3', { event_id: '26rj6c' }, 'expo.modules.notifications.actions.DISMISS'), go)).toBe(false);
    expect(openResponse(response('n4', { kind: 'digest' }), go)).toBe(false);
    expect(go).not.toHaveBeenCalled();
  });
});
