/**
 * Hendelse (F5, §7.3, D12), top to bottom: category and status chips, the title and «gate, område
 * · dato tid», the map with the dashed place circle and the incident's uncertainty ring (never a
 * pin without a ring) and its legend, «Hvor presist er dette?», «Hvorfor fikk jeg dette?», the
 * police updates with times, «Del med familien» and «Færre slike varsler», and the source line.
 * District notices (D2) use the same screen without the map and the precision card.
 *
 * Opened from Hjem with `{id, place}`, from a notice row with `{id}`, and from a tapped push
 * (lib/pushLinks.ts). Opening it marks the incident as seen («N ny»).
 */
import Ionicons from '@expo/vector-icons/Ionicons';
import { useLocalSearchParams, useRouter } from 'expo-router';
import { useCallback, useEffect, useMemo, useState } from 'react';
import { ActivityIndicator, Pressable, ScrollView, Share, StyleSheet, Text, View } from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';

import { PrecisionBadge } from '@/components/HomeParts';
import { PlaceMap } from '@/components/PlaceMap';
import { ApiError } from '@/lib/api';
import { errorText } from '@/lib/errors';
import {
  badgeText,
  categoryName,
  type EventDetail,
  FALLBACK_UNCERTAINTY_M,
  hasPoint,
  isNotice,
  messageTime,
  methodText,
  plain,
  shareText,
  statusText,
  subtitle,
  uncertaintyText,
  whyText,
} from '@/lib/event';
import { radiusShort, type Tier } from '@/lib/home';
import { openedStore } from '@/lib/openedFile';
import type { Place } from '@/lib/places';
import { session } from '@/lib/session';
import { t } from '@/lib/strings';
import { MAX_SCALE, useLargeText } from '@/lib/textScale';
import { color, font, radius, spacing } from '@/theme/tokens';

type Load =
  | { status: 'loading' }
  | { status: 'ok'; event: EventDetail; place: Place | null }
  | { status: 'error'; message: string };

const TIERS: Tier[] = ['gate', 'nabolag', 'bydel'];

async function load(id: string, placeId: string | undefined): Promise<{ event: EventDetail; place: Place | null }> {
  if (!placeId) return { event: await session.call((api) => api.event(id)), place: null };
  try {
    const [event, places] = await Promise.all([
      session.call((api) => api.event(id, placeId)),
      session.call((api) => api.listPlaces()),
    ]);
    return { event, place: places.find((p) => p.id === placeId) ?? null };
  } catch (e) {
    // The place may be gone (deleted since the push came): show the incident on its own.
    if (e instanceof ApiError && e.status === 404) {
      return { event: await session.call((api) => api.event(id)), place: null };
    }
    throw e;
  }
}

export default function EventScreen() {
  const { id, place: placeId } = useLocalSearchParams<{ id: string; place?: string }>();
  const router = useRouter();
  const [state, setState] = useState<Load>({ status: 'loading' });
  const [attempt, setAttempt] = useState(0);

  useEffect(() => {
    openedStore.markOpened(id);
  }, [id]);

  useEffect(() => {
    let alive = true;
    load(id, placeId).then(
      (r) => alive && setState({ status: 'ok', ...r }),
      (e) => alive && setState({ status: 'error', message: errorText(e) }),
    );
    return () => {
      alive = false;
    };
  }, [id, placeId, attempt]);

  const back = useCallback(() => (router.canGoBack() ? router.back() : router.replace('/')), [router]);

  return (
    <SafeAreaView style={styles.screen} edges={['top', 'left', 'right']}>
      <Pressable
        onPress={back}
        accessibilityRole="button"
        style={({ pressed }) => [styles.back, pressed && styles.pressed]}
        testID="event-back"
      >
        <Ionicons name="chevron-back" size={20} color={color.accentStrong} />
        <Text maxFontSizeMultiplier={MAX_SCALE.body} style={styles.backText}>
          {t('event.back')}
        </Text>
      </Pressable>
      <ScrollView contentContainerStyle={styles.content} testID="event-scroll">
        {state.status === 'ok' ? (
          <EventBody
            event={state.event}
            place={state.place}
            onFewer={(p) => router.push({ pathname: '/place/[id]', params: { id: p.id, highlight: state.event.category } })}
          />
        ) : state.status === 'error' ? (
          <View style={styles.errorBox}>
            <Text maxFontSizeMultiplier={MAX_SCALE.body} style={styles.body}>
              {t('event.loadFailed')} {state.message}
            </Text>
            <Pressable
              onPress={() => {
                setState({ status: 'loading' });
                setAttempt((n) => n + 1);
              }}
              accessibilityRole="button"
              style={styles.retry}
            >
              <Text maxFontSizeMultiplier={MAX_SCALE.body} style={styles.link}>
                {t('event.retry')}
              </Text>
            </Pressable>
          </View>
        ) : (
          <ActivityIndicator color={color.muted} style={styles.loading} />
        )}
      </ScrollView>
    </SafeAreaView>
  );
}

