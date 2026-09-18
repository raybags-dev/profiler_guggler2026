"""
Trip.com OTA parser.

Two-phase:

  Phase 1 — parse the search-results page that Google's deeplink lands on.
  The property ID appears in three places on the page; we majority-vote
  on them to get a confident canonical Trip.com hotel ID. We also pull
  the city ID and city name from the same page, since Trip.com's detail
  URL requires them for the best route.

  Phase 2 — fetch the property detail page. Trip.com renders with Next.js
  App Router, which ships its SSR payload in two forms:

    1. A small `window.__NFES_DATA__ = {...}` object with routing info.
    2. A stream of `<script>self.__next_f.push([1,"..."])</script>` calls
       that together contain the full React Server Component payload —
       which is where the property details actually live.

  We reassemble both and merge them into one `page_props` dict, then
  flatten the fields we care about.

This parser performs no HTTP itself — the manager drives the follow-up.
"""
from __future__ import annotations

import html as html_module
import json
import logging
import re
from collections import Counter
from typing import Any, Dict, List, Optional, Set, Tuple, cast

from profile_plugins.base_parser import BaseOtaParser

from utils.logging_utils import configure_logging, get_logger
configure_logging(level=logging.INFO)
logger = get_logger(__name__)


class TripParser(BaseOtaParser):
    name = "trip_com"

    # -----------------------------------------------------------------
    # Phase 1 — property ID from the search page
    # -----------------------------------------------------------------

    _RE_CARD_ID = re.compile(
        r'<div[^>]*class="[^"]*hotel-card[^"]*"[^>]*id="(\d{4,})"',
    )
    _RE_MASTER_HOTEL_ID = re.compile(
        r'masterhotelid(?:&quot;|")?\s*:\s*"?(\d{4,})"?',
    )
    _RE_FULLURL_HOTEL_ID = re.compile(
        r'hotelid[=%]3?D?(\d{4,})',
    )
    _RE_CITY_ID = re.compile(r'[?&]city[=%]3?D?(\d{2,6})')
    _RE_CITY_EN_NAME = re.compile(
        r'(?:&quot;|")cityEnName(?:&quot;|")\s*:\s*(?:&quot;|")([^"&]{2,80})(?:&quot;|")'
    )

    _RE_CHECKIN = re.compile(r'[?&]checkin=(\d{4}-\d{2}-\d{2})')
    _RE_CHECKOUT = re.compile(r'[?&]checkout=(\d{4}-\d{2}-\d{2})')    

    def _extract_property_id(self, html: str) -> Optional[int]:
        """
        Return the majority-voted Trip.com hotel ID, or None.

        Trip.com emits the ID in multiple spots on the search page. We
        gather every candidate from three patterns and take the mode;
        ties break toward the first candidate seen.
        """
        candidates: List[int] = []

        pattern: re.Pattern[str]
        for pattern in (
            self._RE_CARD_ID,
            self._RE_MASTER_HOTEL_ID,
            self._RE_FULLURL_HOTEL_ID,
        ):
            m: Optional[re.Match[str]] = pattern.search(html)
            if m:
                try:
                    candidates.append(int(m.group(1)))
                except ValueError:
                    pass

        if not candidates:
            return None

        counts: Counter[int] = Counter(candidates)
        value, occurrences = counts.most_common(1)[0]
        if occurrences >= 2:
            return value
        return candidates[0]

    def _extract_city(self, html: str) -> Tuple[Optional[int], Optional[str]]:
        """Return (city_id, city_name) — either or both may be None."""
        city_id: Optional[int] = None
        city_name: Optional[str] = None

        m: Optional[re.Match[str]] = self._RE_CITY_ID.search(html)
        if m:
            try:
                city_id = int(m.group(1))
            except ValueError:
                pass

        m = self._RE_CITY_EN_NAME.search(html)
        if m:
            candidate: str = html_module.unescape(m.group(1)).strip()
            if candidate and not candidate.isdigit() and len(candidate) >= 2:
                city_name = candidate

        return city_id, city_name

    def _extract_dates(self, url: str) -> Tuple[Optional[str], Optional[str]]:
        """Pull checkin / checkout from the provider deeplink, if present."""
        checkin: Optional[str] = None
        checkout: Optional[str] = None

        # Declare the match variables with explicit types so Pylance can
        # narrow them through the `if m:` branch.
        m: Optional[re.Match[str]] = self._RE_CHECKIN.search(url)
        if m is not None:
            checkin = m.group(1)

        m = self._RE_CHECKOUT.search(url)
        if m is not None:
            checkout = m.group(1)

        return checkin, checkout
    
    # -----------------------------------------------------------------
    # Phase 1 — parse
    # -----------------------------------------------------------------
    def parse(self, html: str, source_url: str) -> Dict[str, Any]:
        property_id: Optional[int] = self._extract_property_id(html)
        city_id, city_name = self._extract_city(html)
        checkin, checkout = self._extract_dates(source_url)

        property_url: Optional[str] = None
        if property_id is not None:
            # Extract checkin/checkout from the provider deeplink. If we
            # don't pass them, Trip.com serves a shell payload with no
            # room inventory — rooms live under ssrHotelRoomListResponse
            # and only appear when dates are provided.

            base: str = "https://nl.trip.com/hotels/detail/"
            params: List[str] = [f"hotelId={property_id}"]
            if city_name:
                params.append(f"cityEnName={city_name}")
            if city_id is not None:
                params.append(f"cityId={city_id}")
            if checkin:
                params.append(f"checkIn={checkin}")
            if checkout:
                params.append(f"checkOut={checkout}")

            property_url = base + "?" + "&".join(params)

        return {
            "source_url": source_url,
            "title": self.parse_title(html),
            "og_site_name": self.parse_og_site_name(html),
            "html_length": len(html),

            "trip_property_id": property_id,
            "trip_city_id": city_id,
            "trip_city_name": city_name,
            "trip_property_url": property_url,

            "trip_property_page_url": None,
            "trip_property_page_length": None,
            "trip_property_name": None,
            "trip_property_type": None,
            "trip_checkin": checkin,
            "trip_checkout": checkout,
            "trip_star_rating": None,
            "trip_review_score": None,
            "trip_review_count": None,
            "trip_review_description": None,
            "trip_address": None,
            "trip_city": None,
            "trip_province": None,
            "trip_country": None,
            "trip_lat": None,
            "trip_lng": None,
            "trip_description": None,
            "trip_check_in": None,
            "trip_check_out": None,
            "trip_amenities": None,
            "trip_rooms": None,

            "parse_ok": True,
        }

    # -----------------------------------------------------------------
    # Phase 2 — follow the property URL
    # -----------------------------------------------------------------
    def follow_up_urls(self, parsed: Dict[str, Any]) -> List[str]:
        url: Optional[str] = self._str_or_none(parsed.get("trip_property_url"))
        return [url] if url else []

    def merge_follow_up(
        self,
        parsed: Dict[str, Any],
        url: str,
        html: str,
    ) -> None:
        parsed["trip_property_page_url"] = url
        parsed["trip_property_page_length"] = len(html)

        # Two sources of property data. Both are merged into one dict
        # keyed by the top-level keys Trip.com uses (hotelBaseInfo,
        # hotelPositionInfo, hotelComment, ...).
        merged_props: Dict[str, Any] = {}

        # 1) __NFES_DATA__.props.pageProps — the smaller shell payload.
        nfes: Optional[Dict[str, Any]] = self._extract_nfes_data(html)
        if nfes is not None:
            props_any: Any = nfes.get("props")
            if isinstance(props_any, dict):
                props_dict: Dict[str, Any] = cast(Dict[str, Any], props_any)
                page_props_any: Any = props_dict.get("pageProps")
                if isinstance(page_props_any, dict):
                    page_props: Dict[str, Any] = cast(
                        Dict[str, Any], page_props_any
                    )
                    merged_props.update(page_props)

        # 2) Next.js RSC stream — where the actual detail data lives.
        stream: str = self._extract_next_f_stream(html)
        if stream:
            stream_props: Optional[Dict[str, Any]] = self._extract_stream_props(
                stream
            )
            if stream_props is not None:
                merged_props.update(stream_props)

        if not merged_props:
            logger.warning(
                "trip_com: no property props found in either __NFES_DATA__ "
                "or __next_f stream (html_len=%d)",
                len(html),
            )
            return

        # Dispatch into the field-level extractors.
        self._merge_base_info(parsed, merged_props)
        self._merge_position_info(parsed, merged_props)
        self._merge_review_info(parsed, merged_props)
        self._merge_description(parsed, merged_props)
        self._merge_policies(parsed, merged_props)
        self._merge_facilities(parsed, merged_props)
        self._merge_rooms(parsed, merged_props)

    # -----------------------------------------------------------------
    # NFES_DATA__ extraction
    # -----------------------------------------------------------------
    _RE_NFES_ANCHOR = re.compile(
        r'window\.__NFES_DATA__\s*=\s*(\{)',
    )

    def _extract_nfes_data(self, html: str) -> Optional[Dict[str, Any]]:
        m: Optional[re.Match[str]] = self._RE_NFES_ANCHOR.search(html)
        if not m:
            return None

        start: int = m.start(1)
        end: int = self._find_matching_brace(html, start)
        if end == -1:
            return None

        raw: str = html[start:end + 1]
        try:
            parsed_any: Any = json.loads(raw)
        except json.JSONDecodeError:
            return None

        if not isinstance(parsed_any, dict):
            return None
        return cast(Dict[str, Any], parsed_any)

    # -----------------------------------------------------------------
    # Next.js 13+ RSC stream extraction
    # -----------------------------------------------------------------
    _RE_NEXT_F_PUSH = re.compile(
        r'<script>self\.__next_f\.push\(\[1,\s*"((?:[^"\\]|\\.)*)"\]\)</script>',
    )

    def _extract_next_f_stream(self, html: str) -> str:
        """
        Reassemble the Next.js 13+ streaming payload.

        Each `<script>self.__next_f.push([1,"..."])</script>` carries a
        JSON-string-encoded fragment. Concatenating them yields the full
        server-side data model.
        """
        fragments: List[str] = []
        m: re.Match[str]
        for m in self._RE_NEXT_F_PUSH.finditer(html):
            encoded: str = m.group(1)
            try:
                decoded: str = json.loads(f'"{encoded}"')
                fragments.append(decoded)
            except json.JSONDecodeError:
                continue
        return "".join(fragments)

    def _extract_stream_props(self, stream: str) -> Optional[Dict[str, Any]]:
        """
        Pull the Trip.com property keys out of the RSC stream.

        The stream is a linear sequence of serialized RSC fragments. We
        search for each top-level key we care about and brace-match its
        value. Missing keys yield None rather than crashing.
        """
        out: Dict[str, Any] = {}

        key: str
        for key in (
            "hotelBaseInfo",
            "hotelPositionInfo",
            "hotelComment",
            "hotelDescriptionInfo",
            "hotelPolicyInfo",
            "hotelFacilityPopV2",
            "hotelStatus",
            "hotelHostInfo",
            "ssrHotelRoomListResponse",
            "ssrHotelRoomListRequest",
        ):
            value: Optional[Any] = self._extract_json_value_for_key(stream, key)
            if value is not None:
                out[key] = value

        return out or None

    def _extract_json_value_for_key(
        self, stream: str, key: str
    ) -> Optional[Any]:
        """
        Find `"key":` in the RSC stream and return the JSON value that
        follows, whatever its type.

        The stream escapes quotes as `\\"`, so we have to tolerate both
        forms. Brace/bracket matching handles nested structures.
        """
        pattern: re.Pattern[str] = re.compile(
            rf'(?:\\"|"){re.escape(key)}(?:\\"|")\s*:\s*',
        )
        m: Optional[re.Match[str]] = pattern.search(stream)
        if not m:
            return None

        start: int = m.end()
        if start >= len(stream):
            return None

        first_char: str = stream[start]
        raw: str

        if first_char == "{":
            end: int = self._find_matching_brace(stream, start)
            if end == -1:
                return None
            raw = stream[start:end + 1]
        elif first_char == "[":
            end = self._find_matching_bracket(stream, start)
            if end == -1:
                return None
            raw = stream[start:end + 1]
        elif first_char == '"':
            i: int = start + 1
            while i < len(stream):
                if stream[i] == "\\":
                    i += 2
                    continue
                if stream[i] == '"':
                    break
                i += 1
            else:
                return None
            raw = stream[start:i + 1]
        else:
            j: int = start
            while j < len(stream) and stream[j] not in ",}]":
                j += 1
            raw = stream[start:j]

        # Undo the RSC double-escaping before JSON parsing.
        normalized: str = raw.replace('\\"', '"').replace("\\\\", "\\")

        try:
            return json.loads(normalized)
        except json.JSONDecodeError:
            return None

    # -----------------------------------------------------------------
    # Low-level matchers
    # -----------------------------------------------------------------
    @staticmethod
    def _find_matching_brace(text: str, start_idx: int) -> int:
        if start_idx >= len(text) or text[start_idx] != "{":
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
            elif ch == "{":
                depth += 1
            elif ch == "}":
                depth -= 1
                if depth == 0:
                    return i
        return -1

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

    # -----------------------------------------------------------------
    # Field-level mergers (unchanged logic, correctly indented now)
    # -----------------------------------------------------------------
    def _merge_base_info(
        self,
        parsed: Dict[str, Any],
        page_props: Dict[str, Any],
    ) -> None:
        base_any: Any = page_props.get("hotelBaseInfo")
        if not isinstance(base_any, dict):
            return
        base: Dict[str, Any] = cast(Dict[str, Any], base_any)

        name_info_any: Any = base.get("nameInfo")
        if isinstance(name_info_any, dict):
            name_info: Dict[str, Any] = cast(Dict[str, Any], name_info_any)
            name = self._str_or_none(name_info.get("name"))
            if name:
                parsed["trip_property_name"] = name

        star_any: Any = base.get("starInfo")
        if isinstance(star_any, dict):
            star: Dict[str, Any] = cast(Dict[str, Any], star_any)
            level: Any = star.get("level")
            if isinstance(level, (int, float)):
                parsed["trip_star_rating"] = int(level)

        city = self._str_or_none(base.get("cityName"))
        if city:
            parsed["trip_city"] = city
        province = self._str_or_none(base.get("provinceName"))
        if province:
            parsed["trip_province"] = province
        country = self._str_or_none(base.get("countryName"))
        if country:
            parsed["trip_country"] = country

    def _merge_position_info(
        self,
        parsed: Dict[str, Any],
        page_props: Dict[str, Any],
    ) -> None:
        pos_any: Any = page_props.get("hotelPositionInfo")
        if not isinstance(pos_any, dict):
            return
        pos: Dict[str, Any] = cast(Dict[str, Any], pos_any)

        addr = self._str_or_none(pos.get("address"))
        if addr:
            parsed["trip_address"] = addr

        lat_any: Any = pos.get("lat")
        lng_any: Any = pos.get("lng")
        try:
            if lat_any is not None and lng_any is not None:
                parsed["trip_lat"] = float(lat_any)
                parsed["trip_lng"] = float(lng_any)
        except (TypeError, ValueError):
            pass

    def _merge_review_info(
        self,
        parsed: Dict[str, Any],
        page_props: Dict[str, Any],
    ) -> None:
        comment_any: Any = page_props.get("hotelComment")
        if not isinstance(comment_any, dict):
            return
        comment: Dict[str, Any] = cast(Dict[str, Any], comment_any)

        inner_any: Any = comment.get("comment")
        if not isinstance(inner_any, dict):
            return
        inner: Dict[str, Any] = cast(Dict[str, Any], inner_any)

        score_any: Any = inner.get("score")
        if score_any is not None:
            try:
                parsed["trip_review_score"] = float(score_any)
            except (TypeError, ValueError):
                pass

        count_any: Any = inner.get("totalComment")
        if isinstance(count_any, (int, float)):
            parsed["trip_review_count"] = int(count_any)

        desc = self._str_or_none(inner.get("scoreDescription"))
        if desc:
            parsed["trip_review_description"] = desc

    def _merge_description(
        self,
        parsed: Dict[str, Any],
        page_props: Dict[str, Any],
    ) -> None:
        desc_any: Any = page_props.get("hotelDescriptionInfo")
        if not isinstance(desc_any, dict):
            return
        desc: Dict[str, Any] = cast(Dict[str, Any], desc_any)

        short = self._str_or_none(desc.get("description"))
        if short:
            parsed["trip_description"] = short

    def _merge_policies(
        self,
        parsed: Dict[str, Any],
        page_props: Dict[str, Any],
    ) -> None:
        policy_any: Any = page_props.get("hotelPolicyInfo")
        if not isinstance(policy_any, dict):
            return
        policy: Dict[str, Any] = cast(Dict[str, Any], policy_any)

        cio_any: Any = policy.get("checkInAndOut")
        if not isinstance(cio_any, dict):
            return
        cio: Dict[str, Any] = cast(Dict[str, Any], cio_any)

        contents_any: Any = cio.get("content")
        if not isinstance(contents_any, list):
            return
        contents: List[Any] = cast(List[Any], contents_any)

        entry: Any
        for entry in contents:
            if not isinstance(entry, dict):
                continue
            entry_dict: Dict[str, Any] = cast(Dict[str, Any], entry)
            title = self._str_or_none(entry_dict.get("title")) or ""
            description = self._str_or_none(entry_dict.get("description")) or ""
            title_low = title.lower()
            if "inchecken" in title_low or "check-in" in title_low:
                parsed["trip_check_in"] = description
            elif "uitcheck" in title_low or "check-out" in title_low:
                parsed["trip_check_out"] = description

    def _merge_facilities(
        self,
        parsed: Dict[str, Any],
        page_props: Dict[str, Any],
    ) -> None:
        fac_any: Any = page_props.get("hotelFacilityPopV2")
        if not isinstance(fac_any, dict):
            return
        fac: Dict[str, Any] = cast(Dict[str, Any], fac_any)

        names: List[str] = []
        seen: Set[str] = set()

        flat_any: Any = fac.get("hotelNormalFacilityList")
        if isinstance(flat_any, list):
            flat: List[Any] = cast(List[Any], flat_any)
            item: Any
            for item in flat:
                if not isinstance(item, dict):
                    continue
                item_dict: Dict[str, Any] = cast(Dict[str, Any], item)
                name = self._str_or_none(item_dict.get("facilityDesc"))
                if name and name not in seen:
                    seen.add(name)
                    names.append(name)

        grouped_any: Any = fac.get("hotelFacility")
        if not names and isinstance(grouped_any, list):
            grouped: List[Any] = cast(List[Any], grouped_any)
            group: Any
            for group in grouped:
                if not isinstance(group, dict):
                    continue
                group_dict: Dict[str, Any] = cast(Dict[str, Any], group)
                cat_list_any: Any = group_dict.get("categoryList")
                if not isinstance(cat_list_any, list):
                    continue
                cat_list: List[Any] = cast(List[Any], cat_list_any)
                cat: Any
                for cat in cat_list:
                    if not isinstance(cat, dict):
                        continue
                    cat_dict: Dict[str, Any] = cast(Dict[str, Any], cat)
                    items_any: Any = cat_dict.get("list")
                    if not isinstance(items_any, list):
                        continue
                    items: List[Any] = cast(List[Any], items_any)
                    fac_item: Any
                    for fac_item in items:
                        if not isinstance(fac_item, dict):
                            continue
                        fac_dict: Dict[str, Any] = cast(Dict[str, Any], fac_item)
                        name = self._str_or_none(fac_dict.get("facilityDesc"))
                        if name and name not in seen:
                            seen.add(name)
                            names.append(name)

        if names:
            parsed["trip_amenities"] = names

    def _merge_rooms(
        self,
        parsed: Dict[str, Any],
        page_props: Dict[str, Any],
    ) -> None:
        room_list_any: Any = page_props.get("ssrHotelRoomListResponse")
        if not isinstance(room_list_any, dict):
            return
        room_list: Dict[str, Any] = cast(Dict[str, Any], room_list_any)

        data_any: Any = room_list.get("data")
        if not isinstance(data_any, dict):
            return
        data: Dict[str, Any] = cast(Dict[str, Any], data_any)

        physic_map_any: Any = data.get("physicRoomMap")
        sale_map_any: Any = data.get("saleRoomMap")
        if not isinstance(physic_map_any, dict) or not isinstance(sale_map_any, dict):
            return
        physic_map: Dict[str, Any] = cast(Dict[str, Any], physic_map_any)
        sale_map: Dict[str, Any] = cast(Dict[str, Any], sale_map_any)

        sale_by_physical: Dict[str, List[Dict[str, Any]]] = {}
        code_key: str
        block_any: Any
        for code_key, block_any in sale_map.items():
            if not isinstance(block_any, dict):
                continue
            block: Dict[str, Any] = cast(Dict[str, Any], block_any)
            phys_any: Any = block.get("physicalRoomId")
            if phys_any is None:
                continue
            phys_key: str = str(phys_any)
            slot: List[Dict[str, Any]] = sale_by_physical.setdefault(phys_key, [])

            cancel_any: Any = block.get("cancelInfo")
            payment_any: Any = block.get("paymentInfo")
            price_info_any: Any = block.get("priceInfo")
            total_info_any: Any = block.get("totalPriceInfo")
            guest_any: Any = block.get("guestCountInfo")
            booking_any: Any = block.get("bookingStatusInfo")

            cancel_title: Optional[str] = None
            if isinstance(cancel_any, dict):
                cancel: Dict[str, Any] = cast(Dict[str, Any], cancel_any)
                cancel_title = self._str_or_none(cancel.get("title"))

            payment_title: Optional[str] = None
            if isinstance(payment_any, dict):
                payment: Dict[str, Any] = cast(Dict[str, Any], payment_any)
                payment_title = self._str_or_none(payment.get("subTitle"))

            price_display: Optional[str] = None
            price_value: Optional[float] = None
            if isinstance(price_info_any, dict):
                price_info: Dict[str, Any] = cast(Dict[str, Any], price_info_any)
                price_display = self._str_or_none(price_info.get("displayPrice"))
                price_num_any: Any = price_info.get("price")
                try:
                    if price_num_any is not None:
                        price_value = float(price_num_any)
                except (TypeError, ValueError):
                    pass

            total_display: Optional[str] = None
            if isinstance(total_info_any, dict):
                total_info: Dict[str, Any] = cast(Dict[str, Any], total_info_any)
                total_any: Any = total_info.get("totalV2")
                if isinstance(total_any, dict):
                    total_dict: Dict[str, Any] = cast(Dict[str, Any], total_any)
                    total_display = self._str_or_none(total_dict.get("content"))

            max_guests: Optional[int] = None
            if isinstance(guest_any, dict):
                guest: Dict[str, Any] = cast(Dict[str, Any], guest_any)
                gc_any: Any = guest.get("guestCount")
                if isinstance(gc_any, (int, float)):
                    max_guests = int(gc_any)

            remaining: Optional[int] = None
            if isinstance(booking_any, dict):
                booking: Dict[str, Any] = cast(Dict[str, Any], booking_any)
                rem_any: Any = booking.get("remainRoomQuantity")
                if isinstance(rem_any, (int, float)):
                    remaining = int(rem_any)

            slot.append({
                "room_code": code_key,
                "cancel_policy": cancel_title,
                "payment_method": payment_title,
                "price_display": price_display,
                "price": price_value,
                "total_display": total_display,
                "max_guests": max_guests,
                "rooms_left": remaining,
            })

        rooms: List[Dict[str, Any]] = []
        phys_key: str
        phys_val_any: Any
        for phys_key, phys_val_any in physic_map.items():
            if not isinstance(phys_val_any, dict):
                continue
            phys: Dict[str, Any] = cast(Dict[str, Any], phys_val_any)

            room_name = self._str_or_none(phys.get("name"))
            area_info_any: Any = phys.get("areaInfo")
            area_str: Optional[str] = None
            if isinstance(area_info_any, dict):
                area_dict: Dict[str, Any] = cast(Dict[str, Any], area_info_any)
                area_str = self._str_or_none(area_dict.get("title"))

            bed_info_any: Any = phys.get("bedInfo")
            bed_str: Optional[str] = None
            if isinstance(bed_info_any, dict):
                bed_dict: Dict[str, Any] = cast(Dict[str, Any], bed_info_any)
                bed_str = self._str_or_none(bed_dict.get("title"))

            window_info_any: Any = phys.get("windowInfo")
            window_str: Optional[str] = None
            if isinstance(window_info_any, dict):
                window_dict: Dict[str, Any] = cast(Dict[str, Any], window_info_any)
                window_str = self._str_or_none(window_dict.get("title"))

            rates: List[Dict[str, Any]] = sale_by_physical.get(phys_key, [])
            rooms.append({
                "room_id": phys.get("id"),
                "room_name": room_name,
                "area": area_str,
                "bed": bed_str,
                "window": window_str,
                "rates": rates,
            })

        if rooms:
            parsed["trip_rooms"] = rooms

    # -----------------------------------------------------------------
    # Helpers
    # -----------------------------------------------------------------
    @staticmethod
    def _str_or_none(value: object) -> Optional[str]:
        if isinstance(value, str):
            stripped = value.strip()
            return stripped if stripped else None
        return None