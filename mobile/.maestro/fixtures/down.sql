-- Removes what up.sql and the flows made (messages go with their events).
DELETE FROM events WHERE id LIKE 'e2e-%';
DELETE FROM places WHERE label LIKE 'E2E %';
