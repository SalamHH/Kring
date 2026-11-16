/**
 * Nytt sted (F1–F3, §7.3), also used to edit and delete a place. Top to bottom: «Avbryt» ·
 * search and the selected result · type chips · name · map with the live radius circle ·
 * radius slider · small-radius InfoNote · preview card · category chips · «Når» and
 * «Push-varsel» · «Lagre sted» pinned at the bottom.
 */
import Feather from '@expo/vector-icons/Feather';
import { useRouter } from 'expo-router';
import { useMemo, useRef, useState } from 'react';
import {
  ActivityIndicator,
  Alert,
  Keyboard,
  Pressable,
  ScrollView,
  type ScrollViewInstance,
  StyleSheet,
  Switch,
  Text,
  TextInput,
  type TextInputInstance,
  View,
} from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';

import { CategoryChip, TypeChip } from '@/components/Chip';
import { InfoNote } from '@/components/InfoNote';
import { PlaceMap } from '@/components/PlaceMap';
import { RadiusSlider } from '@/components/RadiusSlider';
import { askForPush } from '@/lib/bootstrap';
import { errorText } from '@/lib/errors';
import {
  APP_CATEGORIES,
  type AppCategory,
  canonical,
  DEFAULT_TEMPLATE,
  defaultLabel,
  LABEL_MAX,
  type Place,
  type PlaceFields,
  placeChanges,
  PLACE_NAME_MAX,
  previewText,
  RADIUS_DEFAULT,
  radiusLabel,
  type SearchResult,
  sameWindow,
  showsSmallRadiusNote,
  type Template,
  TEMPLATE_ORDER,
  TEMPLATES,
  type TimeWindow,
  windowChoices,
  windowLabel,
} from '@/lib/places';
import { type PreviewState, usePlaceSearch, usePreview } from '@/lib/placeHooks';
import { session } from '@/lib/session';
import { t } from '@/lib/strings';
import { MAX_SCALE, useLargeText } from '@/lib/textScale';
import { color, font, radius as radii, spacing } from '@/theme/tokens';

/** The chosen location: a search result, or the place being edited. */
interface Spot {
  /** The search result's name, stored as `place_name`. null for places made before it existed. */
  placeName: string | null;
  secondary: string | null;
  lat: number;
  lon: number;
  covered: boolean;
}

function fieldsOf(p: Place): PlaceFields {
  return {
    label: p.label,
    place_name: p.place_name,
    template: p.template,
    lat: p.lat,
    lon: p.lon,
    radius_m: p.radius_m,
    categories: p.categories,
    time_window: p.time_window,
    push: p.push,
  };
}

const [PUSH_LABEL, PUSH_DETAIL] = t('new.push').split(' · ');

export interface PlaceEditorProps {
  place?: Place;
  /**
   * A category to point out, from Hendelse's «Færre slike varsler» (D12): the editor scrolls to
   * the categories and marks that chip, so it can be turned off.
   */
  highlight?: string;
}

