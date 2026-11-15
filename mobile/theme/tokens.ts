/**
 * Design tokens, spec §7.1 (direction A, deep teal).
 * `__tests__/tokens.test.ts` checks every value here against the table in docs/kring-spec.md.
 */

export const color = {
  bg: '#F5F6F3',
  surface: '#FFFFFF',
  border: '#E2E5E0',
  borderStrong: '#C9CFC8',
  ink: '#16201C',
  ink2: '#33433B',
  muted: '#5B6660',
  accent: '#007F82',
  accentStrong: '#00676A',
  accentTint: '#E3F2F2',
  severe: '#A4501A',
  severeTint: '#FBEDE3',
  calmTint: '#F2F4F1',
} as const;

export const radius = {
  card: 18,
  inner: 12,
  button: 14,
  badge: 6,
  chip: 999,
} as const;

export const spacing = {
  screen: 20,
  cardPadding: 16,
  stackGap: 16,
  stackGapTight: 12,
} as const;

/**
 * Font families as loaded by `useFonts` in app/_layout.tsx. Each weight is its own family,
 * because React Native does not synthesise weights from one custom font file.
 */
export const font = {
  body: {
    400: 'Inter_400Regular',
    500: 'Inter_500Medium',
    600: 'Inter_600SemiBold',
    700: 'Inter_700Bold',
  },
  display: {
    600: 'SpaceGrotesk_600SemiBold',
    700: 'SpaceGrotesk_700Bold',
  },
} as const;
