/**
 * The parts of Hjem (§7.2): PrecisionBadge, IncidentRow, PlaceCard and the district notice row.
 * Precision and severity are shown by shape and text, not by colour alone (§7.5).
 */
import Ionicons from '@expo/vector-icons/Ionicons';
import type { ComponentProps } from 'react';
import { Pressable, StyleSheet, Text, View } from 'react-native';

import {
  type EventSummary,
  impreciseText,
  incidentMeta,
  type Notice,
  placeMeta,
  type Status,
  type Tier,
  timeText,
} from '@/lib/home';
import type { Place, Template } from '@/lib/places';
import { t } from '@/lib/strings';
import { MAX_SCALE, useLargeText } from '@/lib/textScale';
import { color, font, radius, spacing } from '@/theme/tokens';

type IconName = ComponentProps<typeof Ionicons>['name'];

const PLACE_ICON: Record<Template, IconName> = {
  skole: 'school-outline',
  hjem: 'home-outline',
  hytte: 'bonfire-outline',
  jobb: 'briefcase-outline',
  annet: 'location-outline',
};

const CATEGORY_ICON: Record<string, IconName> = {
  Vold: 'hand-left-outline',
  Brann: 'flame-outline',
  Savnet: 'search-outline',
  'Ro og orden': 'megaphone-outline',
  Innbrudd: 'lock-open-outline',
  Tyveri: 'bag-handle-outline',
  Trafikk: 'car-outline',
};

export function categoryIcon(category: string): IconName {
  return CATEGORY_ICON[category] ?? 'ellipsis-horizontal-circle-outline';
}

// --- PrecisionBadge --------------------------------------------------------------------------

/** The tier by fill and outline (§7.2). `text` replaces the tier name, as in «Gatenivå · ±150 m». */
export function PrecisionBadge({ tier, text, large }: { tier: Tier; text?: string; large?: boolean }) {
  return (
    <View style={[styles.badge, large && styles.badgeLarge, badgeStyles[tier]]} testID={`badge-${tier}`}>
      <Text
        maxFontSizeMultiplier={MAX_SCALE.body}
        style={[styles.badgeText, large && styles.badgeTextLarge, badgeTextStyles[tier]]}
      >
        {text ?? t(`tier.${tier}`)}
      </Text>
    </View>
  );
}

// --- IncidentRow -----------------------------------------------------------------------------

export function IncidentRow({ event, now, onPress }: { event: EventSummary; now: Date; onPress: () => void }) {
  const severe = event.severity === 'severe';
  const meta = incidentMeta(event, now);
  return (
    <Pressable
      onPress={onPress}
      accessibilityRole="button"
      accessibilityLabel={`${event.title}, ${t(`tier.${event.precision_tier}`)}, ${meta}`}
      accessibilityHint={t('home.openHint')}
      style={({ pressed }) => [styles.statusRow, severe ? styles.severeRow : styles.incidentRow, pressed && styles.pressed]}
      testID={`incident-${event.id}`}
    >
      <Ionicons name={categoryIcon(event.category)} size={20} color={severe ? color.severe : color.ink2} />
      <View style={styles.statusBody}>
        <Text maxFontSizeMultiplier={MAX_SCALE.body} style={styles.incidentTitle}>{event.title}</Text>
        <View style={styles.incidentMetaRow}>
          <PrecisionBadge tier={event.precision_tier} />
          <Text maxFontSizeMultiplier={MAX_SCALE.body} style={styles.incidentMeta}>{meta}</Text>
        </View>
      </View>
    </Pressable>
  );
}

// --- PlaceCard -------------------------------------------------------------------------------

export interface PlaceCardProps {
  place: Place;
  /** null while the events load, or when they couldn't be loaded. */
  status: Status | null;
  newCount: number;
  failed: boolean;
  now: Date;
  onEdit: () => void;
  onOpenIncident: (e: EventSummary) => void;
}

