/**
 * Push permission and the Expo push token (§8.7). The token goes to the API with
 * PUT /v1/devices/me; a refused permission clears it there.
 */
import Constants from 'expo-constants';
import * as Notifications from 'expo-notifications';
import { Platform } from 'react-native';

import type { DeviceSession } from './device';
import { deviceInfo } from './session';

export type PushStatus = 'granted' | 'denied' | 'unavailable';

/** Android channel. The backend sends no channelId, so Expo delivers to «default». */
const ANDROID_CHANNEL = 'default';

/** Notifications that arrive while the app is open are shown as usual. */
export function configureForegroundNotifications(): void {
  Notifications.setNotificationHandler({
    handleNotification: async () => ({
      shouldShowBanner: true,
      shouldShowList: true,
      shouldPlaySound: true,
      shouldSetBadge: false,
    }),
  });
}

function projectId(): string | undefined {
  return Constants.expoConfig?.extra?.eas?.projectId ?? Constants.easConfig?.projectId;
}

/**
 * Asks for permission if it hasn't been refused, then sends the token to the API.
 * Returns 'unavailable' when there is no token to get: no EAS project yet (`eas init`),
 * or a simulator without push.
 */
export async function syncPushToken(session: DeviceSession): Promise<PushStatus> {
  if (Platform.OS === 'android') {
    // Android 13+ shows the permission prompt only once a channel exists.
    await Notifications.setNotificationChannelAsync(ANDROID_CHANNEL, {
      name: 'Varsler',
      importance: Notifications.AndroidImportance.HIGH,
    });
  }

  let { granted, canAskAgain } = await Notifications.getPermissionsAsync();
  if (!granted && canAskAgain) {
    ({ granted } = await Notifications.requestPermissionsAsync({
      ios: { allowAlert: true, allowSound: true, allowBadge: false },
    }));
  }
  if (!granted) {
    await session.call((api) => api.updateDevice({ push_token: null }));
    return 'denied';
  }

  const id = projectId();
  if (!id) {
    console.info('push: no EAS projectId in app config yet (run `eas init`), so no push token');
    return 'unavailable';
  }
  let token: string;
  try {
    token = (await Notifications.getExpoPushTokenAsync({ projectId: id })).data;
  } catch (e) {
    console.info('push: no push token on this device', e);
    return 'unavailable';
  }
  await session.call((api) => api.updateDevice({ ...deviceInfo(), push_token: token }));
  return 'granted';
}
