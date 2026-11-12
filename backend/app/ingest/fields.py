"""Defensive field lookup for the undocumented Politiloggen payload (spec §8.3).

Ported from `pick()` in research/presisjonstest.py.
"""

from __future__ import annotations

from typing import Any


def pick(obj: Any, names: tuple[str, ...]) -> Any:
    """First non-empty field among the candidate names, ignoring case.
    If the value is an object, try name/value/displayName/navn inside it."""
    if not isinstance(obj, dict):
        return None
    lower = {k.lower(): v for k, v in obj.items()}
    for n in names:
        v = lower.get(n.lower())
        if v in (None, "", [], {}):
            continue
        if isinstance(v, dict):
            inner = pick(v, ("name", "value", "displayName", "navn"))
            if inner is not None:
                return inner
        return v
    return None
