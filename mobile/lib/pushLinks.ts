/**
 * Tapping a push opens Hendelse (F6, §8.7). The payload is `{event_id, place_id}`; a district
 * notice has a place too, the one it was pushed for (D2).
 *
 * Works from a cold start (the tap that launched the app is read once the navigator is up) and
 * from the background (a listener). Each notification is opened once, even when both report it.
 */
import * as Notifications from 'expo-notifications';
import { router } from 'expo-router';
import { useEffect } from 'react';

export interface EventLink {
  pathname: '/event/[id]';
  params: { id: string; place?: string };
}

const EVENT_ID = /^[\w.:-]{1,200}$/;
const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;

/** The Hendelse route for a push's data, or null when it isn't one of ours. Parsed defensively. */
export function eventLink(data: unknown): EventLink | null {
  if (!data || typeof data !== 'object') return null;
  const { event_id, place_id } = data as Record<string, unknown>;
  if (typeof event_id !== 'string' || !EVENT_ID.test(event_id)) return null;
  const params: EventLink['params'] = { id: event_id };
  if (typeof place_id === 'string' && UUID.test(place_id)) params.place = place_id;
  return { pathname: '/event/[id]', params };
}

/** Notification ids already opened in this JS session. */
const handled = new Set<string>();

/** Opens the incident of a tapped push. Returns whether it navigated. */
export function openResponse(
  response: Notifications.NotificationResponse | null,
  navigate: (link: EventLink) => void,
): boolean {
  if (!response || response.actionIdentifier !== Notifications.DEFAULT_ACTION_IDENTIFIER) return false;
  const id = response.notification.request.identifier;
  if (handled.has(id)) return false;
  const link = eventLink(response.notification.request.content.data);
  if (!link) return false;
  handled.add(id);
  navigate(link);
  return true;
}

/** Call in the root layout once the navigator is rendered (`ready`). */
export function usePushLinks(ready: boolean): void {
  useEffect(() => {
    if (!ready) return;
    const go = (link: EventLink) => router.push(link);
    // Cold start: the tap that opened the app. Cleared, so a reload doesn't open it again.
    if (openResponse(Notifications.getLastNotificationResponse(), go)) {
      Notifications.clearLastNotificationResponse();
    }
    const sub = Notifications.addNotificationResponseReceivedListener((r) => {
      if (openResponse(r, go)) Notifications.clearLastNotificationResponse();
    });
    return () => sub.remove();
  }, [ready]);
}

/** For tests. */
export function resetHandled(): void {
  handled.clear();
}
