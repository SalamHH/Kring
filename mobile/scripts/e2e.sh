#!/bin/bash
# Runs the Maestro flows (.maestro/) on the iOS Simulator against the LOCAL API, with test data
# from .maestro/fixtures/ in the local dev database. Needs the dev build, Metro and the local API.
# Extra arguments go to `maestro test`, e.g. `npm run test:e2e -- .maestro/hjem.yaml`.
set -euo pipefail
cd "$(dirname "$0")/.."

PSQL=$(command -v psql || echo /opt/homebrew/opt/postgresql@17/bin/psql)
DB=${KRING_E2E_DB:-kring}
if grep -qs '^EXPO_PUBLIC_API_URL=' .env.local; then
  echo "e2e: .env.local points the app at another API; the flows need the local one." >&2
  exit 1
fi

"$PSQL" -d "$DB" -X -q -t -v ON_ERROR_STOP=1 -v run="$(date +%s)" -f .maestro/fixtures/up.sql
trap '"$PSQL" -d "$DB" -X -q -v ON_ERROR_STOP=1 -f .maestro/fixtures/down.sql' EXIT

flows=("$@")
[ ${#flows[@]} -eq 0 ] && flows=(.maestro)
MAESTRO_CLI_NO_ANALYTICS=1 MAESTRO_CLI_ANALYSIS_NOTIFICATION_DISABLED=true \
  maestro test --exclude-tags=helper "${flows[@]}"
