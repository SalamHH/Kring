/**
 * Nytt sted (components/PlaceEditor.tsx) rendered in Node with React Native Testing Library.
 * The map, the router, the API session and the push prompt are stand-ins, so these tests check
 * what the screen shows and sends, without a simulator.
 */
import { act, fireEvent, render, screen } from '@testing-library/react-native';
import type { ReactElement } from 'react';
import { Alert } from 'react-native';
import { GestureHandlerRootView } from 'react-native-gesture-handler';

import { PlaceEditor } from '@/components/PlaceEditor';
import { ApiError } from '@/lib/api';
import { type Place, TEMPLATES } from '@/lib/places';
import type { SearchResult } from '@/lib/places';

jest.mock('@/components/PlaceMap', () => ({ PlaceMap: () => null }));
jest.mock('react-native-safe-area-context', () => {
  const { View } = jest.requireActual('react-native');
  return { SafeAreaView: View };
});
const mockBack = jest.fn();
jest.mock('expo-router', () => ({ useRouter: () => ({ back: mockBack }) }));
const mockAskForPush = jest.fn();
jest.mock('@/lib/bootstrap', () => ({ askForPush: () => mockAskForPush() }));
const mockApi = {
  searchPlaces: jest.fn(),
  preview: jest.fn(),
  createPlace: jest.fn(),
  updatePlace: jest.fn(),
  deletePlace: jest.fn(),
};
jest.mock('@/lib/session', () => ({ session: { call: (fn: (api: unknown) => unknown) => fn(mockApi) } }));

const TOYEN: SearchResult = {
  kind: 'sted',
  label: 'Tøyen skole',
  secondary: 'Skole, Oslo',
  lat: 59.91483,
  lon: 10.77318,
  kommunenummer: '0301',
  covered: true,
};
const TRONDHEIM: SearchResult = { ...TOYEN, label: 'Nidarosdomen', secondary: 'Kirke, Trondheim', covered: false };
const PREVIEW = { days: 30, matched: 5, severe: 5, hidden_traffic: 3, imprecise_nearby: 2 };

const SAVED: Place = {
  id: 'p1',
  label: 'Skolen',
  place_name: 'Tøyen skole',
  template: 'skole',
  lat: TOYEN.lat,
  lon: TOYEN.lon,
  radius_m: 1000,
  categories: [...TEMPLATES.skole.categories],
  time_window: TEMPLATES.skole.window,
  push: true,
  kommunenummer: '0301',
  covered: true,
  created_at: '2026-11-15T12:00:00Z',
};

/** Renders inside the gesture root, as app/_layout.tsx does. */
function show(el: ReactElement) {
  return render(<GestureHandlerRootView style={{ flex: 1 }}>{el}</GestureHandlerRootView>);
}

/** Runs the debounce timers and lets the API promises settle. */
async function settle() {
  await act(async () => {
    jest.advanceTimersByTime(400);
  });
}

async function choose(result: SearchResult) {
  mockApi.searchPlaces.mockResolvedValue([result]);
  await fireEvent.changeText(screen.getByTestId('search-input'), result.label);
  await settle();
  await fireEvent.press(screen.getByTestId('search-result-0'));
  await settle();
}

beforeEach(() => {
  jest.useFakeTimers();
  jest.clearAllMocks();
  mockApi.preview.mockResolvedValue(PREVIEW);
  mockApi.createPlace.mockResolvedValue(SAVED);
  mockApi.updatePlace.mockResolvedValue(SAVED);
  mockApi.deletePlace.mockResolvedValue(undefined);
});

afterEach(() => jest.useRealTimers());

