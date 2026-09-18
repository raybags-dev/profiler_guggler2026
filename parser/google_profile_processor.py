"""
Parses a raw Google Maps/Places HTML page (fetched via httpx)
into a structured property profile object.
"""
from __future__ import annotations
import re
import html
import json
import logging
from typing import Any, Dict, Iterator, List, Optional, Set, Tuple, cast

from utils.logging_utils import configure_logging, get_logger

configure_logging(level=logging.INFO)
logger = get_logger(__name__)


class GoogleProfileProcessor:
    """Extract property profile data from a Google Maps HTML page."""

    def __init__(self, raw_html: str, source_url: str) -> None:
        self.raw_html: str = raw_html
        self.source_url: str = source_url
        self.html: str = html.unescape(raw_html)
        self._jsdata_cache: Optional[List[str]] = None

    # -----------------------------------------------------------------
    # Helpers
    # -----------------------------------------------------------------

    @staticmethod
    def _first_match(pattern: str, text: str, flags: int = 0) -> Optional[str]:
        match: Optional[re.Match[str]] = re.search(pattern, text, flags)
        if not match:
            return None
        if match.lastindex:
            return match.group(1)
        return match.group(0)

    # -----------------------------------------------------------------
    # Individual extractors
    # -----------------------------------------------------------------
    _AMENITY_WHITELIST: List[str] = [
        "Wi-Fi", "Free Wi-Fi", "Paid Wi-Fi", "WiFi", "Internet",
        "Parking", "Free parking", "Paid parking", "Valet parking",
        "Parking garage", "Parking lot", "Street parking",
        "Breakfast", "Free breakfast", "Paid breakfast", "Breakfast buffet",
        "Restaurant", "Bar", "Room service", "Vending machines",
        "Coffee maker", "Minibar", "Table service", "Buffet dinner",
        "Coffee/tea in lobby",
        "Pool", "Indoor pool", "Outdoor pool", "No pools", "No hot tub",
        "Fitness center", "Gym", "Spa", "Massage", "Sauna", "Steam room",
        "Hot tub", "Elliptical machine", "Treadmill", "Free weights",
        "Front desk", "24-hour front desk", "Concierge", "Baggage storage",
        "Currency exchange", "Full-service laundry", "Laundry service",
        "Dry cleaning", "Elevator", "Wake-up calls", "Housekeeping",
        "Turndown service", "ATM", "Gift shop", "Newsstand",
        "Business center", "Meeting rooms", "Conference facilities",
        "Banquet hall", "Copy center",
        "Wheelchair accessible", "Accessible elevator",
        "Accessible parking",
        "Air conditioning", "Heating", "Non-smoking", "Smoke-free property",
        "Private bathroom", "Shower", "Bathtub", "Hair dryer",
        "Iron", "In-room safe", "Refrigerator", "Microwave",
        "Pet-friendly", "Pets allowed", "No pets", "Pet-friendly rooms",
        "Children", "Kid-friendly", "Babysitting", "Activities for kids",
        "Cribs", "High chairs",
        "Bicycle rental", "Watercraft rental", "Game room", "Tennis court",
        "Golf course", "Hiking", "Fishing", "Ski storage",
        "Airport shuttle", "Airport transfer", "Free airport shuttle",
        "Paid airport shuttle", "Taxi service", "Private car service",
        "Bicycle parking", "EV charging",
        "Credit cards", "Debit cards", "Cash", "NFC mobile payments",
        "Dutch", "English", "French", "German", "Spanish",
        "Eco-certified", "Eco certifications", "Green Key", "ECOsmart",
    ]

    def extract_property_name(self) -> Optional[str]:
        patterns: List[str] = [
            r'<h1[^>]*class="[^"]*FNkAEc[^"]*"[^>]*>([^<]+)</h1>',
            r'<h1[^>]*jsname="Xmv8Ce"[^>]*>([^<]+)</h1>',
            r'<h1[^>]*>([^<]+)</h1>',
        ]
        pattern: str
        for pattern in patterns:
            name: Optional[str] = self._first_match(pattern, self.html)
            if name:
                return name.strip()
        return None

    def extract_property_name_alt(self) -> Optional[str]:
        pattern: str = r'<h2[^>]*>([^<]+)</h2>'
        return self._first_match(pattern, self.html)

    def extract_rating_and_reviews(self) -> Dict[str, Optional[Any]]:
        result: Dict[str, Optional[Any]] = {"rating": None, "review_count": None}

        m: Optional[re.Match[str]] = re.search(
            r'([\d.]+)\s+out of 5 stars?\s+from\s+([\d,]+)\s+reviews?',
            self.html,
        )
        if m:
            try:
                result["rating"] = float(m.group(1))
            except ValueError:
                pass
            try:
                result["review_count"] = int(m.group(2).replace(",", ""))
            except ValueError:
                pass
            return result

        m2: Optional[re.Match[str]] = re.search(r'>([\d,]+)\s+reviews?<', self.html)
        if m2:
            try:
                result["review_count"] = int(m2.group(1).replace(",", ""))
            except ValueError:
                pass

        return result

    def extract_address(self) -> Optional[str]:
        pattern: str = r'aria-label="hotel address is ([^"]+)"'
        match: Optional[re.Match[str]] = re.search(pattern, self.html)
        return match.group(1).strip() if match else None

    def extract_phone(self) -> Optional[str]:
        pattern: str = r'aria-label="call this hotel:\s*([^"]+)"'
        match: Optional[re.Match[str]] = re.search(pattern, self.html)
        return match.group(1).strip() if match else None

    def extract_hotel_feature_id(self) -> Optional[str]:
        pattern: str = r'data-hotel-feature-id="([^"]+)"'
        match: Optional[re.Match[str]] = re.search(pattern, self.html)
        return match.group(1).strip() if match else None

    def extract_place_id(self) -> Optional[str]:
        patterns: List[str] = [
            r'/travel/hotels/entity/([A-Za-z0-9_\-]+)',
            r'/entity/([A-Za-z0-9_\-]+)',
            r'&quot;(Ch[A-Za-z0-9_\-]+)&quot;',
            r'"(Ch[A-Za-z0-9_\-]+)"',
        ]
        pattern: str
        for pattern in patterns:
            match: Optional[re.Match[str]] = re.search(pattern, self.html)
            if match:
                return match.group(1)
        return None

    def extract_property_url(self) -> Optional[str]:
        m: Optional[re.Match[str]] = re.search(
            r'data-href="/entity/([A-Za-z0-9_\-]+)"', self.html
        )
        if m:
            return f"https://www.google.com/travel/hotels/entity/{m.group(1)}?hl=en&gl=us"

        m = re.search(r'href="/travel/hotels/entity/([A-Za-z0-9_\-]+)', self.html)
        if m:
            return f"https://www.google.com/travel/hotels/entity/{m.group(1)}?hl=en&gl=us"

        place_id: Optional[str] = self.extract_place_id()
        if place_id:
            return f"https://www.google.com/travel/hotels/entity/{place_id}?hl=en&gl=us"

        return None

    def extract_rating_string(self) -> Optional[str]:
        pattern: str = r'<span class="CFH2De">([\d-]+-star hotel)</span>'
        match: Optional[re.Match[str]] = re.search(pattern, self.html)
        return match.group(1) if match else None

    def extract_check_in_out(self) -> Dict[str, Optional[str]]:
        result: Dict[str, Optional[str]] = {"check_in": None, "check_out": None}

        ci: Optional[re.Match[str]] = re.search(
            r'Check-in time:\s*<span[^>]*>([^<]+)</span>', self.html
        )
        if ci:
            result["check_in"] = ci.group(1).strip()
        co: Optional[re.Match[str]] = re.search(
            r'Check-out time:\s*<span[^>]*>([^<]+)</span>', self.html
        )
        if co:
            result["check_out"] = co.group(1).strip()

        if result["check_in"] is None:
            m: Optional[re.Match[str]] = re.search(
                r'check-?in\s+time\s+of\s+([0-9]{1,2}(?::[0-9]{2})?\s*(?:AM|PM|am|pm))',
                self.html,
            )
            if m:
                result["check_in"] = m.group(1).strip()

        if result["check_out"] is None:
            m = re.search(
                r'check-?out\s+time\s+of\s+([0-9]{1,2}(?::[0-9]{2})?\s*(?:AM|PM|am|pm))',
                self.html,
            )
            if m:
                result["check_out"] = m.group(1).strip()

        return result

    def extract_amenities(self) -> List[str]:
        amenities: List[str] = []
        seen: Set[str] = set()

        block: str = self.html
        anchor: Optional[re.Match[str]] = re.search(r'>\s*Amenities\s*<', self.html)
        if anchor:
            start: int = anchor.start()
            next_head: Optional[re.Match[str]] = re.search(
                r'>\s*(?:Accessibility|Policies|Reviews|Location|About|Activities|Wellness|Parking|Food\s*&\s*drink)\s*<',
                self.html[start:],
            )
            end: int = (
                start + next_head.start()
                if next_head
                else min(len(self.html), start + 100_000)
            )
            block = self.html[start:end]

        m: re.Match[str]
        for m in re.finditer(r'<span[^>]*class="[^"]*"[^>]*>([^<>]{2,60})</span>', block):
            raw: str = m.group(1).strip()
            if not raw:
                continue
            raw_low: str = raw.lower()
            matched: Optional[str] = next(
                (a for a in self._AMENITY_WHITELIST if a.lower() == raw_low),
                None,
            )
            if matched and matched not in seen:
                seen.add(matched)
                amenities.append(matched)

        if not amenities:
            name: str
            for name in self._AMENITY_WHITELIST:
                if re.search(rf'>{re.escape(name)}<', self.html, re.IGNORECASE):
                    if name not in seen:
                        seen.add(name)
                        amenities.append(name)

        return amenities

    def _split_room_anchors(self) -> List[str]:
        patterns: List[str] = [
            r'<a class="gw2Gcf',
            r'<a[^>]+class="[^"]*gw2Gcf',
        ]
        for pattern in patterns:
            chunks: List[str] = re.split(pattern, self.html)
            if len(chunks) >= 2:
                return chunks

        fallback: List[str] = re.split(
            r'<a\b(?=[^>]*>)(?=[\s\S]{0,4000}?<span class="iqYCVb")',
            self.html,
        )
        if len(fallback) >= 2:
            return fallback

        return re.split(r'(?=<h4\b)', self.html)    

    def extract_room_rates(self) -> List[Dict[str, Any]]:
        rooms: List[Dict[str, Any]] = []
        seen: Set[Tuple[Any, ...]] = set()

        anchors: List[str] = self._split_room_anchors()

        chunk: str
        for chunk in anchors[1:]:
            # ---- 1) room title: known class, then any <h4> ----
            title_match: Optional[re.Match[str]] = re.search(
                r'<h4 class="VuHI7">([^<]{1,120})</h4>', chunk
            )
            if not title_match:
                title_match = re.search(r'<h4[^>]*>([^<]{1,120})</h4>', chunk)
            if not title_match:
                continue

            room_type_raw: str = title_match.group(1).strip()
            room_type: Optional[str] = self._sanitize_string(
                room_type_raw, max_len=120
            )
            if not room_type:
                continue

            # ---- 2) anchor class -> hidden / collapsed row flag ----
            is_hidden: bool = False
            anchor_class_match: Optional[re.Match[str]] = re.search(
                r'^([^>]*)>', chunk
            )
            if anchor_class_match:
                attrs: str = anchor_class_match.group(1)
                class_attr: Optional[re.Match[str]] = re.search(
                    r'class="([^"]*)"', attrs
                )
                if class_attr:
                    classes: str = class_attr.group(1)
                    is_hidden = ("eLNT1d" in classes) or ("YJe4Tc" in classes)

            # ---- 3) booking_url from /aclk on this anchor ----
            booking_url: Optional[str] = None
            booking_url_needs_redirect: bool = False
            href_match: Optional[re.Match[str]] = re.search(
                r'href="(/aclk\?[^"]{1,2000})"', chunk
            )
            if href_match:
                raw_href: str = html.unescape(href_match.group(1))
                booking_url = "https://www.google.com" + raw_href
                booking_url_needs_redirect = True

            # ---- 4) scope: 2000 chars after the title ----
            start: int = title_match.end()
            meta_scope: str = chunk[start:start + 2000]

            room: Dict[str, Any] = {
                "room_type": room_type,
                "rate": None,
                "currency": None,
                "cancellation_policy": "Unknown",
                "board_type": None,
                "image_url": None,
                "booking_url": booking_url,
                "booking_url_needs_redirect": booking_url_needs_redirect,
                "_hidden": is_hidden,
            }

            # ---- 5a) image URL (whole anchor chunk) ----
            img_match: Optional[re.Match[str]] = re.search(
                r'<img[^>]+src="(https?://[^"]{1,500})"', chunk
            )
            if img_match:
                url: Optional[str] = self._sanitize_string(
                    img_match.group(1), max_len=500
                )
                if url and "gstatic.com/travel-hotels/branding" not in url:
                    room["image_url"] = url

            # ---- 5b) price: chunk, then forward, then backward ----
            price_match: Optional[re.Match[str]] = re.search(
                r'<span class="iqYCVb">([^<]{1,20})</span>', chunk
            )
            if not price_match:
                price_match = re.search(
                    r'<span class="iqYCVb">([^<]{1,20})</span>', meta_scope
                )
            if not price_match:
                back_scope: str = chunk[
                    max(0, title_match.start() - 2000):title_match.start()
                ]
                price_match = re.search(
                    r'<span class="iqYCVb">([^<]{1,20})</span>', back_scope
                )

            if price_match:
                price_str: str = price_match.group(1).strip()
                # Guard: skip "View more options from €X" pseudo-prices
                if "view more" in price_str.lower():
                    price_match = None
                else:
                    currency_match: Optional[re.Match[str]] = re.match(
                        r'([^\d]{1,5})', price_str
                    )
                    number_match: Optional[re.Match[str]] = re.search(
                        r'([\d.,]{1,12})', price_str
                    )
                    if currency_match:
                        room["currency"] = self._sanitize_string(
                            currency_match.group(1), max_len=5
                        )
                    if number_match:
                        try:
                            room["rate"] = int(
                                float(number_match.group(1).replace(",", ""))
                            )
                        except ValueError:
                            pass

            # ---- 5c) cancellation policy (bounded) ----
            free_cancel: Optional[re.Match[str]] = re.search(
                r'(Free cancellation[^<&#"]{0,80})', meta_scope
            )
            if free_cancel:
                room["cancellation_policy"] = (
                    self._sanitize_string(free_cancel.group(1), max_len=80)
                    or "Unknown"
                )
            else:
                non_refund: Optional[re.Match[str]] = re.search(
                    r'(Non-?refundable[^<&#"]{0,80})',
                    meta_scope,
                    re.IGNORECASE,
                )
                if non_refund:
                    room["cancellation_policy"] = (
                        self._sanitize_string(non_refund.group(1), max_len=80)
                        or "Unknown"
                    )

            # ---- 5d) board type (narrow 300-char scope) ----
            board_scope: str = chunk[start:start + 300].lower()
            room["board_type"] = self._normalize_board_type(board_scope, room_type)

            # ---- 6) dedupe ----
            key: Tuple[Any, ...] = (
                room["room_type"],
                room["rate"],
                room["board_type"],
                room["image_url"],
            )
            if key in seen:
                continue
            seen.add(key)
            rooms.append(room)

        if not rooms:
            logger.warning(
                "extract_room_rates: 0 rooms parsed from %s — "
                "check Google anchor class / source URL variant",
                self.source_url,
            )

        for r in rooms:
            r.pop("_hidden", None)

        return rooms

    @staticmethod
    def _normalize_board_type(meta_lower: str, room_type: str) -> str:
        meta: str = meta_lower or ""
        rt: str = (room_type or "").lower()

        if "all inclusive" in meta or "all-inclusive" in meta or "all inclusive" in rt:
            return "All Inclusive"

        if "half board" in meta or "half-board" in meta or "half board" in rt:
            return "Half Board"
        if "full board" in meta or "full-board" in meta or "full board" in rt:
            return "Full Board"

        bnb_signals: Tuple[str, ...] = (
            "breakfast included",
            "breakfast",
            "bed & breakfast",
            "bed and breakfast",
            "b&b",
        )
        if any(s in meta for s in bnb_signals) or any(s in rt for s in bnb_signals):
            return "Bed & Breakfast"

        room_only_signals: Tuple[str, ...] = (
            "room only",
            "no breakfast",
            "without breakfast",
        )
        if any(s in meta for s in room_only_signals) or any(
            s in rt for s in room_only_signals
        ):
            return "Room only"

        # Tightened fallback — only claim Room only when the scope looks
        # like an actual rate card. Otherwise stay Unknown so analytics can
        # tell "genuinely room-only" from "we didn't see the metadata".
        rate_card_signals: Tuple[str, ...] = (
            "cancellation",
            "refundable",
            "rate",
            "per night",
        )
        if any(s in meta for s in rate_card_signals):
            return "Room only"

        return "Unknown"


    @staticmethod
    def _sanitize_string(value: object, max_len: int = 200) -> Optional[str]:
        if value is None:
            return None
        if not isinstance(value, str):
            return None

        if len(value) > max_len:
            return None
        if "<" in value or ">" in value:
            return None
        if '"' in value:
            return None
        if "\\" in value:
            return None
        if "],[" in value or "]]" in value or "[[" in value:
            return None
        if "u003d" in value or "u0026" in value:
            return None
        if "googleusercontent.com" in value:
            return None
        if "gstatic.com" in value:
            return None

        # Trim trailing metadata fragments that bled into the capture.
        for sep in ("\n", "\r", "·", "•", "|"):
            if sep in value:
                value = value.split(sep, 1)[0]

        cleaned: str = value.strip()
        return cleaned if cleaned else None

    @staticmethod
    def _room_match_key(name: str) -> str:
        """Normalize a room title so DOM and JSData versions match."""
        n: str = name.lower().strip()
        suffixes: Tuple[str, ...] = (
            " - flexible rate - including breakfast",
            " - non-refundable rate - including breakfast",
            " - flexible rate",
            " - non-refundable rate",
            " - including breakfast",
            " - room only",
        )
        suffix: str
        for suffix in suffixes:
            if n.endswith(suffix):
                return n[: -len(suffix)].strip()
        return n

    def _iter_jsdata_arrays(self) -> List[str]:
        if self._jsdata_cache is not None:
            return self._jsdata_cache

        blocks: List[str] = []

        anchor: re.Pattern[str] = re.compile(
            r'AF_initDataCallback\s*\(\s*\{[^)]*?\bdata\s*:\s*\[',
            re.DOTALL,
        )
        m: re.Match[str]
        for m in anchor.finditer(self.html):
            start: int = m.end() - 1
            end: int = self._find_matching_bracket(self.html, start)
            if end > start:
                blocks.append(self.html[start:end + 1])

        anchor2: re.Pattern[str] = re.compile(
            r'\{\s*"key"\s*:\s*"ds:[0-9]+"\s*[^{}]*?"data"\s*:\s*\[',
            re.DOTALL,
        )
        for m in anchor2.finditer(self.html):
            start = m.end() - 1
            end = self._find_matching_bracket(self.html, start)
            if end > start:
                blocks.append(self.html[start:end + 1])

        self._jsdata_cache = blocks
        return blocks

    @staticmethod
    def _find_matching_bracket(text: str, start_idx: int) -> int:
        if start_idx >= len(text) or text[start_idx] != "[":
            return -1
        depth: int = 0
        in_str: bool = False
        escape: bool = False
        i: int
        ch: str
        for i in range(start_idx, len(text)):
            ch = text[i]
            if in_str:
                if escape:
                    escape = False
                elif ch == "\\":
                    escape = True
                elif ch == '"':
                    in_str = False
                continue
            if ch == '"':
                in_str = True
            elif ch == "[":
                depth += 1
            elif ch == "]":
                depth -= 1
                if depth == 0:
                    return i
        return -1

    def _walk_json(self, node: Any) -> Iterator[Any]:
        yield node
        if isinstance(node, list):
            items: List[Any] = cast(List[Any], node)
            item: Any
            for item in items:
                yield from self._walk_json(item)
        elif isinstance(node, dict):
            values: Any = cast(Dict[Any, Any], node).values()
            v: Any
            for v in values:
                yield from self._walk_json(v)

    @staticmethod
    def _safe_json_loads(s: str) -> Optional[Any]:
        try:
            result: Any = json.loads(s)
            return result
        except (json.JSONDecodeError, TypeError, ValueError):
            return None

    def extract_providers(self) -> Optional[List[Dict[str, Any]]]:
        from urllib.parse import unquote

        candidates: Dict[str, Dict[str, Any]] = {}

        known_names: Set[str] = {
            "Booking.com", "Agoda", "Trip.com", "Expedia.nl", "Expedia.com",
            "Hotels.com", "Priceline", "Vio.com", "Super.com",
            "Bluepillow.nl", "BusinessHotels.com", "Amimir.com",
            "Tripadvisor.com", "HotelsCombined", "Trivago", "Kayak",
            "HRS", "Tablet Hotels", "Mr & Mrs Smith", "Design Hotels",
            "Hotelbeds", "Travelocity", "Orbitz", "CheapTickets",
            "Hilton", "Marriott", "IHG", "Accor", "Radisson",
            "Hyatt", "Wyndham", "Best Western",
            "Traveluro", "trivago DEALS", "Stayforlong.com",
            "Luxury Escapes", "weloveholidays", "Kiwi.com", "Destinia",
            "Reserving", "Qantas Hotels", "Etrip.net", "Clicktrip.com",
            "goseek.com", "dealbase.com", "Clicktrip",
        }

        block: str
        for block in self._iter_jsdata_arrays():
            m: re.Match[str]
            for m in re.finditer(
                r'\[\s*"([A-Za-z0-9 .&\'\-]+)"\s*,\s*(-?\d+)\s*,\s*"((?:/travel/lodging/clk|/aclk|/url)\?[^"]+)"\s*,\s*\["([^"]+)"\]',
                block,
            ):
                name: str = m.group(1).strip()
                raw_link: str = m.group(3)
                logo: str = m.group(4)

                if name not in known_names:
                    continue

                raw_link = (
                    raw_link.replace("\\u003d", "=")
                    .replace("\\u0026", "&")
                    .replace("\\/", "/")
                )
                logo = (
                    logo.replace("\\u003d", "=")
                    .replace("\\u0026", "&")
                    .replace("\\/", "/")
                )

                if logo.startswith("//"): 
                    logo = "https:" + logo

                real_url: Optional[str] = None

                pcurl: Optional[re.Match[str]] = re.search(r'pcurl=([^&]+)', raw_link)
                if pcurl:
                    real_url = unquote(pcurl.group(1))

                if not real_url:
                    nested: Optional[re.Match[str]] = re.search(
                        r'pcurl%3D([^&]+)', raw_link
                    )
                    if nested:
                        real_url = unquote(unquote(nested.group(1)))

                if not real_url:
                    direct: Optional[re.Match[str]] = re.search(
                        r'(https?://[^&]+)', raw_link
                    )
                    if direct and "google.com" not in direct.group(1):
                        real_url = direct.group(1)

                quality: int
                if (
                    real_url
                    and "google.com" not in real_url
                    and real_url.startswith("http")
                ):
                    quality = 2
                else:
                    quality = 1

                candidate: Dict[str, Any] = {
                    "name": name,
                    "deeplink": real_url or raw_link,
                    "logo_url": logo,
                    "_quality": quality,
                }

                existing: Optional[Dict[str, Any]] = candidates.get(name)
                if existing is None or candidate["_quality"] > existing["_quality"]:
                    candidates[name] = candidate

        if not candidates:
            return None

        result: List[Dict[str, Any]] = []
        c: Dict[str, Any]
        for c in candidates.values():
            c.pop("_quality", None)
            result.append(c)
        return result


    def extract_website_url(self) -> Optional[str]:
        from urllib.parse import urlsplit, urlunsplit, parse_qsl, urlencode

        m: Optional[re.Match[str]] = re.search(
            r'<a[^>]*aria-label="Website"[^>]*href="([^"]+)"', self.html
        )
        if not m:
            m = re.search(
                r'<a[^>]*href="([^"]+)"[^>]*aria-label="Website"', self.html
            )
        if not m:
            return None

        raw: str = html.unescape(m.group(1)).strip()
        if not raw.startswith(("http://", "https://")):
            return None

        parts = urlsplit(raw)
        kept: List[Tuple[str, str]] = [
            (k, v) for k, v in parse_qsl(parts.query)
            if k.lower() not in {"sa", "ved", "usg"}
        ]
        return urlunsplit(
            (parts.scheme, parts.netloc, parts.path, urlencode(kept), parts.fragment)
        ) or None    

    def extract_ota_targets(self) -> Optional[List[Dict[str, Any]]]:
        from urllib.parse import unquote

        results: List[Dict[str, Any]] = []
        seen: Set[str] = set()

        pattern: re.Pattern[str] = re.compile(
            r'<a[^>]*class="[^"]*hUGVEe[^"]*"[^>]*'
            r'href="(/travel/lodging/clk\?[^"]+)"',
            re.DOTALL,
        )

        m: re.Match[str]
        for m in pattern.finditer(self.html):
            raw_href: str = html.unescape(m.group(1))

            pcurl_match: Optional[re.Match[str]] = re.search(r'pcurl=([^&]+)', raw_href)
            if not pcurl_match:
                continue

            decoded: str = unquote(pcurl_match.group(1))
            if not decoded.startswith("http"):
                continue
            if decoded in seen:
                continue
            seen.add(decoded)

            tail: str = self.html[m.end():m.end() + 2500]

            # Provider name: the data-click-type="268" span
            name_m: Optional[re.Match[str]] = re.search(
                r'data-click-type="268">([^<]{1,60})</span>', tail
            )
            provider: str = name_m.group(1).strip() if name_m else "unknown"

            price_m: Optional[re.Match[str]] = re.search(
                r'<span class="iqYCVb">([^<]{1,20})</span>', tail
            )
            price_raw: Optional[str] = self._sanitize_string(
                price_m.group(1).strip(), max_len=20
            ) if price_m else None            


            results.append({
                "provider": provider,
                "google_redirect": "https://www.google.com" + raw_href,
                "decoded_target": decoded,
                "needs_redirect": False,
                "price_raw": price_raw, 
            })

        # Also capture /aclk anchors that carry a pcurl (the "sponsored" OTA tile)
        pattern2: re.Pattern[str] = re.compile(
            r'<a[^>]*href="(/aclk\?[^"]*pcurl=[^"]+)"',
            re.DOTALL,
        )
        for m in pattern2.finditer(self.html):
            raw_href = html.unescape(m.group(1))
            pcurl_match = re.search(r'pcurl=([^&]+)', raw_href)
            if not pcurl_match:
                continue
            decoded = unquote(unquote(pcurl_match.group(1)))
            if not decoded.startswith("http") or decoded in seen:
                continue
            seen.add(decoded)

            tail = self.html[m.end():m.end() + 2500]
            name_m = re.search(r'data-click-type="268">([^<]{1,60})</span>', tail)
            provider = name_m.group(1).strip() if name_m else "unknown"

            # Also grab the price here
            price_m = re.search(r'<span class="iqYCVb">([^<]{1,20})</span>', tail)
            price_raw = self._sanitize_string(
                price_m.group(1).strip(), max_len=20
            ) if price_m else None

            results.append({
                "provider": provider,
                "google_redirect": "https://www.google.com" + raw_href,
                "decoded_target": decoded,
                "needs_redirect": False,
                "price_raw": price_raw,
            })

        return results or None

    def resolve_redirect(
        self,
        google_redirect_url: str,
        timeout: float = 10.0,
    ) -> Optional[str]:
        """
        Follow a Google /travel/lodging/clk or /aclk redirect and return the
        final landing URL after all redirects.

        Google's recommendation: send a browser-like User-Agent and allow
        redirects. The Google endpoint returns a 302 to the OTA, which in turn
        returns 200. This preserves all tracking tokens (pc, s, gclid) that
        some OTAs validate.

        This performs an HTTP request — call it lazily, per-provider, and cache.
        Returns None on any network error or non-2xx final status.
        """
        headers: Dict[str, str] = {
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/120.0.0.0 Safari/537.36"
            ),
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.9",
        }
        try:
            import httpx  
        except ImportError:
            logger.warning("resolve_redirect: httpx not installed")
            return None

        try:
            with httpx.Client(
                follow_redirects=True,
                timeout=timeout,
                headers=headers,
            ) as client:
                resp = client.get(google_redirect_url)
        except httpx.HTTPError as exc:
            logger.debug("resolve_redirect failed for %s: %s", google_redirect_url, exc)
            return None

        if 200 <= resp.status_code < 300:
            return str(resp.url)
        logger.debug(
            "resolve_redirect got %d for %s", resp.status_code, google_redirect_url
        )
        return None

    def extract_room_prices_by_provider(self) -> Optional[List[Dict[str, Any]]]:
        results: List[Dict[str, Any]] = []
        seen: Set[Tuple[str, Tuple[str, ...]]] = set()

        block: str
        for block in self._iter_jsdata_arrays():
            m: re.Match[str]
            for m in re.finditer(
                r'\[\s*"([A-Z][A-Za-z0-9 \-\'&/]+(?:Room|Suite|Apartment|Studio|Villa|Chalet|Loft|Penthouse|Bungalow|Cabin)[A-Za-z0-9 \-\'&/]*)"\s*,\s*\[((?:\["[^"]+"[^\]]*\],?\s*)+)\]',
                block,
            ):
                room_name: str = m.group(1).strip()
                images_blob: str = m.group(2)

                images: List[str] = []
                img_m: re.Match[str]
                for img_m in re.finditer(
                    r'"(https://lh3\.googleusercontent\.com/[^"]+)"', images_blob
                ):
                    u: str = (
                        img_m.group(1)
                        .replace("\\u003d", "=")
                        .replace("\\u0026", "&")
                        .replace("\\/", "/")
                    )
                    if u not in images:
                        images.append(u)

                if not images and not room_name:
                    continue

                tail: str = block[m.end():m.end() + 1500]
                price_m: Optional[re.Match[str]] = re.search(
                    r'\[\s*"([€$£¥₹₩][\d.,]+)"\s*,\s*(?:null|\d+)\s*,\s*([\d.]+)',
                    tail,
                )

                price_obj: Optional[Dict[str, Any]] = None
                if price_m:
                    raw: str = price_m.group(1)
                    amount: Optional[int] = None
                    try:
                        amount = int(float(price_m.group(2)))
                    except ValueError:
                        pass
                    currency: Optional[str] = raw[0] if raw else None
                    price_obj = {
                        "amount": amount,
                        "currency": currency,
                        "raw": raw,
                    }

                key: Tuple[str, Tuple[str, ...]] = (room_name, tuple(images[:1]))
                if key in seen:
                    continue
                seen.add(key)

                results.append({
                    "room_type": room_name,
                    "images": images,
                    "price": price_obj,
                })

        return results or None

    def extract_multi_night_pricing(self) -> Optional[List[Dict[str, Any]]]:
        results: List[Dict[str, Any]] = []
        seen: Set[Tuple[str, str, int]] = set()

        block: str
        for block in self._iter_jsdata_arrays():
            m: re.Match[str]
            for m in re.finditer(
                r'\[\s*\[\s*\[(\d{4}),\s*(\d{1,2}),\s*(\d{1,2})\]\s*,\s*\[(\d{4}),\s*(\d{1,2}),\s*(\d{1,2})\]\s*,\s*(\d+)\s*,\s*(\d+)\s*\]\s*,\s*\d+\s*,\s*"([€$£¥₹₩][\d.,]+)"',
                block,
            ):
                y1: str = m.group(1)
                m1: str = m.group(2)
                d1: str = m.group(3)
                y2: str = m.group(4)
                m2: str = m.group(5)
                d2: str = m.group(6)
                guests: int = int(m.group(7))
                amount_raw: str = m.group(9)

                ci: str = f"{y1}-{int(m1):02d}-{int(d1):02d}"
                co: str = f"{y2}-{int(m2):02d}-{int(d2):02d}"
                key: Tuple[str, str, int] = (ci, co, guests)
                if key in seen:
                    continue
                seen.add(key)

                results.append({
                    "check_in": ci,
                    "check_out": co,
                    "guests": guests,
                    "amount_raw": amount_raw,
                })

        return results or None

    def extract_description(self) -> Optional[str]:
        """
        Extract the hotel's prose description from the 'About this hotel' section.

        Google renders it as:
            <p class="D35lie">Set in a landmark skyscraper...</p>
        inside a <section class="OEscc YFK2Re"> block, but the class names rotate.
        We try the specific class first, then fall back to any <p> in the
        'About this hotel' section that is long enough to be prose.
        """
        # Primary: the D35lie class used in the About block
        m: Optional[re.Match[str]] = re.search(
            r'<p class="D35lie">([^<]{40,2000})</p>', self.html
        )
        if m:
            return self._sanitize_description(m.group(1))

        # Fallback: locate the "About this hotel" heading, then take the first
        # long <p> inside the following ~4000 chars.
        anchor: Optional[re.Match[str]] = re.search(
            r'>\s*About this hotel\s*<', self.html
        )
        if anchor:
            window: str = self.html[anchor.end():anchor.end() + 4000]
            p_match: Optional[re.Match[str]] = re.search(
                r'<p[^>]*>([^<]{40,2000})</p>', window
            )
            if p_match:
                return self._sanitize_description(p_match.group(1))

        return None

    @staticmethod
    def _sanitize_description(value: str) -> Optional[str]:
        """Descriptions may contain unicode punctuation but must not contain tags."""
        if not value:
            return None
        if "<" in value or ">" in value:
            return None
        cleaned: str = html.unescape(value).strip()
        return cleaned if len(cleaned) >= 40 else None

    def build_profile(self) -> Dict[str, Any]:
        rating_info: Dict[str, Optional[Any]] = self.extract_rating_and_reviews()
        check_in_out: Dict[str, Optional[str]] = self.extract_check_in_out()

        profile: Dict[str, Any] = {
            "source_url": self.source_url,
            "property_name": self.extract_property_name(),
            "property_name_alt": self.extract_property_name_alt(),
            "description": self.extract_description(),
            "rating_string": self.extract_rating_string(),
            "rating": rating_info.get("rating"),
            "review_count": rating_info.get("review_count"),
            "address": self.extract_address(),
            "phone": self.extract_phone(),
            "check_in": check_in_out.get("check_in"),
            "check_out": check_in_out.get("check_out"),
            "hotel_feature_id": self.extract_hotel_feature_id(),
            "place_id": self.extract_place_id(),
            "property_url": self.extract_property_url(),
            "website_url": self.extract_website_url(),
            "providers": self.extract_providers(),
            "ota_targets": self.extract_ota_targets(),
            "room_prices_by_provider": self.extract_room_prices_by_provider(),
            "multi_night_pricing": self.extract_multi_night_pricing(),
            "amenities": self.extract_amenities(),
            "room_rates": self.extract_room_rates(),
        }

        # ---- Backfill room_rates[].image_url from room_prices_by_provider ----
        prices_by_provider: List[Dict[str, Any]] = cast(
            List[Dict[str, Any]], profile.get("room_prices_by_provider") or []
        )
        room_rates: List[Dict[str, Any]] = cast(
            List[Dict[str, Any]], profile.get("room_rates") or []
        )

        # Build lookup: normalized room_type -> entry
        by_type: Dict[str, Dict[str, Any]] = {}
        entry: Dict[str, Any]
        for entry in prices_by_provider:
            room_name: object = entry.get("room_type")
            if isinstance(room_name, str) and room_name:
                by_type[self._room_match_key(room_name)] = entry

        # Walk the rates and backfill
        rate: Dict[str, Any]
        for rate in room_rates:
            if rate.get("image_url"):
                continue

            rate_name: object = rate.get("room_type")
            if not isinstance(rate_name, str):
                continue

            match: Optional[Dict[str, Any]] = by_type.get(self._room_match_key(rate_name))
            if match is None:
                continue

            raw_images_obj: object = match.get("images")
            if not isinstance(raw_images_obj, list) or not raw_images_obj:
                continue

            raw_images: List[object] = cast(List[object], raw_images_obj)
            first_image: object = raw_images[0]
            if isinstance(first_image, str) and first_image:
                rate["image_url"] = first_image

        return profile

    def to_json(self) -> str:
        return json.dumps(self.build_profile(), ensure_ascii=False, indent=2)