# Kring

Calm, place-based alerts from the Norwegian police log (Politiloggen). The full spec is in [`docs/kring-spec.md`](docs/kring-spec.md). Changes made after v0.1 are marked "(decided <date>)" in the section they belong to.

## Current milestone

**M1:** API, matching, push, and the Expo screens Hjem, Nytt sted and Hendelse, plus the Render deploy. The plan, with a checkbox per step, how each one is verified, and the design choices D1–D12, is in [`docs/plans/m1.md`](docs/plans/m1.md). M0 is done: [`docs/m0-report.md`](docs/m0-report.md).

## Board

The backlog is the GitHub project [Kring](https://github.com/users/SalamHH/projects/2) (project 2, owner `SalamHH`), with one issue per plan step or task and milestones M1–M4. Status columns: Backlog (later milestones), Todo, In progress, Done. Use `gh`; the project's IDs are fetched with `gh project field-list 2 --owner SalamHH`. Keep it current, but ask before each GitHub write (board status, closing or opening issues, pushes) with a short question:

- Starting a step or issue: set its status to In progress.
- Its commit: end the message with `Closes #N`. When it reaches the default branch, or when the step is ticked in the plan, close the issue and set it to Done.
- Missing work, a bug, or an open question found along the way: open an issue with the right milestone and labels (`backend`, `mobile`, `infra`, `docs`, `your-track`, `decision`), add it to the project, and say so in your reply.
- A new milestone plan: one issue per step, added as Todo; the milestone after it stays Backlog.
- The plan in `docs/plans/` stays the source of truth for how a step is verified. The board tracks status only.

## Mobile steps

- How a mobile step is tested is in the plan's settings (`docs/plans/m1.md`): component tests, a Maestro flow, `npm run test:e2e`. Check with text first (API, psql, logs); keep simulator screenshots few and small.
- Before calling a step done, say what was verified on the simulator and what only in jest.
- Test places are named «E2E …». Never delete other places on the simulator device; they are the user's.

## Read first

- Spec §8 (architecture) and §9 (geocoding and classification) are the core. Words in capitals (MUST, SHOULD, MAY) are requirements.
- `research/presisjonstest.py` (v4) is the reference geocoder. Port its logic; don't reinvent it. Where it disagrees with §9, the script wins. The deliberate exceptions are the `by`/`flyplass` place-name ranking (§9.2, `app/geocode/places.py`) and the additions where the script gives up (§9.2, `app/geocode/tillegg.py`). Both are listed in spec §9.2. Appendix C lists the fixtures it must pass.
- Politiloggen field names are not officially documented. Inspect a live response before writing parsers, and parse defensively (§8.3).
- Never cache failed external lookups. Never push the same event twice to the same place.

## Repo layout

The repo root is the `kring/` level in spec §8.9.

## Local environment

Homebrew `postgresql@17` + `postgis`, and `uv` pinning Python 3.12. There is no Docker. Setup and test commands: `backend/README.md`.
