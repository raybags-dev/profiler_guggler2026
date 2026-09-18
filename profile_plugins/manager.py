"""
PluginManager: consumes the `providers` array from a Google profile and
dispatches each deeplink to the matching plugin.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List, Optional, Type

from profile_plugins.base_client import BaseOtaClient
from profile_plugins.base_parser import BaseOtaParser
from utils.jsonl_utils import append_jsonl
from utils.logging_utils import get_logger

logger = get_logger(__name__)

_registry_cache: Optional[Dict[str, Dict[str, Any]]] = None


def _build_registry() -> Dict[str, Dict[str, Any]]:
    registry: Dict[str, Dict[str, Any]] = {}

    # --- Booking.com ---
    try:
        from profile_plugins.shared_client.booking_client import BookingClient
        from profile_plugins.plugin_parsers.booking_parser import BookingParser

        registry["Booking.com"] = {
            "client_cls": BookingClient,
            "parser_cls": BookingParser,
            "output_name": "booking_com",
            "aliases": ("booking", "booking.com"),
        }
    except ImportError:
        logger.debug("Booking.com plugin not installed")

    # --- Agoda ---
    try:
        from profile_plugins.shared_client.agoda_client import AgodaClient
        from profile_plugins.plugin_parsers.agoda_parser import AgodaParser

        registry["Agoda"] = {
            "client_cls": AgodaClient,
            "parser_cls": AgodaParser,
            "output_name": "agoda",
            "aliases": ("agoda", "agoda.com"),
        }
    except ImportError:
        logger.debug("Agoda plugin not installed")

    # --- Trip.com ---
    try:
        from profile_plugins.shared_client.trip_client import TripClient
        from profile_plugins.plugin_parsers.trip_parser import TripParser

        registry["Trip.com"] = {
            "client_cls": TripClient,
            "parser_cls": TripParser,
            "output_name": "trip_com",
            "aliases": ("trip", "trip.com"),
        }
    except ImportError:
        logger.debug("Trip.com plugin not installed")

    # --- Expedia.com ---
    try:
        from profile_plugins.shared_client.expedia_client import ExpediaClient
        from profile_plugins.plugin_parsers.expedia_parser import ExpediaParser

        registry["Expedia.com"] = {
            "client_cls": ExpediaClient,
            "parser_cls": ExpediaParser,
            "output_name": "expedia_com",
            "aliases": ("expedia", "expedia.nl", "expedia.com"),
        }
    except ImportError:
        logger.debug("Expedia.com plugin not installed")

    # --- Tripadvisor ---
    try:
        from profile_plugins.shared_client.tripadvisor_client import TripadvisorClient
        from profile_plugins.plugin_parsers.tripadvisor_parser import TripadvisorParser

        registry["Tripadvisor"] = {
            "client_cls": TripadvisorClient,
            "parser_cls": TripadvisorParser,
            "output_name": "tripadvisor_com",
            "aliases": ("tripadvisor", "tripadvisor.com"),
        }
    except ImportError:
        logger.debug("Tripadvisor plugin not installed")

    return registry


def get_registry() -> Dict[str, Dict[str, Any]]:
    global _registry_cache
    if _registry_cache is None:
        _registry_cache = _build_registry()
    return _registry_cache


def get_registry_entry(name: str) -> Optional[Dict[str, Any]]:
    return get_registry().get(name)


def list_registered_providers() -> List[str]:
    return sorted(get_registry().keys())


def _entry_aliases(entry: Dict[str, Any]) -> set[str]:
    aliases: set[str] = set()
    aliases.add(str(entry.get("output_name", "")).strip().lower())
    client_cls = entry.get("client_cls")
    if client_cls is not None:
        aliases.add(str(getattr(client_cls, "name", "")).strip().lower())
    for a in entry.get("aliases", ()):  # type: ignore[arg-type]
        aliases.add(str(a).strip().lower())
    aliases.discard("")
    return aliases


def resolve_registry_entry(name: str) -> Optional[Dict[str, Any]]:
    needle = (name or "").strip().lower()
    if not needle:
        return None
    base = needle.split(".", 1)[0]
    for key, entry in get_registry().items():
        candidates = _entry_aliases(entry)
        candidates.add(key.strip().lower())
        if needle in candidates or base in candidates:
            return entry
    return None


def list_known_domains() -> List[str]:
    out: set[str] = set()
    for key, entry in get_registry().items():
        out.add(key.strip().lower())
        out.update(_entry_aliases(entry))
    out.discard("")
    return sorted(out)


class PluginManager:
    """Dispatch each provider deeplink to its plugin; write parsed JSONL."""

    def __init__(
        self,
        output_dir: str = "./sub_profiles",
        timeout: float = 15.0,
    ) -> None:
        self.output_dir: Path = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.timeout: float = timeout
        self.registry: Dict[str, Dict[str, Any]] = get_registry()

    @property
    def output_path(self) -> Path:
        return self.output_dir

    def process_profile(self, profile: Dict[str, Any]) -> Dict[str, int]:
        providers: List[Dict[str, Any]] = profile.get("providers") or []
        stats: Dict[str, int] = {
            "dispatched": 0,
            "fetched": 0,
            "parsed": 0,
            "skipped": 0,
            "failed": 0,
        }

        property_name: str = profile.get("property_name") or "unknown"

        provider: Dict[str, Any]
        for provider in providers:
            name: str = str(provider.get("name") or "").strip()
            deeplink: str = str(provider.get("deeplink") or "").strip()

            if not name or not deeplink:
                stats["skipped"] += 1
                continue

            entry: Optional[Dict[str, Any]] = resolve_registry_entry(name)
            if entry is None:
                logger.info(
                    "PluginManager: no plugin for %r (have: %s)",
                    name, ", ".join(list_registered_providers()),
                )
                stats["skipped"] += 1
                continue

            stats["dispatched"] += 1
            self._process_one(
                provider=provider,
                entry=entry,
                property_name=property_name,
                stats=stats,
            )

        logger.info(
            "PluginManager: property=%r dispatched=%d fetched=%d parsed=%d "
            "skipped=%d failed=%d",
            property_name,
            stats["dispatched"],
            stats["fetched"],
            stats["parsed"],
            stats["skipped"],
            stats["failed"],
        )
        return stats

    def _process_one(
        self,
        provider: Dict[str, Any],
        entry: Dict[str, Any],
        property_name: str,
        stats: Dict[str, int],
    ) -> None:
        client_cls: Type[BaseOtaClient] = entry["client_cls"]
        parser_cls: Type[BaseOtaParser] = entry["parser_cls"]
        output_name: str = entry["output_name"]

        client: BaseOtaClient = client_cls(timeout=self.timeout)
        parser: BaseOtaParser = parser_cls()

        deeplink: str = str(provider.get("deeplink") or "")
        html: Optional[str] = client.fetch(deeplink)
        if html is None:
            logger.warning(
                "%s: primary fetch returned None for %s",
                output_name, deeplink,
            )
            stats["failed"] += 1
            return
        stats["fetched"] += 1

        try:
            parsed: Dict[str, Any] = parser.parse(html, deeplink)
        except Exception:  # noqa: BLE001
            logger.exception(
                "%s: parser raised for %s", output_name, deeplink
            )
            stats["failed"] += 1
            return

        follow_ups: List[str] = parser.follow_up_urls(parsed)
        logger.info(
            "%s: %d follow-up URL(s) scheduled for %r",
            output_name, len(follow_ups), property_name,
        )

        follow_url: str
        for follow_url in follow_ups:
            logger.info(
                "%s: fetching follow-up %s", output_name, follow_url
            )
            follow_html: Optional[str] = client.fetch(follow_url)

            if follow_html is None:
                logger.warning(
                    "%s: follow-up fetch failed for %s "
                    "(property=%r, source_url=%s)",
                    output_name, follow_url, property_name,
                    parsed.get("source_url"),
                )
                parsed["_follow_up_status"] = "failed"
                continue

            logger.info(
                "%s: follow-up OK len=%d for %s",
                output_name, len(follow_html), follow_url,
            )
            try:
                parser.merge_follow_up(parsed, follow_url, follow_html)
                parsed["_follow_up_status"] = "ok"
            except Exception:  # noqa: BLE001
                logger.exception(
                    "%s: merge_follow_up raised for %s",
                    output_name, follow_url,
                )
                parsed["_follow_up_status"] = "merge_error"

        if not follow_ups:
            parsed["_follow_up_status"] = "not_scheduled"

        parsed["_property_name"] = property_name
        parsed["_provider_name"] = provider.get("name")
        parsed["_provider_logo_url"] = provider.get("logo_url")

        stats["parsed"] += 1
        append_jsonl(self.output_dir / f"{output_name}.jsonl", parsed)