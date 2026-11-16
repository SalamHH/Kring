/** What to tell the user when an API call fails. */
import { ApiError } from './api';
import { t } from './strings';

export function errorText(e: unknown): string {
  if (e instanceof ApiError) {
    if (e.status === 0) return t('error.network');
    if (e.code === 'place_limit') return t('error.placeLimit');
    if (e.status === 502) return t('error.kartverket');
    if (e.status === 429) return t('error.rateLimited');
    if (e.status === 404) return t('error.notFound');
  }
  return t('error.generic');
}
