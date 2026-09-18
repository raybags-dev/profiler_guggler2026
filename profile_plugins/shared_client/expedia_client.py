"""Expedia.com OTA client.

All Expedia URLs are rewritten to `www.expedia.com` before fetching, so
one captured curl (for expedia.com) works for every locale Google emits
(expedia.nl, expedia.de, expedia.co.uk, ...). The upstream deeplink is
preserved in `source_url` — only the outgoing request is rewritten.
"""
from __future__ import annotations

import re
from pathlib import Path

from profile_plugins.base_client import BaseOtaClient
from utils.logging_utils import get_logger

logger = get_logger(__name__)


class ExpediaClient(BaseOtaClient):
    name = "expedia_com"

    accepts_hosts = (
        r'^(?:www\.)?expedia\.com$',
        r'^(?:www\.)?expedia\.(?:co\.uk|co\.jp|com\.au|com\.br|com\.mx|com\.ar|com\.cl|com\.pe|com\.co)$',
        r'^(?:www\.)?expedia\.[a-z]{2}$',
    )

    min_response_bytes = 30_000

    curl_file = str(
        Path(__file__).resolve().parents[1]
        / "curl_sessions"
        / "expedia_com.curl"
    )

    session_expired_markers = (
        "are you a robot",
        "px-captcha",
        "access denied",
    )

    # Match `https?://<any-sub>expedia.<tld>` up to the next `/` or end.
    # We only rewrite the host portion; path and query are preserved.
    _RE_EXPEDIA_HOST = re.compile(
        r'^(https?://)(?:[a-z0-9-]+\.)*expedia\.[a-z.]+',
        re.IGNORECASE,
    )

    def normalize_url(self, raw_deeplink: str) -> str:
        url = raw_deeplink.strip()
        if not url:
            return url

        # Rewrite any Expedia locale host to www.expedia.com.
        def _sub(m: re.Match[str]) -> str:
            return m.group(1) + "www.expedia.com"

        rewritten = self._RE_EXPEDIA_HOST.sub(_sub, url)
        if rewritten != url:
            logger.info(
                "%s: rewrote host to expedia.com: %s -> %s",
                self.name, url, rewritten,
            )
        return rewritten


# """Expedia.com OTA client.

# Expedia ships per-locale sites with domain-scoped sessions. A curl
# captured from `expedia.com` cannot be replayed against `expedia.nl` —
# the cookies are scoped to the origin that issued them, and cross-domain
# cookie replay triggers Akamai Bot Manager's `ak_bmsc` block (observed as
# a 429 "Bot or Not?" page).

# This client loads a per-host session on demand. Each target domain gets
# its own curl file at:

#     profile_plugins/curl_sessions/expedia/<host_with_underscores>.curl

# For example:
#     www.expedia.nl     -> expedia/expedia_nl.curl
#     www.expedia.com    -> expedia/expedia_com.curl
#     www.expedia.co.uk  -> expedia/expedia_co_uk.curl

# If a domain has no curl file, the client falls back to default browser
# headers with no cookies. Some properties work that way; others will
# receive a 429 challenge.
# """
# from __future__ import annotations

# import re
# from pathlib import Path
# from typing import Dict, Optional, Tuple

# from profile_plugins.base_client import BaseOtaClient
# from profile_plugins.curl_parser import PluginCurlParser, CurlSession
# from utils.logging_utils import get_logger

# logger = get_logger(__name__)


# class ExpediaClient(BaseOtaClient):
#     name = "expedia_com"

#     accepts_hosts = (
#         r'^(?:www\.)?expedia\.[a-z]{2}$',
#         r'^(?:www\.)?expedia\.(?:co\.uk|co\.jp|com\.au|com\.br|com\.mx|com\.ar|com\.cl|com\.pe|com\.co)$',
#         r'^(?:www\.)?expedia\.com$',
#     )

#     min_response_bytes = 30_000