describe('Nytt sted', () => {
  it('starts as Skole with its categories, window and name', async () => {
    await show(<PlaceEditor />);
    expect(screen.getByTestId('template-skole')).toBeSelected();
    expect(screen.getByTestId('template-hjem')).not.toBeSelected();
    for (const c of ['Vold', 'Brann', 'Savnet', 'Ro og orden']) {
      expect(screen.getByTestId(`category-${c}`)).toBeSelected();
    }
    for (const c of ['Innbrudd', 'Tyveri', 'Trafikk', 'Andre']) {
      expect(screen.getByTestId(`category-${c}`)).not.toBeSelected();
    }
    expect(screen.getByTestId('label-input').props.value).toBe('Skolen');
    expect(screen.getByText('Hverdager 08–16')).toBeOnTheScreen();
    expect(screen.getByTestId('radius-label')).toHaveTextContent('1,0 km');
    expect(screen.getByText('Velg et sted for å se hvor mange hendelser det har vært der.')).toBeOnTheScreen();
    expect(mockApi.preview).not.toHaveBeenCalled();
  });

  it('searches after a pause, shows the choice and the real preview', async () => {
    await show(<PlaceEditor />);
    mockApi.searchPlaces.mockResolvedValue([TOYEN]);
    await fireEvent.changeText(screen.getByTestId('search-input'), 'tøy');
    await fireEvent.changeText(screen.getByTestId('search-input'), 'tøyen skole');
    await settle();
    expect(mockApi.searchPlaces).toHaveBeenCalledTimes(1);
    expect(mockApi.searchPlaces).toHaveBeenCalledWith('tøyen skole');

    await fireEvent.press(screen.getByTestId('search-result-0'));
    await settle();
    expect(screen.getByTestId('selected-place')).toHaveTextContent(/Tøyen skole · Skole, Oslo\s*Valgt$/);
    expect(screen.queryByTestId('search-results')).not.toBeOnTheScreen();
    expect(mockApi.preview).toHaveBeenLastCalledWith({
      lat: TOYEN.lat,
      lon: TOYEN.lon,
      radius_m: 1000,
      categories: ['Vold', 'Brann', 'Savnet', 'Ro og orden'],
    });
    expect(screen.getByTestId('preview-count')).toHaveTextContent('5 hendelser');
    expect(screen.getByText(/3 trafikkhendelser er skjult/)).toBeOnTheScreen();
  });

  it('keeps the answered results hidden if the keyboard resends the text', async () => {
    await show(<PlaceEditor />);
    await choose(TOYEN);
    await fireEvent.changeText(screen.getByTestId('search-input'), 'Tøyen skole');
    await settle();
    expect(screen.queryByTestId('search-results')).not.toBeOnTheScreen();
  });

  it('a template sets categories, window and name, but keeps a typed name', async () => {
    await show(<PlaceEditor />);
    await fireEvent.press(screen.getByTestId('template-hjem'));
    expect(screen.getByTestId('template-hjem')).toBeSelected();
    expect(screen.getByTestId('category-Innbrudd')).toBeSelected();
    expect(screen.getByTestId('category-Savnet')).not.toBeSelected();
    expect(screen.getByText('Hele døgnet')).toBeOnTheScreen();
    expect(screen.getByTestId('label-input').props.value).toBe('Hjemme');

    await fireEvent.changeText(screen.getByTestId('label-input'), 'Mormor');
    await fireEvent.press(screen.getByTestId('template-jobb'));
    expect(screen.getByTestId('label-input').props.value).toBe('Mormor');
    expect(screen.getByText('Hverdager 07–17')).toBeOnTheScreen();
  });

  it('shows the small-radius note below 1 km and asks for a new preview on release', async () => {
    await show(<PlaceEditor />);
    await choose(TOYEN);
    expect(screen.queryByTestId('small-radius-note')).not.toBeOnTheScreen();

    await fireEvent(screen.getByTestId('radius-slider'), 'accessibilityAction', {
      nativeEvent: { actionName: 'decrement' },
    });
    await settle();
    expect(screen.getByTestId('radius-label')).toHaveTextContent('900 m');
    expect(screen.getByTestId('small-radius-note')).toBeOnTheScreen();
    expect(mockApi.preview).toHaveBeenLastCalledWith(expect.objectContaining({ radius_m: 900 }));
  });

  it('shows the coverage note instead of a preview outside Oslo and Akershus (D9)', async () => {
    await show(<PlaceEditor />);
    await choose(TRONDHEIM);
    expect(screen.getByText('Vi dekker foreløpig Oslo og Akershus')).toBeOnTheScreen();
    expect(screen.queryByTestId('preview-card')).not.toBeOnTheScreen();
    expect(mockApi.preview).not.toHaveBeenCalled();
  });

  it('needs a place and a category before saving', async () => {
    await show(<PlaceEditor />);
    await fireEvent.press(screen.getByTestId('save'));
    expect(screen.getByText('Søk opp og velg et sted først.')).toBeOnTheScreen();

    await choose(TOYEN);
    for (const c of ['Vold', 'Brann', 'Savnet', 'Ro og orden']) {
      await fireEvent.press(screen.getByTestId(`category-${c}`));
    }
    expect(screen.getAllByText('Velg minst én kategori.').length).toBeGreaterThan(0);
    await fireEvent.press(screen.getByTestId('save'));
    expect(mockApi.createPlace).not.toHaveBeenCalled();
  });

  it('saves the place, then asks for push and closes', async () => {
    await show(<PlaceEditor />);
    await choose(TOYEN);
    await fireEvent.press(screen.getByTestId('save'));
    await settle();
    expect(mockApi.createPlace).toHaveBeenCalledWith({
      label: 'Skolen',
      place_name: 'Tøyen skole',
      template: 'skole',
      lat: TOYEN.lat,
      lon: TOYEN.lon,
      radius_m: 1000,
      categories: ['Vold', 'Brann', 'Savnet', 'Ro og orden'],
      time_window: TEMPLATES.skole.window,
      push: true,
    });
    expect(mockAskForPush).toHaveBeenCalledTimes(1);
    expect(mockBack).toHaveBeenCalledTimes(1);
  });

  it('does not ask for push when push is off', async () => {
    await show(<PlaceEditor />);
    await choose(TOYEN);
    await fireEvent(screen.getByTestId('push-switch'), 'valueChange', false);
    await fireEvent.press(screen.getByTestId('save'));
    await settle();
    expect(mockApi.createPlace).toHaveBeenCalledWith(expect.objectContaining({ push: false }));
    expect(mockAskForPush).not.toHaveBeenCalled();
  });

  it('shows the place limit and stays open', async () => {
    mockApi.createPlace.mockRejectedValue(new ApiError(409, 'place_limit', 'limit'));
    await show(<PlaceEditor />);
    await choose(TOYEN);
    await fireEvent.press(screen.getByTestId('save'));
    await settle();
    expect(screen.getByTestId('save-error')).toHaveTextContent(
      'Du kan ha opptil 10 steder. Slett et sted for å legge til et nytt.',
    );
    expect(mockBack).not.toHaveBeenCalled();
  });
});

