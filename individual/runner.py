"""
Drive one client + parser pair against a single URL.

This is the individual-profile equivalent of
`PluginManager._process_one`, minus the Google-profile bookkeeping.

Domain lookup is registry-driven: adding a new OTA does NOT require
touching this file. The registry entry itself carries the aliases and
the client class carries the host patterns.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, Type

from profile_plugins.base_client import BaseOtaClient
from profile_plugins.base_parser import BaseOtaParser
from profile_plugins.manager import (
    list_known_domains,
    resolve_registry_entry,
)
from utils.jsonl_utils import append_jsonl
from utils.logging_utils import get_logger

logger = get_logger(__name__)


@dataclass
class RunResult:
    ok: bool
    output_path: Optional[Path]
    parsed: Optional[Dict[str, Any]]
    reason: Optional[str] = None


def run_single(
    *,
    url: str,
    domain: str,
    output_dir: str = "./sub_profiles",
    timeout: float = 15.0,
    property_name: Optional[str] = None,
) -> RunResult:
    """
    Fetch `url` using the client registered for `domain`, parse it, and
    append the resulting dict to <output_dir>/<output_name>.jsonl.

    Returns a RunResult describing what happened. Never raises for
    expected failures (fetch None, parser error) — those become
    RunResult(ok=False, reason=...).
    """
    entry = resolve_registry_entry(domain)
    if entry is None:
        return RunResult(
            ok=False,
            output_path=None,
            parsed=None,
            reason=(
                f"unknown domain {domain!r}. "
                f"Known: {', '.join(list_known_domains())}"
            ),
        )

    client_cls: Type[BaseOtaClient] = entry["client_cls"]
    parser_cls: Type[BaseOtaParser] = entry["parser_cls"]
    output_name: str = entry["output_name"]

    out_dir = Path(output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / f"{output_name}.jsonl"

    logger.info(
        "individual: domain=%s output=%s url=%s",
        domain, out_path, url,
    )

    client: BaseOtaClient = client_cls(timeout=timeout)
    parser: BaseOtaParser = parser_cls()

    # ---- primary fetch ----
    html: Optional[str] = client.fetch(url)
    if html is None:
        logger.warning("individual: primary fetch returned None")
        return RunResult(
            ok=False, output_path=None, parsed=None,
            reason="primary fetch returned None",
        )

    # ---- parse ----
    try:
        parsed: Dict[str, Any] = parser.parse(html, url)
    except Exception as exc:  # noqa: BLE001
        logger.exception("individual: parser raised")
        return RunResult(
            ok=False, output_path=None, parsed=None,
            reason=f"parser raised: {type(exc).__name__}: {exc}",
        )

    # ---- follow-ups ----
    follow_ups: List[str] = parser.follow_up_urls(parsed)
    logger.info(
        "individual: %d follow-up URL(s) scheduled", len(follow_ups)
    )

    for follow_url in follow_ups:
        logger.info("individual: fetching follow-up %s", follow_url)
        follow_html: Optional[str] = client.fetch(follow_url)
        if follow_html is None:
            logger.warning(
                "individual: follow-up fetch failed for %s", follow_url,
            )
            parsed["_follow_up_status"] = "failed"
            continue
        try:
            parser.merge_follow_up(parsed, follow_url, follow_html)
            parsed["_follow_up_status"] = "ok"
        except Exception:  # noqa: BLE001
            logger.exception(
                "individual: merge_follow_up raised for %s", follow_url,
            )
            parsed["_follow_up_status"] = "merge_error"

    if not follow_ups:
        parsed["_follow_up_status"] = "not_scheduled"

    # ---- provenance ----
    # The wildcard path sets `_property_name` from the Google profile.
    # In the individual path we don't have that, so:
    #   1) prefer an explicit CLI --name,
    #   2) else use whatever the parser managed to derive,
    #   3) else fall back to the URL.
    if property_name:
        resolved_name = property_name
    else:
        resolved_name = (
            parsed.get("expedia_property_name")
            or parsed.get("trip_property_name")
            or parsed.get("agoda_property_name")
            or parsed.get("booking_property_name")
            or parsed.get("title")
            or url
        )
    parsed["_property_name"] = resolved_name
    parsed["_provider_name"] = domain
    parsed["_provider_logo_url"] = None
    parsed["_source"] = "individual_cli"

    append_jsonl(out_path, parsed)
    logger.info("individual: wrote one row to %s", out_path)

    return RunResult(ok=True, output_path=out_path, parsed=parsed)