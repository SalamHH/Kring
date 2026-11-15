/**
 * Hjem (app/index.tsx) rendered in Node: place cards with each status row, «N ny», the district
 * notice row, the poll status, and navigation. The API session, the router and the opened-file
 * are stand-ins.
 */
import { act, fireEvent, render, screen } from '@testing-library/react-native';

import Home from '@/app/index';
import type { EventSummary, Notice, PlaceEvents } from '@/lib/home';
import { OpenedStore } from '@/lib/opened';
import { ALL_DAY, type Place, TEMPLATES } from '@/lib/places';

jest.mock('react-native-safe-area-context', () => {
  const { View } = jest.requireActual('react-native');
  return { SafeAreaView: View };
});
const mockPush = jest.fn();
jest.mock('expo-router', () => {
  const { useEffect } = jest.requireActual('react');
  return {
    useRouter: () => ({ push: mockPush }),
    useFocusEffect: (effect: () => void) => useEffect(effect, [effect]),
  };
});
jest.mock('@/lib/bootstrap', () => ({ useDeviceBootstrap: () => ({ state: 'pending' }) }));
const mockStore = { current: null as unknown as OpenedStore };
jest.mock('@/lib/openedFile', () => ({
  get openedStore() {
    return mockStore.current;
  },
}));
const mockApi = { listPlaces: jest.fn(), placeEvents: jest.fn(), health: jest.fn() };
jest.mock('@/lib/session', () => ({ session: { call: (fn: (api: unknown) => unknown) => fn(mockApi) } }));

const NOW = new Date(2026, 10, 15, 14, 0);
const hoursAgo = (h: number) => new Date(NOW.getTime() - h * 3600_000).toISOString();

const place = (id: string, label: string, over: Partial<Place> = {}): Place => ({
  id,
  label,
  place_name: null,
  template: 'hjem',
  lat: 59.9,
  lon: 10.7,
  radius_m: 1000,
  categories: [...TEMPLATES.hjem.categories],
  time_window: ALL_DAY,
  push: true,
  kommunenummer: '0301',
  covered: true,
  created_at: '2026-11-01T00:00:00Z',
  ...over,
});

const event = (id: string, h: number, over: Partial<EventSummary> = {}): EventSummary => ({
  id,
  title: 'Brann · Hølandsgata',
  category: 'Brann',
  police_category: 'Brann',
  severity: 'severe',
  first_message_at: hoursAgo(h),
  last_message_at: hoursAgo(h),
  is_active: true,
  area: 'Kampen',
  municipality: 'Oslo',
  lat: 59.9,
  lon: 10.7,
  uncertainty_m: 40,
  precision_tier: 'gate',
  geocode_method: 'adresse',
  distance_m: 148,
  relation: 'match',
  pushed: true,
  ...over,
});

const NOTICE: Notice = {
  id: 'n1',
  title: 'Savnet · Oslo politidistrikt',
  category: 'Savnet',
  police_category: 'Savnet',
  district: 'Oslo politidistrikt',
  first_message_at: hoursAgo(3),
  last_message_at: hoursAgo(3),
  is_active: true,
};

const HJEMME = place('p1', 'Hjemme', { place_name: 'Hølandsgata 1A' });
const SKOLEN = place('p2', 'Skolen', {
  template: 'skole',
  place_name: 'Tøyen skole',
  time_window: TEMPLATES.skole.window,
});
const JOBBEN = place('p3', 'Jobben', { template: 'jobb', place_name: 'Grensen 10', radius_m: 500 });

const events = (place_id: string, list: EventSummary[], extra: Partial<PlaceEvents> = {}): PlaceEvents => ({
  place_id,
  days: 7,
  events: list,
  municipality_only: 0,
  district_notices: [],
  ...extra,
});

function serve(byPlace: Record<string, PlaceEvents | Error>) {
  mockApi.placeEvents.mockImplementation(async (id: string) => {
    const r = byPlace[id];
    if (r instanceof Error) throw r;
    return r;
  });
}

async function show() {
  await render(<Home />);
  await act(async () => {});
}

beforeEach(() => {
  jest.useFakeTimers({ now: NOW });
  jest.clearAllMocks();
  mockStore.current = new OpenedStore({ read: () => null, write: () => {} }, () => NOW.getTime());
  mockApi.health.mockResolvedValue({ status: 'ok', last_success_at: hoursAgo(0.05), age_s: 180 });
  mockApi.listPlaces.mockResolvedValue([HJEMME, SKOLEN, JOBBEN]);
  serve({
    p1: events('p1', [event('e1', 1), event('e0', 30, { title: 'Vold · Kampen' })]),
    p2: events('p2', [event('far', 2, { relation: 'imprecise_nearby', precision_tier: 'bydel' })], {
      municipality_only: 5,
    }),
    p3: events('p3', [event('near', 2, { relation: 'imprecise_nearby', precision_tier: 'bydel' })], {
      municipality_only: 2,
    }),
  });
});

