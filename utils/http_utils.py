"""
HTTP helpers shared across OTA clients.
"""
from __future__ import annotations

import time
from typing import Any, Dict, Optional, cast

import httpx

from utils.logging_utils import get_logger

logger = get_logger(__name__)


DEFAULT_MIN_RESPONSE_BYTES: int = 50_000
RETRYABLE_STATUSES: frozenset[int] = frozenset({202, 429, 503})
DEFAULT_RETRY_DELAY_SECONDS: float = 1.5


def build_client(
    headers: Dict[str, str],
    timeout: float = 15.0,
) -> httpx.Client:
    return httpx.Client(
        timeout=timeout,
        headers=headers,
        follow_redirects=True,
    )


def should_retry(status_code: int, body_len: int, min_bytes: int) -> bool:
    if status_code in RETRYABLE_STATUSES:
        return True
    if 200 <= status_code < 300 and body_len < min_bytes:
        return True
    return False


def looks_like_challenge(
    status_code: int,
    body_len: int,
    min_bytes: int,
) -> bool:
    if not (200 <= status_code < 300):
        return True
    return body_len < min_bytes


def sleep_before_retry(seconds: float = DEFAULT_RETRY_DELAY_SECONDS) -> None:
    time.sleep(seconds)


def curl_cffi_available() -> bool:
    try:
        import curl_cffi  # noqa: F401  # type: ignore[import-not-found]
        return True
    except ImportError:
        return False


def get_curl_cffi() -> Optional[Any]:
    try:
        from curl_cffi import requests  # type: ignore[import-not-found]
    except ImportError:
        return None
    return cast(Any, requests)


def default_impersonate_profile() -> str:
    """Fallback Chrome profile for curl_cffi when a client has none set."""
    return "chrome120"