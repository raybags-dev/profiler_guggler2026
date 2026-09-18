"""
Curl file parser for OTA plugins.

Separate from curl_workers/google_profile_curl_parser.py because OTA curl
files contain header values with embedded double quotes (e.g. sec-ch-ua)
that a simple regex can't handle correctly. This parser is line-based:
it splits on physical lines, peels off the outer single-quote wrapping,
and splits each header on the first ": ".

The URL in the curl is captured but callers usually ignore it — only the
headers and cookies are reused.
"""
from __future__ import annotations

import re
import urllib.parse
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, cast


@dataclass
class CurlSession:
    """Parsed curl command: URL, headers, cookies, and optional body."""

    url: str
    method: str = "GET"
    headers: Dict[str, str] = field(default_factory=lambda: cast(Dict[str, str], {}))
    cookies: Dict[str, str] = field(default_factory=lambda: cast(Dict[str, str], {}))
    payload: str = ""
    body_params: Dict[str, Any] = field(default_factory=lambda: cast(Dict[str, Any], {}))


class PluginCurlParser:
    """Line-based curl parser for OTA session capture files."""

    _URL_RE = re.compile(r"--url\s+['\"]([^'\"]+)['\"]")
    _METHOD_RE = re.compile(r"-X\s+(\w+)")
    _DATA_RE = re.compile(r"--data(?:-raw)?\s+['\"]([^'\"]+)['\"]")

    @classmethod
    def parse_text(cls, curl_text: str) -> CurlSession:
        url_match = cls._URL_RE.search(curl_text)
        if not url_match:
            # Some editors strip `--url` and use a bare URL argument.
            # Fall back to the first http(s) URL on a line.
            fallback = re.search(
                r"curl\s+(?:--location\s+)?'(https?://[^']+)'", curl_text
            )
            if not fallback:
                raise ValueError("URL not found in curl command")
            url = fallback.group(1)
        else:
            url = url_match.group(1)

        method_match = cls._METHOD_RE.search(curl_text)
        method: str = method_match.group(1) if method_match else "GET"

        headers: Dict[str, str] = {}
        cookies: Dict[str, str] = {}

        # Split on physical lines; strip the trailing `\` continuations.
        raw_lines: List[str] = curl_text.split("\n")
        raw_line: str
        for raw_line in raw_lines:
            line: str = raw_line.strip()
            if line.endswith("\\"):
                line = line[:-1].rstrip()
            if not line:
                continue

            # Header flag (-H / --header)
            header_value: str = ""
            if line.startswith("-H "):
                header_value = line[3:].strip()
            elif line.startswith("--header "):
                header_value = line[9:].strip()
            else:
                # Cookie flag (-b / --cookie)
                if line.startswith("-b "):
                    cls._ingest_cookie_arg(line[3:].strip(), cookies)
                elif line.startswith("--cookie "):
                    cls._ingest_cookie_arg(line[9:].strip(), cookies)
                continue

            # Strip the outer wrapping quote (single or double).
            if (
                len(header_value) >= 2
                and header_value[0] in ("'", '"')
                and header_value[-1] == header_value[0]
            ):
                header_value = header_value[1:-1]

            # Split on the FIRST ": " — values can contain further colons.
            if ": " in header_value:
                k, v = header_value.split(": ", 1)
                k = k.strip()
                v = v.strip()
                if k:
                    headers[k.lower()] = v

        payload: str = ""
        body_params: Dict[str, Any] = {}
        data_match = cls._DATA_RE.search(curl_text)
        if data_match:
            payload = data_match.group(1)
            try:
                body_params = {
                    k: v[0]
                    for k, v in urllib.parse.parse_qs(payload).items()
                }
            except Exception:
                body_params = {"raw_data": payload}

        return CurlSession(
            url=url,
            method=method,
            headers=headers,
            cookies=cookies,
            payload=payload,
            body_params=body_params,
        )

    @staticmethod
    def _ingest_cookie_arg(arg: str, cookies: Dict[str, str]) -> None:
        """Parse the value of a -b/--cookie argument into the cookie dict."""
        if (
            len(arg) >= 2
            and arg[0] in ("'", '"')
            and arg[-1] == arg[0]
        ):
            arg = arg[1:-1]
        pair: str
        for pair in arg.split(";"):
            pair = pair.strip()
            if not pair or "=" not in pair:
                continue
            k, _, v = pair.partition("=")
            k = k.strip()
            v = v.strip()
            if k:
                cookies[k] = v

    @classmethod
    def parse(cls, curl_file: str) -> CurlSession:
        """Read a curl file from disk and parse it."""
        path = Path(curl_file)
        with open(path, "r", encoding="utf-8") as f:
            return cls.parse_text(f.read())