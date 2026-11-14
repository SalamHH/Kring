# Kring

Calm, place-based alerts from the Norwegian police log (Politiloggen). The full spec is in [`docs/kring-spec.md`](docs/kring-spec.md). Changes made after v0.1 are marked "(decided <date>)" in the section they belong to.

## Current milestone

**M1:** API, matching, push, and the Expo screens Hjem, Nytt sted and Hendelse, plus the Render deploy. The plan, with a checkbox per step, how each one is verified, and the design choices D1–D12, is in [`docs/plans/m1.md`](docs/plans/m1.md). M0 is done: [`docs/m0-report.md`](docs/m0-report.md).

## Read first

- Spec §8 (architecture) and §9 (geocoding and classification) are the core. Words in capitals (MUST, SHOULD, MAY) are requirements.
- `research/presisjonstest.py` (v4) is the reference geocoder. Port its logic; don't reinvent it. Where it disagrees with §9, the script wins. The deliberate exceptions are the `by`/`flyplass` place-name ranking (§9.2, `app/geocode/places.py`) and the additions where the script gives up (§9.2, `app/geocode/tillegg.py`). Both are listed in spec §9.2. Appendix C lists the fixtures it must pass.
- Politiloggen field names are not officially documented. Inspect a live response before writing parsers, and parse defensively (§8.3).
- Never cache failed external lookups. Never push the same event twice to the same place.

## Repo layout

The repo root is the `kring/` level in spec §8.9.

## Local environment

Homebrew `postgresql@17` + `postgis`, and `uv` pinning Python 3.12. There is no Docker. Setup and test commands: `backend/README.md`.
