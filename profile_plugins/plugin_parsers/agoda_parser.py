"""
Agoda.com OTA parser.

Two-phase:

  Phase 1 — parse the search-page HTML that Google's deeplink lands on.
  Agoda serves a JS shell for the search page, but the property ID and
  session metadata are embedded across three inline scripts:
    - "SelectedHotelId":NNNNN
    - {"PropertyId":NNNNN,
    - "mseHotelIds":[NNNNN]
  We extract all three candidates, majority-vote on the ID, then expose
  a canonical property URL for phase 2.

  Phase 2 — follow that URL. The property detail page carries the rich
  JSON payload (`agoda.pageConfig`, embedded schema.org data, review
  scores, facilities, coordinates, room inventory). `merge_follow_up`
  walks it.
"""
from __future__ import annotations

import html as html_module
import json
import re
from collections import Counter
from typing import Any, Dict, List, Optional, Tuple, cast

from profile_plugins.base_parser import BaseOtaParser


class AgodaParser(BaseOtaParser):
    name = "agoda_com"

    # -----------------------------------------------------------------
    # Phase 1 — property ID
    # -----------------------------------------------------------------
    _RE_SELECTED_HOTEL_ID = re.compile(r'"SelectedHotelId"\s*:\s*(\d+)')
    _RE_PROPERTY_ID = re.compile(r'\{\s*"PropertyId"\s*:\s*(\d+)')
    _RE_MSE_HOTEL_IDS = re.compile(r'"mseHotelIds"\s*:\s*\[\s*(\d+)')

    def _extract_property_id(self, html: str) -> Optional[int]:
        """Majority vote across three candidate sources."""
        candidates: List[int] = []
        for pattern in (
            self._RE_SELECTED_HOTEL_ID,
            self._RE_PROPERTY_ID,
            self._RE_MSE_HOTEL_IDS,
        ):
            m = pattern.search(html)
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

    # -----------------------------------------------------------------
    # Phase 1 — inline page config
    # -----------------------------------------------------------------
    # Agoda emits `agoda.pageConfig = {...}` with a large object. We
    # bracket-match instead of regex-parsing to handle nested braces
    # inside the object safely.
    _MARKER_PAGE_CONFIG = "agoda.pageConfig"

    def _extract_page_config(self, html: str) -> Optional[Dict[str, Any]]:
        """Parse the inline `agoda.pageConfig = {...}` object."""
        idx = html.find(self._MARKER_PAGE_CONFIG)
        if idx == -1:
            return None

        eq = html.find("=", idx)
        if eq == -1:
            return None

        brace = html.find("{", eq)
        if brace == -1:
            return None

        end = self._find_matching_brace(html, brace)
        if end == -1:
            return None

        raw = html[brace:end + 1]
        try:
            parsed_any: Any = json.loads(raw)
        except (json.JSONDecodeError, ValueError):
            return None

        if not isinstance(parsed_any, dict):
            return None

        parsed: Dict[str, Any] = cast(Dict[str, Any], parsed_any)

        keys: List[str] = [
            # session / identity
            "cid", "sessionId", "userId", "correlationId",
            "analyticsSessionId", "storefrontId", "whitelabelid",
            "whiteLabelId", "trafficGroupId", "trafficSubGroupId",
            # locale / currency
            "currencyCode", "currencyDisplay", "cultureInfoName",
            "htmlLanguage", "languageId", "realLanguageId", "origin",
            # page identity
            "pageTypeId", "urlMappingId", "subTypeId", "propertyId",
            # stay params
            "adults", "children", "rooms",
            # feature flags
            "isPackages", "isDayUseFunnel", "appVersion",
            "removeMachineName", "isMaintenanceBannerEnabled",
        ]
        slim: Dict[str, Any] = {
            k: parsed.get(k) for k in keys if k in parsed
        }
        return slim or None

    @staticmethod
    def _find_matching_brace(text: str, start_idx: int) -> int:
        """Given an opening { in `text`, return the index of its match."""
        if start_idx >= len(text) or text[start_idx] != "{":
            return -1
        depth = 0
        in_str = False
        escape = False
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

    # -----------------------------------------------------------------
    # Phase 1 — parse
    # -----------------------------------------------------------------
    def parse(self, html: str, source_url: str) -> Dict[str, Any]:
        property_id: Optional[int] = self._extract_property_id(html)
        property_url: Optional[str] = (
            f"https://www.agoda.com/en-gb/accom/property"
            f"?propertyId={property_id}"
            if property_id is not None
            else None
        )

        return {
            "source_url": source_url,
            "title": self.parse_title(html),
            "og_site_name": self.parse_og_site_name(html),
            "html_length": len(html),

            "agoda_property_id": property_id,
            "agoda_property_url": property_url,
            "agoda_page_config": self._extract_page_config(html),

            # Filled by phase 2
            "agoda_property_page_url": None,
            "agoda_property_page_length": None,
            "agoda_property_name": None,
            "agoda_property_stars": None,
            "agoda_review_score": None,
            "agoda_review_count": None,
            "agoda_lat": None,
            "agoda_lng": None,
            "agoda_address": None,
            "agoda_description": None,
            "agoda_facilities": None,
            "agoda_images": None,
            "agoda_rooms": None,

            "parse_ok": True,
        }

    # -----------------------------------------------------------------
    # Phase 2 — follow-up
    # -----------------------------------------------------------------
    def follow_up_urls(self, parsed: Dict[str, Any]) -> List[str]:
        url_any: Any = parsed.get("agoda_property_url")
        if isinstance(url_any, str) and url_any:
            return [url_any]
        return []

    @staticmethod
    def _pick_jsonld_property(
        blocks: List[Dict[str, Any]],
    ) -> Dict[str, Any]:
        """Return the JSON-LD block whose @type is Hotel/LodgingBusiness."""
        block: Dict[str, Any]
        for block in blocks:
            t: Any = block.get("@type")
            if isinstance(t, str) and t in (
                "Hotel", "LodgingBusiness", "Resort", "Hostel",
                "Motel", "BedAndBreakfast",
            ):
                return block
            if isinstance(t, list):
                types: List[Any] = cast(List[Any], t)
                entry: Any
                for entry in types:
                    if isinstance(entry, str) and entry in (
                        "Hotel", "LodgingBusiness", "Resort", "Hostel",
                        "Motel", "BedAndBreakfast",
                    ):
                        return block
        # No Hotel-typed block found — return the first non-empty one
        if blocks:
            return blocks[0]
        return {}

    def merge_follow_up(
        self,
        parsed: Dict[str, Any],
        url: str,
        html: str,
    ) -> None:
        """
        Follow-up fetch of the Agoda property page.

        The property page is a React shell — the initial HTML contains no
        review scores, coordinates, address, description, facilities, or
        room inventory. Those are loaded by JS from a GraphQL endpoint
        after render. We keep the follow-up because:

          1. It confirms the property URL resolves (a 200 with a
             300 KB+ body proves the session is alive).
          2. It gives us a second `agoda.pageConfig` blob, which we can
             merge over the one from the search page for fresher session
             metadata.

        Fields that would require JS rendering or a GraphQL call are left
        as None. To populate them, swap `AgodaClient.fetch` for a
        Playwright-based client, or enrich manually via the GraphQL
        endpoint captured in `tools/`.
        """
        parsed["agoda_property_page_url"] = url
        parsed["agoda_property_page_length"] = len(html)

        # Merge the richer pageConfig from the property page (if present)
        # over the one from the search page.
        detail_config: Optional[Dict[str, Any]] = self._extract_page_config(html)
        if detail_config:
            existing_any: Any = parsed.get("agoda_page_config")
            if isinstance(existing_any, dict):
                existing: Dict[str, Any] = cast(Dict[str, Any], existing_any)
                merged_config: Dict[str, Any] = dict(existing)
                merged_config.update(detail_config)
                parsed["agoda_page_config"] = merged_config
            else:
                parsed["agoda_page_config"] = detail_config

        # Backfill the property ID if the search page didn't find it.
        if not parsed.get("agoda_property_id"):
            new_id: Optional[int] = self._extract_property_id(html)
            if new_id is not None:
                parsed["agoda_property_id"] = new_id
    # -----------------------------------------------------------------
    # Phase 2 helpers — extract from the detail page
    # -----------------------------------------------------------------

    # -----------------------------------------------------------------
    # Phase 2 helpers — extract from the detail page
    # -----------------------------------------------------------------

    # JSON-LD blocks — the most reliable source for structured fields
    # (name, stars, aggregateRating, geo, address). Agoda embeds them as
    # `<script type="application/ld+json">{...}</script>`.
    _RE_LD_JSON = re.compile(
        r'<script[^>]*type="application/ld\+json"[^>]*>([\s\S]*?)</script>',
    )

    # Property name — appears in a few places; the og:title is the cleanest
    _RE_OG_TITLE = re.compile(
        r'<meta\s+property="og:title"\s+content="([^"]{3,200})"',
        re.IGNORECASE,
    )
    _RE_H1 = re.compile(r'<h1[^>]*>([^<]{3,200})</h1>')


    def _extract_property_name(self, html: str) -> Optional[str]:
        m = self._RE_OG_TITLE.search(html)
        if m:
            return html_module.unescape(m.group(1)).strip()
        m = self._RE_H1.search(html)
        if m:
            return html_module.unescape(m.group(1)).strip()
        return None

    # Star rating — Agoda emits "starRating" in JSON-LD schema.org data
    _RE_STARS_JSONLD = re.compile(r'"starRating"\s*:\s*\{[^}]*?"ratingValue"\s*:\s*"?(\d+(?:\.\d+)?)"?')
    _RE_STARS_TEXT = re.compile(r'(\d)\s*-?\s*star\s+property', re.IGNORECASE)

    def _extract_star_rating(self, html: str) -> Optional[int]:
        m = self._RE_STARS_JSONLD.search(html)
        if m:
            try:
                return int(float(m.group(1)))
            except ValueError:
                pass
        m = self._RE_STARS_TEXT.search(html)
        if m:
            try:
                return int(m.group(1))
            except ValueError:
                pass
        return None

    # Review score + count — schema.org aggregateRating
    _RE_AGG_RATING = re.compile(
        r'"aggregateRating"\s*:\s*\{[^}]*?'
        r'"ratingValue"\s*:\s*"?([\d.]+)"?[^}]*?'
        r'"reviewCount"\s*:\s*"?(\d+)"?',
        re.DOTALL,
    )
    # Fallback: text pattern like "8.9 Excellent · 1,015 reviews"
    _RE_REVIEW_TEXT = re.compile(
        r'(\d(?:\.\d)?)\s+[A-Z][^<]{0,40}?(\d[\d,]+)\s+reviews?',
    )

    def _extract_review_info(
        self, html: str
    ) -> Tuple[Optional[float], Optional[int]]:
        m = self._RE_AGG_RATING.search(html)
        if m:
            try:
                score = float(m.group(1))
            except ValueError:
                score = None
            try:
                count = int(m.group(2).replace(",", ""))
            except ValueError:
                count = None
            if score is not None or count is not None:
                return score, count

        m = self._RE_REVIEW_TEXT.search(html)
        if m:
            try:
                return (
                    float(m.group(1)),
                    int(m.group(2).replace(",", "")),
                )
            except ValueError:
                pass
        return None, None

    # Coordinates — schema.org geo block or booking.env-style
    _RE_GEO = re.compile(
        r'"geo"\s*:\s*\{[^}]*?'
        r'"latitude"\s*:\s*"?([-\d.]+)"?[^}]*?'
        r'"longitude"\s*:\s*"?([-\d.]+)"?',
        re.DOTALL,
    )
    _RE_LATLNG = re.compile(
        r'"latitude"\s*:\s*"?([-\d.]+)"?\s*,\s*"longitude"\s*:\s*"?([-\d.]+)"?',
    )

    def _extract_coordinates(
        self, html: str
    ) -> Optional[Tuple[float, float]]:
        for pattern in (self._RE_GEO, self._RE_LATLNG):
            m = pattern.search(html)
            if m:
                try:
                    return float(m.group(1)), float(m.group(2))
                except ValueError:
                    continue
        return None

    # Address — schema.org address block
    _RE_ADDRESS = re.compile(
        r'"address"\s*:\s*\{[^}]*?'
        r'"streetAddress"\s*:\s*"([^"]{3,200})"',
        re.DOTALL,
    )
    _RE_ADDRESS_ALT = re.compile(
        r'"addressLocality"\s*:\s*"([^"]{3,80})"',
    )

    def _extract_address(self, html: str) -> Optional[str]:
        m = self._RE_ADDRESS.search(html)
        if m:
            return html_module.unescape(m.group(1)).strip()
        m = self._RE_ADDRESS_ALT.search(html)
        if m:
            return html_module.unescape(m.group(1)).strip()
        return None

    # Description — schema.org description
    _RE_DESCRIPTION = re.compile(
        r'<meta\s+property="og:description"\s+content="([^"]{40,2000})"',
        re.IGNORECASE,
    )
    _RE_DESCRIPTION_ALT = re.compile(
        r'"description"\s*:\s*"([^"]{40,2000})"',
    )

    def _extract_description(self, html: str) -> Optional[str]:
        for pattern in (self._RE_DESCRIPTION, self._RE_DESCRIPTION_ALT):
            m = pattern.search(html)
            if m:
                text = html_module.unescape(m.group(1)).strip()
                # Skip generic "Book at Agoda" boilerplate
                if text and "agoda.com" not in text.lower():
                    return text
        return None

    # Facilities — Agoda emits amenity lists in a few places. The
    # cleanest signal is `data-selenium="hotel-facilities-item"` with a
    # span carrying the amenity name.
    _RE_FACILITY = re.compile(
        r'data-selenium="[^"]*facility[^"]*"[^>]*>'
        r'[^<]*<[^>]*>([^<]{2,80})</',
        re.IGNORECASE,
    )
    _RE_FACILITY_ALT = re.compile(
        r'"facilityName"\s*:\s*"([^"]{2,80})"',
    )

    def _extract_facilities(self, html: str) -> List[str]:
        out: List[str] = []
        seen: set[str] = set()

        for pattern in (self._RE_FACILITY, self._RE_FACILITY_ALT):
            for m in pattern.finditer(html):
                name = html_module.unescape(m.group(1)).strip()
                if name and name not in seen:
                    seen.add(name)
                    out.append(name)

        return out

    # Images — Agoda embeds property photos as https://pix*.agoda.net/...
    _RE_IMAGE = re.compile(
        r'"(https://pix\d*\.agoda\.net/[^"]+\.(?:jpg|jpeg|png|webp))"',
        re.IGNORECASE,
    )

    def _extract_images(self, html: str) -> List[str]:
        out: List[str] = []
        seen: set[str] = set()
        for m in self._RE_IMAGE.finditer(html):
            url = m.group(1)
            if url not in seen:
                seen.add(url)
                out.append(url)
            if len(out) >= 30:   # cap
                break
        return out

    # Rooms — Agoda emits room data inside a JSON structure with keys
    # like "roomName" / "roomId". This is a best-effort extractor; if the
    # markup changes, it degrades to [].
    _MARKER_ROOMS = "agoda.accomFeatures"

    def _extract_rooms(self, html: str) -> Optional[List[Dict[str, Any]]]:
        """
        Best-effort room inventory. Currently returns [] because Agoda's
        room data is inside a JS bundle that isn't always in the initial
        HTML. The infrastructure is here for when it is.
        """
        # Look for a common JSON shape:  "rooms":[{"roomId":..., ...}, ...]
        pattern = re.compile(
            r'"rooms"\s*:\s*(\[[\s\S]*?\])\s*,\s*"',
            re.DOTALL,
        )
        m = pattern.search(html)
        if not m:
            return None

        start = m.start(1)
        end = self._find_matching_bracket(html, start)
        if end == -1:
            return None

        raw = html[start:end + 1]
        try:
            rooms_any: Any = json.loads(raw)
        except json.JSONDecodeError:
            return None

        if not isinstance(rooms_any, list):
            return None

        rooms_list: List[Any] = cast(List[Any], rooms_any)
        out: List[Dict[str, Any]] = []
        item: Any
        for item in rooms_list:
            if not isinstance(item, dict):
                continue
            item_dict: Dict[str, Any] = cast(Dict[str, Any], item)
            out.append({
                "room_id": item_dict.get("roomId") or item_dict.get("room_id"),
                "room_name": item_dict.get("roomName") or item_dict.get("name"),
                "max_occupancy": item_dict.get("maxOccupancy"),
                "bed_type": item_dict.get("bedType"),
                "size_sqm": item_dict.get("sizeSqm") or item_dict.get("roomSize"),
            })
        return out or None

    @staticmethod
    def _find_matching_bracket(text: str, start_idx: int) -> int:
        if start_idx >= len(text) or text[start_idx] != "[":
            return -1
        depth = 0
        in_str = False
        escape = False
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

    def _extract_jsonld(self, html: str) -> List[Dict[str, Any]]:
        """
        Return every JSON-LD object embedded in the page.

        Agoda emits schema.org data as one or more
        `<script type="application/ld+json">` blocks. Each block is a
        single JSON object (or an array of them). This flattens all of
        them into a list so callers can scan for `@type` keys.
        """
        out: List[Dict[str, Any]] = []
        m: re.Match[str]
        for m in self._RE_LD_JSON.finditer(html):
            raw: str = m.group(1).strip()
            if not raw:
                continue
            obj_any: Any = None
            try:
                obj_any = json.loads(raw)
            except json.JSONDecodeError:
                continue

            if isinstance(obj_any, dict):
                out.append(cast(Dict[str, Any], obj_any))
            elif isinstance(obj_any, list):
                arr: List[Any] = cast(List[Any], obj_any)
                item: Any
                for item in arr:
                    if isinstance(item, dict):
                        out.append(cast(Dict[str, Any], item))
        return out

    