function EventBody({ event: e, place, onFewer }: { event: EventDetail; place: Place | null; onFewer: (p: Place) => void }) {
  const large = useLargeText();
  const notice = isNotice(e);
  const status = statusText(e.is_active);
  const severe = e.severity === 'severe';
  const why = whyText(e, place);
  const uncertainty = e.uncertainty_m ?? FALLBACK_UNCERTAINTY_M;

  const mapPlace = useMemo(
    () => (place ? { center: { lat: place.lat, lon: place.lon }, radiusM: place.radius_m } : undefined),
    [place],
  );
  const incident = useMemo(
    () => (hasPoint(e) ? { point: { lat: e.lat, lon: e.lon }, uncertaintyM: uncertainty } : undefined),
    [e, uncertainty],
  );

  const share = () => {
    Share.share({ message: shareText(e) }).catch(() => {
      // The sheet failed to open; there's nothing to undo.
    });
  };

  return (
    <>
      {/* Category and status */}
      <View style={styles.chips}>
        <View style={[styles.chip, severe ? styles.chipSevere : styles.chipPlain]} testID="event-category">
          <Text maxFontSizeMultiplier={MAX_SCALE.body} style={[styles.chipText, severe && styles.chipTextSevere]}>
            {categoryName(e)}
          </Text>
        </View>
        {status ? (
          <View style={[styles.chip, styles.chipPlain]} testID="event-status">
            <Text maxFontSizeMultiplier={MAX_SCALE.body} style={styles.chipText}>
              {status}
            </Text>
          </View>
        ) : null}
      </View>

      <View style={styles.heading}>
        <Text maxFontSizeMultiplier={MAX_SCALE.display} style={styles.title} accessibilityRole="header" testID="event-title">
          {e.title}
        </Text>
        <Text maxFontSizeMultiplier={MAX_SCALE.body} style={styles.subtitle} testID="event-subtitle">
          {subtitle(e)}
        </Text>
      </View>

      {/* Map and legend: only for an incident with a point, always with its ring. */}
      {!notice && incident ? (
        <View style={styles.mapBlock}>
          <PlaceMap
            place={mapPlace}
            dashed
            incident={incident}
            height={230}
            accessibilityLabel={
              place
                ? t('event.mapLabel', { place: place.label, uncertainty: uncertaintyText(uncertainty) })
                : t('event.mapLabelNoPlace', { uncertainty: uncertaintyText(uncertainty) })
            }
          />
          <View style={styles.legend}>
            {place ? (
              <LegendItem dot={color.accent} text={`${place.label} · ${radiusShort(place.radius_m)}`} />
            ) : null}
            <LegendItem dot={color.severe} text={`${t('event.incident')} · ${uncertaintyText(uncertainty)}`} />
          </View>
        </View>
      ) : null}

      {/* «Hvor presist er dette?» */}
      {!notice && e.precision_tier ? (
        <View style={styles.card} testID="event-precision">
          <View style={[styles.cardHead, large && styles.stacked]}>
            <Text maxFontSizeMultiplier={MAX_SCALE.body} style={[styles.cardTitle, !large && styles.grow]} accessibilityRole="header">
              {t('event.precision')}
            </Text>
            <PrecisionBadge tier={e.precision_tier} text={badgeText(e.precision_tier, e.uncertainty_m)} large />
          </View>
          <Text maxFontSizeMultiplier={MAX_SCALE.body} style={styles.body} testID="event-method">
            {methodText(e.geocode_method, e.uncertainty_m)}
          </Text>
          <View style={styles.divider} />
          <View style={styles.tierLegend}>
            {TIERS.map((tier) => (
              <View key={tier} style={[styles.tierRow, large && styles.stackedTight]}>
                <View style={styles.tierBadge}>
                  <PrecisionBadge tier={tier} large />
                </View>
                <Text maxFontSizeMultiplier={MAX_SCALE.body} style={[styles.tierText, !large && styles.grow]}>
                  {t(`tier.${tier}Legend`)}
                </Text>
              </View>
            ))}
          </View>
        </View>
      ) : null}

      {/* «Hvorfor fikk jeg dette?» */}
      {why ? (
        <View style={styles.why} accessible accessibilityLabel={`${t('event.why')} ${plain(why)}`} testID="event-why">
          <Text maxFontSizeMultiplier={MAX_SCALE.body} style={styles.whyTitle}>
            {t('event.why')}
          </Text>
          <Text maxFontSizeMultiplier={MAX_SCALE.body} style={styles.whyText}>
            {why.map((p, i) =>
              p.bold ? (
                <Text key={i} style={styles.bold}>
                  {p.text}
                </Text>
              ) : (
                p.text
              ),
            )}
          </Text>
        </View>
      ) : null}

      {/* Police updates */}
      <View style={styles.updates}>
        <Text maxFontSizeMultiplier={MAX_SCALE.body} style={styles.sectionTitle} accessibilityRole="header">
          {t('event.updates')}
        </Text>
        {e.messages.map((m, i) => {
          const last = i === e.messages.length - 1;
          const time = messageTime(m.created_at, e.first_message_at);
          return (
            <View key={m.seq} style={styles.update} accessible accessibilityLabel={`${time}. ${m.text}`}>
              <View style={styles.rail}>
                <View style={styles.railDot} />
                {last ? null : <View style={styles.railLine} />}
              </View>
              <View style={[styles.updateBody, !last && styles.updateGap]}>
                <Text maxFontSizeMultiplier={MAX_SCALE.body} style={styles.updateTime}>
                  {time}
                </Text>
                <Text maxFontSizeMultiplier={MAX_SCALE.body} style={styles.body}>
                  {m.text}
                </Text>
              </View>
            </View>
          );
        })}
      </View>

      {/* D12 */}
      <View style={[styles.actions, large && styles.actionsStacked]}>
        <Pressable
          onPress={share}
          accessibilityRole="button"
          style={({ pressed }) => [styles.action, !large && styles.grow, pressed && styles.pressed]}
          testID="event-share"
        >
          <Text maxFontSizeMultiplier={MAX_SCALE.body} style={styles.actionText}>
            {t('event.share')}
          </Text>
        </Pressable>
        {place ? (
          <Pressable
            onPress={() => onFewer(place)}
            accessibilityRole="button"
            accessibilityHint={t('event.fewerHint', { category: e.category })}
            style={({ pressed }) => [styles.action, !large && styles.grow, pressed && styles.pressed]}
            testID="event-fewer"
          >
            <Text maxFontSizeMultiplier={MAX_SCALE.body} style={styles.actionText}>
              {t('event.fewer')}
            </Text>
          </Pressable>
        ) : null}
      </View>

      <Text maxFontSizeMultiplier={MAX_SCALE.body} style={styles.source}>
        {t('event.source')}
      </Text>
    </>
  );
}