export function PlaceEditor({ place, highlight }: PlaceEditorProps) {
  const router = useRouter();
  const editing = place !== undefined;
  const scroll = useRef<ScrollViewInstance>(null);
  const searchInput = useRef<TextInputInstance>(null);
  const scrolledToHighlight = useRef(false);
  const large = useLargeText();

  const [query, setQuery] = useState('');
  // The query a result was chosen for. Its results stay hidden even if the keyboard sends that
  // text again after the field was cleared (a late change event as the keyboard closes).
  const [answeredQuery, setAnsweredQuery] = useState<string | null>(null);
  const [spot, setSpot] = useState<Spot | null>(
    place
      ? { placeName: place.place_name, secondary: null, lat: place.lat, lon: place.lon, covered: place.covered }
      : null,
  );
  const [template, setTemplate] = useState<Template>(place?.template ?? DEFAULT_TEMPLATE);
  const [label, setLabel] = useState(place?.label ?? defaultLabel(DEFAULT_TEMPLATE, null));
  // A label the user typed (or an existing place's) is never replaced by a template default.
  const [labelEdited, setLabelEdited] = useState(editing);
  const [radiusM, setRadiusM] = useState(place?.radius_m ?? RADIUS_DEFAULT);
  // The radius at the last slider release: the map camera and the preview follow this one.
  const [settledRadiusM, setSettledRadiusM] = useState(radiusM);
  const [categories, setCategories] = useState<AppCategory[]>(
    place?.categories ?? [...TEMPLATES[DEFAULT_TEMPLATE].categories],
  );
  const [timeWindow, setTimeWindow] = useState<TimeWindow>(place?.time_window ?? TEMPLATES[DEFAULT_TEMPLATE].window);
  const [push, setPush] = useState(place?.push ?? true);
  const [whenOpen, setWhenOpen] = useState(false);
  const [triedToSave, setTriedToSave] = useState(false);
  const [busy, setBusy] = useState<'saving' | 'deleting' | null>(null);
  const [saveError, setSaveError] = useState<string | null>(null);

  const search = usePlaceSearch(query);
  const center = useMemo(() => (spot ? { lat: spot.lat, lon: spot.lon } : null), [spot]);
  const preview = usePreview(
    spot && spot.covered && categories.length > 0
      ? { lat: spot.lat, lon: spot.lon, radius_m: settledRadiusM, categories }
      : null,
  );

  const shownName = spot?.placeName ?? place?.label ?? '';
  const missingSpot = spot === null;
  const missingLabel = label.trim() === '';
  const missingCategories = categories.length === 0;

  function chooseResult(r: SearchResult) {
    setSpot({ placeName: r.label.slice(0, PLACE_NAME_MAX), secondary: r.secondary, lat: r.lat, lon: r.lon, covered: r.covered });
    setAnsweredQuery(query.trim());
    setQuery('');
    Keyboard.dismiss();
    if (!labelEdited) setLabel(defaultLabel(template, r.label));
    setSaveError(null);
  }

  function chooseTemplate(next: Template) {
    // §6.1, F2: a template sets categories and time window; the user can change them after.
    setTemplate(next);
    setCategories([...TEMPLATES[next].categories]);
    setTimeWindow(TEMPLATES[next].window);
    if (!labelEdited) setLabel(defaultLabel(next, spot?.placeName ?? null));
  }

  function toggleCategory(c: AppCategory) {
    setCategories((cs) => canonical(cs.includes(c) ? cs.filter((x) => x !== c) : [...cs, c]));
  }

  async function save() {
    setTriedToSave(true);
    setSaveError(null);
    if (spot === null) {
      scroll.current?.scrollTo({ y: 0, animated: true });
      searchInput.current?.focus();
      return;
    }
    if (missingLabel || missingCategories) return;
    const fields: PlaceFields = {
      label: label.trim(),
      place_name: spot.placeName,
      template,
      lat: spot.lat,
      lon: spot.lon,
      radius_m: radiusM,
      categories,
      time_window: timeWindow,
      push,
    };
    setBusy('saving');
    try {
      if (place) {
        const changes = placeChanges(fieldsOf(place), fields);
        if (Object.keys(changes).length > 0) await session.call((api) => api.updatePlace(place.id, changes));
      } else {
        await session.call((api) => api.createPlace(fields));
        // The push prompt comes after the first saved place, not at launch (decided 2026-11-15).
        if (push) void askForPush();
      }
      router.back();
    } catch (e) {
      setSaveError(errorText(e));
      setBusy(null);
    }
  }

  function confirmDelete() {
    if (!place) return;
    Alert.alert(t('new.deleteTitle', { label: place.label }), t('new.deleteBody'), [
      { text: t('new.cancel'), style: 'cancel' },
      {
        text: t('new.deleteConfirm'),
        style: 'destructive',
        onPress: async () => {
          setBusy('deleting');
          setSaveError(null);
          try {
            await session.call((api) => api.deletePlace(place.id));
            router.back();
          } catch (e) {
            setSaveError(errorText(e));
            setBusy(null);
          }
        },
      },
    ]);
  }

  const results = search.status === 'done' || search.status === 'loading' ? (search.results ?? []) : [];
  const choices = windowChoices(timeWindow);

  return (
    <SafeAreaView style={styles.screen} edges={['top', 'left', 'right']}>
      <View style={styles.header}>
        <Pressable
          onPress={() => router.back()}
          accessibilityRole="button"
          hitSlop={8}
          style={styles.cancel}
          testID="cancel"
        >
          <Text maxFontSizeMultiplier={MAX_SCALE.body} style={styles.cancelText}>{t('new.cancel')}</Text>
        </Pressable>
        <Text maxFontSizeMultiplier={MAX_SCALE.body} style={styles.headerTitle} accessibilityRole="header">
          {editing ? t('new.editTitle') : t('new.title')}
        </Text>
        <View style={styles.cancel} />
      </View>

      <ScrollView
        ref={scroll}
        contentContainerStyle={styles.content}
        keyboardShouldPersistTaps="handled"
        keyboardDismissMode="on-drag"
        automaticallyAdjustKeyboardInsets
      >
        {/* Search and the selected result */}
        <View style={styles.section}>
          <Text maxFontSizeMultiplier={MAX_SCALE.body} style={styles.sectionLabel} nativeID="search-label">
            {t('new.question')}
          </Text>
          <View style={[styles.searchBox, triedToSave && missingSpot && styles.inputProblem]}>
            <Feather name="search" size={18} color={color.muted} />
            <TextInput maxFontSizeMultiplier={MAX_SCALE.body}
              ref={searchInput}
              value={query}
              onChangeText={setQuery}
              placeholder={t('new.search')}
              placeholderTextColor={color.muted}
              style={styles.searchInput}
              accessibilityLabel={t('new.search')}
              autoCorrect={false}
              autoCapitalize="none"
              returnKeyType="search"
              clearButtonMode="never"
              testID="search-input"
            />
            {query.length > 0 ? (
              <Pressable
                onPress={() => setQuery('')}
                accessibilityRole="button"
                accessibilityLabel={t('new.searchClear')}
                hitSlop={10}
                style={styles.clear}
              >
                <Feather name="x-circle" size={18} color={color.muted} />
              </Pressable>
            ) : null}
          </View>

          {search.status !== 'idle' && query.trim() !== answeredQuery ? (
            <View style={styles.results} testID="search-results">
              {search.status === 'loading' && results.length === 0 ? (
                <Text maxFontSizeMultiplier={MAX_SCALE.body} style={styles.resultNote}>{t('new.searching')}</Text>
              ) : null}
              {search.status === 'error' ? <Text maxFontSizeMultiplier={MAX_SCALE.body} style={styles.resultNote}>{search.message}</Text> : null}
              {search.status === 'done' && results.length === 0 ? (
                <Text maxFontSizeMultiplier={MAX_SCALE.body} style={styles.resultNote}>{t('new.noResults', { q: query.trim() })}</Text>
              ) : null}
              {results.map((r, i) => (
                <Pressable
                  key={`${r.kind}:${r.label}:${r.lat}:${r.lon}`}
                  onPress={() => chooseResult(r)}
                  accessibilityRole="button"
                  accessibilityLabel={`${r.label}, ${r.secondary}`}
                  style={({ pressed }) => [styles.result, i > 0 && styles.resultDivider, pressed && styles.pressed]}
                  testID={`search-result-${i}`}
                >
                  <Feather name={r.kind === 'adresse' ? 'home' : 'map-pin'} size={16} color={color.muted} />
                  <View style={styles.resultText}>
                    <Text maxFontSizeMultiplier={MAX_SCALE.body} style={styles.resultLabel}>{r.label}</Text>
                    <Text maxFontSizeMultiplier={MAX_SCALE.body} style={styles.resultSecondary}>{r.secondary}</Text>
                  </View>
                </Pressable>
              ))}
            </View>
          ) : null}

          {spot ? (
            <View style={styles.selected} accessible testID="selected-place">
              <Feather name="map-pin" size={18} color={color.accentStrong} />
              <Text maxFontSizeMultiplier={MAX_SCALE.body} style={styles.selectedText}>
                <Text maxFontSizeMultiplier={MAX_SCALE.body} style={styles.selectedName}>{shownName}</Text>
                {spot.secondary ? ` · ${spot.secondary}` : ''}
              </Text>
              <Text maxFontSizeMultiplier={MAX_SCALE.body} style={styles.selectedTag}>{t('new.selected')}</Text>
            </View>
          ) : null}
          {triedToSave && missingSpot ? <Text maxFontSizeMultiplier={MAX_SCALE.body} style={styles.problem}>{t('new.pickFirst')}</Text> : null}
        </View>

        {/* Type */}
        <View style={styles.section}>
          <Text maxFontSizeMultiplier={MAX_SCALE.body} style={styles.sectionLabel}>{t('new.type')}</Text>
          <View style={styles.chips}>
            {TEMPLATE_ORDER.map((tpl) => (
              <TypeChip
                key={tpl}
                label={TEMPLATES[tpl].name}
                selected={template === tpl}
                onPress={() => chooseTemplate(tpl)}
                testID={`template-${tpl}`}
              />
            ))}
          </View>
        </View>

        {/* Name */}
        <View style={styles.section}>
          <Text maxFontSizeMultiplier={MAX_SCALE.body} style={styles.sectionLabel}>{t('new.label')}</Text>
          <TextInput maxFontSizeMultiplier={MAX_SCALE.body}
            value={label}
            onChangeText={(v) => {
              setLabel(v);
              setLabelEdited(true);
            }}
            maxLength={LABEL_MAX}
            style={[styles.textInput, triedToSave && missingLabel && styles.inputProblem]}
            accessibilityLabel={t('new.label')}
            accessibilityHint={t('new.labelHint', { label: label.trim() || '…' })}
            returnKeyType="done"
            testID="label-input"
          />
          {triedToSave && missingLabel ? (
            <Text maxFontSizeMultiplier={MAX_SCALE.body} style={styles.problem}>{t('new.labelMissing')}</Text>
          ) : (
            <Text maxFontSizeMultiplier={MAX_SCALE.body} style={styles.hint}>{t('new.labelHint', { label: label.trim() || '…' })}</Text>
          )}
        </View>

        {/* Map and radius */}
        <View style={styles.sectionTight}>
          {spot && center ? (
            <PlaceMap
              place={{ center, radiusM }}
              fitRadiusM={settledRadiusM}
              animationMs={300}
              height={190}
              accessibilityLabel={t('new.mapLabel', { name: shownName, radius: radiusLabel(radiusM) })}
            />
          ) : null}
          {/* With large text the value goes below the label (§7.5). */}
          <View style={[styles.radiusHeader, large && styles.radiusHeaderLarge]}>
            <Text maxFontSizeMultiplier={MAX_SCALE.body} style={styles.sectionLabel}>{t('new.radius')}</Text>
            <Text maxFontSizeMultiplier={MAX_SCALE.display} style={styles.radiusValue} testID="radius-label">
              {radiusLabel(radiusM)}
            </Text>
          </View>
          <RadiusSlider
            value={radiusM}
            onChange={setRadiusM}
            onChangeEnd={(m) => {
              setRadiusM(m);
              setSettledRadiusM(m);
            }}
            accessibilityLabel={t('new.radius')}
          />
          <View style={styles.radiusEnds} importantForAccessibility="no-hide-descendants" accessibilityElementsHidden>
            <Text maxFontSizeMultiplier={MAX_SCALE.body} style={styles.radiusEnd}>{t('new.radiusMin')}</Text>
            <Text maxFontSizeMultiplier={MAX_SCALE.body} style={styles.radiusEnd}>{t('new.radiusMax')}</Text>
          </View>
          {showsSmallRadiusNote(radiusM) ? <InfoNote text={t('new.smallRadius')} testID="small-radius-note" /> : null}
        </View>

        {/* Preview, or the coverage note (D9) */}
        {spot && !spot.covered ? (
          <InfoNote title={t('new.notCovered')} text={t('new.notCoveredDetail')} testID="not-covered-note" />
        ) : (
          <PreviewCard state={preview} hasSpot={spot !== null} noCategories={missingCategories} />
        )}

        {/* Categories */}
        <View
          style={styles.section}
          onLayout={(ev) => {
            if (!highlight || scrolledToHighlight.current) return;
            scrolledToHighlight.current = true;
            scroll.current?.scrollTo({ y: Math.max(0, ev.nativeEvent.layout.y - 16), animated: true });
          }}
          testID="categories"
        >
          <Text maxFontSizeMultiplier={MAX_SCALE.body} style={styles.sectionLabel}>{t('new.categories')}</Text>
          <View style={styles.chips}>
            {APP_CATEGORIES.map((c) => (
              <CategoryChip
                key={c}
                label={c}
                selected={categories.includes(c)}
                highlighted={c === highlight}
                onPress={() => toggleCategory(c)}
                testID={`category-${c}`}
              />
            ))}
          </View>
          {highlight && categories.includes(highlight as AppCategory) ? (
            <Text maxFontSizeMultiplier={MAX_SCALE.body} style={styles.hint} testID="fewer-note">
              {t('new.fewerNote', { category: highlight })}
            </Text>
          ) : null}
          {missingCategories ? <Text maxFontSizeMultiplier={MAX_SCALE.body} style={styles.problem}>{t('new.noCategories')}</Text> : null}
        </View>

        {/* When and push */}
        <View style={styles.card}>
          <Pressable
            onPress={() => setWhenOpen((o) => !o)}
            accessibilityRole="button"
            accessibilityState={{ expanded: whenOpen }}
            accessibilityLabel={`${t('new.when')}: ${windowLabel(timeWindow)}`}
            style={({ pressed }) => [styles.row, pressed && styles.pressed]}
            testID="when-row"
          >
            <Text maxFontSizeMultiplier={MAX_SCALE.body} style={styles.rowLabel}>{t('new.when')}</Text>
            <View style={styles.rowRight}>
              <Text maxFontSizeMultiplier={MAX_SCALE.body} style={styles.rowValue}>{windowLabel(timeWindow)}</Text>
              <Feather name={whenOpen ? 'chevron-up' : 'chevron-down'} size={18} color={color.muted} />
            </View>
          </Pressable>
          {whenOpen
            ? choices.map((w) => {
                const on = sameWindow(w, timeWindow);
                return (
                  <Pressable
                    key={windowLabel(w)}
                    onPress={() => {
                      setTimeWindow(w);
                      setWhenOpen(false);
                    }}
                    accessibilityRole="radio"
                    accessibilityState={{ checked: on }}
                    style={({ pressed }) => [styles.choice, pressed && styles.pressed]}
                  >
                    <Text maxFontSizeMultiplier={MAX_SCALE.body} style={[styles.choiceText, on && styles.choiceTextOn]}>{windowLabel(w)}</Text>
                    {on ? <Feather name="check" size={18} color={color.accentStrong} /> : null}
                  </Pressable>
                );
              })
            : null}
          <View style={styles.rowDivider} />
          <View style={styles.row}>
            <View style={styles.rowText}>
              <Text maxFontSizeMultiplier={MAX_SCALE.body} style={styles.rowLabel}>{PUSH_LABEL}</Text>
              <Text maxFontSizeMultiplier={MAX_SCALE.body} style={styles.rowDetail}>{PUSH_DETAIL}</Text>
            </View>
            <Switch
              value={push}
              onValueChange={setPush}
              trackColor={{ true: color.accent, false: color.borderStrong }}
              accessibilityLabel={t('new.push')}
              testID="push-switch"
            />
          </View>
        </View>
        <Text maxFontSizeMultiplier={MAX_SCALE.body} style={styles.footnote}>{t('new.footnote')}</Text>

        {editing ? (
          <Pressable
            onPress={confirmDelete}
            disabled={busy !== null}
            accessibilityRole="button"
            style={({ pressed }) => [styles.delete, pressed && styles.pressed]}
            testID="delete"
          >
            <Feather name="trash-2" size={18} color={color.ink2} />
            <Text maxFontSizeMultiplier={MAX_SCALE.body} style={styles.deleteText}>{t('new.delete')}</Text>
          </Pressable>
        ) : null}
      </ScrollView>

      <SafeAreaView edges={['bottom']} style={styles.bottomBar}>
        {saveError ? (
          <Text maxFontSizeMultiplier={MAX_SCALE.body} style={styles.saveError} accessibilityLiveRegion="polite" testID="save-error">
            {saveError}
          </Text>
        ) : null}
        <Pressable
          onPress={save}
          disabled={busy !== null}
          accessibilityRole="button"
          accessibilityState={{ disabled: busy !== null, busy: busy === 'saving' }}
          style={({ pressed }) => [styles.primary, (pressed || busy) && styles.primaryPressed]}
          testID="save"
        >
          <Text maxFontSizeMultiplier={MAX_SCALE.body} style={styles.primaryText}>
            {busy === 'saving' ? t('new.saving') : editing ? t('new.saveChanges') : t('new.save')}
          </Text>
        </Pressable>
      </SafeAreaView>
    </SafeAreaView>
  );
}

