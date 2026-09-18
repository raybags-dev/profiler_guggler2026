"""
Minimal curl parser for extracting URL, headers, and cookies
from a saved curl command.
"""
from __future__ import annotations
import re
import urllib.parse
from dataclasses import dataclass, field
from typing import Dict, Any,cast


@dataclass
class CurlRequest:
    url: str
    method: str = "GET"
    headers: Dict[str, str] = field(default_factory=lambda: cast(Dict[str, str], {}))
    cookies: Dict[str, str] = field(default_factory=lambda: cast(Dict[str, str], {}))
    payload: str = ""
    body_params: Dict[str, Any] = field(default_factory=lambda: cast(Dict[str, Any], {}))


class CurlParser:
    """Parse a curl command string into a CurlRequest."""

    _URL_RE = re.compile(r"--url\s+['\"]([^'\"]+)['\"]")
    _H_RE = re.compile(r"-H\s+['\"]([^'\"]+)['\"]")
    _B_RE = re.compile(r"-b\s+['\"]([^'\"]+)['\"]")
    _DATA_RE = re.compile(r"--data(?:-raw)?\s+['\"]([^'\"]+)['\"]")
    _METHOD_RE = re.compile(r"-X\s+(\w+)")

    @classmethod
    def parse_text(cls, curl_text: str) -> CurlRequest:
        url_match = cls._URL_RE.search(curl_text)
        if not url_match:
            raise ValueError("URL not found in curl command")
        url = url_match.group(1)

        method_match = cls._METHOD_RE.search(curl_text)
        method = method_match.group(1) if method_match else "GET"

        headers: Dict[str, str] = {}
        for match in cls._H_RE.finditer(curl_text):
            header_line = match.group(1)
            if ": " in header_line:
                k, v = header_line.split(": ", 1)
                headers[k] = v

        cookies: Dict[str, str] = {}
        cookie_match = cls._B_RE.search(curl_text)
        if cookie_match:
            cookie_string = cookie_match.group(1)
            for pair in cookie_string.split("; "):
                if "=" in pair:
                    k, v = pair.split("=", 1)
                    cookies[k] = v

        payload = ""
        body_params: Dict[str, Any] = {}
        data_match = cls._DATA_RE.search(curl_text)
        if data_match:
            payload = data_match.group(1)
            try:
                body_params = {
                    k: v[0] for k, v in urllib.parse.parse_qs(payload).items()
                }
            except Exception:
                body_params = {"raw_data": payload}

        return CurlRequest(
            url=url,
            method=method,
            headers=headers,
            cookies=cookies,
            payload=payload,
            body_params=body_params,
        )

    @classmethod
    def parse(cls, curl_file: str) -> CurlRequest:
        """Read a curl file from disk and parse it."""
        with open(curl_file, "r", encoding="utf-8") as f:
            return cls.parse_text(f.read())