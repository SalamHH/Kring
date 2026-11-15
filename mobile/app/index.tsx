/**
 * Hjem. Step 8 skeleton: the title, and in development a PlaceMap of Tøyen and the device
 * status, to check registration and the map. Step 10 replaces this with the place cards.
 */
import { ScrollView, StyleSheet, Text, View } from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';

import { PlaceMap } from '@/components/PlaceMap';
import { type DeviceState, useDeviceBootstrap } from '@/lib/bootstrap';
import { apiBaseUrl } from '@/lib/config';
import { t } from '@/lib/strings';
import { color, font, spacing } from '@/theme/tokens';

/** Tøyen torg, for the development map only. */
const TOYEN = { lat: 59.9152, lon: 10.7745 };

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
  const device = useDeviceBootstrap();

  return (
    <SafeAreaView style={styles.screen} edges={['top', 'left', 'right']}>
      <ScrollView contentContainerStyle={styles.content}>
        <Text style={styles.title} accessibilityRole="header">
          {t('home.title')}
        </Text>

        {__DEV__ ? (
          <View style={styles.dev}>
            <PlaceMap place={{ center: TOYEN, radiusM: 1000 }} accessibilityLabel="Kart: Tøyen, 1 km" />
            <Text style={styles.devText} testID="device-status">
              {describe(device)}
            </Text>
            <Text style={styles.devText}>API: {apiBaseUrl()}</Text>
          </View>
        ) : null}

        <Text style={styles.source}>{t('source')}</Text>
      </ScrollView>
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  screen: { flex: 1, backgroundColor: color.bg },
  content: { padding: spacing.screen, gap: spacing.stackGap },
  title: { fontFamily: font.display[700], fontSize: 32, color: color.ink },
  dev: { gap: spacing.stackGapTight },
  devText: { fontFamily: font.body[400], fontSize: 13, color: color.muted },
  source: { fontFamily: font.body[400], fontSize: 13, color: color.muted },
});
