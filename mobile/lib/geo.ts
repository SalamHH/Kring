/** Small geometry helpers for the map. Coordinates are WGS 84; GeoJSON order is [lon, lat]. */

export interface LatLon {
  lat: number;
  lon: number;
}

const EARTH_RADIUS_M = 6_371_008.8;
const rad = (d: number) => (d * Math.PI) / 180;
const deg = (r: number) => (r * 180) / Math.PI;

/** The point `distanceM` metres from `from` along `bearingDeg` (great circle). */
export function destination(from: LatLon, distanceM: number, bearingDeg: number): LatLon {
  const d = distanceM / EARTH_RADIUS_M;
  const b = rad(bearingDeg);
  const lat1 = rad(from.lat);
  const lon1 = rad(from.lon);
  const lat2 = Math.asin(Math.sin(lat1) * Math.cos(d) + Math.cos(lat1) * Math.sin(d) * Math.cos(b));
  const lon2 =
    lon1 + Math.atan2(Math.sin(b) * Math.sin(d) * Math.cos(lat1), Math.cos(d) - Math.sin(lat1) * Math.sin(lat2));
  return { lat: deg(lat2), lon: deg(lon2) };
}

/** Great-circle distance in metres. */
export function distanceM(a: LatLon, b: LatLon): number {
  const dLat = rad(b.lat - a.lat);
  const dLon = rad(b.lon - a.lon);
  const h = Math.sin(dLat / 2) ** 2 + Math.cos(rad(a.lat)) * Math.cos(rad(b.lat)) * Math.sin(dLon / 2) ** 2;
  return 2 * EARTH_RADIUS_M * Math.asin(Math.sqrt(h));
}

/** A circle of `radiusM` metres on the ground, as a closed GeoJSON polygon. */
export function circlePolygon(center: LatLon, radiusM: number, steps = 96): GeoJSON.Polygon {
  const ring: [number, number][] = [];
  for (let i = 0; i < steps; i++) {
    const p = destination(center, radiusM, (360 * i) / steps);
    ring.push([p.lon, p.lat]);
  }
  ring.push(ring[0]);
  return { type: 'Polygon', coordinates: [ring] };
}

/** [west, south, east, north] around circles given as center and radius. */
export function boundsOfCircles(circles: { center: LatLon; radiusM: number }[]): [number, number, number, number] {
  let [w, s, e, n] = [Infinity, Infinity, -Infinity, -Infinity];
  for (const { center, radiusM } of circles) {
    const north = destination(center, radiusM, 0).lat;
    const south = destination(center, radiusM, 180).lat;
    const east = destination(center, radiusM, 90).lon;
    const west = destination(center, radiusM, 270).lon;
    w = Math.min(w, west);
    s = Math.min(s, south);
    e = Math.max(e, east);
    n = Math.max(n, north);
  }
  return [w, s, e, n];
}
