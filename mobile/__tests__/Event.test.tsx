/**
 * Hendelse (app/event/[id].tsx) rendered in Node: the sections for an incident and a district
 * notice, the place used for the map and «Hvorfor», «Del med familien», «Færre slike varsler»,
 * a deleted place, a failed load, and «N ny». The map, router, API session and file store are
 * stand-ins.
 */
import { act, fireEvent, render, screen } from '@testing-library/react-native';
import { Share } from 'react-native';

import EventScreen from '@/app/event/[id]';
import { ApiError } from '@/lib/api';
import type { EventDetail } from '@/lib/event';
import { ALL_DAY, type Place, TEMPLATES } from '@/lib/places';

const mockMap = jest.fn();
jest.mock('@/components/PlaceMap', () => ({
  PlaceMap: (props: unknown) => {
    mockMap(props);
    return null;
  },
}));
jest.mock('react-native-safe-area-context', () => {
  const { View } = jest.requireActual('react-native');
  return { SafeAreaView: View };
});
const mockRouter = { push: jest.fn(), back: jest.fn(), replace: jest.fn(), canGoBack: jest.fn(() => true) };
const mockParams = { current: {} as { id: string; place?: string } };
jest.mock('expo-router', () => ({
  useRouter: () => mockRouter,
  useLocalSearchParams: () => mockParams.current,
}));
const mockMarkOpened = jest.fn();
jest.mock('@/lib/openedFile', () => ({ openedStore: { markOpened: (id: string) => mockMarkOpened(id) } }));
const mockApi = { event: jest.fn(), listPlaces: jest.fn() };
jest.mock('@/lib/session', () => ({ session: { call: (fn: (api: unknown) => unknown) => fn(mockApi) } }));

const at = (d: number, h: number, m: number) => new Date(2026, 10, d, h, m).toISOString();

const HJEMME: Place = {
  id: 'p1',
  label: 'Hjemme',
  place_name: 'Hølandsgata 1A',
  template: 'hjem',
  lat: 59.914,
  lon: 10.779,
  radius_m: 1000,
  categories: [...TEMPLATES.hjem.categories],
  time_window: ALL_DAY,
  push: true,
  kommunenummer: '0301',
  covered: true,
  created_at: '2026-11-01T00:00:00Z',
};

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
    { seq: 2, created_at: at(2, 9, 2), text: 'Nødetatene ferdig på stedet.' },
  ],
  for_place: { place_id: 'p1', distance_m: 148, relation: 'match', category_followed: true, pushed: true },
};

const NOTICE: EventDetail = {
  ...FIRE,
  id: '26notice',
  title: 'Savnet · Oslo politidistrikt',
  category: 'Savnet',
  police_category: 'Savnet',
  scope: 'distrikt',
  is_active: true,
  lat: null,
  lon: null,
  uncertainty_m: null,
  precision_tier: null,
  geocode_method: null,
  geocode_match: null,
  messages: [{ seq: 1, created_at: at(2, 8, 23), text: 'Politiet ber om tips om en savnet person.' }],
  for_place: null,
};

async function show(params: { id: string; place?: string }) {
  mockParams.current = params;
  await render(<EventScreen />);
  await act(async () => {});
}

beforeEach(() => {
  jest.clearAllMocks();
  mockApi.listPlaces.mockResolvedValue([HJEMME]);
  mockApi.event.mockResolvedValue(FIRE);
});