export function PlaceCard({ place, status, newCount, failed, now, onEdit, onOpenIncident }: PlaceCardProps) {
  const large = useLargeText();
  const meta = placeMeta(place);
  const badge = newCount > 0 ? t('place.new', { n: newCount }) : null;
  return (
    <View style={styles.card} testID={`place-${place.id}`}>
      <Pressable
        onPress={onEdit}
        accessibilityRole="button"
        accessibilityLabel={[place.label, meta, badge].filter(Boolean).join(', ')}
        accessibilityHint={t('home.editHint')}
        style={({ pressed }) => [styles.cardHead, large && styles.cardHeadLarge, pressed && styles.pressed]}
        testID={`place-head-${place.id}`}
      >
        {/* With large text the icon and badge sit above the label, which gets the full width. */}
        <View style={large ? styles.cardTop : styles.contents}>
          <View style={styles.iconTile}>
            <Ionicons name={PLACE_ICON[place.template]} size={22} color={color.accent} />
          </View>
          {large && badge ? <NewBadge id={place.id} text={badge} /> : null}
        </View>
        <View style={[styles.cardText, large && styles.cardTextLarge]}>
          <Text maxFontSizeMultiplier={MAX_SCALE.body} style={styles.cardLabel}>{place.label}</Text>
          <Text maxFontSizeMultiplier={MAX_SCALE.body} style={styles.cardMeta}>{meta}</Text>
        </View>
        {!large && badge ? <NewBadge id={place.id} text={badge} /> : null}
      </Pressable>

      {status?.kind === 'incident' ? (
        <IncidentRow event={status.event} now={now} onPress={() => onOpenIncident(status.event)} />
      ) : status?.kind === 'imprecise' ? (
        <View style={[styles.statusRow, styles.calmRow]} accessible testID={`imprecise-${place.id}`}>
          <Ionicons name="radio-outline" size={20} color={color.muted} />
          <Text maxFontSizeMultiplier={MAX_SCALE.body} style={[styles.statusText, styles.statusBody]}>{impreciseText(status.count)}</Text>
        </View>
      ) : status?.kind === 'calm' ? (
        <View style={[styles.statusRow, styles.calmRow]} accessible testID={`calm-${place.id}`}>
          <Ionicons name="checkmark-circle-outline" size={20} color={color.accent} />
          <Text maxFontSizeMultiplier={MAX_SCALE.body} style={[styles.statusText, styles.statusBody]}>{t('place.calm')}</Text>
        </View>
      ) : failed ? (
        <View style={[styles.statusRow, styles.calmRow]} accessible>
          <Text maxFontSizeMultiplier={MAX_SCALE.body} style={[styles.statusText, styles.statusBody]}>{t('home.eventsFailed')}</Text>
        </View>
      ) : null}
    </View>
  );
}

function NewBadge({ id, text }: { id: string; text: string }) {
  return (
    <View style={styles.newBadge} testID={`new-${id}`}>
      <Text maxFontSizeMultiplier={MAX_SCALE.body} style={styles.newBadgeText}>
        {text}
      </Text>
    </View>
  );
}

// --- «Fra politidistriktet» (D2) -------------------------------------------------------------

export function NoticeRow({ notice, now, onPress }: { notice: Notice; now: Date; onPress: () => void }) {
  const large = useLargeText();
  const when = timeText(notice.first_message_at, now);
  return (
    <Pressable
      onPress={onPress}
      accessibilityRole="button"
      accessibilityLabel={`${t('home.district')}: ${notice.title}, ${when}`}
      accessibilityHint={t('home.openHint')}
      style={({ pressed }) => [styles.notice, pressed && styles.pressed]}
      testID={`notice-${notice.id}`}
    >
      <Ionicons name={categoryIcon(notice.category)} size={18} color={color.muted} />
      <View style={styles.statusBody}>
        <Text maxFontSizeMultiplier={MAX_SCALE.body} style={styles.noticeLabel}>{t('home.district')}</Text>
        <Text maxFontSizeMultiplier={MAX_SCALE.body} style={styles.noticeTitle}>{notice.title}</Text>
        {large ? <Text maxFontSizeMultiplier={MAX_SCALE.body} style={styles.noticeTime}>{when}</Text> : null}
      </View>
      {large ? null : <Text maxFontSizeMultiplier={MAX_SCALE.body} style={styles.noticeTime}>{when}</Text>}
      <Ionicons name="chevron-forward" size={16} color={color.muted} />
    </Pressable>
  );
}

