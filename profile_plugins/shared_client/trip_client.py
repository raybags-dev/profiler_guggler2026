"""Trip.com OTA client."""
from __future__ import annotations

from pathlib import Path

from profile_plugins.base_client import BaseOtaClient


class TripClient(BaseOtaClient):
    name = "trip_com"
    accepts_hosts = (
        r'^(?:[a-z]{2}\.)?trip\.com$',
        r'^(?:www\.)?trip\.com$',
    )
    curl_file = str(
        Path(__file__).resolve().parents[1]
        / "curl_sessions"
        / "trip_com.curl"
    )

    session_expired_markers = (
        "access denied",
        "your request has been blocked",
        "please verify you are a human",
    )

    def normalize_url(self, raw_deeplink: str) -> str:
        return raw_deeplink.strip()