function LegendItem({ dot, text }: { dot: string; text: string }) {
  return (
    <View style={styles.legendItem}>
      <View style={[styles.legendDot, { backgroundColor: dot }]} />
      <Text maxFontSizeMultiplier={MAX_SCALE.body} style={styles.legendText}>
        {text}
      </Text>
    </View>
  );
}

const styles = StyleSheet.create({
  screen: { flex: 1, backgroundColor: color.bg },
  pressed: { opacity: 0.7 },
  grow: { flex: 1 },
  stacked: { flexDirection: 'column', alignItems: 'flex-start' },
  stackedTight: { flexDirection: 'column', alignItems: 'flex-start', gap: 4 },
  back: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 4,
    minHeight: 44,
    alignSelf: 'flex-start',
    paddingHorizontal: spacing.screen - 4,
  },
  backText: { fontFamily: font.body[500], fontSize: 17, color: color.accentStrong },
  content: { paddingHorizontal: spacing.screen, paddingTop: 8, paddingBottom: 32, gap: spacing.stackGap },
  loading: { marginVertical: 32 },
  errorBox: { gap: 8, alignItems: 'flex-start' },
  retry: { minHeight: 44, justifyContent: 'center' },
  link: { fontFamily: font.body[500], fontSize: 16, color: color.accentStrong },

  chips: { flexDirection: 'row', flexWrap: 'wrap', gap: 8 },
  chip: { borderRadius: radius.chip, paddingHorizontal: 12, paddingVertical: 5 },
  chipPlain: { backgroundColor: color.border },
  chipSevere: { backgroundColor: color.severeTint },
  chipText: { fontFamily: font.body[500], fontSize: 13, color: color.ink2 },
  chipTextSevere: { color: color.severe },

  heading: { gap: 6, marginTop: -4 },
  title: { fontFamily: font.display[700], fontSize: 28, lineHeight: 34, color: color.ink },
  subtitle: { fontFamily: font.body[400], fontSize: 15, lineHeight: 21, color: color.muted },

  mapBlock: { gap: 10 },
  legend: { flexDirection: 'row', flexWrap: 'wrap', columnGap: 18, rowGap: 6 },
  legendItem: { flexDirection: 'row', alignItems: 'center', gap: 6, flexShrink: 1 },
  legendDot: { width: 10, height: 10, borderRadius: 5 },
  legendText: { fontFamily: font.body[400], fontSize: 13, color: color.muted, flexShrink: 1 },

  card: {
    backgroundColor: color.surface,
    borderWidth: 1,
    borderColor: color.border,
    borderRadius: radius.card,
    padding: spacing.cardPadding + 2,
    gap: 12,
  },
  cardHead: { flexDirection: 'row', alignItems: 'center', gap: 10 },
  cardTitle: { fontFamily: font.body[600], fontSize: 16, color: color.ink },
  divider: { height: 1, backgroundColor: color.border },
  tierLegend: { gap: 10 },
  tierRow: { flexDirection: 'row', alignItems: 'center', gap: 12 },
  tierBadge: { minWidth: 92, alignItems: 'stretch' },
  tierText: { fontFamily: font.body[400], fontSize: 14, lineHeight: 19, color: color.muted },

  why: { backgroundColor: color.accentTint, borderRadius: radius.card, padding: spacing.cardPadding + 2, gap: 6 },
  // §7.5: accentStrong on the tint passes (5.9:1); accent would not.
  whyTitle: { fontFamily: font.body[600], fontSize: 16, color: color.accentStrong },
  whyText: { fontFamily: font.body[400], fontSize: 15, lineHeight: 22, color: color.ink },
  bold: { fontFamily: font.body[600] },

  updates: { gap: 12, marginTop: 4 },
  sectionTitle: { fontFamily: font.body[600], fontSize: 16, color: color.ink },
  update: { flexDirection: 'row', gap: 12 },
  rail: { width: 12, alignItems: 'center', paddingTop: 4 },
  railDot: { width: 10, height: 10, borderRadius: 5, backgroundColor: color.accent },
  railLine: { flex: 1, width: 2, marginTop: 4, marginBottom: -4, backgroundColor: color.border },
  updateBody: { flex: 1, gap: 2 },
  updateGap: { paddingBottom: 14 },
  updateTime: { fontFamily: font.body[600], fontSize: 13, color: color.muted },
  body: { fontFamily: font.body[400], fontSize: 15, lineHeight: 22, color: color.ink },

  actions: { flexDirection: 'row', gap: 10, alignItems: 'stretch' },
  actionsStacked: { flexDirection: 'column' },
  action: {
    minHeight: 50,
    paddingHorizontal: 12,
    paddingVertical: 10,
    borderRadius: radius.button,
    borderWidth: 1.5,
    borderColor: color.borderStrong,
    backgroundColor: color.surface,
    alignItems: 'center',
    justifyContent: 'center',
    alignSelf: 'stretch',
  },
  actionText: { fontFamily: font.body[600], fontSize: 15, color: color.ink, textAlign: 'center' },
  source: { fontFamily: font.body[400], fontSize: 13, lineHeight: 19, color: color.muted },
});
