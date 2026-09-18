"""Tripadvisor OTA client.

Tripadvisor serves three URL shapes for a hotel:

  * `/Hotel_Review-<loc>-<prop>-Reviews-<slug>.html` — full SSR page
    with `<h1 id="HEADING">` and the LodgingBusiness JSON-LD block.

  * `/HotelHighlight-<loc>-<prop>-Reviews-<slug>.html` — same path
    shape, but a *stripped* template. No LodgingBusiness JSON-LD, no
    HEADING block. Only chrome (Organization, WebSite, BreadcrumbList).

  * `/HotelHighlight?detail=<prop>&...` — query-string shell. Redirects
    to the `HotelHighlight-<...>.html` form above (also stripped).

The `Hotel_Review-` prefix always yields the full page. We normalize
every incoming URL to that prefix before fetching.
"""
from __future__ import annotations

import re
from pathlib import Path
from typing import Optional

from profile_plugins.base_client import BaseOtaClient
from utils.logging_utils import get_logger

logger = get_logger(__name__)


class TripadvisorClient(BaseOtaClient):
    name = "tripadvisor_com"

    impersonate_tls = "chrome120"

    accepts_hosts = (
        r'^(?:www\.)?tripadvisor\.com$',
        r'^(?:www\.)?tripadvisor\.(?:co\.uk|co\.jp|com\.au|com\.br|com\.mx|com\.ar|com\.cl|com\.pe|com\.co|ca|ie)$',
        r'^(?:www\.)?tripadvisor\.[a-z]{2}$',
    )

    min_response_bytes = 100_000

    curl_file = str(
        Path(__file__).resolve().parents[1]
        / "curl_sessions"
        / "tripadvisor_com.curl"
    )

    session_expired_markers = (
        "px-captcha",
        "are you a robot",
        "access denied",
        "unusual traffic",
    )

    # Match `/HotelHighlight-` or `/Hotel_Review-` immediately after the
    # leading path segment. Rewrite HotelHighlight to Hotel_Review.
    _RE_HIGHLIGHT_PATH = re.compile(
        r'(/HotelHighlight)(-g\d+-d\d+-Reviews-)',
    )

    # Extract canonical URL from the page head.
    _RE_CANONICAL = re.compile(
        r'<link\s+rel="canonical"\s+href="([^"]+)"',
        re.IGNORECASE,
    )

    # A canonical hotel page path contains "-gNNN-dNNN-Reviews-".
    _RE_CANONICAL_HOTEL = re.compile(r'-g\d+-d\d+-Reviews-')

    def normalize_url(self, raw_deeplink: str) -> str:
        url = raw_deeplink.strip()
        if not url:
            return url

        # Case 1: we already have the full slug path — just swap the
        # prefix from HotelHighlight- to Hotel_Review-.
        new_url, n = self._RE_HIGHLIGHT_PATH.subn(
            r'/Hotel_Review\2', url,
        )
        if n:
            logger.info(
                "%s: rewrote HotelHighlight path to Hotel_Review: %s -> %s",
                self.name, url, new_url,
            )
            return new_url

        return url

    def fetch(self, raw_deeplink: str) -> Optional[str]:
        """
        Fetch the property page.

        Two-fetch upgrade when the incoming URL is a query-string shell:
          1. Fetch the shell.
          2. Read its canonical URL (which has the HotelHighlight- path).
          3. Rewrite that to Hotel_Review- and fetch again.
        """
        url = self.normalize_url(raw_deeplink)
        html = super().fetch(url)
        if html is None:
            return None

        # If we're already on a full-slug path, we have everything.
        if self._RE_CANONICAL_HOTEL.search(url):
            return html

        # Shell case: read the canonical URL from the response and
        # refetch it in the Hotel_Review- form.
        canonical = self._extract_canonical(html)
        if canonical is None:
            return html
        if not self._RE_CANONICAL_HOTEL.search(canonical):
            return html

        review_url, n = self._RE_HIGHLIGHT_PATH.subn(
            r'/Hotel_Review\2', canonical,
        )
        if not n:
            # Canonical is already Hotel_Review- or otherwise unexpected.
            review_url = canonical

        logger.info(
            "%s: shell detected — refetching canonical Hotel_Review URL %s",
            self.name, review_url,
        )
        review_html = super().fetch(review_url)
        if review_html is None:
            logger.warning(
                "%s: canonical refetch failed, using original shell",
                self.name,
            )
            return html
        return review_html

    def _extract_canonical(self, html: str) -> Optional[str]:
        m = self._RE_CANONICAL.search(html)
        if not m:
            return None
        url = m.group(1).strip()
        return url or None