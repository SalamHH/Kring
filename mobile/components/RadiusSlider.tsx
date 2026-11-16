/**
 * RadiusSlider (§7.2): 300–2 000 m in steps of 100. Drag or tap the track. `onChange` fires
 * at every step while dragging, so the map circle follows the finger; `onChangeEnd` fires when
 * the finger lifts, for work that should not run at every step (the preview, the map camera).
 *
 * VoiceOver: an adjustable element whose value is the label («1,0 km»); swipe up and down moves
 * one step. Built on gesture-handler rather than a native slider, so the horizontal drag wins
 * over the screen's vertical scroll without a new native module.
 */
import { useEffect, useRef, useState } from 'react';
import { type AccessibilityActionEvent, type LayoutChangeEvent, StyleSheet, View } from 'react-native';
import { GestureDetector, useCompetingGestures, usePanGesture, useTapGesture } from 'react-native-gesture-handler';

import { radiusLabel, RADIUS_MAX, RADIUS_MIN, RADIUS_STEP, snapRadius } from '@/lib/places';
import { color } from '@/theme/tokens';

const THUMB = 26;
const TRACK = 4;
const HEIGHT = 44;

export interface RadiusSliderProps {
  value: number;
  onChange: (m: number) => void;
  onChangeEnd: (m: number) => void;
  accessibilityLabel: string;
}

/** The radius at `x` points from the left edge of a slider `width` wide. */
export function radiusAt(x: number, width: number): number {
  const usable = Math.max(1, width - THUMB);
  const f = Math.min(1, Math.max(0, (x - THUMB / 2) / usable));
  return snapRadius(RADIUS_MIN + f * (RADIUS_MAX - RADIUS_MIN));
}

export function RadiusSlider({ value, onChange, onChangeEnd, accessibilityLabel }: RadiusSliderProps) {
  const [width, setWidth] = useState(0);
  // The gesture callbacks read these refs, so they never see a stale width, value or handler.
  const widthRef = useRef(0);
  const last = useRef(value);
  const handlers = useRef({ onChange, onChangeEnd });
  useEffect(() => {
    last.current = value;
  }, [value]);
  useEffect(() => {
    handlers.current = { onChange, onChangeEnd };
  });

  const move = (x: number) => {
    const m = radiusAt(x, widthRef.current);
    if (m !== last.current) {
      last.current = m;
      handlers.current.onChange(m);
    }
  };
  const end = () => handlers.current.onChangeEnd(last.current);

  const pan = usePanGesture({
    runOnJS: true,
    activeOffsetX: [-4, 4],
    failOffsetY: [-12, 12],
    onActivate: (e) => move(e.x),
    onUpdate: (e) => move(e.x),
    onDeactivate: end,
  });
  const tap = useTapGesture({
    runOnJS: true,
    onActivate: (e) => {
      move(e.x);
      end();
    },
  });
  const gesture = useCompetingGestures(pan, tap);

  const step = (e: AccessibilityActionEvent) => {
    const delta = e.nativeEvent.actionName === 'increment' ? RADIUS_STEP : -RADIUS_STEP;
    const m = snapRadius(value + delta);
    if (m !== value) {
      onChange(m);
      onChangeEnd(m);
    }
  };

  const f = (value - RADIUS_MIN) / (RADIUS_MAX - RADIUS_MIN);
  const thumbLeft = f * Math.max(0, width - THUMB);

  return (
    <GestureDetector gesture={gesture}>
      <View
        style={styles.root}
        onLayout={(e: LayoutChangeEvent) => {
          widthRef.current = e.nativeEvent.layout.width;
          setWidth(e.nativeEvent.layout.width);
        }}
        accessible
        accessibilityRole="adjustable"
        accessibilityLabel={accessibilityLabel}
        accessibilityValue={{ min: RADIUS_MIN, max: RADIUS_MAX, now: value, text: radiusLabel(value) }}
        accessibilityActions={[{ name: 'increment' }, { name: 'decrement' }]}
        onAccessibilityAction={step}
        testID="radius-slider"
      >
        <View style={styles.track} />
        <View style={[styles.fill, { width: thumbLeft }]} />
        <View style={[styles.thumb, { left: thumbLeft }]} />
      </View>
    </GestureDetector>
  );
}

const styles = StyleSheet.create({
  root: { height: HEIGHT, justifyContent: 'center' },
  track: {
    position: 'absolute',
    left: THUMB / 2,
    right: THUMB / 2,
    height: TRACK,
    borderRadius: TRACK / 2,
    backgroundColor: color.borderStrong,
  },
  fill: {
    position: 'absolute',
    left: THUMB / 2,
    height: TRACK,
    borderRadius: TRACK / 2,
    backgroundColor: color.accent,
  },
  thumb: {
    position: 'absolute',
    width: THUMB,
    height: THUMB,
    borderRadius: THUMB / 2,
    backgroundColor: color.accent,
    borderWidth: 3,
    borderColor: color.surface,
    shadowColor: color.ink,
    shadowOpacity: 0.2,
    shadowRadius: 3,
    shadowOffset: { width: 0, height: 1 },
    elevation: 2,
  },
});
