/** InfoNote (§7.2): dashed 1 px border, info icon, 13 px text. */
import Feather from '@expo/vector-icons/Feather';
import { StyleSheet, Text, View } from 'react-native';

import { MAX_SCALE } from '@/lib/textScale';
import { color, font, radius } from '@/theme/tokens';

export function InfoNote({ title, text, testID }: { title?: string; text: string; testID?: string }) {
  return (
    <View style={styles.note} accessible testID={testID}>
      <Feather name="info" size={16} color={color.muted} style={styles.icon} />
      <View style={styles.body}>
        {title ? <Text maxFontSizeMultiplier={MAX_SCALE.body} style={styles.title}>{title}</Text> : null}
        <Text maxFontSizeMultiplier={MAX_SCALE.body} style={styles.text}>{text}</Text>
      </View>
    </View>
  );
}

const styles = StyleSheet.create({
  note: {
    flexDirection: 'row',
    gap: 10,
    padding: 12,
    borderRadius: radius.inner,
    borderWidth: 1,
    borderStyle: 'dashed',
    borderColor: color.borderStrong,
  },
  icon: { marginTop: 1 },
  body: { flex: 1, gap: 2 },
  title: { fontFamily: font.body[600], fontSize: 13, lineHeight: 19, color: color.ink2 },
  text: { fontFamily: font.body[400], fontSize: 13, lineHeight: 19, color: color.ink2 },
});
