/**
 * Map tiles: Kartverket's raster WMTS, greyscale layer, web mercator (spec §8.1, D11).
 * CC BY 4.0, shown as «© Kartverket». No key and no published rate limit. Tiles are streamed only:
 * never bulk-download, offline-pack, prefetch or re-host them (Geovekst data at zoom 12+).
 * To change the layer (`topo` for colour) or the provider, change this file only.
 */
import type { StyleSpecification } from '@maplibre/maplibre-react-native';

import { color } from '@/theme/tokens';

/** Note `{y}/{x}`: Kartverket's WMTS REST order, not the usual `{x}/{y}`. */
export const KARTVERKET_TILE_URL =
  'https://cache.kartverket.no/v1/wmts/1.0.0/topograatone/default/webmercator/{z}/{y}/{x}.png';

/** The highest zoom the service serves; zoom 19 returns 400. */
export const KARTVERKET_MAX_ZOOM = 18;

export const KARTVERKET_URL = 'https://www.kartverket.no';

export const mapStyle: StyleSpecification = {
  version: 8,
  sources: {
    kartverket: {
      type: 'raster',
      tiles: [KARTVERKET_TILE_URL],
      tileSize: 256,
      minzoom: 0,
      maxzoom: KARTVERKET_MAX_ZOOM,
      attribution: '© Kartverket',
    },
  },
  layers: [
    { id: 'background', type: 'background', paint: { 'background-color': color.calmTint } },
    { id: 'kartverket', type: 'raster', source: 'kartverket' },
  ],
};
