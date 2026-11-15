/**
 * Hendelse, placeholder until step 11: the title, the time and the police updates, so Hjem's
 * incident and notice rows have somewhere to go. Opening it marks the incident as seen («N ny»).
 * Step 11 replaces this with the full screen (F5, D12).
 */
import Ionicons from '@expo/vector-icons/Ionicons';
import { useLocalSearchParams, useRouter } from 'expo-router';
import { useEffect, useState } from 'react';
import { ActivityIndicator, Pressable, ScrollView, StyleSheet, Text, View } from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';

import { errorText } from '@/lib/errors';
import { type EventDetail, timeText } from '@/lib/home';
import { openedStore } from '@/lib/openedFile';
import { session } from '@/lib/session';
import { t } from '@/lib/strings';
import { color, font, spacing } from '@/theme/tokens';

export default function EventScreen() {
  const { id, place } = useLocalSearchParams<{ id: string; place?: string }>();
  const router = useRouter();
  const [event, setEvent] = useState<EventDetail | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    openedStore.markOpened(id);
    let alive = true;
    session
      .call((api) => api.event(id, place))
      .then(
        (e) => alive && setEvent(e),
        (e) => alive && setError(errorText(e)),
      );
    return () => {
      alive = false;
    };
  }, [id, place]);

  const now = new Date();
  return (
    <SafeAreaView style={styles.screen}>
      <Pressable onPress={() => router.back()} accessibilityRole="button" style={styles.back} testID="event-back">
        <Ionicons name="arrow-back" size={20} color={color.accentStrong} />
        <Text style={styles.backText}>{t('event.back')}</Text>
      </Pressable>
      <ScrollView contentContainerStyle={styles.content}>
        {event ? (
          <>
            <Text style={styles.title} accessibilityRole="header" testID="event-title">
              {event.title}
            </Text>
            <Text style={styles.muted}>{timeText(event.first_message_at, now)}</Text>
            <Text style={styles.section}>{t('event.updates')}</Text>
            {event.messages.map((m) => (
              <View key={m.seq} style={styles.message}>
                <Text style={styles.muted}>{timeText(m.created_at, now)}</Text>
                <Text style={styles.body}>{m.text}</Text>
              </View>
            ))}
            <Text style={styles.muted}>{t('source')}</Text>
          </>
        ) : error ? (
          <Text style={styles.body}>
            {t('event.loadFailed')} {error}
          </Text>
        ) : (
          <ActivityIndicator color={color.muted} />
        )}
      </ScrollView>
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  screen: { flex: 1, backgroundColor: color.bg },
  back: { flexDirection: 'row', alignItems: 'center', gap: 6, minHeight: 44, paddingHorizontal: spacing.screen },
  backText: { fontFamily: font.body[500], fontSize: 16, color: color.accentStrong },
  content: { padding: spacing.screen, gap: spacing.stackGapTight },
  title: { fontFamily: font.display[700], fontSize: 26, color: color.ink },
  section: { fontFamily: font.body[600], fontSize: 15, color: color.ink2, marginTop: 8 },
  message: { gap: 2 },
  body: { fontFamily: font.body[400], fontSize: 15, lineHeight: 22, color: color.ink },
  muted: { fontFamily: font.body[400], fontSize: 13, lineHeight: 19, color: color.muted },
});
