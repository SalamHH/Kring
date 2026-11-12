"""Record live Kartverket responses for the Appendix C fixtures (M0 step 4).

Runs the reference geocoder (research/presisjonstest.py, `plasser`) over each fixture
with its HTTP session wrapped, and saves every final response to
tests/fixtures/kartverket/. Because the recordings are the script's own requests, the
port must make exactly the same requests to replay them (checked by the tests).

Usage, from backend/:
    uv run python -m scripts.record_kartverket            # record missing responses
    uv run python -m scripts.record_kartverket --refresh  # re-record everything

Hits the public Kartverket APIs (no key). Transient errors (429/5xx) are not saved.
"""

from __future__ import annotations

import argparse
import os
import tempfile

from tests import kartverket_replay as replay
from tests.appendix_c import FIXTURES, KNR, KOMMUNE
from tests.test_text_parity import ref


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--refresh", action="store_true", help="delete existing recordings first")
    args = ap.parse_args()

    if args.refresh:
        for p in replay.FIXTURE_DIR.glob("*.json"):
            p.unlink()
    existing = set(replay.load_all())

    saved: list[str] = []
    original_get = ref.HTTP.get

    def recording_get(url, params=None, **kwargs):
        resp = original_get(url, params=params, **kwargs)
        if resp.status_code == 429 or resp.status_code >= 500:
            return resp  # transient: never recorded, mirrors the cache rule
        key = replay.request_key(url, params or {})
        if key not in existing:
            body = resp.json() if resp.status_code < 400 else None
            replay.save(url, params or {}, resp.status_code, body)
            existing.add(key)
            saved.append(key)
        return resp

    ref.HTTP.get = recording_get
    # The script keeps a JSON cache relative to the working directory; run in an empty
    # temp dir so every request really goes to the API.
    cwd = os.getcwd()
    with tempfile.TemporaryDirectory() as tmp:
        os.chdir(tmp)
        try:
            geo = ref.Geokoder(KNR)
            for f in FIXTURES:
                rad = {"omrade": f.area, "tekst": f.text, "kategori": f.category}
                res = ref.plasser(rad, geo, KOMMUNE)
                print(f"#{f.nr:>2}  {res['metode']:<18} {res.get('treff')!s:<40} u={res['usikkerhet_m']}")
            if geo.feilede:
                print(f"WARNING: {geo.feilede} lookups failed (not recorded); run again to fill them in")
        finally:
            os.chdir(cwd)
            ref.HTTP.get = original_get

    print(f"saved {len(saved)} new recordings, {len(existing)} in total, in {replay.FIXTURE_DIR}")


if __name__ == "__main__":
    main()
