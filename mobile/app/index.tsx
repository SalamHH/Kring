/**
 * Hjem («Dine steder», F4, §7.3): the poll status, one card per place with its status row and
 * «N ny», a quiet row per district notice from the last 24 h (D2), the source line, and
 * «Legg til sted» pinned at the bottom. Pull to refresh. No digest card until M2.
 */
import Ionicons from '@expo/vector-icons/Ionicons';
import { useFocusEffect, useRouter } from 'expo-router';
import { useCallback } from 'react';
import { ActivityIndicator, Pressable, RefreshControl, ScrollView, StyleSheet, Text, View } from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';

import { NoticeRow, PlaceCard } from '@/components/HomeParts';
import { type DeviceState, useDeviceBootstrap } from '@/lib/bootstrap';
import { apiBaseUrl } from '@/lib/config';
import { districtNotices, newCount, placeStatus, updatedText } from '@/lib/home';
import { useOpened } from '@/lib/opened';
import { openedStore } from '@/lib/openedFile';
import { t } from '@/lib/strings';
import { MAX_SCALE } from '@/lib/textScale';
import { useHome } from '@/lib/useHome';
import { color, font, radius, spacing } from '@/theme/tokens';

function describe(s: DeviceState): string {
  switch (s.state) {
    case 'pending':
      return 'Registrerer enheten …';
    case 'error':
      return `Feil: ${s.message}`;
    case 'ready':
      return `Enhet ${s.deviceId?.slice(0, 8)} · push: ${s.push}`;
  }
}

export default function Home() {
  const router = useRouter();
  const device = useDeviceBootstrap();
  const isOpened = useOpened(openedStore);
  const { state, refreshing, load } = useHome();

  // Reload whenever Hjem is shown again, such as after Nytt sted or Hendelse closes.
  useFocusEffect(
    useCallback(() => {
      void load();
    }, [load]),
  );

  const now = new Date();
  const data = state.status === 'ok' ? state.data : null;
  const updated = updatedText(data?.health ?? null);
  const notices = data ? districtNotices(Object.values(data.events)) : [];

  const openEvent = (id: string, placeId?: string) =>
    router.push({ pathname: '/event/[id]', params: placeId ? { id, place: placeId } : { id } });

  return (
    <SafeAreaView style={styles.screen} edges={['top', 'left', 'right']}>
      <ScrollView
        contentContainerStyle={styles.content}
        refreshControl={<RefreshControl refreshing={refreshing} onRefresh={() => load(true)} tintColor={color.muted} />}
        testID="home-scroll"
      >
        <Text maxFontSizeMultiplier={MAX_SCALE.display} style={styles.logo} accessibilityRole="text">
          Kring
        </Text>
        <View style={styles.titleBlock}>
          <Text maxFontSizeMultiplier={MAX_SCALE.display} style={styles.title} accessibilityRole="header">
            {t('home.title')}
          </Text>
          {updated ? (
            <Text maxFontSizeMultiplier={MAX_SCALE.body} style={styles.updated} testID="updated">
              {updated}
            </Text>
          ) : null}
        </View>

        {state.status === 'loading' ? <ActivityIndicator color={color.muted} style={styles.loading} /> : null}
        {state.status === 'error' ? (
          <Text maxFontSizeMultiplier={MAX_SCALE.body} style={styles.muted}>
            {t('home.loadFailed')} {state.message}
          </Text>
        ) : null}
        {data && data.places.length === 0 ? (
          <Text maxFontSizeMultiplier={MAX_SCALE.body} style={styles.muted} testID="home-empty">
            {t('home.empty')}
          </Text>
        ) : null}

        {data?.places.map((p) => {
          const pe = data.events[p.id];
          return (
            <PlaceCard
              key={p.id}
              place={p}
              status={pe ? placeStatus(p, pe, now) : null}
              newCount={pe ? newCount(pe, isOpened, now) : 0}
              failed={data.failed.has(p.id)}
              now={now}
              onEdit={() => router.push({ pathname: '/place/[id]', params: { id: p.id } })}
              onOpenIncident={(e) => openEvent(e.id, p.id)}
            />
          );
        })}

        {notices.map((n) => (
          <NoticeRow key={n.id} notice={n} now={now} onPress={() => openEvent(n.id)} />
        ))}

        <Text maxFontSizeMultiplier={MAX_SCALE.body} style={styles.source}>{t('source')}</Text>

        {__DEV__ ? (
          <View style={styles.dev}>
            <Text maxFontSizeMultiplier={MAX_SCALE.body} style={styles.devText} testID="device-status">
              {describe(device)}
            </Text>
            <Text maxFontSizeMultiplier={MAX_SCALE.body} style={styles.devText}>API: {apiBaseUrl()}</Text>
          </View>
        ) : null}
      </ScrollView>

      <SafeAreaView edges={['bottom']} style={styles.bottomBar}>
        <Pressable
          onPress={() => router.push('/place/new')}
          accessibilityRole="button"
          style={({ pressed }) => [styles.primary, pressed && styles.primaryPressed]}
          testID="add-place"
        >
          <Ionicons name="add" size={22} color={color.surface} />
          <Text maxFontSizeMultiplier={MAX_SCALE.body} style={styles.primaryText}>{t('home.add')}</Text>
        </Pressable>
      </SafeAreaView>
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  screen: { flex: 1, backgroundColor: color.bg },
  content: { padding: spacing.screen, gap: spacing.stackGapTight },
  logo: { fontFamily: font.display[700], fontSize: 17, color: color.accentStrong },
  titleBlock: { gap: 2, marginBottom: 4 },
  title: { fontFamily: font.display[700], fontSize: 32, color: color.ink },
  updated: { fontFamily: font.body[400], fontSize: 14, color: color.muted },
  loading: { marginVertical: 24 },
  muted: { fontFamily: font.body[400], fontSize: 14, lineHeight: 20, color: color.muted },
  source: { fontFamily: font.body[400], fontSize: 13, lineHeight: 19, color: color.muted, marginTop: 4 },
  dev: { gap: 4, marginTop: 4 },
  devText: { fontFamily: font.body[400], fontSize: 12, color: color.muted },
  bottomBar: {
    paddingHorizontal: spacing.screen,
    paddingTop: 12,
    borderTopWidth: 1,
    borderTopColor: color.border,
    backgroundColor: color.bg,
  },
  primary: {
    minHeight: 52,
    paddingHorizontal: 16,
    paddingVertical: 8,
    borderRadius: radius.button,
    backgroundColor: color.accent,
    flexDirection: 'row',
    gap: 6,
    alignItems: 'center',
    justifyContent: 'center',
    marginBottom: 8,
  },
  primaryPressed: { backgroundColor: color.accentStrong },
  primaryText: { fontFamily: font.body[600], fontSize: 16, color: color.surface, textAlign: 'center', flexShrink: 1 },
});
