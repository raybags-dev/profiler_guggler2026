"""
Session-expiry detection and curl-rotation signalling.

Each OTA signals "your session is stale" differently:

  - Booking.com:   HTTP 202 + a small HTML shell
  - Agoda:         HTTP 200 + tiny body, served from /partnersearch.aspx
  - Trip.com:      HTTP 200 shell missing `__NFES_DATA__`
  - Expedia:       HTTP 200 shell missing `__PLUGIN_STATE__`

This module gives clients a uniform way to say "this was a session
expiry, not a transient failure", and writes a flag file when enough
expiries have piled up so the operator knows it's time to rotate the
curl file.
"""
from __future__ import annotations

from pathlib import Path
from utils.logging_utils import get_logger

logger = get_logger(__name__)

# Consecutive session-expiry events before we nag the operator.
EXPIRY_THRESHOLD: int = 3

# Flag file naming: <output_dir>/<client>.session_expired
_FLAG_SUFFIX: str = ".session_expired"


class SessionExpiryTracker:
    """
    Per-client counter of consecutive session-expiry events.

    Call `record_expiry()` whenever a fetch looks like a stale session.
    Call `record_success()` on any successful fetch to reset the
    counter. When the counter crosses `EXPIRY_THRESHOLD`, a flag file
    is written and one ERROR log line is emitted.
    """

    def __init__(
        self,
        client_name: str,
        flag_dir: Path,
        threshold: int = EXPIRY_THRESHOLD,
    ) -> None:
        self.client_name: str = client_name
        self.flag_dir: Path = flag_dir
        self.threshold: int = threshold
        self.count: int = 0
        self._nagged: bool = False

    @property
    def flag_path(self) -> Path:
        return self.flag_dir / f"{self.client_name}{_FLAG_SUFFIX}"

    def record_expiry(self) -> None:
        self.count += 1
        if self.count >= self.threshold and not self._nagged:
            self._write_flag()
            logger.error(
                "%s: %d consecutive session-expiry events. "
                "Rotate the curl file at the path configured on the "
                "client class, then delete %s.",
                self.client_name, self.count, self.flag_path,
            )
            self._nagged = True

    def record_success(self) -> None:
        self.count = 0
        self._nagged = False
        # Clear any stale flag from a previous expired session.
        try:
            if self.flag_path.exists():
                self.flag_path.unlink()
        except OSError:
            pass

    def _write_flag(self) -> None:
        try:
            self.flag_dir.mkdir(parents=True, exist_ok=True)
            self.flag_path.write_text(
                f"{self.client_name}: {self.count} consecutive "
                f"session-expiry events\n",
                encoding="utf-8",
            )
        except OSError as exc:
            logger.warning(
                "%s: could not write session-expired flag: %s",
                self.client_name, exc,
            )


def contains_any_marker(text: str, markers: tuple[str, ...]) -> bool:
    """Case-insensitive substring match for any of the markers."""
    if not markers:
        return False
    low = text.lower()
    for m in markers:
        if m.lower() in low:
            return True
    return False