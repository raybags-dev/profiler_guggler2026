from __future__ import annotations
import asyncio
import json
import math
import re
from enum import Enum
from pathlib import Path
from typing import Dict, Optional, TypedDict, List
import httpx
import logging
from tenacity import retry, stop_after_attempt, wait_exponential
from urllib.parse import quote, urlparse, parse_qs, urlencode, urlunparse
from configs.config import CONFIG, DepthType
from curl_workers.google_review_curl_parser import CurlParser, CurlRequest
from token_extractor import NextPageTokenExtractor
from parser.data_review_processessor import Review, parse_reviews_from_response

# Configure logging
from utils.logging_utils import configure_logging, get_logger

configure_logging(level=logging.INFO)
logger = get_logger(__name__)

# ---------------------------------------------------------------------
# Regex
# ---------------------------------------------------------------------

PROPERTY_TOKEN_RE = re.compile(
    r'%5C%22(?P<token>Ch[^%]+?)%5C%22%2C%5C%22'
)

AT_RE = re.compile(r"&at=([^&]+)&")


class RequestType(str, Enum):
    TRAVEL = "travel"
    MAPS = "maps"


class ResponseLog(TypedDict):
    page: int
    next_page_token: Optional[str]
    response: str


# ---------------------------------------------------------------------
# Payload Logger
# ---------------------------------------------------------------------

class PayloadLogger:
    """Logger for payloads with console output only."""

    def __init__(self, log_file: str = "payloads.log") -> None:
        self.log_file: str = log_file
        # No file clearing needed since we only log to console

    def log_payload(self, payload: str, page_number: int) -> None:
            """
            Log the payload to console only.

            Args:
                payload: The payload string to log
                page_number: The page number for context
            """
            logger.info(f"\n{'*' * 50}")
            logger.info(f"PAGE {page_number} PAYLOAD")
            logger.info(f"Payload (first 200 chars): {payload[:200]}...")
            logger.info(f"\n{'*' * 50}")


# ---------------------------------------------------------------------
# Google client
# ---------------------------------------------------------------------

class GoogleClient:

    def __init__(self) -> None:
        self.client = httpx.AsyncClient(timeout=CONFIG.timeout_seconds)
        self.payload_logger: Optional[PayloadLogger] = None

    def set_payload_logger(self, logger: PayloadLogger) -> None:
        """Set the payload logger instance."""
        self.payload_logger = logger

    async def close(self) -> None:
        await self.client.aclose()

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=2),
    )
    async def post(
        self,
        url: str,
        headers: Dict[str, str],
        cookies: Dict[str, str],
        payload: str,
        page_number: Optional[int] = None,
    ) -> str:

        clean_headers: Dict[str, str] = {
            k: v
            for k, v in headers.items()
            if k.lower() != "cookie"
        }

        # Log payload if logger is set and page number provided
        if self.payload_logger and page_number:
            self.payload_logger.log_payload(payload, page_number)

        response = await self.client.post(
            url=url,
            headers=clean_headers,
            cookies=cookies,
            content=payload,
        )

        response.raise_for_status()

        return response.text

    @staticmethod
    def extract_next_token(response: str) -> Optional[str]:
        return NextPageTokenExtractor.extract(response)


# ---------------------------------------------------------------------
# Payload Builder
# ---------------------------------------------------------------------

