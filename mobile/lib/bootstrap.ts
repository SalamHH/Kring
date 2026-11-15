/**
 * First launch and every return to the app: make sure the device is registered (§8.6)
 * and the push token on the server is current (§8.7).
 */
import * as Notifications from 'expo-notifications';
import { useEffect, useState } from 'react';
import { AppState } from 'react-native';

import { type PushStatus, syncPushToken } from './push';
import { session } from './session';

export type DeviceState =
  | { state: 'pending' }
  | { state: 'ready'; deviceId: string | null; push: PushStatus }
  | { state: 'error'; message: string };

let running: Promise<DeviceState> | null = null;

async function run(): Promise<DeviceState> {
  try {
    await session.ensure();
    const push = await syncPushToken(session);
    return { state: 'ready', deviceId: await session.deviceId(), push };
  } catch (e) {
    console.warn('device bootstrap failed', e);
    return { state: 'error', message: e instanceof Error ? e.message : String(e) };
  }
}

/** Runs the bootstrap once at a time. */
export function bootstrapDevice(): Promise<DeviceState> {
  running ??= run().finally(() => (running = null));
  return running;
}

/** Bootstraps on mount, again when the app comes back to the foreground, and when the OS issues a new push token. */
export function useDeviceBootstrap(): DeviceState {
  const [state, setState] = useState<DeviceState>({ state: 'pending' });

  useEffect(() => {
    let alive = true;
    const go = () => bootstrapDevice().then((s) => alive && setState(s));
    go();
    const appState = AppState.addEventListener('change', (s) => s === 'active' && go());
    const token = Notifications.addPushTokenListener(() => go());
    return () => {
      alive = false;
      appState.remove();
      token.remove();
    };
  }, []);

  return state;
}
