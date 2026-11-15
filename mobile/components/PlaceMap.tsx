/**
 * The shared map (§7.3): a place circle, solid in Nytt sted and dashed in Hendelse, and
 * optionally an incident point with its uncertainty ring. Kartverket tiles, «© Kartverket» on the map.
 */
import { Camera, GeoJSONSource, Layer, Map } from '@maplibre/maplibre-react-native';
import { useMemo, useState } from 'react';
import { Linking, Pressable, StyleSheet, Text, View } from 'react-native';

import { boundsOfCircles, circlePolygon, type LatLon } from '@/lib/geo';
import { t } from '@/lib/strings';
import { KARTVERKET_MAX_ZOOM, KARTVERKET_URL, mapStyle } from '@/lib/tiles';
import { color, font, radius } from '@/theme/tokens';

export interface PlaceMapProps {
  place: { center: LatLon; radiusM: number };
  /** Dashed outline, as on Hendelse. Solid by default. */
  dashed?: boolean;
  incident?: { point: LatLon; uncertaintyM: number };
  /**
   * The radius the camera fits, if not the drawn one. Nytt sted passes the radius at the last
   * slider release, so the circle grows and shrinks over a still map while dragging.
   */
  fitRadiusM?: number;
  /** Milliseconds the camera takes to a new place or radius. 0 (the default) jumps. */
  animationMs?: number;
  height?: number;
  /** Pan and zoom. Off by default: the map shows the area, it is not for browsing. */
  interactive?: boolean;
  /** What the map shows, for screen readers, such as «Kart: Hjemme, 1 km». */
  accessibilityLabel?: string;
}

const PADDING = { top: 24, right: 24, bottom: 24, left: 24 };

function feature(geometry: GeoJSON.Geometry): GeoJSON.Feature {
  return { type: 'Feature', properties: {}, geometry };
}

export function PlaceMap({
  place,
  dashed = false,
  incident,
  fitRadiusM,
  animationMs = 0,
  height = 220,
  interactive = false,
  accessibilityLabel,
}: PlaceMapProps) {
  const { center, radiusM } = place;
  const circle = useMemo(() => feature(circlePolygon(center, radiusM)), [center, radiusM]);
  const centerPoint = useMemo(() => feature({ type: 'Point', coordinates: [center.lon, center.lat] }), [center]);
  const ring = useMemo(
    () => (incident ? feature(circlePolygon(incident.point, incident.uncertaintyM)) : null),
    [incident],
  );
  const incidentPoint = useMemo(
    () => (incident ? feature({ type: 'Point', coordinates: [incident.point.lon, incident.point.lat] }) : null),
    [incident],
  );
  const fitRadius = fitRadiusM ?? radiusM;
  const bounds = useMemo(
    () =>
      boundsOfCircles([
        { center, radiusM: fitRadius },
        ...(incident ? [{ center: incident.point, radiusM: incident.uncertaintyM }] : []),
      ]),
    [center, fitRadius, incident],
  );
  // The first frame starts at the first bounds, so an animated camera doesn't fly in from afar.
  const [initialBounds] = useState(bounds);

  return (
    <View style={[styles.frame, { height }]}>
      <View style={StyleSheet.absoluteFill} accessible accessibilityRole="image" accessibilityLabel={accessibilityLabel}>
        <Map
          style={StyleSheet.absoluteFill}
          mapStyle={mapStyle}
          attribution={false}
          logo={false}
          compass={false}
          scaleBar={false}
          dragPan={interactive}
          touchZoom={interactive}
          doubleTapZoom={interactive}
          doubleTapHoldZoom={interactive}
          touchRotate={false}
          touchPitch={false}
        >
          <Camera
            initialViewState={{ bounds: initialBounds, padding: PADDING }}
            bounds={bounds}
            padding={PADDING}
            duration={animationMs}
            easing={animationMs ? 'ease' : undefined}
            maxZoom={KARTVERKET_MAX_ZOOM}
          />

          <GeoJSONSource id="place-area" data={circle}>
            <Layer id="place-fill" type="fill" paint={{ 'fill-color': color.accent, 'fill-opacity': 0.12 }} />
            <Layer
              id="place-line"
              type="line"
              paint={{
                'line-color': color.accent,
                'line-width': 2,
                ...(dashed ? { 'line-dasharray': [2, 2] } : {}),
              }}
            />
          </GeoJSONSource>
          <GeoJSONSource id="place-center" data={centerPoint}>
            <Layer
              id="place-dot"
              type="circle"
              paint={{
                'circle-radius': 6,
                'circle-color': color.accent,
                'circle-stroke-color': color.surface,
                'circle-stroke-width': 2,
              }}
            />
          </GeoJSONSource>

          {ring && incidentPoint ? (
            <>
              <GeoJSONSource id="incident-ring" data={ring}>
                <Layer id="incident-fill" type="fill" paint={{ 'fill-color': color.severe, 'fill-opacity': 0.18 }} />
                <Layer id="incident-line" type="line" paint={{ 'line-color': color.severe, 'line-width': 1.5 }} />
              </GeoJSONSource>
              <GeoJSONSource id="incident-point" data={incidentPoint}>
                <Layer
                  id="incident-dot"
                  type="circle"
                  paint={{
                    'circle-radius': 6,
                    'circle-color': color.severe,
                    'circle-stroke-color': color.surface,
                    'circle-stroke-width': 2,
                  }}
                />
              </GeoJSONSource>
            </>
          ) : null}
        </Map>
      </View>

      <Pressable
        style={styles.attribution}
        hitSlop={12}
        accessibilityRole="link"
        accessibilityLabel={t('map.attributionLabel')}
        onPress={() => Linking.openURL(KARTVERKET_URL)}
      >
        <Text style={styles.attributionText}>{t('map.attribution')}</Text>
      </Pressable>
    </View>
  );
}

const styles = StyleSheet.create({
  frame: {
    borderRadius: radius.card,
    borderWidth: 1,
    borderColor: color.border,
    overflow: 'hidden',
    backgroundColor: color.calmTint,
  },
  attribution: {
    position: 'absolute',
    right: 8,
    bottom: 8,
    paddingHorizontal: 6,
    paddingVertical: 2,
    borderRadius: radius.badge,
    backgroundColor: 'rgba(255, 255, 255, 0.85)',
  },
  attributionText: {
    fontFamily: font.body[500],
    fontSize: 11,
    color: color.ink2,
  },
});
