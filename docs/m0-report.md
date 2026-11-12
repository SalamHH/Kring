# M0 report: backend spike (ingest + geocode + DB)

*12 November 2026. Plan: [`plans/m0.md`](plans/m0.md). Spec: §8, §9, §14.*

## Summary

The backend can ingest the police log for Oslo and Akershus, place each incident on the map with an honest uncertainty radius, and keep it up to date every minute. Oslo passes every quality gate. Akershus works but places incidents much less precisely, because of how the police write its messages.

| M0 definition of done (§14) | Status |
|---|---|
| Live Oslo ingestion running | Done: 1-hour live run, 63 cycles, no errors (Oslo and Akershus) |
| Appendix C fixtures green | Done: all pass, offline, in CI |
| Interview notes summarised | **Not done.** This is your track; the notes go in `docs/interviews/` |

## Quality gates (§9.5)

### Oslo replay (gated)

This replays the recorded Oslo quarter offline: 421 threads, 28 planned traffic controls excluded, leaving 393 incidents.

| Uncertainty ≤ | 300 m | 500 m | 1 000 m | 2 000 m | Unplaced |
|---|---:|---:|---:|---:|---:|
| Oslo | 21 % | **27 %** (gate ≥ 25 %) | **63 %** (gate ≥ 60 %) | 75 % | 18 % |
| Research script, Appendix A | 21 % | 28 % | 63 % | 75 % | 18 % |

Both gates pass, and the port reproduces the research script's results. `tests/test_quality_gate.py` runs this replay on every `pytest` run, in under a second.

### Manual sample of 25 street placements

The review page is [`m0/street-sample.html`](m0/street-sample.html). Open it in a browser and mark each placement; your marks are kept in that browser.

My first pass: 24 of 25 have the right street (**96 %**, gate ≥ 90 %). The miss is a stop «på E6 like ved Sandstuveien», placed on Sandstuveien, which the message only uses as a reference point. Two placements on Østre Aker vei have the right street but ±3.1 km, because the road is long and the message names no part of it. The uncertainty is honest, so these land in the bydel tier.

### Akershus replay (reported, not gated)

813 threads in 21 municipalities, 45 controls excluded, leaving 768 incidents.

| Uncertainty ≤ | 500 m | 1 000 m | Unplaced |
|---|---:|---:|---:|
| Akershus | 16 % | 30 % | 32 % |

The main causes, from [`m0/replay-tables.md`](m0/replay-tables.md):
- **No area field.** 107 incidents (14 %) have an empty area field. Oslo has 16.
- **«Sentrum».** «Sentrum» appears 16 times; the alias exists only for Oslo, so these stay unplaced.
- **Large place names.** More placements are town-level, such as Jessheim, Ski or Lillestrøm (±1–2.5 km), than street-level.

Per-municipality results range from Bærum (57 % within 1 km) to Ullensaker and Vestby (13–15 %).

Full breakdowns by method, tier, category and municipality are in [`m0/replay-tables.md`](m0/replay-tables.md). Regenerate them with `uv run python -m scripts.m0_report` from `backend/`.

## Live run (step 8)

The worker ran live on 12 November 2026 from 21:59 to 23:04 CET.

- **First cycle:** on the empty database it read the whole quarter (101 pages, 10,020 threads) and placed 1,231 Oslo and Akershus threads in 2.5 minutes. Later cycles take about 1 second.
- **Freshness:** the database matched the live feed exactly: all 19 current in-scope threads were stored, with identical last-message times.
- **Errors:** no ERROR lines and no failed Kartverket lookups.
- **Spot check:** 10 events checked by hand, 8 right. It also confirmed that a police correction («Rett sted er ved Røykenveien 397») moves the event.

## Decisions made during M0

All are recorded in the spec with «(decided 2026-11-12)».

- **Polling:** LastDay normally, and LastQuarter after more than 23 h without a successful poll. At least 3 pages per cycle, with a 15-minute safety margin (§8.3).
- **Messages:** the message number comes from its id. Removed and Draft messages are dropped, and stored messages that disappear are deleted (§8.3).
- **Failed lookups:** if Kartverket fails, the event is stored without a point and retried every cycle. Failures are never cached (§8.3).
- **Worker:** cycles start every 60 s. Stopping it rolls back the cycle in progress, and only one worker can run per database (§8.3).
- **Place-name ranking:** «by» (town) and «flyplass» (airport) now rank above bridges. Before, «Jessheim» and «Gardermoen» were placed at bridges with ±150 m. This is the one deliberate difference from the research script (§9.2).

## After M0: Akershus pass (13 November 2026)

New rules handle incidents the script left unplaced (spec §9.2, `app/geocode/tillegg.py`):
- road and direction words around a place («E18 Inn Sandvika»);
- «Ski Sentrum» as the whole town;
- a place named in the text when the area field is empty («brann på Åkrene»);
- a municipality name, placed at its town at ±2 500 m («slåss i Lillestrøm»).

Safeguards keep these rules from overstating precision. All 136 new placements were read by hand against the police text.

| Replay | ≤ 500 m | ≤ 1 000 m | ≤ 2 000 m | Unplaced |
|---|---:|---:|---:|---:|
| Akershus, M0 | 16 % | 30 % | 40 % | 32 % |
| Akershus, now | 18 % | 34 % | 46 % | 18 % |
| Oslo, M0 | 27 % | 63 % | 75 % | 18 % |
| Oslo, now | 28 % | 68 % | 81 % | 12 % |

Akershus now has a regression floor in the quality gate (34 % within 1 000 m and at most 18 % unplaced). It is still not a gate, because the Akershus target is undecided.

Most of what remains is how the police write:
- About 29 % of Akershus incidents name only a town, such as «Kløfta». Town level (±2.5 km) is the honest answer for these.
- Many of the remaining unplaced messages name no place at all.

## Open issues for M1 and later

1. **District-wide notices are skipped.** Examples: «Oslo politidistrikt», «Øst politidistrikt»; about 1 a week each. These are missing persons, weather and airspace notices. How to show them is spec §15 question 8.
2. **Akershus precision** (partly addressed in the Akershus pass above). The remaining levers are:
   - per-municipality aliases («Sentrum» → that municipality's centre; «Ski Sentrum», «Thon Senter Jessheim»);
   - reading a place from the message text when the area field is empty;
   - road data (DATEX II) for E6/E18/E16 messages.
   Spec M3 already plans Akershus work.
3. **Road-only messages are unplaced.** Examples: «E6 Inng. Trosterud», «E6 Skulleruddumpa», «Ring 3 Økern». A named place after the road, such as Trosterud, could be tried as a place name. This applies to Oslo and Akershus alike.
4. **Re-geocoding stored events.** After a ranking change, stored events keep their old placement until the thread changes. In M0 the dev data was simply rebuilt. M1, with a real database, needs a re-geocode command.
5. **Deploy.** Everything runs locally. Render (web, worker and Postgres) is planned for M1.
