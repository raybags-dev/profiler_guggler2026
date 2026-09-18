from __future__ import annotations

import re
from typing import List, Optional, Pattern


class NextPageTokenExtractor:
    """
    Robust Google Travel next-page token extractor.

    Extraction order:
        1. User registered regex patterns
        2. Primary structural pattern
        3. Quoted token fallback
        4. Raw token fallback

    Custom patterns should capture the token in group(1). If they do not,
    the entire match is returned.
    """

    _custom_patterns: List[Pattern[str]] = []

    # ------------------------------------------------------------------
    # Primary pattern
    # Matches:
    #   \"\",\"TOKEN:10\",null
    # ------------------------------------------------------------------
    _primary: Pattern[str] = re.compile(
        r'\\"\\"\\s*,\\s*\\"([^"\\\\]+?:\d+)\\"\\s*,\\s*null',
        re.DOTALL,
    )

    # ------------------------------------------------------------------
    # Fallback 1
    # Any escaped quoted token ending with :digits
    # ------------------------------------------------------------------
    _quoted: Pattern[str] = re.compile(
        r'\\"([A-Za-z0-9_\-+/=]{20,}:\d+)\\"',
        re.DOTALL,
    )

    # ------------------------------------------------------------------
    # Fallback 2
    # Any sufficiently long raw token ending :digits
    # ------------------------------------------------------------------
    _raw: Pattern[str] = re.compile(
        r'([A-Za-z0-9_\-+/=]{20,}:\d+)',
        re.DOTALL,
    )

    @classmethod
    def register_pattern(cls, regex: str) -> None:
        """
        Register a higher-priority extraction pattern.

        Example:
            NextPageTokenExtractor.register_pattern(
                r'MY_PREFIX([^"]+:\\d+)'
            )
        """
        cls._custom_patterns.insert(0, re.compile(regex, re.DOTALL))

    @classmethod
    def extract(cls, response: str) -> Optional[str]:
        """
        Extract next page token from a Google response.
        """

        # Normalize whitespace only.
        text: str = re.sub(r"\s+", "", response)

        # --------------------------------------------------------------
        # User patterns
        # --------------------------------------------------------------
        for pattern in cls._custom_patterns:
            match = pattern.search(text)

            if match:
                if match.lastindex:
                    return match.group(1)
                return match.group(0)

        # --------------------------------------------------------------
        # Primary pattern
        # --------------------------------------------------------------
        match = cls._primary.search(text)
        if match:
            return match.group(1)

        # --------------------------------------------------------------
        # Quoted fallback
        # --------------------------------------------------------------
        for match in cls._quoted.finditer(text):
            token = match.group(1)

            suffix = token.rsplit(":", 1)[-1]
            if suffix.isdigit():
                return token

        # --------------------------------------------------------------
        # Raw fallback
        # --------------------------------------------------------------
        match = cls._raw.search(text)
        if match:
            return match.group(1)

        return None