const badgeStyles = StyleSheet.create({
  gate: { backgroundColor: color.accent, borderColor: color.accent, borderStyle: 'solid' },
  nabolag: { backgroundColor: color.surface, borderColor: color.accent, borderStyle: 'solid' },
  bydel: { backgroundColor: color.surface, borderColor: color.borderStrong, borderStyle: 'dashed' },
});

const badgeTextStyles = StyleSheet.create({
  gate: { color: color.surface },
  nabolag: { color: color.accentStrong },
  bydel: { color: color.muted },
});

const styles = StyleSheet.create({
  pressed: { opacity: 0.7 },

  badge: { borderWidth: 1.5, borderRadius: radius.badge, paddingHorizontal: 6, paddingVertical: 1 },
  badgeText: { fontFamily: font.body[600], fontSize: 12 },
  badgeLarge: { paddingHorizontal: 10, paddingVertical: 4, borderRadius: radius.badge + 2 },
  badgeTextLarge: { fontSize: 14 },

  card: {
    backgroundColor: color.surface,
    borderWidth: 1,
    borderColor: color.border,
    borderRadius: radius.card,
    padding: spacing.cardPadding,
    gap: spacing.stackGapTight,
  },
  cardHead: { flexDirection: 'row', alignItems: 'center', gap: 12, minHeight: 44 },
  cardHeadLarge: { flexDirection: 'column', alignItems: 'stretch', gap: 8 },
  cardTop: { flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between' },
  contents: { display: 'contents' },
  cardTextLarge: { flex: 0 },
  iconTile: {
    width: 40,
    height: 40,
    borderRadius: radius.inner,
    backgroundColor: color.accentTint,
    alignItems: 'center',
    justifyContent: 'center',
  },
  cardText: { flex: 1, gap: 2 },
  cardLabel: { fontFamily: font.body[600], fontSize: 16, color: color.ink },
  cardMeta: { fontFamily: font.body[400], fontSize: 13, lineHeight: 18, color: color.muted },
  newBadge: {
    backgroundColor: color.severeTint,
    borderRadius: radius.badge,
    paddingHorizontal: 8,
    paddingVertical: 3,
  },
  newBadgeText: { fontFamily: font.body[600], fontSize: 12, color: color.severe },

  statusRow: {
    flexDirection: 'row',
    alignItems: 'flex-start',
    gap: 10,
    borderRadius: radius.inner,
    padding: 12,
    minHeight: 44,
  },
  statusBody: { flex: 1, gap: 4 },
  calmRow: { backgroundColor: color.calmTint },
  incidentRow: { backgroundColor: color.calmTint },
  severeRow: { backgroundColor: color.severeTint },
  statusText: { fontFamily: font.body[400], fontSize: 14, lineHeight: 20, color: color.ink2 },
  incidentTitle: { fontFamily: font.body[600], fontSize: 14, lineHeight: 20, color: color.ink },
  incidentMetaRow: { flexDirection: 'row', alignItems: 'center', flexWrap: 'wrap', gap: 8 },
  incidentMeta: { fontFamily: font.body[400], fontSize: 13, color: color.muted },

  notice: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 10,
    minHeight: 52,
    paddingHorizontal: 14,
    paddingVertical: 10,
    borderRadius: radius.inner,
    borderWidth: 1,
    borderColor: color.border,
  },
  noticeLabel: { fontFamily: font.body[500], fontSize: 12, color: color.muted },
  noticeTitle: { fontFamily: font.body[600], fontSize: 14, color: color.ink2 },
  noticeTime: { fontFamily: font.body[400], fontSize: 13, color: color.muted },
});
