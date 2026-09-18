"""
Booking.com OTA parser.

Two-phase:

  Phase 1 — parse the search-results HTML that Google's deeplink lands on.
  Extract the canonical property URL from the first property card, along
  with the review score/count and distance (those are on the card).

  Phase 2 — follow that canonical property URL. The property page carries
  the full hotel description, star rating, address, coordinates, canonical
  Booking IDs, room inventory with per-rate pricing, and facilities. The
  manager invokes `merge_follow_up` with the fetched HTML.
"""
from __future__ import annotations

import html as html_module
import json
import re
from typing import Any, Dict, List, Optional, Set, Tuple, cast
from urllib.parse import urlsplit, urlunsplit

from profile_plugins.base_parser import BaseOtaParser


class BookingParser(BaseOtaParser):
    name = "booking_com"

    # -----------------------------------------------------------------
    # Phase 1 — search-results page
    # -----------------------------------------------------------------

    _RE_CARD_ARIA = re.compile(
        r'data-testid="property-card"[^>]*?aria-label="([^"]+)"',
    )
    _RE_TITLE_DIV = re.compile(
        r'data-testid="title"[^>]*>([^<]+)</div>',
    )
    _RE_HOTEL_URL = re.compile(
        r'href="(https://www\.booking\.com/hotel/[^"]+)"',
    )
    _RE_REVIEW_LABEL = re.compile(
        r'aria-label="Scored\s+([\d.]+),\s+[^,]+,\s+([\d,]+)\s+reviews?',
    )
    _RE_REVIEW_COUNT_DIV = re.compile(
        r'>([\d,]+)\s+reviews?</div>',
    )
    _RE_DISTANCE = re.compile(
        r'data-testid="distance"[^>]*>([^<]+)</button>',
    )

    # Additional property-page signals
    _RE_ENV_HOTEL_ID = re.compile(
        r"booking\.env\.b_hotel_id\s*=\s*'(\d+)'",
    )
    _RE_ENV_LAT = re.compile(
        r"booking\.env\.b_map_center_latitude\s*=\s*([-\d.]+)",
    )
    _RE_ENV_LNG = re.compile(
        r"booking\.env\.b_map_center_longitude\s*=\s*([-\d.]+)",
    )
    _RE_META_DESC = re.compile(
        r'<meta\s+name="description"\s+content="([^"]{20,2000})"',
        re.IGNORECASE,
    )
    _RE_CANONICAL = re.compile(
        r'<link\s+rel="canonical"\s+href="(https://www\.booking\.com/hotel/[^"]+)"',
        re.IGNORECASE,
    )    

    _RE_CHECKIN = re.compile(r'[?&]checkin=(\d{4}-\d{2}-\d{2})')
    _RE_CHECKOUT = re.compile(r'[?&]checkout=(\d{4}-\d{2}-\d{2})')

    # -----------------------------------------------------------------
    # Phase 2 — property page
    # -----------------------------------------------------------------

    _RE_PROPERTY_NAME = re.compile(
        r'<h2[^>]*class="[^"]*pp-header__title[^"]*"[^>]*>([^<]+)</h2>',
    )
    _RE_PROPERTY_NAME_ALT = re.compile(
        r'<h1[^>]*class="[^"]*pp-header__title[^"]*"[^>]*>([^<]+)</h1>',
    )

    # Address: Booking uses several wrappers. Try the class-hash one first,
    # then fall back to a postcode-shaped heuristic.
    _RE_ADDRESS = re.compile(
        r'<div[^>]*class="[^"]*b99b6ef58f[^"]*"[^>]*>\s*([^<]+?)\s*<div',
    )
    _RE_ADDRESS_HEURISTIC = re.compile(
        r'>([^<]*\d{4}\s+[A-Z]{2}\s+[A-Za-z][^<]{5,200})<',
    )

    _RE_STARS_LABEL = re.compile(
        r'aria-label="(\d)\s+out of 5 stars"',
    )

    _RE_DESCRIPTION = re.compile(
        r'<div[^>]*class="[^"]*hp_desc_main_content[^"]*"[^>]*>'
        r'<p[^>]*>([^<]{40,4000})</p>',
    )

    # Coordinates — appears on the "Check location" anchor.
    _RE_LATLNG = re.compile(
        r'data-atlas-latlng="([-\d.]+),([-\d.]+)"',
    )
    _RE_BBOX = re.compile(
        r'data-atlas-bbox="([-\d.,]+)"',
    )

    # ----------------------------------------------------------------
    # Helper: URL normalization
    # ----------------------------------------------------------------
    @staticmethod
    def _clean_booking_url(raw: str) -> Optional[str]:
        """Strip tracking/query params, keep only the canonical path."""
        if not raw.startswith("https://www.booking.com/hotel/"):
            return None
        parts = urlsplit(html_module.unescape(raw))
        return urlunsplit((parts.scheme, parts.netloc, parts.path, "", ""))

    @staticmethod
    def _country_from_url(url: str) -> Optional[str]:
        """Extract the ISO country code from /hotel/<cc>/..."""
        m = re.search(r"/hotel/([a-z]{2})/", url)
        return m.group(1) if m else None

    @staticmethod
    def _int_or_none(value: Optional[str]) -> Optional[int]:
        if not value:
            return None
        try:
            return int(value)
        except (TypeError, ValueError):
            return None

    @staticmethod
    def _str_or_none(value: object) -> Optional[str]:
        """Narrow an unknown-shaped value to a str or None."""
        if isinstance(value, str):
            return value
        return None

    @staticmethod
    def _get_str(mapping: Dict[str, Any], key: str) -> Optional[str]:
        """Fetch a string field from a possibly-unknown dict."""
        return BookingParser._str_or_none(mapping.get(key))

    # ----------------------------------------------------------------
    # Phase 1 helpers
    # ----------------------------------------------------------------
    def _extract_property_name(self, html: str) -> Optional[str]:
        m = self._RE_CARD_ARIA.search(html)
        if m:
            name = html_module.unescape(m.group(1)).strip()
            if name.endswith(", Property"):
                name = name[: -len(", Property")].strip()
            if name:
                return name

        m = self._RE_TITLE_DIV.search(html)
        if m:
            name = html_module.unescape(m.group(1)).strip()
            if name:
                return name
        return None

    def _extract_review_info(
        self, html: str
    ) -> Tuple[Optional[float], Optional[int]]:
        score: Optional[float] = None
        count: Optional[int] = None

        m = self._RE_REVIEW_LABEL.search(html)
        if m:
            try:
                score = float(m.group(1))
            except ValueError:
                pass
            try:
                count = int(m.group(2).replace(",", ""))
            except ValueError:
                pass
            if score is not None or count is not None:
                return score, count

        m2 = self._RE_REVIEW_COUNT_DIV.search(html)
        if m2:
            try:
                count = int(m2.group(1).replace(",", ""))
            except ValueError:
                pass
        return score, count

    def _extract_env_hotel_id(self, html: str) -> Optional[str]:
        m = self._RE_ENV_HOTEL_ID.search(html)
        return m.group(1) if m else None

    def _extract_env_coords(
        self, html: str
    ) -> Optional[Tuple[float, float]]:
        lat_m = self._RE_ENV_LAT.search(html)
        lng_m = self._RE_ENV_LNG.search(html)
        if not (lat_m and lng_m):
            return None
        try:
            return float(lat_m.group(1)), float(lng_m.group(1))
        except ValueError:
            return None

    def _extract_meta_description(self, html: str) -> Optional[str]:
        m = self._RE_META_DESC.search(html)
        if not m:
            return None
        text = html_module.unescape(m.group(1)).strip()
        return text if text else None

    def _extract_canonical_url(self, html: str) -> Optional[str]:
        m = self._RE_CANONICAL.search(html)
        if not m:
            return None
        return self._clean_booking_url(m.group(1))    
    # ----------------------------------------------------------------
    # Phase 2 helpers — meta
    # ----------------------------------------------------------------
    def _extract_address(self, html: str) -> Optional[str]:
        m = self._RE_ADDRESS.search(html)
        if m:
            addr = html_module.unescape(m.group(1)).strip()
            if addr:
                return addr

        m = self._RE_ADDRESS_HEURISTIC.search(html)
        if m:
            addr = html_module.unescape(m.group(1)).strip()
            if addr:
                return addr
        return None

    def _extract_coordinates(
        self, html: str
    ) -> Optional[Tuple[float, float]]:
        m = self._RE_LATLNG.search(html)
        if not m:
            return None
        try:
            return float(m.group(1)), float(m.group(2))
        except ValueError:
            return None

    def _extract_bbox(self, html: str) -> Optional[List[float]]:
        m = self._RE_BBOX.search(html)
        if not m:
            return None
        parts: List[str] = m.group(1).split(",")
        out: List[float] = []
        part: str
        for part in parts:
            try:
                out.append(float(part))
            except ValueError:
                return None
        return out or None

    # ----------------------------------------------------------------
    # Phase 2 helpers — hprt-form
    # ----------------------------------------------------------------
    def _extract_hprt_form(self, html: str) -> Dict[str, str]:
        m = re.search(
            r'<form\s+id="hprt-form"[^>]*>([\s\S]*?)</form>',
            html,
        )
        if not m:
            return {}
        form_html: str = m.group(1)
        out: Dict[str, str] = {}
        inp: re.Match[str]
        for inp in re.finditer(
            r'<input[^>]*type="hidden"[^>]*name="([^"]+)"[^>]*value="([^"]*)"',
            form_html,
        ):
            out[inp.group(1)] = html_module.unescape(inp.group(2))
        return out

    # ----------------------------------------------------------------
    # Phase 2 helpers — facilities
    # ----------------------------------------------------------------
    def _extract_facilities(self, html: str) -> List[str]:
        """
        Booking renders each facility as:
            <span class="hprt-facilities-facility" data-name-en="Wi-Fi">…</span>
        or with an empty data-name-en and the label in visible text:
            <div class="hprt-facilities-facility" data-name-en="">
                <span class="bui-badge ...">15 m²</span>
            </div>
        We capture both, deduped.
        """
        out: List[str] = []
        seen: Set[str] = set()

        # Pattern A — data-name-en with visible text inside the same element
        m: re.Match[str]
        for m in re.finditer(
            r'<(?:div|span)[^>]*class="[^"]*hprt-facilities-facility[^"]*"[^>]*'
            r'data-name-en="([^"]*)"[^>]*>([^<]*)<',
            html,
        ):
            name: str = m.group(1).strip()
            text: str = html_module.unescape(m.group(2)).strip()
            label: str = name or text
            if label and label not in seen:
                seen.add(label)
                out.append(label)

        # Pattern B — data-name-en on a <span> followed by visible text
        for m in re.finditer(
            r'<span[^>]*class="[^"]*hprt-facilities-facility[^"]*"[^>]*'
            r'data-name-en="([^"]+)"[^>]*>([^<]+)</span>',
            html,
        ):
            name = m.group(1).strip()
            if name and name not in seen:
                seen.add(name)
                out.append(name)

        return out

    # ----------------------------------------------------------------
    # Phase 2 helpers — room inventory JSON
    # ----------------------------------------------------------------
    @staticmethod
    def _find_matching_bracket(text: str, start_idx: int) -> int:
        """Given the index of an opening [ in `text`, return the index of its match."""
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

    def _extract_rooms_json(
        self, html: str
    ) -> Optional[List[Dict[str, Any]]]:
        """
        Extract the `b_rooms_available_and_soldout` JSON blob from the
        property page and slim it down to the fields we care about.
        """
        marker: str = "b_rooms_available_and_soldout"
        idx: int = html.find(marker)
        if idx == -1:
            return None

        start: int = html.find("[", idx)
        if start == -1:
            return None

        end: int = self._find_matching_bracket(html, start)
        if end == -1:
            return None

        raw: str = html[start:end + 1]
        parsed_any: Any = None
        try:
            parsed_any = json.loads(raw)
        except json.JSONDecodeError:
            return None

        if not isinstance(parsed_any, list):
            return None

        # Pin the type: JSON arrays decode to List[Any], so cast for clarity.
        rooms_data: List[Any] = cast(List[Any], parsed_any)

        out: List[Dict[str, Any]] = []
        room: Any
        for room in rooms_data:
            if not isinstance(room, dict):
                continue
            room_dict: Dict[str, Any] = cast(Dict[str, Any], room)

            blocks_raw_any: Any = room_dict.get("b_blocks")
            blocks_raw: List[Any] = (
                cast(List[Any], blocks_raw_any)
                if isinstance(blocks_raw_any, list)
                else []
            )

            slim_blocks: List[Dict[str, Any]] = []
            blk: Any
            for blk in blocks_raw:
                if not isinstance(blk, dict):
                    continue
                blk_dict: Dict[str, Any] = cast(Dict[str, Any], blk)

                breakdown_any: Any = blk_dict.get("b_price_breakdown_simplified")
                breakdown: Dict[str, Any] = (
                    cast(Dict[str, Any], breakdown_any)
                    if isinstance(breakdown_any, dict)
                    else {}
                )

                total_arr_any: Any = breakdown.get("b_total_price")
                net_arr_any: Any = breakdown.get("b_net_room_price")
                incl_arr_any: Any = breakdown.get("b_included_charges")

                total_arr: List[Any] = (
                    cast(List[Any], total_arr_any)
                    if isinstance(total_arr_any, list)
                    else []
                )
                net_arr: List[Any] = (
                    cast(List[Any], net_arr_any)
                    if isinstance(net_arr_any, list)
                    else []
                )
                incl_arr: List[Any] = (
                    cast(List[Any], incl_arr_any)
                    if isinstance(incl_arr_any, list)
                    else []
                )

                total_price: Optional[str] = None
                if total_arr:
                    first_any: Any = total_arr[0]
                    if isinstance(first_any, dict):
                        first_dict: Dict[str, Any] = cast(Dict[str, Any], first_any)
                        v: Any = first_dict.get("b_value_user_currency")
                        if isinstance(v, str):
                            total_price = v

                net_room_price: Optional[str] = None
                if net_arr:
                    first_any = net_arr[0]
                    if isinstance(first_any, dict):
                        first_dict = cast(Dict[str, Any], first_any)
                        v = first_dict.get("b_value")
                        if isinstance(v, str):
                            net_room_price = v

                included: List[Dict[str, Any]] = []
                charge: Any
                for charge in incl_arr:
                    if not isinstance(charge, dict):
                        continue
                    charge_dict: Dict[str, Any] = cast(Dict[str, Any], charge)
                    included.append({
                        "name": self._str_or_none(charge_dict.get("b_copy")),
                        "value": self._str_or_none(charge_dict.get("b_value")),
                    })

                slim_blocks.append({
                    "block_id": self._str_or_none(blk_dict.get("b_block_id")),
                    "price": self._str_or_none(blk_dict.get("b_raw_price")),
                    "price_display": self._str_or_none(blk_dict.get("b_price")),
                    "avg_per_night_eur": self._str_or_none(
                        blk_dict.get("b_avg_price_per_night_eur")
                    ),
                    "cancellation_type": self._str_or_none(
                        blk_dict.get("b_cancellation_type")
                    ),
                    "meal_plan": self._str_or_none(
                        blk_dict.get("b_mealplan_included_name")
                    ),
                    "max_persons": blk_dict.get("b_max_persons"),
                    "nr_stays": blk_dict.get("b_nr_stays"),
                    "is_genius": blk_dict.get("b_rate_is_genius"),
                    "total_price": total_price,
                    "net_room_price": net_room_price,
                    "included_charges": included,
                })

            out.append({
                "room_id": room_dict.get("b_id"),
                "room_type_id": room_dict.get("b_roomtype_id"),
                "room_name": self._str_or_none(room_dict.get("b_name")),
                "has_inventory": room_dict.get("b_has_room_inventory"),
                "blocks": slim_blocks,
            })

        return out or None

    # ----------------------------------------------------------------
    # Phase 1 — parse the search page
    # ----------------------------------------------------------------
    def parse(self, html: str, source_url: str) -> Dict[str, Any]:
        property_name: Optional[str] = self._extract_property_name(html)

        url_m: Optional[re.Match[str]] = self._RE_HOTEL_URL.search(html)
        property_url: Optional[str] = None
        country: Optional[str] = None
        if url_m:
            property_url = self._clean_booking_url(url_m.group(1))
            if property_url:
                country = self._country_from_url(property_url)

        review_score, review_count = self._extract_review_info(html)

        dist_m: Optional[re.Match[str]] = self._RE_DISTANCE.search(html)
        distance: Optional[str] = (
            html_module.unescape(dist_m.group(1)).strip() if dist_m else None
        )

        return {
            "source_url": source_url,
            "title": self.parse_title(html),
            "og_site_name": self.parse_og_site_name(html),
            "html_length": len(html),

            # From the search card
            "booking_property_name": property_name,
            "booking_property_url": property_url,
            "booking_country": country,
            "booking_review_score": review_score,
            "booking_review_count": review_count,
            "booking_distance_from_centre": distance,

            # Filled by phase 2
            "booking_star_rating": None,
            "booking_address": None,
            "booking_description": None,
            "booking_lat": None,
            "booking_lng": None,
            "booking_bbox": None,
            "booking_hotel_id": None,
            "booking_sid": None,
            "booking_room_count": None,
            "booking_rate_block_count": None,
            "booking_cheapest_price_raw": None,
            "booking_rooms": None,
            "booking_facilities": None,
            "booking_property_page_url": None,
            "booking_property_page_length": None,

            "parse_ok": True,
        }

    # ----------------------------------------------------------------
    # Phase 2 — follow the property URL
    # ----------------------------------------------------------------
    def follow_up_urls(self, parsed: Dict[str, Any]) -> List[str]:
        url: Optional[str] = self._str_or_none(parsed.get("booking_property_url"))
        return [url] if url else []

    def merge_follow_up(
        self,
        parsed: Dict[str, Any],
        url: str,
        html: str,
    ) -> None:
        parsed["booking_property_page_url"] = url
        parsed["booking_property_page_length"] = len(html)

        # --- property name ---
        name_m: Optional[re.Match[str]] = (
            self._RE_PROPERTY_NAME.search(html)
            or self._RE_PROPERTY_NAME_ALT.search(html)
        )
        if name_m:
            parsed["booking_property_name"] = html_module.unescape(
                name_m.group(1)
            ).strip()

        # --- canonical URL cross-check (fallback if the search card missed) ---
        canonical = self._extract_canonical_url(html)
        if canonical and not parsed.get("booking_property_url"):
            parsed["booking_property_url"] = canonical
            parsed["booking_country"] = self._country_from_url(canonical)

        # --- address ---
        addr = self._extract_address(html)
        if addr:
            parsed["booking_address"] = addr

        # --- coordinates: data-atlas-latlng is primary, booking.env fallback ---
        coords = self._extract_coordinates(html)
        if coords:
            parsed["booking_lat"] = coords[0]
            parsed["booking_lng"] = coords[1]
        else:
            env_coords = self._extract_env_coords(html)
            if env_coords:
                parsed["booking_lat"] = env_coords[0]
                parsed["booking_lng"] = env_coords[1]

        bbox = self._extract_bbox(html)
        if bbox:
            parsed["booking_bbox"] = bbox

        # --- star rating ---
        stars_m = self._RE_STARS_LABEL.search(html)
        if stars_m:
            try:
                parsed["booking_star_rating"] = int(stars_m.group(1))
            except ValueError:
                pass

        # --- description: main content first, meta description fallback ---
        desc_m = self._RE_DESCRIPTION.search(html)
        if desc_m:
            parsed["booking_description"] = html_module.unescape(
                desc_m.group(1)
            ).strip()
        else:
            meta_desc = self._extract_meta_description(html)
            if meta_desc:
                parsed["booking_description"] = meta_desc

        # --- hprt-form: canonical IDs + stay metadata ---
        form = self._extract_hprt_form(html)
        if form:
            parsed["booking_hotel_id"] = form.get("hotel_id")
            parsed["booking_sid"] = form.get("sid")
            parsed["booking_room_count"] = self._int_or_none(
                form.get("rt_num_rooms")
            )
            parsed["booking_rate_block_count"] = self._int_or_none(
                form.get("rt_num_blocks")
            )
            parsed["booking_cheapest_price_raw"] = self._int_or_none(
                form.get("rt_cheapest_search_price")
            )

        # --- hotel_id fallback from booking.env ---
        if not parsed.get("booking_hotel_id"):
            env_id = self._extract_env_hotel_id(html)
            if env_id:
                parsed["booking_hotel_id"] = env_id

        # --- room inventory + per-rate pricing ---
        rooms = self._extract_rooms_json(html)
        if rooms:
            parsed["booking_rooms"] = rooms

        # --- facilities ---
        facilities = self._extract_facilities(html)
        if facilities:
            parsed["booking_facilities"] = facilities