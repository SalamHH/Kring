/**
 * Hjem. Interim (step 9): the title, a plain list of the device's places that opens the edit
 * screen, and «Legg til sted» pinned at the bottom. In development builds also the device
 * status. Step 10 replaces the list with the place cards (F4).
 */
import { useFocusEffect, useRouter } from 'expo-router';
import { useCallback, useState } from 'react';
import { Pressable, ScrollView, StyleSheet, Text, View } from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';

import { type DeviceState, useDeviceBootstrap } from '@/lib/bootstrap';
import { apiBaseUrl } from '@/lib/config';
import { type Place, radiusLabel, windowLabel } from '@/lib/places';
import { session } from '@/lib/session';
import { t } from '@/lib/strings';
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

/** «Tøyen skole · 1 km · hverdager 08–16» (§7.2 PlaceCard meta). */
function meta(p: Place): string {
  const w = windowLabel(p.time_window);
  return [p.place_name, radiusLabel(p.radius_m), w.charAt(0).toLowerCase() + w.slice(1)]
    .filter(Boolean)
    .join(' · ');
}

export default function Home() {
  const router = useRouter();
  const device = useDeviceBootstrap();
  const [places, setPlaces] = useState<Place[] | null>(null);
  const [failed, setFailed] = useState(false);

  // Reload whenever Hjem is shown again, such as after Nytt sted closes.
  useFocusEffect(
    useCallback(() => {
      let alive = true;
      session
        .call((api) => api.listPlaces())
        .then(
          (ps) => {
            if (!alive) return;
            setPlaces(ps);
            setFailed(false);
          },
          () => alive && setFailed(true),
        );
      return () => {
        alive = false;
      };
    }, []),
  );

  return (
    <SafeAreaView style={styles.screen} edges={['top', 'left', 'right']}>
      <ScrollView contentContainerStyle={styles.content}>
        <Text style={styles.title} accessibilityRole="header">
          {t('home.title')}
        </Text>

        {failed ? <Text style={styles.muted}>{t('home.loadFailed')}</Text> : null}
        {places && places.length === 0 ? <Text style={styles.muted}>{t('home.empty')}</Text> : null}
        {places?.map((p) => (
          <Pressable
            key={p.id}
            onPress={() => router.push({ pathname: '/place/[id]', params: { id: p.id } })}
            accessibilityRole="button"
            style={({ pressed }) => [styles.card, pressed && styles.pressed]}
            testID={`place-${p.id}`}
          >
            <Text style={styles.label}>{p.label}</Text>
            <Text style={styles.meta}>{meta(p)}</Text>
          </Pressable>
        ))}

        {__DEV__ ? (
          <View style={styles.dev}>
            <Text style={styles.devText} testID="device-status">
              {describe(device)}
            </Text>
            <Text style={styles.devText}>API: {apiBaseUrl()}</Text>
          </View>
        ) : null}

        <Text style={styles.muted}>{t('source')}</Text>
      </ScrollView>

      <SafeAreaView edges={['bottom']} style={styles.bottomBar}>
        <Pressable
          onPress={() => router.push('/place/new')}
          accessibilityRole="button"
          style={({ pressed }) => [styles.primary, pressed && styles.primaryPressed]}
          testID="add-place"
        >
          <Text style={styles.primaryText}>{t('home.add')}</Text>
        </Pressable>
      </SafeAreaView>
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  screen: { flex: 1, backgroundColor: color.bg },
  content: { padding: spacing.screen, gap: spacing.stackGapTight },
  title: { fontFamily: font.display[700], fontSize: 32, color: color.ink, marginBottom: 4 },
  pressed: { opacity: 0.7 },
  card: {
    backgroundColor: color.surface,
    borderWidth: 1,
    borderColor: color.border,
    borderRadius: radius.card,
    padding: spacing.cardPadding,
    gap: 2,
  },
  label: { fontFamily: font.body[600], fontSize: 16, color: color.ink },
  meta: { fontFamily: font.body[400], fontSize: 13, color: color.muted },
  muted: { fontFamily: font.body[400], fontSize: 13, lineHeight: 19, color: color.muted },
  dev: { gap: 4, marginTop: 8 },
  devText: { fontFamily: font.body[400], fontSize: 12, color: color.muted },
  bottomBar: {
    paddingHorizontal: spacing.screen,
    paddingTop: 12,
    borderTopWidth: 1,
    borderTopColor: color.border,
    backgroundColor: color.bg,
  },
  primary: {
    height: 52,
    borderRadius: radius.button,
    backgroundColor: color.accent,
    alignItems: 'center',
    justifyContent: 'center',
    marginBottom: 8,
  },
  primaryPressed: { backgroundColor: color.accentStrong },
  primaryText: { fontFamily: font.body[600], fontSize: 16, color: color.surface },
});
