"""
Fetch the Google Travel search page using a session from a curl file,
iterate over CONFIG.property_searchKeywords, and build a property profile.

The URL inside the curl file is IGNORED. Only headers + cookies are used.
"""

from __future__ import annotations
import json
import asyncio
import httpx
import logging
import traceback
from pathlib import Path
from typing import Dict, Any, List, Optional
from tenacity import retry, stop_after_attempt, wait_exponential

from configs.config import CONFIG
from curl_workers.google_profile_curl_parser import CurlParser, CurlRequest
from parser.google_profile_processor import GoogleProfileProcessor
from profile_plugins.manager import PluginManager
from utils.logging_utils import configure_logging, get_logger

configure_logging(level=logging.INFO)
logger = get_logger(__name__)


# ---------------------------------------------------------------------
# Session helper
# ---------------------------------------------------------------------
def build_session_from_curl(curl_template: CurlRequest) -> Dict[str, Any]:
    headers: Dict[str, str] = {
        k: v for k, v in curl_template.headers.items()
        if k.lower() != "cookie"
    }
    cookies: Dict[str, str] = dict(curl_template.cookies)

    headers.setdefault(
        "accept",
        "text/html,application/xhtml+xml,application/xml;q=0.9,"
        "image/avif,image/webp,*/*;q=0.8",
    )
    headers.setdefault("accept-language", "en-US,en;q=0.9")
    headers.setdefault("upgrade-insecure-requests", "1")
    headers.setdefault("sec-fetch-dest", "document")
    headers.setdefault("sec-fetch-mode", "navigate")
    headers.setdefault("sec-fetch-site", "none")
    headers.setdefault("sec-fetch-user", "?1")
    headers.setdefault("cache-control", "no-cache")
    headers.setdefault("pragma", "no-cache")

    cookies.setdefault("PREF", "hl=en&gl=US")
    cookies.setdefault("CONSENT", "YES+cb")
    cookies.setdefault("SOCS", "CAI")

    return {"headers": headers, "cookies": cookies}


# ---------------------------------------------------------------------
# Consent page detection
# ---------------------------------------------------------------------
_CONSENT_MARKERS = (
    "Before you continue",
    "consent.google.com",
    "/sorry/index",
    "detected unusual traffic",
    "Please click here if you are not redirected",
)


def is_consent_or_blocked(html: str) -> bool:
    head = html[:5000]
    return any(m.lower() in head.lower() for m in _CONSENT_MARKERS)


# ---------------------------------------------------------------------
# Client
# ---------------------------------------------------------------------
class GoogleProfileClient:
    """Uses a single session (from curl) to fetch multiple URLs."""

    def __init__(self, curl_template: CurlRequest) -> None:
        session = build_session_from_curl(curl_template)
        self.headers = session["headers"]
        self.cookies = session["cookies"]

        logger.info(
            f"Session ready: {len(self.headers)} headers, "
            f"{len(self.cookies)} cookies"
        )

        self.client = httpx.AsyncClient(
            timeout=CONFIG.timeout_seconds,
            headers=self.headers,
            cookies=self.cookies,
            follow_redirects=True,
        )

    async def close(self) -> None:
        await self.client.aclose()

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=2),
    )
    async def fetch(self, url: str) -> str:
        logger.info(f"GET {url}")
        response = await self.client.get(url)

        if is_consent_or_blocked(response.text):
            logger.warning(
                f"Consent/block page detected (HTTP {response.status_code}, "
                f"len={len(response.text)}). Retrying with ncr=1 + consent cookies."
            )
            self.client.cookies.set("CONSENT", "YES+cb")
            self.client.cookies.set("SOCS", "CAI")
            self.client.cookies.set("PREF", "hl=en&gl=US")

            sep = "&" if "?" in url else "?"
            retry_url = f"{url}{sep}ncr=1"
            logger.info(f"GET (retry) {retry_url}")
            response = await self.client.get(retry_url)

        logger.info(
            f"← HTTP {response.status_code} "
            f"len={len(response.text)} "
            f"final_url={response.url}"
        )
        response.raise_for_status()
        return response.text


