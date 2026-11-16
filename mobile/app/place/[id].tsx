/** Edit or delete a place (F1): Nytt sted with the place filled in. */
import { useLocalSearchParams, useRouter } from 'expo-router';
import { useEffect, useState } from 'react';
import { ActivityIndicator, Pressable, StyleSheet, Text, View } from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';

import { PlaceEditor } from '@/components/PlaceEditor';
import { ApiError } from '@/lib/api';
import { errorText } from '@/lib/errors';
import type { Place } from '@/lib/places';
import { session } from '@/lib/session';
import { t } from '@/lib/strings';
import { MAX_SCALE } from '@/lib/textScale';
import { color, font, spacing } from '@/theme/tokens';

type Load = { status: 'loading' } | { status: 'ok'; place: Place } | { status: 'error'; message: string };

export default function EditPlace() {
  // `highlight`: a category, from Hendelse's «Færre slike varsler» (D12).
  const { id, highlight } = useLocalSearchParams<{ id: string; highlight?: string }>();
  const router = useRouter();
  const [attempt, setAttempt] = useState(0);
  const [load, setLoad] = useState<Load>({ status: 'loading' });

  useEffect(() => {
    let alive = true;
    // There is no GET /v1/places/{id}; a device has at most 10 places.
    session
      .call((api) => api.listPlaces())
      .then(
        (places) => {
          const place = places.find((p) => p.id === id);
          if (!alive) return;
          if (place) setLoad({ status: 'ok', place });
          else setLoad({ status: 'error', message: errorText(new ApiError(404, 'not_found', 'No such place')) });
        },
        (e) => alive && setLoad({ status: 'error', message: errorText(e) }),
      );
    return () => {
      alive = false;
    };
  }, [id, attempt]);

  if (load.status === 'ok') return <PlaceEditor key={load.place.id} place={load.place} highlight={highlight} />;

  return (
    <SafeAreaView style={styles.screen}>
      <Pressable onPress={() => router.back()} accessibilityRole="button" style={styles.cancel}>
        <Text maxFontSizeMultiplier={MAX_SCALE.body} style={styles.link}>{t('new.cancel')}</Text>
      </Pressable>
      <View style={styles.center}>
        {load.status === 'loading' ? (
          <ActivityIndicator color={color.muted} />
        ) : (
          <>
            <Text maxFontSizeMultiplier={MAX_SCALE.body} style={styles.text}>{t('new.loadFailed')}</Text>
            <Text maxFontSizeMultiplier={MAX_SCALE.body} style={styles.text}>{load.message}</Text>
            <Pressable
              onPress={() => {
                setLoad({ status: 'loading' });
                setAttempt((n) => n + 1);
              }}
              accessibilityRole="button"
              style={styles.retry}
            >
              <Text maxFontSizeMultiplier={MAX_SCALE.body} style={styles.link}>{t('new.retry')}</Text>
            </Pressable>
          </>
        )}
      </View>
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  screen: { flex: 1, backgroundColor: color.bg, paddingHorizontal: spacing.screen },
  cancel: { minHeight: 44, justifyContent: 'center', alignSelf: 'flex-start' },
  center: { flex: 1, alignItems: 'center', justifyContent: 'center', gap: 8 },
  text: { fontFamily: font.body[400], fontSize: 15, color: color.ink2, textAlign: 'center' },
  retry: { minHeight: 44, justifyContent: 'center' },
  link: { fontFamily: font.body[500], fontSize: 16, color: color.accentStrong },
});