class PayloadBuilder:

    def __init__(self, request: CurlRequest) -> None:

        self.url = request.url
        self.at = self._extract_at(request.payload)

        # Detect request type
        self.is_maps = "MapsWizUi" in request.url
        self.is_travel = "TravelFrontendUi" in request.url

        if self.is_travel:

            property_match = PROPERTY_TOKEN_RE.search(request.payload)

            if property_match is None:
                raise ValueError("Property token not found in Travel payload.")

            self.property_token = property_match.group("token")

        elif self.is_maps:

            # Store the original encoded Maps payload.
            m = re.search(r"f\.req=([^&]+)&at=", request.payload)

            if m is None:
                raise ValueError("Maps f.req payload not found.")

            self.maps_template = m.group(1)

        else:
            raise ValueError("Unsupported Google request type.")

    @staticmethod
    def _extract_at(payload: str) -> str:

        match = AT_RE.search(payload)

        if match is None:
            raise ValueError("at parameter not found.")

        return match.group(1)

    # -----------------------------------------------------------------
    # Main entry
    # -----------------------------------------------------------------

    def build(self, next_token: Optional[str]) -> str:

        if self.is_travel:
            return self._build_travel(next_token)

        return self._build_maps(next_token)

    # -----------------------------------------------------------------
    # Google Travel
    # -----------------------------------------------------------------

    def _build_travel(self, next_token: Optional[str]) -> str:

        payload = (
            "f.req=%5B%5B%5B%22ocp93e%22%2C%22"
            "%5Bnull%2Cnull%2Cnull%2C10%2C2%2C%5B-1%5D%2Cnull%2C"
            "%5C%22%5C%22%2C"
            "%5C%22"
            + self.property_token +
            "%5C%22%2C"
            "%5C%22"
        )

        if next_token:
            payload += quote(next_token, safe="")

        payload += (
            "%5C%22%2Cnull%2C%5B%5B%5D%5D%2Cnull%2C"
            "%5C%22%5C%22%5D%22%2Cnull%2C%22generic%22%5D%5D%5D"
        )

        payload += "&at=" + self.at + "&"

        return payload

    # -----------------------------------------------------------------
    # Google Maps
    # -----------------------------------------------------------------

    def _build_maps(self, next_token: Optional[str]) -> str:

        token = quote(next_token or "", safe="")

        # Replace only the [10,"TOKEN"] pagination field.
        payload = re.sub(
            r"%5B10%2C%5C%22.*?%5C%22%5D",
            f"%5B10%2C%5C%22{token}%5C%22%5D",
            self.maps_template,
            count=1,
        )

        return f"f.req={payload}&at={self.at}&"


# ---------------------------------------------------------------------
# Scraper
# ---------------------------------------------------------------------

class GoogleTravelScraper:

    def __init__(self) -> None:

        self.request: CurlRequest = CurlParser.parse(CONFIG.curl_file)

        self.builder = PayloadBuilder(self.request)

        # Initialize payload logger
        self.payload_logger = PayloadLogger()

        Path(CONFIG.response_log_file).write_text("", encoding="utf-8")

    def log_payload(self, page: int, payload: str) -> None:
        """Log payload to file using the payload logger."""
        self.payload_logger.log_payload(payload, page)

    def log_reviews(
        self,
        page: int,
        reviews: List[Review],
    ) -> None:

        # clear file
        mode: str = 'w' if page == 1 else 'a'

        with open("json_data/parsed_reviews.jsonl", mode, encoding="utf-8") as f:
            for review in reviews:
                obj = { # type: ignore
                    "page": page,
                    **review,
                }

                f.write(json.dumps(obj, ensure_ascii=False) + "\n")

    def log_response(
        self,
        page: int,
        token: Optional[str],
        response: str,
    ) -> None:

        obj: ResponseLog = {
            "page": page,
            "next_page_token": token,
            "response": response,
        }

        with open(
            CONFIG.response_log_file,
            "a",
            encoding="utf-8",
        ) as f:
            f.write(json.dumps(obj) + "\n")

    @staticmethod
    def increment_reqid(url: str) -> str:

        parsed = urlparse(url)

        params = parse_qs(parsed.query)

        current = int(params["_reqid"][0])

        params["_reqid"] = [
            str(current + CONFIG.reqid_increment)
        ]

        query = urlencode(params, doseq=True)

        return urlunparse(
            (
                parsed.scheme,
                parsed.netloc,
                parsed.path,
                parsed.params,
                query,
                parsed.fragment,
            )
        )

    async def scrape(self, depth: DepthType) -> None:

        client = GoogleClient()
        client.set_payload_logger(self.payload_logger)

        if depth == "full_run":
            max_pages = math.inf
        else:
            max_pages = float(depth)

        page = 1
        next_token: Optional[str] = None
        url = self.request.url

        try:

            while page <= max_pages:

                payload = self.builder.build(next_token)

                print(f"Fetching page {page}")

                response = await client.post(
                    url=url,
                    headers=self.request.headers,
                    cookies=self.request.cookies,
                    payload=payload,
                    page_number=page,
                )

                next_token = client.extract_next_token(response)

                self.log_response(
                    page,
                    next_token,
                    response,
                )

                # Parse reviews from this response
                reviews = parse_reviews_from_response(response)

                self.log_reviews(page, reviews)

                if next_token is None:
                    print("No next page token returned.")
                    break

                url = self.increment_reqid(url)

                page += 1

                await asyncio.sleep(
                    CONFIG.delay_between_requests
                )

        finally:
            await client.close()


# ---------------------------------------------------------------------
# Entry
# ---------------------------------------------------------------------

async def main() -> None:

    scraper = GoogleTravelScraper()

    await scraper.scrape(CONFIG.depth)


if __name__ == "__main__":
    asyncio.run(main())

