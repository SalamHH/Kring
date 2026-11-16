-- Test data for the Maestro flows (mobile/.maestro), loaded by scripts/e2e.sh into the LOCAL dev
-- database and removed by down.sql. It sits at Kikut in Nordmarka (Oslo), where real incidents
-- are rare, so the flows can check exact rows. Ids end with the run's number (:run), so «N ny»
-- starts fresh each run. notified_at is set, so the notifier never pushes these.
--
--   e2e-gate   Innbrudd, gatenivå, 700 m north of Kikut: matches a 1 km place, not a 500 m one.
--   e2e-bydel  Innbrudd, bydel (±2 km), 800 m east: imprecise nearby, for the small-radius note.
--   e2e-notice Savnet, district-wide (D2), for «Fra politidistriktet».
DELETE FROM events WHERE id LIKE 'e2e-%';
DELETE FROM places WHERE label LIKE 'E2E %';

WITH kikut AS (SELECT ST_SetSRID(ST_MakePoint(10.64511, 60.08407), 4326)::geography AS g)
INSERT INTO events (id, district, municipality, kommunenummer, area, category, severity,
                    first_message_at, last_message_at, is_active, geom, uncertainty_m,
                    precision_tier, geocode_method, raw, scope, notified_at)
SELECT 'e2e-gate-' || :'run', 'Oslo Politidistrikt', 'Oslo', '0301', 'Kikutstua', 'Innbrudd', 'normal',
       now() - interval '5 minutes', now() - interval '5 minutes', true,
       ST_Project(g, 700, 0), 40, 'gate', NULL, '{}'::jsonb, 'kommune', now()
FROM kikut
UNION ALL
SELECT 'e2e-bydel-' || :'run', 'Oslo Politidistrikt', 'Oslo', '0301', 'Nordmarka', 'Innbrudd', 'normal',
       now() - interval '2 hours', now() - interval '2 hours', false,
       ST_Project(g, 800, pi() / 2), 2000, 'bydel', NULL, '{}'::jsonb, 'kommune', now()
FROM kikut
UNION ALL
SELECT 'e2e-notice-' || :'run', 'Oslo Politidistrikt', NULL, NULL, NULL, 'Savnet', 'severe',
       now() - interval '1 hour', now() - interval '1 hour', true,
       NULL, NULL, NULL, NULL, '{}'::jsonb, 'distrikt', now()
FROM kikut;

INSERT INTO event_messages (event_id, seq, created_at, text)
SELECT id, 1, first_message_at,
       CASE WHEN scope = 'distrikt' THEN 'E2E-test: Politiet ber om tips om en savnet person.'
            ELSE 'E2E-test: Innbrudd i en hytte. Politiet er på stedet.' END
FROM events WHERE id LIKE 'e2e-%';

-- Real incidents near Kikut would change the counts the flows expect.
SELECT CASE WHEN count(*) > 0 THEN 'warning: ' || count(*) || ' real incidents near Kikut in the last 7 days; hjem.yaml may fail'
            ELSE 'fixtures loaded (run ' || :'run' || ')' END AS e2e
FROM events
WHERE id NOT LIKE 'e2e-%' AND geom IS NOT NULL AND first_message_at > now() - interval '7 days'
  AND ST_DWithin(geom, ST_SetSRID(ST_MakePoint(10.64511, 60.08407), 4326)::geography, 3000);
