"""String sanitization helpers shared by OTA parsers."""
from __future__ import annotations

import html as html_module
import re
from typing import Optional

# Characters to delete entirely (zero-width, bidi controls).
_BIDI_DELETE = (
    "\u200b", "\u200c", "\u200d", "\u200e", "\u200f",
    "\u202a", "\u202b", "\u202c", "\u202d", "\u202e",
    "\u2060", "\u2066", "\u2067", "\u2068", "\u2069",
    "\ufeff",
)

# Characters to convert to a regular space.
_BIDI_TO_SPACE = (
    "\u00a0", "\u202f", "\u2007", "\u2009",
)

_WS_RUN = re.compile(r"\s+")


def clean_text(value: object) -> Optional[str]:
    """
    Unescape HTML entities, strip bidi/zero-width characters, collapse
    whitespace, and return None for empty results.
    """
    if not isinstance(value, str):
        return None
    s = html_module.unescape(value)
    for ch in _BIDI_DELETE:
        s = s.replace(ch, "")
    for ch in _BIDI_TO_SPACE:
        s = s.replace(ch, " ")
    s = _WS_RUN.sub(" ", s).strip()
    return s if s else None