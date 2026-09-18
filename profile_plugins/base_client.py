"""
Base HTTP client for OTA plugins.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any, Dict, Optional, Tuple, cast

import httpx

from profile_plugins.curl_parser import PluginCurlParser, CurlSession
from utils.http_utils import (
    DEFAULT_MIN_RESPONSE_BYTES,
    build_client,
    curl_cffi_available,
    default_impersonate_profile,
    get_curl_cffi,
    looks_like_challenge,
    should_retry,
    sleep_before_retry,
)
from utils.logging_utils import get_logger
from utils.session_utils import SessionExpiryTracker, contains_any_marker

logger = get_logger(__name__)


class BaseOtaClient(ABC):
    """Base class for all OTA HTTP clients."""

    name: str = "base"
    accepts_hosts: tuple[str, ...] = ()

    extra_headers: Dict[str, str] = {}
    curl_file: Optional[str] = None
    min_response_bytes: int = DEFAULT_MIN_RESPONSE_BYTES
    session_expired_markers: tuple[str, ...] = ()
    flag_dir: Path = Path("./sub_profiles")
    impersonate_tls: Optional[str] = None

    def __init__(
        self,
        timeout: float = 15.0,
        user_agent: Optional[str] = None,
        curl_file: Optional[str] = None,
    ) -> None:
        self.timeout: float = timeout
        self.user_agent: str = user_agent or (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/120.0.0.0 Safari/537.36"
        )

        headers: Dict[str, str] = {
            "user-agent": self.user_agent,
            "accept": (
                "text/html,application/xhtml+xml,application/xml;q=0.9,"
                "image/avif,image/webp,*/*;q=0.8"
            ),
            "accept-language": "en-US,en;q=0.9",
            "upgrade-insecure-requests": "1",
            "sec-fetch-dest": "document",
            "sec-fetch-mode": "navigate",
            "sec-fetch-site": "none",
            "sec-fetch-user": "?1",
            "cache-control": "no-cache",
            "pragma": "no-cache",
        }
        headers.update(self.extra_headers)
        self.headers: Dict[str, str] = headers

        self.cookies: Dict[str, str] = {}

        curl_path: Optional[str] = curl_file or self.curl_file
        if curl_path:
            self._load_curl_session(curl_path)

        if self.impersonate_tls and not curl_cffi_available():
            logger.warning(
                "%s: impersonate_tls=%r set but curl_cffi is not "
                "installed. Install with: pip install curl_cffi. "
                "Falling back to httpx (may be blocked by the WAF).",
                self.name, self.impersonate_tls,
            )

        self._expiry: SessionExpiryTracker = SessionExpiryTracker(
            client_name=self.name,
            flag_dir=self.flag_dir,
        )

    def _load_curl_session(self, curl_path: str) -> None:
        path = Path(curl_path)
        if not path.is_file():
            logger.warning(
                "%s: curl file not found: %s", self.name, curl_path
            )
            return

        try:
            curl: CurlSession = PluginCurlParser.parse(str(path))
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "%s: failed to parse curl file %s: %s",
                self.name, curl_path, exc,
            )
            return

        merged: Dict[str, str] = {
            k.lower(): v for k, v in self.headers.items()
        }
        for k, v in curl.headers.items():
            merged[k.lower()] = v
        self.headers = merged

        self.cookies = dict(curl.cookies)

        logger.info(
            "%s: loaded curl session — %d headers, %d cookies",
            self.name, len(self.headers), len(self.cookies),
        )

    @abstractmethod
    def normalize_url(self, raw_deeplink: str) -> str:
        raise NotImplementedError

    def warm_up(self, client: Any) -> None:
        return None

    def _headers_and_cookies_for_url(
        self,
        url: str,
    ) -> Tuple[Dict[str, str], Dict[str, str]]:
        """
        Return (headers, cookies) to use for this request.

        Default: whatever was loaded in __init__. Subclasses may
        override to pick a different session per URL host — useful
        for OTAs whose sessions are domain-scoped (Expedia, Tripadvisor).
        """
        return self.headers, self.cookies

    def fetch(self, raw_deeplink: str) -> Optional[str]:
        url: str = self.normalize_url(raw_deeplink)
        if not url:
            logger.warning("%s: could not normalize deeplink", self.name)
            return None

        base_headers, cookies = self._headers_and_cookies_for_url(url)

        headers_for_request: Dict[str, str] = dict(base_headers)
        if cookies:
            cookie_header: str = "; ".join(
                f"{k}={v}" for k, v in cookies.items()
            )
            headers_for_request["cookie"] = cookie_header
            logger.debug(
                "%s: sending %d cookies via raw Cookie header",
                self.name, len(cookies),
            )

        resp: Any = self._do_get(url, headers_for_request)
        if resp is None:
            return None

        status = int(resp.status_code)
        text = str(resp.text or "")
        final_url = getattr(resp, "url", url)

        if should_retry(status, len(text), self.min_response_bytes):
            logger.info(
                "%s: status=%d len=%d — retrying once after 1.5s",
                self.name, status, len(text),
            )
            sleep_before_retry()
            retried = self._do_get(url, headers_for_request)
            if retried is not None:
                resp = retried
                status = int(resp.status_code)
                text = str(resp.text or "")
                final_url = getattr(resp, "url", url)

        if looks_like_challenge(status, len(text), self.min_response_bytes):
            if contains_any_marker(text, self.session_expired_markers):
                logger.warning(
                    "%s: session appears expired (status=%d, "
                    "len=%d) for %s",
                    self.name, status, len(text), url,
                )
                self._expiry.record_expiry()
            else:
                logger.warning(
                    "%s: rejected response (status=%d, len=%d) "
                    "for %s (final=%s) — likely a challenge page. "
                    "body=%r",
                    self.name, status, len(text),
                    url, final_url, text[:300],
                )
            return None

        self._expiry.record_success()
        logger.info(
            "%s: fetched %s (%d bytes, final=%s)",
            self.name, url, len(text), final_url,
        )
        return text

    def _do_get(
        self,
        url: str,
        headers: Dict[str, str],
    ) -> Optional[Any]:
        """
        Primary transport:
          - curl_cffi if `impersonate_tls` is set (Tripadvisor)
          - httpx otherwise (Booking, Agoda, Trip, Expedia)

        Fallback transport:
          - on 403 (TLS fingerprint block), re-issue via curl_cffi with
            a Chrome profile if curl_cffi is available.

          429 is NOT retried via the fallback: curl_cffi cannot bypass
          an IP-level rate limit, and every extra request extends the
          block.
        """
        if self.impersonate_tls and curl_cffi_available():
            return self._do_get_curl_cffi(url, headers)

        resp = self._do_get_httpx(url, headers)
        if resp is None:
            return None

        if resp.status_code == 403 and curl_cffi_available():
            logger.info(
                "%s: httpx got 403 — retrying via curl_cffi",
                self.name,
            )
            profile = (
                self.impersonate_tls or default_impersonate_profile()
            )
            alt = self._do_get_curl_cffi(
                url, headers, profile=profile,
            )
            if alt is not None and 200 <= alt.status_code < 300:
                logger.info(
                    "%s: curl_cffi fallback succeeded (status=%d)",
                    self.name, alt.status_code,
                )
                return alt
            logger.info(
                "%s: curl_cffi fallback also blocked (status=%s)",
                self.name,
                alt.status_code if alt is not None else "None",
            )
        return resp

    def _do_get_httpx(
        self,
        url: str,
        headers: Dict[str, str],
    ) -> Optional[httpx.Response]:
        try:
            with build_client(headers, self.timeout) as client:
                self.warm_up(client)
                return client.get(url)
        except httpx.HTTPError as exc:
            logger.warning(
                "%s: fetch raised %s for %s",
                self.name, type(exc).__name__, url,
            )
            logger.warning(
                "%s: exception detail: %r", self.name, exc,
            )
            return None

    def _do_get_curl_cffi(
        self,
        url: str,
        headers: Dict[str, str],
        profile: Optional[str] = None,
    ) -> Optional[Any]:
        cc = get_curl_cffi()
        if cc is None:
            logger.warning(
                "%s: curl_cffi not available at call time; "
                "falling back to httpx", self.name,
            )
            return self._do_get_httpx(url, headers)

        effective_profile = profile or self.impersonate_tls
        try:
            session = cc.Session(
                impersonate=cast(Any, effective_profile),
                timeout=self.timeout,
            )
            session.headers.update(headers)
            return session.get(url, allow_redirects=True)
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "%s: curl_cffi fetch raised %s for %s",
                self.name, type(exc).__name__, url,
            )
            logger.warning(
                "%s: curl_cffi detail: %r", self.name, exc,
            )
            return None