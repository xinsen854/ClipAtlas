"""Strict vehicle identity normalization.

Only exact, manually confirmed aliases are accepted.  Similar-looking model
names are intentionally absent from the alias map and therefore stay distinct.
"""

from __future__ import annotations

import re


CANONICAL_VEHICLE_NAMES = frozenset({
    "\u6cf0\u94bd700", "\u5766\u514b700", "Tank 700", "BJ40", "BJ40\u589e\u7a0b",
    "BJ40\u589e\u7a0b\u60a6\u91ce\u98de\u884c\u7248", "BJ30",
})

# These are deliberately conservative.  In particular, Tank 700 is not an
# alias of Titan 700 and English spelling is not inferred from Chinese spelling.
MANUALLY_CONFIRMED_ALIASES: dict[str, tuple[str, ...]] = {
    "\u6cf0\u94bd700": ("\u6cf0\u94bd 700",),
    "BJ40": ("BJ 40",),
    "BJ40\u589e\u7a0b": ("BJ40 \u589e\u7a0b",),
}

_ALIASES = {
    alias.casefold(): canonical
    for canonical, aliases in MANUALLY_CONFIRMED_ALIASES.items()
    for alias in (canonical, *aliases)
}


def canonical_vehicle_name(value: str) -> str:
    normalized = re.sub(r"\s+", " ", value.strip())
    return _ALIASES.get(normalized.casefold(), normalized)


def is_known_vehicle_name(value: str) -> bool:
    return canonical_vehicle_name(value) in CANONICAL_VEHICLE_NAMES