#     session_expired_markers = (
#         "are you a robot",
#         "px-captcha",
#         "access denied",
#     )

#     # Per-host curl files live here.
#     _curl_dir: Path = (
#         Path(__file__).resolve().parents[1]
#         / "curl_sessions"
#         / "expedia"
#     )

#     # Per-host session cache: {host: (headers, cookies)}.
#     # Class-level so it survives across client instances within one run.
#     _session_cache: Dict[str, Tuple[Dict[str, str], Dict[str, str]]] = {}

#     # No single curl_file for the whole class — resolution is per-host.
#     curl_file: Optional[str] = None

#     def normalize_url(self, raw_deeplink: str) -> str:
#         return raw_deeplink.strip()

#     # -----------------------------------------------------------------
#     # Per-host session resolution
#     # -----------------------------------------------------------------

#     @staticmethod
#     def _host_from_url(url: str) -> str:
#         m = re.match(r'https?://([^/]+)', url)
#         if not m:
#             return ""
#         return m.group(1).lower()

#     @staticmethod
#     def _curl_filename_for_host(host: str) -> str:
#         """
#         expedia.nl         -> expedia_nl.curl
#         www.expedia.com    -> expedia_com.curl
#         www.expedia.co.uk  -> expedia_co_uk.curl
#         """
#         h = host
#         if h.startswith("www."):
#             h = h[4:]
#         h = h.replace(".", "_")
#         return f"{h}.curl"

#     def _load_session_for_host(
#         self,
#         host: str,
#     ) -> Tuple[Dict[str, str], Dict[str, str]]:
#         """
#         Return (headers, cookies) for the given host.

#         Loads from `_curl_dir/<host_with_underscores>.curl` if present.
#         Falls back to default browser headers with no cookies otherwise.
#         Results are cached per host for the lifetime of the process.
#         """
#         cached = self._session_cache.get(host)
#         if cached is not None:
#             return cached

#         filename = self._curl_filename_for_host(host)
#         path = self._curl_dir / filename

#         base_headers: Dict[str, str] = dict(self.headers)
#         cookies: Dict[str, str] = {}

#         if path.is_file():
#             try:
#                 curl: CurlSession = PluginCurlParser.parse(str(path))
#                 for k, v in curl.headers.items():
#                     base_headers[k.lower()] = v
#                 cookies = dict(curl.cookies)
#                 logger.info(
#                     "%s: loaded per-host session %s "
#                     "(%d headers, %d cookies)",
#                     self.name, filename,
#                     len(base_headers), len(cookies),
#                 )
#             except Exception as exc:  # noqa: BLE001
#                 logger.warning(
#                     "%s: failed to parse %s: %s",
#                     self.name, path, exc,
#                 )
#         else:
#             logger.warning(
#                 "%s: no curl file for host %r (expected %s). "
#                 "Proceeding without session cookies.",
#                 self.name, host, path,
#             )

#         self._session_cache[host] = (base_headers, cookies)
#         return base_headers, cookies

#     def _headers_and_cookies_for_url(
#         self,
#         url: str,
#     ) -> Tuple[Dict[str, str], Dict[str, str]]:
#         host = self._host_from_url(url)
#         if not host:
#             return self.headers, self.cookies
#         headers, cookies = self._load_session_for_host(host)

#         # Rewrite the Referer so it matches the target host. Replaying
#         # a `.com` Referer against `.nl` looks like cross-domain bot
#         # activity to Akamai's bot manager.
#         ref = headers.get("referer", "")
#         if ref:
#             ref_host = self._host_from_url(ref)
#             if ref_host and ref_host != host:
#                 new_ref = f"https://{host}/"
#                 headers = dict(headers)
#                 headers["referer"] = new_ref
#                 logger.debug(
#                     "%s: rewrote referer %s -> %s (host mismatch)",
#                     self.name, ref, new_ref,
#                 )

#         return headers, cookies