function PreviewCard({
  state,
  hasSpot,
  noCategories,
}: {
  state: PreviewState;
  hasSpot: boolean;
  noCategories: boolean;
}) {
  let body: React.ReactNode;
  if (!hasSpot || noCategories) {
    body = <Text maxFontSizeMultiplier={MAX_SCALE.body} style={styles.previewDetail}>{hasSpot ? t('new.noCategories') : t('new.previewPick')}</Text>;
  } else if (state.status === 'error') {
    body = (
      <>
        <Text maxFontSizeMultiplier={MAX_SCALE.body} style={styles.previewDetail}>{state.message}</Text>
        <Pressable onPress={state.retry} accessibilityRole="button" hitSlop={8} style={styles.retry}>
          <Text maxFontSizeMultiplier={MAX_SCALE.body} style={styles.link}>{t('new.retry')}</Text>
        </Pressable>
      </>
    );
  } else {
    const data = state.status === 'ok' ? state.data : state.status === 'loading' ? state.stale : undefined;
    const text = data ? previewText(data) : null;
    body = (
      <>
        <View style={styles.previewRow}>
          <Text maxFontSizeMultiplier={MAX_SCALE.display} style={[styles.previewCount, !text && styles.previewCountEmpty]} testID="preview-count">
            {text ? text.headline : '…'}
          </Text>
          {state.status === 'loading' ? <ActivityIndicator size="small" color={color.muted} /> : null}
        </View>
        {text && text.detail.length > 0 ? <Text maxFontSizeMultiplier={MAX_SCALE.body} style={styles.previewDetail}>{text.detail.join(' ')}</Text> : null}
      </>
    );
  }
  return (
    <View style={styles.previewCard} accessible testID="preview-card">
      <Text maxFontSizeMultiplier={MAX_SCALE.body} style={styles.previewTitle}>{t('new.preview')}</Text>
      {body}
    </View>
  );
}