describe('Hendelse', () => {
  it('shows the incident from top to bottom', async () => {
    await show({ id: '26rj6c', place: 'p1' });
    expect(mockApi.event).toHaveBeenCalledWith('26rj6c', 'p1');

    expect(screen.getByTestId('event-category')).toHaveTextContent('Brann');
    expect(screen.getByTestId('event-status')).toHaveTextContent('Avsluttet');
    expect(screen.getByTestId('event-title')).toHaveTextContent('Brann · Hølandsgata');
    expect(screen.getByTestId('event-subtitle')).toHaveTextContent('Hølandsgata, Kampen · man. 2. nov. 08:23');

    // The map: the place circle dashed, and the incident with its ring.
    expect(mockMap).toHaveBeenLastCalledWith(
      expect.objectContaining({
        place: { center: { lat: 59.914, lon: 10.779 }, radiusM: 1000 },
        dashed: true,
        incident: { point: { lat: 59.913, lon: 10.78 }, uncertaintyM: 150 },
      }),
    );
    expect(screen.getByText('Hjemme · 1 km')).toBeOnTheScreen();
    expect(screen.getByText('Hendelsen · ±150 m')).toBeOnTheScreen();

    expect(screen.getByText('Hvor presist er dette?')).toBeOnTheScreen();
    expect(screen.getByText('Gatenivå · ±150 m')).toBeOnTheScreen();
    expect(screen.getByTestId('event-method')).toHaveTextContent(
      'Politiet oppga gatenavnet. Vi vet hvilken gate, men ikke hvilket hus.',
    );
    for (const tier of ['Gatenivå', 'Nabolag', 'Bydel']) expect(screen.getByText(tier)).toBeOnTheScreen();

    expect(screen.getByTestId('event-why')).toHaveProp(
      'accessibilityLabel',
      'Hvorfor fikk jeg dette? Hendelsen er innenfor Hjemme (1 km), og du følger brann. Du fikk push fordi den regnes som alvorlig og var ny da Kring fant den.',
    );

    expect(screen.getByText('Oppdateringer fra politiet')).toBeOnTheScreen();
    expect(screen.getByText('08:23')).toBeOnTheScreen();
    expect(screen.getByText('Nødetatene rykker ut til melding om branntilløp.')).toBeOnTheScreen();
    expect(screen.getByText('09:02')).toBeOnTheScreen();

    expect(screen.getByTestId('event-share')).toBeOnTheScreen();
    expect(screen.getByTestId('event-fewer')).toBeOnTheScreen();
    expect(screen.getByText(/^Teksten er fra Politiloggen/)).toBeOnTheScreen();
  });

  it('marks the incident opened («N ny»)', async () => {
    await show({ id: '26rj6c', place: 'p1' });
    expect(mockMarkOpened).toHaveBeenCalledWith('26rj6c');
  });

  it('shows a district notice without the map and the precision card', async () => {
    mockApi.event.mockResolvedValue(NOTICE);
    await show({ id: '26notice' });
    expect(mockApi.event).toHaveBeenCalledWith('26notice');
    expect(mockApi.listPlaces).not.toHaveBeenCalled();
    expect(mockMap).not.toHaveBeenCalled();
    expect(screen.queryByTestId('event-precision')).toBeNull();
    expect(screen.getByTestId('event-status')).toHaveTextContent('Pågår');
    expect(screen.getByTestId('event-subtitle')).toHaveTextContent('Oslo politidistrikt · man. 2. nov. 08:23');
    expect(screen.getByTestId('event-why')).toHaveProp(
      'accessibilityLabel',
      expect.stringContaining('Politiet meldte dette for hele Oslo politidistrikt'),
    );
    expect(screen.getByText('Politiet ber om tips om en savnet person.')).toBeOnTheScreen();
    // No place to change, so no «Færre slike varsler».
    expect(screen.getByTestId('event-share')).toBeOnTheScreen();
    expect(screen.queryByTestId('event-fewer')).toBeNull();
  });

  it('shows no map for an incident placed only in a municipality', async () => {
    mockApi.event.mockResolvedValue({
      ...FIRE,
      lat: null,
      lon: null,
      uncertainty_m: null,
      precision_tier: 'bydel',
      geocode_method: 'kommune',
      for_place: { ...FIRE.for_place!, relation: null, distance_m: null, pushed: false },
    });
    await show({ id: '26rj6c', place: 'p1' });
    expect(mockMap).not.toHaveBeenCalled();
    expect(screen.getByTestId('event-method')).toHaveTextContent(
      'Politiet oppga bare kommunen, så vi kan ikke vise hvor det skjedde.',
    );
    // The badge has no ± without a point; the tier legend below still lists Bydel.
    expect(screen.getAllByText('Bydel')).toHaveLength(2);
  });

  it('shares the title, time, police text and source (D12)', async () => {
    const share = jest.spyOn(Share, 'share').mockResolvedValue({ action: 'sharedAction' });
    await show({ id: '26rj6c', place: 'p1' });
    await fireEvent.press(screen.getByTestId('event-share'));
    expect(share).toHaveBeenCalledWith({
      message: [
        'Brann · Hølandsgata',
        'Hølandsgata, Kampen · man. 2. nov. 08:23',
        '',
        '08:23 Nødetatene rykker ut til melding om branntilløp.',
        '09:02 Nødetatene ferdig på stedet.',
        '',
        'Kilde: Politiloggen',
      ].join('\n'),
    });
  });

  it('opens the place with the category highlighted for «Færre slike varsler» (D12)', async () => {
    await show({ id: '26rj6c', place: 'p1' });
    await fireEvent.press(screen.getByTestId('event-fewer'));
    expect(mockRouter.push).toHaveBeenCalledWith({ pathname: '/place/[id]', params: { id: 'p1', highlight: 'Brann' } });
  });

  it('shows the incident on its own when the place is gone', async () => {
    mockApi.event.mockImplementation(async (_id: string, place?: string) => {
      if (place) throw new ApiError(404, 'not_found', 'No such place');
      return { ...FIRE, for_place: null };
    });
    await show({ id: '26rj6c', place: 'deleted' });
    expect(mockApi.event).toHaveBeenLastCalledWith('26rj6c');
    expect(screen.getByTestId('event-title')).toHaveTextContent('Brann · Hølandsgata');
    expect(screen.queryByTestId('event-why')).toBeNull();
    expect(screen.queryByTestId('event-fewer')).toBeNull();
    expect(mockMap).toHaveBeenLastCalledWith(expect.objectContaining({ place: undefined }));
  });

  it('says when it could not load, and tries again', async () => {
    mockApi.event.mockRejectedValueOnce(new ApiError(0, 'network', 'offline'));
    await show({ id: '26rj6c', place: 'p1' });
    expect(screen.getByText(/^Fikk ikke hentet hendelsen\./)).toBeOnTheScreen();
    await fireEvent.press(screen.getByText('Prøv igjen'));
    await act(async () => {});
    expect(screen.getByTestId('event-title')).toBeOnTheScreen();
  });

  it('goes back to Hjem, also when opened from a push at launch', async () => {
    await show({ id: '26rj6c', place: 'p1' });
    await fireEvent.press(screen.getByTestId('event-back'));
    expect(mockRouter.back).toHaveBeenCalled();
    mockRouter.canGoBack.mockReturnValue(false);
    await fireEvent.press(screen.getByTestId('event-back'));
    expect(mockRouter.replace).toHaveBeenCalledWith('/');
  });
});
