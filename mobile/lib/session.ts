/** The app's one DeviceSession, with the secret in the iOS Keychain / Android Keystore. */
import { getCalendars } from 'expo-localization';
import * as SecureStore from 'expo-secure-store';
import { Platform } from 'react-native';

import type { DeviceIn } from './api';
import { apiBaseUrl } from './config';
import { DeviceSession, type SecretStore } from './device';

// AFTER_FIRST_UNLOCK so the secret can be read when a notification is handled with the phone locked.
const options: SecureStore.SecureStoreOptions = {
  keychainAccessible: SecureStore.AFTER_FIRST_UNLOCK,
};

const secureStore: SecretStore = {
  get: (key) => SecureStore.getItemAsync(key, options),
  set: (key, value) => SecureStore.setItemAsync(key, value, options),
  delete: (key) => SecureStore.deleteItemAsync(key, options),
};

export function deviceInfo(): DeviceIn {
  const tz = getCalendars()[0]?.timeZone;
  return {
    platform: Platform.OS === 'ios' || Platform.OS === 'android' ? Platform.OS : null,
    ...(tz ? { tz } : {}),
  };
}

export const session = new DeviceSession({
  baseUrl: apiBaseUrl(),
  store: secureStore,
  registration: deviceInfo,
});
