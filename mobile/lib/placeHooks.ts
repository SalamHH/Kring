/**
 * Data hooks for Nytt sted: the debounced place search and the preview (§8.6). Each keeps the
 * last answer and ignores answers to questions that are no longer asked, so a slow reply to
 * «tøy» never replaces the results for «tøyen skole».
 */
import { useEffect, useState } from 'react';

import { ApiError } from './api';
import { errorText } from './errors';
import type { Preview, SearchResult } from './places';
import { session } from './session';
import { t } from './strings';

export const SEARCH_DEBOUNCE_MS = 300;
export const PREVIEW_DEBOUNCE_MS = 250;

export type SearchState =
  | { status: 'idle' }
  | { status: 'loading'; results?: SearchResult[] }
  | { status: 'done'; results: SearchResult[] }
  | { status: 'error'; message: string };

function searchError(e: unknown): string {
  if (e instanceof ApiError && e.status === 429) return t('new.searchTooMany');
  if (e instanceof ApiError && e.status === 0) return t('error.network');
  return t('new.searchFailed');
}

/** Searches `query` once it has 2 characters and typing has paused. */
export function usePlaceSearch(query: string): SearchState {
  const q = query.trim().slice(0, 100);
  const [done, setDone] = useState<{ q: string; results?: SearchResult[]; error?: string } | null>(null);

  useEffect(() => {
    if (q.length < 2) return;
    let alive = true;
    const timer = setTimeout(() => {
      session
        .call((api) => api.searchPlaces(q))
        .then(
          (results) => alive && setDone({ q, results }),
          (e) => alive && setDone({ q, error: searchError(e) }),
        );
    }, SEARCH_DEBOUNCE_MS);
    return () => {
      alive = false;
      clearTimeout(timer);
    };
  }, [q]);

  if (q.length < 2) return { status: 'idle' };
  if (done?.q !== q) return { status: 'loading', results: done?.results };
  if (done.error !== undefined) return { status: 'error', message: done.error };
  return { status: 'done', results: done.results ?? [] };
}

export type PreviewState =
  | { status: 'idle' }
  | { status: 'loading'; stale?: Preview }
  | { status: 'ok'; data: Preview }
  | { status: 'error'; message: string; retry: () => void };

export interface PreviewQuery {
  lat: number;
  lon: number;
  radius_m: number;
  categories: readonly string[];
}

/** GET /v1/preview for `query`, or idle for null. */
export function usePreview(query: PreviewQuery | null): PreviewState {
  const key = query ? `${query.lat},${query.lon},${query.radius_m},${query.categories.join(',')}` : null;
  const [attempt, setAttempt] = useState(0);
  const [done, setDone] = useState<{ key: string; attempt: number; data?: Preview; error?: string } | null>(
    null,
  );

  useEffect(() => {
    if (key === null) return;
    const [lat, lon, radius_m, cats] = parseKey(key);
    let alive = true;
    const timer = setTimeout(() => {
      session
        .call((api) => api.preview({ lat, lon, radius_m, categories: cats }))
        .then(
          (data) => alive && setDone({ key, attempt, data }),
          (e) => alive && setDone({ key, attempt, error: errorText(e) }),
        );
    }, PREVIEW_DEBOUNCE_MS);
    return () => {
      alive = false;
      clearTimeout(timer);
    };
  }, [key, attempt]);

  if (key === null) return { status: 'idle' };
  if (done?.key !== key || done.attempt !== attempt) return { status: 'loading', stale: done?.data };
  if (done.error !== undefined) {
    return { status: 'error', message: done.error, retry: () => setAttempt((n) => n + 1) };
  }
  return { status: 'ok', data: done.data! };
}

/** The query back from its key. App categories contain no commas. */
function parseKey(key: string): [number, number, number, string[]] {
  const [lat, lon, radius, ...cats] = key.split(',');
  return [Number(lat), Number(lon), Number(radius), cats];
}
