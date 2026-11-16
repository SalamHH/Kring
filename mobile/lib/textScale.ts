/**
 * Dynamic Type (§7.5): text follows the system size, up to a cap, so the largest accessibility
 * sizes (about 3×) still fit a phone without splitting words. Above LARGE_TEXT, rows that sit
 * side by side stack instead.
 */
import { useWindowDimensions } from 'react-native';

export const MAX_SCALE = { body: 2, display: 1.5 } as const;

export const LARGE_TEXT = 1.4;

export function useLargeText(): boolean {
  return useWindowDimensions().fontScale >= LARGE_TEXT;
}
