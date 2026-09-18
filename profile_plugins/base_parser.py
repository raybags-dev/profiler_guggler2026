"""
Base parser for OTA plugin HTML.

Each concrete parser subclasses this and implements `parse(html) -> dict`.
The returned dict is what gets written to sub_profiles/<name>.jsonl.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any, Dict, Optional, List


class BaseOtaParser(ABC):
    """Base class for all OTA HTML parsers."""

    name: str = "base"

    @abstractmethod
    def parse(self, html: str, source_url: str) -> Dict[str, Any]:
        """
        Turn raw HTML into a JSON-serializable dict.

        Must never raise — return a dict with whatever fields you can
        extract, plus a 'parse_ok': bool flag.
        """
        raise NotImplementedError

    def parse_title(self, html: str) -> Optional[str]:
        """
        Extract <meta name="title" content="..."> or <title>...</title>.

        This is the minimum every parser should do for now.
        """
        import re
        import html as html_module

        m = re.search(
            r'<meta\s+name="title"\s+content="([^"]*)"',
            html,
            re.IGNORECASE,
        )
        if m:
            return html_module.unescape(m.group(1)).strip()

        m = re.search(r"<title[^>]*>([^<]*)</title>", html, re.IGNORECASE)
        if m:
            return html_module.unescape(m.group(1)).strip()

        return None

    def parse_og_site_name(self, html: str) -> Optional[str]:
        """Extract og:site_name if present."""
        import re
        import html as html_module

        m = re.search(
            r'<meta\s+property="og:site_name"\s+content="([^"]*)"',
            html,
            re.IGNORECASE,
        )
        return html_module.unescape(m.group(1)).strip() if m else None


    def follow_up_urls(self, parsed: Dict[str, Any]) -> List[str]:
        """
        Optional hook: return a list of URLs to fetch after the initial parse.

        The manager will GET each URL and call `merge_follow_up` with the
        resulting HTML. Parsers that don't need this return an empty list.

        Default: no follow-up requests.
        """
        return []

    def merge_follow_up(
        self,
        parsed: Dict[str, Any],
        url: str,
        html: str,
    ) -> None:
        """
        Optional hook: merge a follow-up response into `parsed` in place.

        The manager calls this once per URL returned by `follow_up_urls`.
        Parsers that don't need this can leave the default no-op.
        """
        return None    