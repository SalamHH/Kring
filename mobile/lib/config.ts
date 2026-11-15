import { Platform } from 'react-native';

/** The live API on Render (§8.1). */
export const PRODUCTION_API_URL = 'https://kring-api.onrender.com';

/**
 * The API base URL.
 * 1. `EXPO_PUBLIC_API_URL`, set per EAS build profile in eas.json or in `.env.local`.
 * 2. In development: the local API (`uv run uvicorn …` on port 8000). The Android emulator
 *    reaches the Mac's localhost at 10.0.2.2.
 * 3. Otherwise the live API.
 */
export function apiBaseUrl(): string {
  const fromEnv = process.env.EXPO_PUBLIC_API_URL;
  if (fromEnv) return fromEnv;
  if (__DEV__) return Platform.OS === 'android' ? 'http://10.0.2.2:8000' : 'http://localhost:8000';
  return PRODUCTION_API_URL;
}
