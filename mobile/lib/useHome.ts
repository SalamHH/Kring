/**
 * Hjem's data: the device's places, each place's events of the last 7 days, and the poll status.
 * Loaded on focus and on pull-to-refresh. A place whose events fail still shows its card.
 */
import { useCallback, useRef, useState } from 'react';

import { errorText } from './errors';
import { type Health, HOME_DAYS, type PlaceEvents } from './home';
import type { Place } from './places';
import { session } from './session';

export interface HomeData {
  places: Place[];
  /** By place id; missing while loading or when that place's events failed. */
  events: Record<string, PlaceEvents>;
  failed: Set<string>;
  health: Health | null;
}

export type HomeState =
  | { status: 'loading' }
  | { status: 'ok'; data: HomeData }
  | { status: 'error'; message: string };

export function useHome(): { state: HomeState; refreshing: boolean; load: (pull?: boolean) => Promise<void> } {
  const [state, setState] = useState<HomeState>({ status: 'loading' });
  const [refreshing, setRefreshing] = useState(false);
  const run = useRef(0);

  const load = useCallback(async (pull = false) => {
    const mine = ++run.current;
    if (pull) setRefreshing(true);
    try {
      const healthP = session.call((api) => api.health()).catch(() => null);
      const places = await session.call((api) => api.listPlaces());
      const results = await Promise.all(
        places.map((p) =>
          session.call((api) => api.placeEvents(p.id, HOME_DAYS)).then(
            (pe) => ({ id: p.id, pe }),
            () => ({ id: p.id, pe: null }),
          ),
        ),
      );
      const health = await healthP;
      if (mine !== run.current) return;
      const events: Record<string, PlaceEvents> = {};
      const failed = new Set<string>();
      for (const r of results) {
        if (r.pe) events[r.id] = r.pe;
        else failed.add(r.id);
      }
      setState({ status: 'ok', data: { places, events, failed, health } });
    } catch (e) {
      if (mine !== run.current) return;
      // Keep what is on screen if a refresh fails; show the error only when there is nothing.
      setState((s) => (s.status === 'ok' ? s : { status: 'error', message: errorText(e) }));
    } finally {
      if (mine === run.current) setRefreshing(false);
    }
  }, []);

  return { state, refreshing, load };
}