# ---------------------------------------------------------------------
# Scraper
# ---------------------------------------------------------------------
class GoogleProfileScraper:

    def __init__(self) -> None:
        # Truncate once per run. Every log_* call afterwards APPENDS.
        Path(CONFIG.raw_google_page_file).write_text("", encoding="utf-8")
        Path(CONFIG.profile_output_file).write_text("", encoding="utf-8")

        logger.info(f"Loading curl: {CONFIG.curl_file}")
        self.curl_template = CurlParser.parse(CONFIG.curl_file)
        logger.info(f"Curl URL (ignored): {self.curl_template.url}")
        logger.info(
            f"Curl session: {len(self.curl_template.cookies)} cookies, "
            f"{len(self.curl_template.headers)} headers"
        )

        self.plugin_manager = PluginManager(output_dir="./sub_profiles")

        # Clear the previous run's sub-profiles
        for jsonl in self.plugin_manager.output_path.glob("*.jsonl"):
            jsonl.write_text("", encoding="utf-8")       

    def log_raw_html(self, label: str, url: str, html: str) -> None:
        """APPEND one labeled HTML capture. File is cleared once in __init__."""
        try:
            with open(CONFIG.raw_google_page_file, "a", encoding="utf-8") as f:
                f.write("=" * 80 + "\n")
                f.write(f"[{label}] {url}\n")
                f.write(f"LENGTH: {len(html)}\n")
                f.write("=" * 80 + "\n")
                f.write(html)
                f.write("\n\n" + "=" * 80 + "\n\n")
        except Exception as e:
            logger.error(f"Failed to write raw HTML: {e}")

    def log_profile(self, profile: Dict[str, Any]) -> None:
        """APPEND one JSON profile per line (JSONL). File is cleared once in __init__."""
        try:
            with open(CONFIG.profile_output_file, "a", encoding="utf-8") as f:
                f.write(json.dumps(profile, ensure_ascii=False) + "\n")
        except Exception as e:
            logger.error(f"Failed to write profile: {e}")

    # -----------------------------------------------------------------
    # Per-keyword pipeline
    # -----------------------------------------------------------------

    async def process_keyword(
        self, client: GoogleProfileClient, keyword: str, idx: int, total: int
    ) -> None:
        logger.info(f"[{idx}/{total}] Keyword: {keyword!r}")

        # ---- Fetch the /travel/search page and build the profile ----
        travel_url = CONFIG.build_travel_url(keyword)
        try:
            travel_html = await client.fetch(travel_url)
        except Exception as e:
            logger.error(f"Travel fetch FAILED: {type(e).__name__}: {e}")
            return

        if not travel_html or len(travel_html) < 500:
            logger.error(f"Travel response too short ({len(travel_html)} bytes).")
            return

        self.log_raw_html("travel", travel_url, travel_html)

        if is_consent_or_blocked(travel_html):
            logger.error(f"STILL getting consent/block page for {travel_url}.")
            return

        try:
            processor = GoogleProfileProcessor(travel_html, travel_url)
            profile = processor.build_profile()
        except Exception as e:
            logger.error(f"Parse FAILED: {type(e).__name__}: {e}")
            logger.debug(traceback.format_exc())
            return

        # Store both URLs as provenance. property_search_url is constructed but
        # NOT fetched — kept for traceability of which keyword produced this profile.
        profile["search_keyword"] = keyword
        profile["property_search_url"] = CONFIG.build_search_url(keyword)
        profile["travel_url"] = travel_url

        has_name: bool = bool(profile.get("property_name"))
        has_rooms: bool = bool(profile.get("room_rates"))
        has_otas: bool = bool(profile.get("ota_targets"))
        has_providers: bool = bool(profile.get("providers"))

        if not (has_name or has_rooms or has_otas or has_providers):
            logger.warning(f"Parser returned truly EMPTY profile for {keyword!r}.")
            return

        self.log_profile(profile)
        logger.info(
            f"✓ '{profile.get('property_name')}' "
            f"rating={profile.get('rating')} "
            f"reviews={profile.get('review_count')} "
            f"rooms={len(profile.get('room_rates') or [])} "
            f"providers={len(profile.get('providers') or [])} "
            f"otas={len(profile.get('ota_targets') or [])}"
        )

        try:
            stats: Dict[str, int] = self.plugin_manager.process_profile(profile)
        except Exception as exc:
            logger.exception("PluginManager failed for %r: %s", keyword, exc)
        else:
            logger.info(
                "Sub-profiles: dispatched=%d fetched=%d parsed=%d skipped=%d failed=%d",
                stats["dispatched"], stats["fetched"], stats["parsed"],
                stats["skipped"], stats["failed"],
            )

    # -----------------------------------------------------------------
    # Main
    # -----------------------------------------------------------------

    async def run(self, keywords: Optional[List[str]] = None) -> None:
        target_keywords: List[str] = keywords or CONFIG.property_searchKeywords
        logger.info(f"Target keywords ({len(target_keywords)}): {target_keywords}")

        if not target_keywords:
            logger.warning("No keywords configured in CONFIG.property_searchKeywords.")
            return

        client = GoogleProfileClient(self.curl_template)

        try:
            for idx, kw in enumerate(target_keywords, 1):
                await self.process_keyword(client, kw, idx, len(target_keywords))
                if idx < len(target_keywords):
                    await asyncio.sleep(CONFIG.delay_between_requests)
        finally:
            await client.close()
            logger.info("Client closed.")


async def main() -> None:
    scraper = GoogleProfileScraper()
    await scraper.run()


if __name__ == "__main__":
    asyncio.run(main())


#     asyncio.run(main())