const styles = StyleSheet.create({
  screen: { flex: 1, backgroundColor: color.bg },
  pressed: { opacity: 0.7 },

  header: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'space-between',
    paddingHorizontal: spacing.screen,
    paddingTop: 4,
    paddingBottom: 4,
  },
  cancel: { minWidth: 64, minHeight: 44, justifyContent: 'center' },
  cancelText: { fontFamily: font.body[500], fontSize: 16, color: color.accentStrong },
  headerTitle: { fontFamily: font.body[600], fontSize: 17, color: color.ink },

  content: { paddingHorizontal: spacing.screen, paddingTop: 8, paddingBottom: 28, gap: 22 },
  section: { gap: 8 },
  sectionTight: { gap: 10 },
  sectionLabel: { fontFamily: font.body[600], fontSize: 14, color: color.ink2 },
  chips: { flexDirection: 'row', flexWrap: 'wrap', gap: 8 },

  searchBox: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 10,
    minHeight: 50,
    paddingHorizontal: 14,
    backgroundColor: color.surface,
    borderWidth: 1,
    borderColor: color.borderStrong,
    borderRadius: radii.inner,
  },
  searchInput: { flex: 1, fontFamily: font.body[400], fontSize: 16, color: color.ink, paddingVertical: 12 },
  clear: { minWidth: 32, minHeight: 44, alignItems: 'center', justifyContent: 'center' },
  inputProblem: { borderColor: color.ink2, borderWidth: 2 },

  results: {
    backgroundColor: color.surface,
    borderWidth: 1,
    borderColor: color.border,
    borderRadius: radii.inner,
    overflow: 'hidden',
  },
  result: { flexDirection: 'row', alignItems: 'center', gap: 12, paddingHorizontal: 14, paddingVertical: 10, minHeight: 52 },
  resultDivider: { borderTopWidth: 1, borderTopColor: color.border },
  resultText: { flex: 1 },
  resultLabel: { fontFamily: font.body[600], fontSize: 15, color: color.ink },
  resultSecondary: { fontFamily: font.body[400], fontSize: 13, color: color.muted },
  resultNote: { fontFamily: font.body[400], fontSize: 14, color: color.muted, padding: 14 },

  selected: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 10,
    paddingHorizontal: 12,
    paddingVertical: 12,
    backgroundColor: color.accentTint,
    borderRadius: radii.inner,
  },
  selectedText: { flex: 1, fontFamily: font.body[400], fontSize: 15, color: color.ink },
  selectedName: { fontFamily: font.body[600] },
  selectedTag: { fontFamily: font.body[600], fontSize: 13, color: color.accentStrong },

  textInput: {
    minHeight: 50,
    paddingHorizontal: 14,
    backgroundColor: color.surface,
    borderWidth: 1,
    borderColor: color.borderStrong,
    borderRadius: radii.inner,
    fontFamily: font.body[400],
    fontSize: 16,
    color: color.ink,
  },
  hint: { fontFamily: font.body[400], fontSize: 13, lineHeight: 18, color: color.muted },
  problem: { fontFamily: font.body[500], fontSize: 13, lineHeight: 18, color: color.ink2 },

  radiusHeader: { flexDirection: 'row', justifyContent: 'space-between', alignItems: 'baseline', marginTop: 4 },
  radiusHeaderLarge: { flexDirection: 'column', alignItems: 'flex-start', gap: 2 },
  radiusValue: { fontFamily: font.display[700], fontSize: 22, color: color.ink },
  radiusEnds: { flexDirection: 'row', justifyContent: 'space-between', marginTop: -6 },
  radiusEnd: { fontFamily: font.body[400], fontSize: 13, color: color.muted },

  previewCard: {
    backgroundColor: color.surface,
    borderWidth: 1,
    borderColor: color.border,
    borderRadius: radii.card,
    paddingHorizontal: spacing.cardPadding,
    paddingVertical: 14,
    gap: 6,
  },
  previewTitle: {
    fontFamily: font.body[600],
    fontSize: 12,
    letterSpacing: 0.6,
    textTransform: 'uppercase',
    color: color.muted,
  },
  previewRow: { flexDirection: 'row', alignItems: 'center', gap: 10 },
  previewCount: { fontFamily: font.display[700], fontSize: 24, color: color.ink },
  previewCountEmpty: { color: color.muted },
  previewDetail: { fontFamily: font.body[400], fontSize: 14, lineHeight: 20, color: color.muted },
  retry: { minHeight: 44, justifyContent: 'center', alignSelf: 'flex-start' },
  link: { fontFamily: font.body[600], fontSize: 14, color: color.accentStrong },

  card: {
    backgroundColor: color.surface,
    borderWidth: 1,
    borderColor: color.border,
    borderRadius: radii.card,
    overflow: 'hidden',
  },
  row: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'space-between',
    gap: 12,
    minHeight: 52,
    paddingHorizontal: spacing.cardPadding,
    paddingVertical: 10,
  },
  rowRight: { flexDirection: 'row', alignItems: 'center', gap: 6, flexShrink: 1 },
  rowLabel: { fontFamily: font.body[400], fontSize: 15, color: color.ink },
  rowValue: { fontFamily: font.body[600], fontSize: 15, color: color.ink, flexShrink: 1, textAlign: 'right' },
  rowText: { flexShrink: 1 },
  rowDetail: { fontFamily: font.body[400], fontSize: 13, color: color.muted },
  rowDivider: { height: 1, backgroundColor: color.border, marginHorizontal: spacing.cardPadding },
  choice: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'space-between',
    minHeight: 48,
    paddingHorizontal: spacing.cardPadding,
    paddingLeft: spacing.cardPadding + 12,
    backgroundColor: color.calmTint,
  },
  choiceText: { fontFamily: font.body[400], fontSize: 15, color: color.ink2 },
  choiceTextOn: { fontFamily: font.body[600], color: color.accentStrong },

  footnote: { fontFamily: font.body[400], fontSize: 13, lineHeight: 19, color: color.muted, marginTop: -10 },

  delete: { flexDirection: 'row', alignItems: 'center', gap: 8, minHeight: 44, alignSelf: 'flex-start' },
  deleteText: { fontFamily: font.body[600], fontSize: 15, color: color.ink2 },

  bottomBar: {
    paddingHorizontal: spacing.screen,
    paddingTop: 12,
    borderTopWidth: 1,
    borderTopColor: color.border,
    backgroundColor: color.bg,
    gap: 8,
  },
  saveError: { fontFamily: font.body[500], fontSize: 14, lineHeight: 20, color: color.ink2, textAlign: 'center' },
  primary: {
    height: 52,
    borderRadius: radii.button,
    backgroundColor: color.accent,
    alignItems: 'center',
    justifyContent: 'center',
    marginBottom: 8,
  },
  primaryPressed: { backgroundColor: color.accentStrong },
  primaryText: { fontFamily: font.body[600], fontSize: 16, color: color.surface },
});
