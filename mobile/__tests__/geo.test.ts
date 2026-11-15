import { boundsOfCircles, circlePolygon, destination, distanceM } from '@/lib/geo';

const TOYEN = { lat: 59.9152, lon: 10.7745 };

describe('geo', () => {
  it('destination is the given distance away', () => {
    for (const bearing of [0, 45, 90, 180, 270]) {
      expect(distanceM(TOYEN, destination(TOYEN, 1000, bearing))).toBeCloseTo(1000, 3);
    }
  });

  it('north is north', () => {
    const p = destination(TOYEN, 1000, 0);
    expect(p.lon).toBeCloseTo(TOYEN.lon, 9);
    expect(p.lat).toBeGreaterThan(TOYEN.lat);
  });

  it('circlePolygon is a closed ring at the radius', () => {
    const poly = circlePolygon(TOYEN, 1000, 64);
    const ring = poly.coordinates[0];
    expect(ring).toHaveLength(65);
    expect(ring[0]).toEqual(ring[64]);
    for (const [lon, lat] of ring) expect(distanceM(TOYEN, { lat, lon })).toBeCloseTo(1000, 3);
  });

  it('boundsOfCircles covers every circle', () => {
    const incident = destination(TOYEN, 800, 60);
    const [w, s, e, n] = boundsOfCircles([
      { center: TOYEN, radiusM: 1000 },
      { center: incident, radiusM: 500 },
    ]);
    for (const [lon, lat] of [
      ...circlePolygon(TOYEN, 1000).coordinates[0],
      ...circlePolygon(incident, 500).coordinates[0],
    ]) {
      expect(lon).toBeGreaterThanOrEqual(w - 1e-9);
      expect(lon).toBeLessThanOrEqual(e + 1e-9);
      expect(lat).toBeGreaterThanOrEqual(s - 1e-9);
      expect(lat).toBeLessThanOrEqual(n + 1e-9);
    }
    // Around 59.9° N, 1 km is about 0.009° of latitude and 0.018° of longitude.
    expect(n - TOYEN.lat).toBeCloseTo(0.009, 3);
  });
});