afterEach(() => jest.useRealTimers());

describe('Hjem', () => {
  it('shows the title, the poll status, the source and a card per place', async () => {
    await show();
    expect(screen.getByText('Dine steder')).toBeOnTheScreen();
    expect(screen.getByTestId('updated')).toHaveTextContent('Oppdatert for 3 minutter siden');
    expect(screen.getByText('Kilde: Politiloggen (NLOD 2.0). Kring er ikke tilknyttet politiet.')).toBeOnTheScreen();
    expect(screen.getByText('Hølandsgata 1A · 1 km · hele døgnet')).toBeOnTheScreen();
    expect(screen.getByText('Tøyen skole · 1 km · hverdager 08–16')).toBeOnTheScreen();
    expect(screen.getByText('Grensen 10 · 500 m · hele døgnet')).toBeOnTheScreen();
    expect(mockApi.placeEvents).toHaveBeenCalledWith('p1', 7);
  });

  it('shows each status: newest incident, calm, and the small-radius note', async () => {
    await show();
    expect(screen.getByTestId('incident-e1')).toHaveTextContent(/Brann · Hølandsgata.*Gatenivå.*ca\. 150 m unna · 13:00/);
    expect(screen.queryByTestId('incident-e0')).not.toBeOnTheScreen();
    expect(screen.getByTestId('calm-p2')).toHaveTextContent(/Rolig siste 7 dager$/);
    expect(screen.getByTestId('imprecise-p3')).toHaveTextContent(/3 hendelser er bare oppgitt med bydel/);
  });

  it('counts «N ny» and lowers it when an incident has been opened', async () => {
    await show();
    expect(screen.getByTestId('new-p1')).toHaveTextContent('2 ny');
    expect(screen.queryByTestId('new-p2')).not.toBeOnTheScreen();

    await act(async () => mockStore.current.markOpened('e1'));
    expect(screen.getByTestId('new-p1')).toHaveTextContent('1 ny');
    await act(async () => mockStore.current.markOpened('e0'));
    expect(screen.queryByTestId('new-p1')).not.toBeOnTheScreen();
  });

  it('opens the incident with its place, and the place settings from the card', async () => {
    await show();
    await fireEvent.press(screen.getByTestId('incident-e1'));
    expect(mockPush).toHaveBeenLastCalledWith({ pathname: '/event/[id]', params: { id: 'e1', place: 'p1' } });
    await fireEvent.press(screen.getByTestId('place-head-p2'));
    expect(mockPush).toHaveBeenLastCalledWith({ pathname: '/place/[id]', params: { id: 'p2' } });
    await fireEvent.press(screen.getByTestId('add-place'));
    expect(mockPush).toHaveBeenLastCalledWith('/place/new');
  });

  it('shows a district notice once (D2)', async () => {
    serve({
      p1: events('p1', [], { district_notices: [NOTICE] }),
      p2: events('p2', [], { district_notices: [NOTICE] }),
      p3: events('p3', []),
    });
    await show();
    expect(screen.getAllByText('Fra politidistriktet')).toHaveLength(1);
    await fireEvent.press(screen.getByTestId('notice-n1'));
    expect(mockPush).toHaveBeenLastCalledWith({ pathname: '/event/[id]', params: { id: 'n1' } });
  });

  it('has no notice row without notices', async () => {
    await show();
    expect(screen.queryByText('Fra politidistriktet')).not.toBeOnTheScreen();
  });

  it('keeps a card whose events failed, with a note', async () => {
    serve({ p1: new Error('boom'), p2: events('p2', []), p3: events('p3', []) });
    await show();
    expect(screen.getByText('Hjemme')).toBeOnTheScreen();
    expect(screen.getByText('Fikk ikke hentet hendelsene. Dra ned for å prøve igjen.')).toBeOnTheScreen();
    expect(screen.getByTestId('calm-p2')).toBeOnTheScreen();
  });

  it('shows the empty text without places, and no poll status when health fails', async () => {
    mockApi.listPlaces.mockResolvedValue([]);
    mockApi.health.mockRejectedValue(new Error('down'));
    await show();
    expect(screen.getByTestId('home-empty')).toBeOnTheScreen();
    expect(screen.queryByTestId('updated')).not.toBeOnTheScreen();
  });
});
