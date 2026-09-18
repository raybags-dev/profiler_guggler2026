from dataclasses import dataclass, field
from typing import Literal, Union, List

DepthType = Union[int, Literal["full_run"]]


def _kw_to_query(keyword: str) -> str:
    """Turn 'Hotel Mansion Amsterdam' into 'Hotel+Mansion+Amsterdam'."""
    return "+".join(keyword.strip().split())


@dataclass(frozen=True)
class ScraperConfig:
    # Files
    curl_file: str = "_cURL.txt"
    response_log_file: str = "json_data/row_review_responses.jsonl"
    raw_google_page_file: str = "row_google_page.txt"
    profile_output_file: str = "json_data/google_profiles.jsonl"

    # Property search keywords — source of truth.
    property_searchKeywords: List[str] = field(default_factory=lambda: [
        "Hotel Mansion Amsterdam",
        "Hotel Okura Amsterdam",
        "Conservatorium Hotel Amsterdam",
        "Rosewood London",
        "Sheraton Hotel Kampala"
        "Serena Hotel Kampala",
        "The Plaza Hotel",
        "The Standard High Line",
        "Arlo SoHo",
        "The Bowery Hotel",
        "Ace Hotel New York",
        "Fairmont Royal York",
        "The Ritz-Carlton Toronto",
        "Drake Hotel",
        "1 Hotel Toronto",
        "Bisha Hotel Toronto",
        "The St. Regis Shenzhen",
        "Four Seasons Hotel Shenzhen",
        "Mandarin Oriental Shenzhen",
        "MUJI Hotel Shenzhen",
        "Andaz Shenzhen Bay",
        "Hotel D'Angleterre",
        "Villa Copenhagen",
        "Nimb Hotel",
        "71 Nyhavn Hotel",
        "CitizenM Copenhagen Radhuspladsen",
        "Hotel Amigo",
        "The Jam Hotel Brussels",
        "The Dominican",
        "Pillows City Hotel Brussels Centre",
        "Mix Brussels",

    ])

    # Networking
    timeout_seconds: int = 30
    delay_between_requests: float = 2.0

    # Request ID increment (unused here, kept for parity with review scraper)
    reqid_increment: int = 200000

    # Depth (unused here, kept for parity)
    depth: DepthType = 3

    # ---- URL builders -------------------------------------------------

    @staticmethod
    def build_search_url(keyword: str) -> str:
        """https://www.google.com/search?q=Hotel+Mansion+Amsterdam&newwindow=1"""
        return f"https://www.google.com/search?q={_kw_to_query(keyword)}&newwindow=1"

    @staticmethod
    def build_travel_url(keyword: str) -> str:
        """https://www.google.com/travel/search?q=Hotel+Mansion+Amsterdam"""
        return f"https://www.google.com/travel/search?q={_kw_to_query(keyword)}"


CONFIG = ScraperConfig()
