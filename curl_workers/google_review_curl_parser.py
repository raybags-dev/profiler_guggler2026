from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Dict


@dataclass(slots=True)
class CurlRequest:
    url: str
    headers: Dict[str, str]
    cookies: Dict[str, str]
    payload: str


class CurlParser:
    """Robust Chrome cURL parser."""

    @classmethod
    def parse(cls, file_path: str) -> CurlRequest:
        path = Path(file_path)

        # ---------- File validation ----------
        if not path.exists():
            raise FileNotFoundError(
                f"Curl file does not exist: {path.resolve()}"
            )

        if not path.is_file():
            raise ValueError(f"Expected a file but received: {path}")

        try:
            text: str = path.read_text(encoding="utf-8").strip()
        except PermissionError as e:
            raise PermissionError(
                f"Permission denied reading '{path}'."
            ) from e
        except UnicodeDecodeError as e:
            raise ValueError(
                f"'{path}' is not a valid UTF-8 text file."
            ) from e
        except OSError as e:
            raise RuntimeError(
                f"Unable to read curl file '{path}'."
            ) from e

        if not text:
            raise ValueError(
                f"Curl file '{path}' is empty."
            )

        if "curl " not in text.lower():
            raise ValueError(
                "The file does not appear to contain a curl command."
            )

        # Flatten multiline curl
        normalized: str = (
            text.replace("\\\r\n", " ")
                .replace("\\\n", " ")
        )
        normalized = re.sub(r"\s+", " ", normalized).strip()

        # ---------- URL ----------
        url_match = re.search(
            r"--url\s+\$?(['\"])(.*?)\1",
            normalized,
            flags=re.IGNORECASE | re.DOTALL,
        )

        if url_match is None:
            raise ValueError(
                "Failed to parse --url from the curl command."
            )

        url: str = url_match.group(2)

        # ---------- Payload ----------
        data_match = re.search(
            r"--data(?:-raw)?\s+\$?(['\"])(.*?)\1",
            normalized,
            flags=re.DOTALL | re.IGNORECASE,
        )

        if data_match is None:
            raise ValueError(
                "Failed to parse --data or --data-raw payload."
            )

        payload: str = data_match.group(2)

        if "f.req=" not in payload:
            raise ValueError(
                "The payload does not contain an f.req parameter."
            )

        # ---------- Headers ----------
        headers: Dict[str, str] = {}

        for match in re.finditer(
            r"-H\s+\$?(['\"])(.*?)\1",
            normalized,
            flags=re.DOTALL,
        ):
            header = match.group(2)

            if ": " not in header:
                continue

            key, value = header.split(": ", 1)
            headers[key] = value

        # ---------- Cookies ----------
        cookies: Dict[str, str] = {}

        cookie_match = re.search(
            r"-b\s+\$?(['\"])(.*?)\1",
            normalized,
            flags=re.DOTALL,
        )

        if cookie_match is not None:
            cookie_string = cookie_match.group(2).strip()

            if cookie_string.upper() != "TOKEN":
                for cookie in cookie_string.split("; "):
                    if "=" not in cookie:
                        continue

                    key, value = cookie.split("=", 1)
                    cookies[key] = value

        return CurlRequest(
            url=url,
            headers=headers,
            cookies=cookies,
            payload=payload,
        )