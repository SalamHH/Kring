"""Record live Kartverket responses for the geocoder tests (M0 steps 4 and 6).

Runs the reference geocoder (research/presisjonstest.py, `plasser`) over the inputs with its
HTTP session wrapped, and saves every final response. Because the recordings are the script's
own requests, the port must make exactly the same requests to replay them (checked by the tests).

Inputs:
- default:    the Appendix C fixtures → one file per request in tests/fixtures/kartverket/
- --threads:  every recorded Oslo and Akershus Politiloggen thread
              (tests/fixtures/politiloggen/quarter.json, rows built with the script's own
              `trad_til_rad`, each geocoded in its own municipality) →
              tests/fixtures/kartverket/threads.jsonl.gz. Requests that are already recorded
              are answered from the recording, not sent again.

Usage, from backend/:
    uv run python -m scripts.record_kartverket                       # record missing responses
    uv run python -m scripts.record_kartverket --refresh             # re-record everything
    uv run python -m scripts.record_kartverket --threads [--refresh]

Hits the public Kartverket APIs (no key). Transient errors (429/5xx) are not saved.
"""

from __future__ import annotations

import argparse
import json
import os
import tempfile
from typing import Any

from app.geocode.places import STED_ALIAS
from tests import kartverket_replay as replay
from tests.appendix_c import FIXTURES, KNR, KOMMUNE
from tests.politiloggen_fixtures import scoped_raw_threads
from tests.test_text_parity import ref


def rows(threads: bool) -> list[tuple[str, dict[str, Any], str, str]]:
    """(label, script row, kommunenummer, kommune name)"""
    if threads:
        return [(t["id"], ref.trad_til_rad(t), k.nummer, k.navn) for t, k in scoped_raw_threads()]
    return [
        (f"#{f.nr:>2}", {"omrade": f.area, "tekst": f.text, "kategori": f.category}, KNR, KOMMUNE)
        for f in FIXTURES
    ]


def recorded_response(rec: dict[str, Any], url: str) -> ref.requests.Response:
    resp = ref.requests.Response()
    resp.status_code = rec["status"]
    resp._content = b"null" if rec["body"] is None else json.dumps(rec["body"]).encode()
    resp.url = url
    return resp


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--refresh", action="store_true", help="delete existing recordings first")
    ap.add_argument("--threads", action="store_true", help="record for the Oslo/Akershus threads")
    args = ap.parse_args()

    files = replay.load_files()
    if args.threads:
        bundle = {} if args.refresh else replay.load_bundle()
    else:
        if args.refresh:
            for p in replay.FIXTURE_DIR.glob("*.json"):
                p.unlink()
            files = {}
        bundle = {}
    known = {**bundle, **files}
    existing = set(known)

    saved: list[str] = []
    original_get = ref.HTTP.get

    def recording_get(url, params=None, **kwargs):
        rec = known.get(replay.request_key(url, params or {}))
        if rec is not None:
            return recorded_response(rec, url)
        resp = original_get(url, params=params, **kwargs)
        if resp.status_code == 429 or resp.status_code >= 500:
            return resp  # transient: never recorded, mirrors the cache rule
        key = replay.request_key(url, params or {})
        if key not in existing:
            body = resp.json() if resp.status_code < 400 else None
            if args.threads:
                bundle[key] = replay.record(url, params or {}, resp.status_code, body)
            else:
                replay.save(url, params or {}, resp.status_code, body)
            existing.add(key)
            saved.append(key)
        return resp

    ref.HTTP.get = recording_get
    ref.STED_ALIAS = STED_ALIAS  # our aliases (script's + decided ones), so requests match the port
    # The script keeps a JSON cache relative to the working directory; run in an empty
    # temp dir so every request really goes to the API.
    cwd = os.getcwd()
    with tempfile.TemporaryDirectory() as tmp:
        os.chdir(tmp)
        ref.DATA_DIR.mkdir()  # the script saves its cache there every 25 lookups
        try:
            geos: dict[str, Any] = {}
            for label, rad, knr, kommune in rows(args.threads):
                geo = geos.setdefault(knr, ref.Geokoder(knr))
                res = ref.plasser(rad, geo, kommune)
                u = res["usikkerhet_m"]
                print(f"{label:<8} {knr} {res['metode']:<18} {res.get('treff')!s:<40} u={u}")
            failed = sum(g.feilede for g in geos.values())
            if failed:
                print(f"WARNING: {failed} lookups failed (not recorded); run again to fill them in")
        finally:
            os.chdir(cwd)
            ref.HTTP.get = original_get

    if args.threads:
        replay.save_bundle(bundle)
    print(f"saved {len(saved)} new recordings, {len(existing)} in total, in {replay.FIXTURE_DIR}")


if __name__ == "__main__":
    main()
