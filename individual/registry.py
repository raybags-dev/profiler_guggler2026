"""
Registry lookup helpers for the individual-profile CLI.

Both `runner.py` (which needs a client + parser pair to fetch + parse)
and `validator.py` (which needs the client class to read its
`accepts_hosts`) need to resolve a CLI domain to a registry entry.
Putting that resolution in one place keeps the two modules decoupled
from each other.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from profile_plugins.manager import get_registry


def _entry_aliases(entry: Dict[str, Any]) -> set[str]:
    """
    Return every lowercase string a user might type for this entry.

    Derived from the entry's `output_name`, the client class's `name`
    attribute, and the entry's `aliases` tuple.
    """
    aliases: set[str] = set()

    aliases.add(str(entry.get("output_name", "")).strip().lower())

    client_cls = entry.get("client_cls")
    if client_cls is not None:
        aliases.add(str(getattr(client_cls, "name", "")).strip().lower())

    for a in entry.get("aliases", ()):  # type: ignore[arg-type]
        aliases.add(str(a).strip().lower())

    aliases.discard("")
    return aliases


def resolve_registry_entry(domain: str) -> Optional[Dict[str, Any]]:
    """
    Find a registry entry by CLI domain name.

    Matches against, in case-insensitive order:
      - the registry key itself (e.g. "Booking.com"),
      - the entry's `output_name` (e.g. "booking_com"),
      - the client class's `name` attribute,
      - the entry's `aliases` tuple if present.

    Adding a new OTA to the registry makes it resolvable here without
    any change to this file.
    """
    needle = (domain or "").strip().lower()
    if not needle:
        return None

    for key, entry in get_registry().items():
        candidates = _entry_aliases(entry)
        candidates.add(key.strip().lower())
        if needle in candidates:
            return entry
    return None


def list_known_domains() -> List[str]:
    """
    Return every CLI-accepted domain name (for -h and error messages).

    Includes registry keys, output names, client names, and aliases.
    """
    out: set[str] = set()
    for key, entry in get_registry().items():
        out.add(key.strip().lower())
        out.update(_entry_aliases(entry))
    out.discard("")
    return sorted(out)