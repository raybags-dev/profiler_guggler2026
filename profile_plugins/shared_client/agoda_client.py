"""Agoda.com OTA client."""
from __future__ import annotations

from pathlib import Path

from profile_plugins.base_client import BaseOtaClient


class AgodaClient(BaseOtaClient):
    name = "agoda_com"
    accepts_hosts = (r'^(?:www\.)?agoda\.com$',)
    curl_file = str(
        Path(__file__).resolve().parents[1]
        / "curl_sessions"
        / "agoda_com.curl"
    )

    session_expired_markers = (
        "captcha",
        "are you a human",
        "request blocked",
    )

    def normalize_url(self, raw_deeplink: str) -> str:
        return raw_deeplink.strip()