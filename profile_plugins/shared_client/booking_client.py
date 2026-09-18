"""Booking.com OTA client."""
from __future__ import annotations

from pathlib import Path

from profile_plugins.base_client import BaseOtaClient

class BookingClient(BaseOtaClient):
    name = "booking_com"
    accepts_hosts = (
        r'^(?:www\.)?booking\.com$',
        r'^(?:www\.)?booking\.[a-z]{2}$',
        r'^(?:www\.)?booking\.(?:co\.uk|com\.au|com\.br|com\.mx)$',
    )
    curl_file = str(
        Path(__file__).resolve().parents[1]
        / "curl_sessions"
        / "booking_com.curl"
    )

    # Booking answers an expired session with a small 202 shell whose
    # body contains one of these markers.
    session_expired_markers = (
        "still processing your request",
        "your request is being processed",
        "please wait while we fetch",
    )

    def normalize_url(self, raw_deeplink: str) -> str:
        return raw_deeplink.strip()