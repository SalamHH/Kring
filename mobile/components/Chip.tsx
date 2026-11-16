/**
 * TypeChip and CategoryChip (§7.2). Both are at least 44 pt tall (§7.5) and report
 * `accessibilityState.selected`. Selection is shown by fill and, for categories, a check
 * mark, not by colour alone.
 */
import Feather from '@expo/vector-icons/Feather';
import { Pressable, StyleSheet, Text } from 'react-native';

import { MAX_SCALE } from '@/lib/textScale';
import { color, font, radius } from '@/theme/tokens';

interface ChipProps {
  label: string;
  selected: boolean;
  onPress: () => void;
  testID?: string;
}

interface CategoryChipProps extends ChipProps {
  /** Opened from «Færre slike varsler» for this category: a thicker outline (with a note beside it). */
  highlighted?: boolean;
}

export function TypeChip({ label, selected, onPress, testID }: ChipProps) {
  return (
    <Pressable
      onPress={onPress}
      accessibilityRole="button"
      accessibilityState={{ selected }}
      testID={testID}
      style={({ pressed }) => [styles.type, selected ? styles.typeOn : styles.typeOff, pressed && styles.pressed]}
    >
      <Text maxFontSizeMultiplier={MAX_SCALE.body} style={[styles.typeText, selected ? styles.typeTextOn : styles.typeTextOff]}>{label}</Text>
    </Pressable>
  );
}

export function CategoryChip({ label, selected, onPress, testID, highlighted = false }: CategoryChipProps) {
  return (
    <Pressable
      onPress={onPress}
      accessibilityRole="button"
      accessibilityState={{ selected }}
      testID={testID}
      style={({ pressed }) => [
        styles.cat,
        selected ? styles.catOn : styles.catOff,
        highlighted && styles.catHighlighted,
        pressed && styles.pressed,
      ]}
    >
      {selected ? <Feather name="check" size={15} color={color.accentStrong} /> : null}
      <Text maxFontSizeMultiplier={MAX_SCALE.body} style={[styles.catText, selected ? styles.catTextOn : styles.catTextOff]}>{label}</Text>
    </Pressable>
  );
}

const styles = StyleSheet.create({
  pressed: { opacity: 0.7 },
  type: {
    minHeight: 44,
    paddingHorizontal: 18,
    borderRadius: radius.chip,
    borderWidth: 1.5,
    justifyContent: 'center',
  },
  typeOn: { backgroundColor: color.accent, borderColor: color.accent },
  typeOff: { backgroundColor: color.surface, borderColor: color.borderStrong },
  typeText: { fontSize: 15 },
  typeTextOn: { fontFamily: font.body[600], color: color.surface },
  typeTextOff: { fontFamily: font.body[500], color: color.ink },
  cat: {
    minHeight: 44,
    paddingHorizontal: 12,
    borderRadius: radius.inner,
    borderWidth: 1.5,
    flexDirection: 'row',
    alignItems: 'center',
    gap: 6,
  },
  catOn: { backgroundColor: color.accentTint, borderColor: color.accent },
  catOff: { backgroundColor: color.surface, borderColor: color.borderStrong },
  catHighlighted: { borderColor: color.severe, borderWidth: 2.5 },
  catText: { fontSize: 14 },
  catTextOn: { fontFamily: font.body[600], color: color.accentStrong },
  catTextOff: { fontFamily: font.body[500], color: color.muted },
});
