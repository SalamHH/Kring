"""Recorded Politiloggen data (tests/fixtures/politiloggen/, see scripts/record_politiloggen.py)."""

from __future__ import annotations

import json
from functools import cache
from pathlib import Path
from typing import Any

from app.ingest.kommuner import Kommune, KommuneRegister

FIXTURE_DIR = Path(__file__).parent / "fixtures" / "politiloggen"


def _load(name: str) -> Any:
    return json.loads((FIXTURE_DIR / name).read_text("utf-8"))


@cache
def kommuner() -> list[dict[str, Any]]:
    return _load("kommuner.json")


def register() -> KommuneRegister:
    return KommuneRegister(kommuner())


@cache
def page_sample() -> dict[str, Any]:
    return _load("page_sample.json")


@cache
def quarter() -> dict[str, Any]:
    return _load("quarter.json")


def raw_threads_in(knr: str) -> list[dict[str, Any]]:
    """Recorded quarter threads whose municipality resolves to `knr`, in recorded order."""
    reg = register()
    out = []
    for t in quarter()["threads"]:
        k = reg.resolve(t.get("municipality"))
        if k is not None and k.nummer == knr:
            out.append(t)
    return out


def scoped_raw_threads() -> list[tuple[dict[str, Any], Kommune]]:
    """Every recorded quarter thread with its resolved municipality, in recorded order."""
    reg = register()
    out = []
    for t in quarter()["threads"]:
        k = reg.resolve(t.get("municipality"))
        assert k is not None, t.get("municipality")
        out.append((t, k))
    return out