describe('Endre sted', () => {
  it('sends only what changed', async () => {
    await show(<PlaceEditor place={SAVED} />);
    expect(screen.getByText('Endre sted')).toBeOnTheScreen();
    expect(screen.getByTestId('selected-place')).toHaveTextContent(/Tøyen skole\s*Valgt$/);
    await fireEvent(screen.getByTestId('radius-slider'), 'accessibilityAction', {
      nativeEvent: { actionName: 'decrement' },
    });
    await fireEvent.press(screen.getByTestId('save'));
    await settle();
    expect(mockApi.updatePlace).toHaveBeenCalledWith('p1', { radius_m: 900 });
    expect(mockAskForPush).not.toHaveBeenCalled();
    expect(mockBack).toHaveBeenCalled();
  });

  it('saves nothing when nothing changed', async () => {
    await show(<PlaceEditor place={SAVED} />);
    await fireEvent.press(screen.getByTestId('save'));
    await settle();
    expect(mockApi.updatePlace).not.toHaveBeenCalled();
    expect(mockBack).toHaveBeenCalled();
  });

  it('deletes after confirmation', async () => {
    const alert = jest.spyOn(Alert, 'alert');
    await show(<PlaceEditor place={SAVED} />);
    await fireEvent.press(screen.getByTestId('delete'));
    expect(alert).toHaveBeenCalledWith('Slette «Skolen»?', expect.any(String), expect.any(Array));
    expect(mockApi.deletePlace).not.toHaveBeenCalled();

    const buttons = alert.mock.calls[0][2]!;
    await act(async () => {
      buttons.find((b) => b.style === 'destructive')!.onPress!();
    });
    await settle();
    expect(mockApi.deletePlace).toHaveBeenCalledWith('p1');
    expect(mockBack).toHaveBeenCalled();
  });
});
