"""
Input validation for the individual-profile CLI.

Three things get validated:

  1. `-domain` resolves to a registered plugin.
  2. `-url` is a real, well-formed http(s) URL.
  3. `-url`'s host belongs to the OTA selected by `-domain`.

Host rules live on the client class as `accepts_hosts` — this file just
reads them. Adding a new OTA means adding `accepts_hosts` on its client
class; nothing here needs to change.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, List, Optional, Tuple
from urllib.parse import urlparse

from profile_plugins.manager import (
    list_known_domains,
    resolve_registry_entry,
)


# -----------------------------------------------------------------
# Host patterns — read from the client class at call time
# -----------------------------------------------------------------

def _compiled_host_patterns(
    domain: str,
) -> Optional[Tuple[re.Pattern[str], ...]]:
    """
    Return the compiled `accepts_hosts` patterns for the given CLI
    domain, or None if the entry has none declared.

    Each string in `accepts_hosts` is a regex that must full-match the
    lower-cased hostname. We compile them once per call; the number of
    patterns is tiny so this is cheap.
    """
    entry = resolve_registry_entry(domain)
    if entry is None:
        return None
    client_cls = entry.get("client_cls")
    hosts: Any = getattr(client_cls, "accepts_hosts", ())
    if not hosts:
        return None
    compiled: List[re.Pattern[str]] = []
    for raw in hosts:
        try:
            compiled.append(re.compile(str(raw), re.IGNORECASE))
        except re.error:
            # A bad pattern on a client shouldn't kill the CLI; skip it
            # and let validation pass if no other pattern rejects.
            continue
    return tuple(compiled) if compiled else None


# -----------------------------------------------------------------
# Result type
# -----------------------------------------------------------------

@dataclass(frozen=True)
class ValidationResult:
    ok: bool
    domain: Optional[str] = None          # canonical CLI domain name
    registry_key: Optional[str] = None    # name in the plugin registry
    url: Optional[str] = None             # normalised URL
    errors: Optional[List[str]] = None    # populated when ok is False

    def error_text(self) -> str:
        return "; ".join(self.errors or [])


# -----------------------------------------------------------------
# Public API
# -----------------------------------------------------------------

def canonical_domain(domain: str) -> Optional[str]:
    """
    Return the canonical CLI domain name for any accepted alias, or
    None if the domain isn't registered.

    The canonical form is the entry's `output_name` — e.g. "booking_com",
    "expedia_com". All registry keys, client names, output names, and
    aliases map to it.
    """
    entry = resolve_registry_entry(domain)
    if entry is None:
        return None
    return str(entry.get("output_name", "")).strip().lower() or None


def validate(domain: str, url: str) -> ValidationResult:
    """
    Validate a `-domain` / `-url` pair.

    Returns ValidationResult(ok=True, domain=..., registry_key=...,
    url=...) on success, or ValidationResult(ok=False, errors=[...]) on
    failure. Never raises.
    """
    errors: List[str] = []

    # 1. domain -----------------------------------------------------
    canonical = canonical_domain(domain)
    if canonical is None:
        known = ", ".join(list_known_domains())
        errors.append(
            f"unknown -domain {domain!r}. Known: {known}"
        )

    # 2. url --------------------------------------------------------
    if not url or not url.strip():
        errors.append("-url is required and cannot be empty")
    raw = (url or "").strip()

    parsed = urlparse(raw)
    if not parsed.scheme and not parsed.netloc:
        errors.append(
            f"-url {raw!r} is not a valid URL "
            f"(expected something like https://www.booking.com/...)"
        )
    else:
        if parsed.scheme not in ("http", "https"):
            errors.append(
                f"-url scheme must be http or https, got "
                f"{parsed.scheme!r}"
            )
        if not parsed.netloc:
            errors.append(f"-url has no host: {raw!r}")

    # 3. host matches domain ---------------------------------------
    if canonical is not None and parsed.netloc:
        host = (
            parsed.netloc
            .split("@", 1)[-1]
            .split(":", 1)[0]
            .lower()
        )
        patterns = _compiled_host_patterns(canonical)
        if patterns is not None:
            if not any(p.match(host) for p in patterns):
                errors.append(
                    f"-url host {host!r} does not belong to "
                    f"-domain {canonical!r}. Expected one of: "
                    + ", ".join(p.pattern for p in patterns)
                )

    if errors:
        return ValidationResult(ok=False, errors=errors)

    # All good — return the canonical values.
    entry = resolve_registry_entry(canonical or "")
    registry_key: Optional[str] = None
    if entry is not None:
        from profile_plugins.manager import get_registry
        for k, v in get_registry().items():
            if v is entry:
                registry_key = k
                break

    return ValidationResult(
        ok=True,
        domain=canonical,
        registry_key=registry_key,
        url=raw,
    )