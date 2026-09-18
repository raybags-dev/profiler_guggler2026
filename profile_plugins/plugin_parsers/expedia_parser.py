"""
Expedia.com OTA parser.

Two-phase:

  Phase 1 — parse the search-results page that Google's deeplink lands on.
  The property ID appears as `selected=<id>` on Hotel-Search deeplinks, or
  as `.h<NUMBER>.` on canonical Hotel-Information URLs. We also pull date
  hints from the URL and read the schema.org <meta itemProp="..."> block,
  which carries name, address, star rating, and true hotel lat/lng.

  Phase 2 — fetch the Hotel-Information page. Expedia renders this with
  Remix + React Server Components. The SSR state lives in:

      window.__PLUGIN_STATE__ = JSON.parse("...")

  We extract that object and pull locale / currency / brand / site_id /
  long-form description / gallery out of it.

This parser performs no HTTP itself — the manager drives the follow-up.
"""
from __future__ import annotations

import json
import logging
import re
from collections import Counter
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple, cast
from utils.string_utils import clean_text

from profile_plugins.base_parser import BaseOtaParser
from utils.logging_utils import configure_logging, get_logger

configure_logging(level=logging.INFO)
logger = get_logger(__name__)

# Flip to True to dump the follow-up HTML to /tmp for inspection.
_DEBUG_DUMP_FOLLOWUP = False


class ExpediaParser(BaseOtaParser):
    name = "expedia_com"

    # -----------------------------------------------------------------
    # Phase 1 — property ID / dates from URL
    # -----------------------------------------------------------------
    # Phase 1 fallback: "<title>NAME Hotel Search results</title>"
    _RE_SEARCH_TITLE = re.compile(
        r'<title>([^<]+?)\s+Hotel Search results\s*</title>',
        re.IGNORECASE,
    )

    # Google-shipped Hotel-Search deeplink: ?selected=17578
    _RE_SELECTED_IN_URL = re.compile(r'[?&]selected=(\d{3,})')

    # Canonical Hotel-Information URL: .h17578.
    _RE_HOTEL_ID_IN_URL = re.compile(r'\.h(\d{3,})\.')

    # HTML fallback — tolerant of escaped quotes and `=` separators.
    _RE_HOTEL_ID_IN_HTML = re.compile(
        r'(?:\\?"|&quot;|")?(?:hotelId|propertyId)(?:\\?"|&quot;|")?'
        r'\s*[:=]\s*\\?"?(\d{3,})',
    )

    _RE_CHECKIN = re.compile(
        r'[?&](?:startDate|checkin|checkIn)=(\d{4}-\d{2}-\d{2})'
    )
    _RE_CHECKOUT = re.compile(
        r'[?&](?:endDate|checkout|checkOut)=(\d{4}-\d{2}-\d{2})'
    )

    # Google Hotel-Search deeplinks carry the price Google already
    # scraped from Expedia:
    #   mpf=301.03  nightly price (float, currency from mpl)
    #   mpj=75.53   taxes & fees
    #   mpr=0.00    resort / facility fees
    #   mpl=EUR     currency
    _RE_MPF = re.compile(r'[?&]mpf=([0-9.]+)')
    _RE_MPJ = re.compile(r'[?&]mpj=([0-9.]+)')
    _RE_MPR = re.compile(r'[?&]mpr=([0-9.]+)')
    _RE_MPL = re.compile(r'[?&]mpl=([A-Z]{3})')

    # Gallery alt-descriptions are "RoomName | amenity1, amenity2, ..."
    _RE_ROOM_IMAGE_DESC = re.compile(r'^([^|]{2,120}?)\s*\|\s*(.+)$')
    # -----------------------------------------------------------------
    # Phase 1 — schema.org microdata
    # -----------------------------------------------------------------

    _RE_META_ITEMPROP = re.compile(
        r'<meta\s+itemProp="([a-zA-Z]+)"\s+content="([^"]*)"',
    )

    # -----------------------------------------------------------------
    # Phase 2 — plugin state anchor
    # -----------------------------------------------------------------
    _RE_PLUGIN_STATE_ANCHOR = re.compile(
        r'window\.__PLUGIN_STATE__\s*=\s*JSON\.parse\(\s*"',
    )

    # -----------------------------------------------------------------
    # Phase 1 helpers
    # -----------------------------------------------------------------

    def _extract_search_name(self, html: str) -> Optional[str]:
        """
        The Hotel-Search page omits <meta itemProp="name">, but the
        <title> tag carries "NAME Hotel Search results". Use it as a
        phase-1 name fallback so downstream consumers see a name even
        before phase 2 runs.
        """
        m = self._RE_SEARCH_TITLE.search(html)
        if m is None:
            return None
        name = self._str_or_none(m.group(1))
        if not name:
            return None
        # Guard against Expedia occasionally returning just "Hotel
        # Search results" without a property name.
        if name.lower() == "hotel search results":
            return None
        return name
    
    def _extract_property_id(
        self, html: str, source_url: str
    ) -> Optional[int]:
        # 1) URL-based, most reliable.
        for pattern in (self._RE_SELECTED_IN_URL, self._RE_HOTEL_ID_IN_URL):
            m = pattern.search(source_url)
            if m:
                try:
                    return int(m.group(1))
                except ValueError:
                    pass

        # 2) HTML fallback — majority vote.
        candidates: List[int] = []
        for mm in self._RE_HOTEL_ID_IN_HTML.finditer(html):
            try:
                candidates.append(int(mm.group(1)))
            except ValueError:
                pass

        if not candidates:
            return None

        counts: Counter[int] = Counter(candidates)
        value, occurrences = counts.most_common(1)[0]
        return value if occurrences >= 2 else candidates[0]

    def _extract_dates(
        self, url: str
    ) -> Tuple[Optional[str], Optional[str]]:
        checkin: Optional[str] = None
        checkout: Optional[str] = None

        m = self._RE_CHECKIN.search(url)
        if m:
            checkin = m.group(1)
        m = self._RE_CHECKOUT.search(url)
        if m:
            checkout = m.group(1)
        return checkin, checkout

    def _extract_deeplink_price(
        self, url: str
    ) -> Dict[str, Any]:
        """
        Parse the price Google already scraped into the deeplink.

        Expedia's Hotel-Search deeplinks embed the nightly price, taxes,
        and currency as `mpf` / `mpj` / `mpl` query params. These are the
        numbers Google showed the user, in the exact currency for the
        exact dates, and they are the only price source available
        without replaying Expedia's post-hydration GraphQL call.
        """
        out: Dict[str, Any] = {
            "expedia_price_nightly": None,
            "expedia_price_taxes": None,
            "expedia_price_fees": None,
            "expedia_price_currency": None,
            "expedia_price_source": None,
        }

        m = self._RE_MPF.search(url)
        if m:
            try:
                out["expedia_price_nightly"] = float(m.group(1))
            except ValueError:
                pass
        m = self._RE_MPJ.search(url)
        if m:
            try:
                out["expedia_price_taxes"] = float(m.group(1))
            except ValueError:
                pass
        m = self._RE_MPR.search(url)
        if m:
            try:
                out["expedia_price_fees"] = float(m.group(1))
            except ValueError:
                pass
        m = self._RE_MPL.search(url)
        if m:
            out["expedia_price_currency"] = m.group(1)

        if out["expedia_price_nightly"] is not None:
            out["expedia_price_source"] = "deeplink"

        return out

    def _extract_meta_itemprops(self, html: str) -> Dict[str, str]:
        """Return every <meta itemProp="X" content="Y"/> as a dict.

        First occurrence per key wins — later partials render the same
        microdata with empty content.
        """
        out: Dict[str, str] = {}
        m: re.Match[str]
        for m in self._RE_META_ITEMPROP.finditer(html):
            key: str = m.group(1)
            value = self._str_or_none(m.group(2))
            if value and key not in out:
                out[key] = value
        return out

    # -----------------------------------------------------------------
    # Phase 1 — parse
    # -----------------------------------------------------------------

    def parse(self, html: str, source_url: str) -> Dict[str, Any]:
        property_id = self._extract_property_id(html, source_url)
        checkin, checkout = self._extract_dates(source_url)
        price_info = self._extract_deeplink_price(source_url)
        metas = self._extract_meta_itemprops(html)

        # Prefer the meta identifier if the URL didn't supply one.
        if property_id is None:
            ident = metas.get("identifier")
            if ident:
                try:
                    property_id = int(ident)
                except ValueError:
                    pass

        meta_name = metas.get("name")
        name = meta_name or self._extract_search_name(html)        
        address = metas.get("streetAddress")
        city = metas.get("addressLocality")
        country = metas.get("addressCountry")
        postal_code = metas.get("postalCode")
        short_description = metas.get("description")

        star_rating: Optional[int] = None
        rating_str = metas.get("ratingValue")
        if rating_str:
            try:
                star_rating = int(float(rating_str))
            except ValueError:
                pass

        lat: Optional[float] = None
        lng: Optional[float] = None
        try:
            lat_str = metas.get("latitude")
            lng_str = metas.get("longitude")
            if lat_str:
                lat = float(lat_str)
            if lng_str:
                lng = float(lng_str)
        except ValueError:
            pass

        property_url: Optional[str] = None
        if property_id is not None:
            base = (
                f"https://www.expedia.nl/en/h{property_id}.Hotel-Information"
            )
            params: List[str] = []
            if checkin:
                params.append(f"startDate={checkin}")
            if checkout:
                params.append(f"endDate={checkout}")
            property_url = base + ("?" + "&".join(params) if params else "")

        logger.info(
            "expedia_com: parsed property_id=%s name=%r checkin=%s "
            "checkout=%s html_len=%d",
            property_id, name, checkin, checkout, len(html),
        )

        return {
            "source_url": source_url,
            "title": self.parse_title(html),
            "og_site_name": self.parse_og_site_name(html),
            "html_length": len(html),

            "expedia_property_id": property_id,
            "expedia_checkin": checkin,
            "expedia_checkout": checkout,
            "expedia_property_url": property_url,

            **price_info,

            "expedia_property_page_url": None,
            "expedia_property_page_length": None,
            "expedia_property_name": name,
            "expedia_property_name_alt": None,
            "expedia_star_rating": star_rating,
            "expedia_locale": None,
            "expedia_currency": None,
            "expedia_brand": None,
            "expedia_site_id": None,
            "expedia_lat": lat,
            "expedia_lng": lng,
            "expedia_city": city,
            "expedia_country": country,
            "expedia_address": address,
            "expedia_postal_code": postal_code,
            "expedia_description": short_description,
            "expedia_highlights": None,
            "expedia_rooms": None,
            "expedia_gallery": None,
            "parse_ok": True,
        }
    # -----------------------------------------------------------------
    # Phase 2 — follow the property URL
    # -----------------------------------------------------------------

    def follow_up_urls(self, parsed: Dict[str, Any]) -> List[str]:
        url = self._str_or_none(parsed.get("expedia_property_url"))
        return [url] if url else []

    def merge_follow_up(
        self,
        parsed: Dict[str, Any],
        url: str,
        html: str,
    ) -> None:
        parsed["expedia_property_page_url"] = url
        parsed["expedia_property_page_length"] = len(html)

        if _DEBUG_DUMP_FOLLOWUP:
            try:
                Path("/tmp/expedia_followup.html").write_text(
                    html, encoding="utf-8"
                )
                logger.info(
                    "expedia_com: dumped /tmp/expedia_followup.html "
                    "(%d bytes)",
                    len(html),
                )
            except OSError as exc:
                logger.warning("expedia_com: dump failed: %s", exc)

        plugin_state = self._extract_plugin_state(html)
        if plugin_state is None:
            logger.warning(
                "expedia_com: no plugin state found (html_len=%d)", len(html)
            )
            return

        # Preserve the phase-1 name for later comparison.
        phase1_name = parsed.get("expedia_property_name")
        if phase1_name:
            parsed["expedia_property_name_alt"] = phase1_name

        description = self._extract_description(plugin_state)
        if description:
            parsed["expedia_description"] = description

        highlights = self._extract_highlights(plugin_state)
        if highlights:
            parsed["expedia_highlights"] = highlights

        gallery = self._extract_gallery(plugin_state)
        if gallery:
            parsed["expedia_gallery"] = gallery

        rooms = self._extract_rooms_from_gallery(plugin_state)
        if rooms:
            parsed["expedia_rooms"] = rooms

        self._merge_meta(parsed, html)
        self._merge_context(parsed, plugin_state)
        self._merge_current_hotel(parsed, plugin_state)
    # -----------------------------------------------------------------
    # Phase 2 — meta refresh
    # -----------------------------------------------------------------

    def _merge_meta(
        self, parsed: Dict[str, Any], html: str
    ) -> None:
        """Refresh schema.org fields from the follow-up page's metas.

        Expedia renders some fields (postalCode, full address) only on
        the Hotel-Information page, so re-read them here. Never
        overwrite an already-populated good value with None.
        """
        metas = self._extract_meta_itemprops(html)

        def _set(key: str, meta_key: str) -> None:
            if parsed.get(key):
                return
            value = metas.get(meta_key)
            if value:
                parsed[key] = value

        _set("expedia_property_name", "name")
        _set("expedia_address", "streetAddress")
        _set("expedia_city", "addressLocality")
        _set("expedia_country", "addressCountry")
        _set("expedia_postal_code", "postalCode")

        if parsed.get("expedia_lat") is None:
            lat_str = metas.get("latitude")
            if lat_str:
                try:
                    parsed["expedia_lat"] = float(lat_str)
                except ValueError:
                    pass
        if parsed.get("expedia_lng") is None:
            lng_str = metas.get("longitude")
            if lng_str:
                try:
                    parsed["expedia_lng"] = float(lng_str)
                except ValueError:
                    pass

        if parsed.get("expedia_star_rating") is None:
            rating_str = metas.get("ratingValue")
            if rating_str:
                try:
                    parsed["expedia_star_rating"] = int(float(rating_str))
                except ValueError:
                    pass

    # -----------------------------------------------------------------
    # Phase 2 — plugin state extraction
    # -----------------------------------------------------------------

    def _extract_plugin_state(
        self, html: str
    ) -> Optional[Dict[str, Any]]:
        m = self._RE_PLUGIN_STATE_ANCHOR.search(html)
        if m is None:
            logger.warning(
                "expedia_com: __PLUGIN_STATE__ anchor not found (html_len=%d)",
                len(html),
            )
            return None

        start = m.end()
        i = start
        escaped = False
        while i < len(html):
            ch = html[i]
            if escaped:
                escaped = False
                i += 1
                continue
            if ch == "\\":
                escaped = True
                i += 1
                continue
            if ch == '"':
                break
            i += 1

        if i >= len(html):
            logger.warning(
                "expedia_com: unterminated __PLUGIN_STATE__ string"
            )
            return None

        encoded = html[start:i]
        logger.info(
            "expedia_com: __PLUGIN_STATE__ raw length=%d", len(encoded)
        )

        decoded: str
        try:
            decoded = json.loads('"' + encoded + '"')
        except json.JSONDecodeError as exc:
            logger.warning(
                "expedia_com: outer JSON decode failed at %d: %s | "
                "context=%r",
                exc.pos, exc.msg,
                encoded[max(0, exc.pos - 60):exc.pos + 60],
            )
            decoded = encoded.replace('\\"', '"').replace('\\\\', '\\')

        try:
            parsed_any: Any = json.loads(decoded)
        except json.JSONDecodeError as exc:
            logger.warning(
                "expedia_com: inner JSON decode failed at %d: %s | "
                "context=%r",
                exc.pos, exc.msg,
                decoded[max(0, exc.pos - 80):exc.pos + 80],
            )
            return None

        if not isinstance(parsed_any, dict):
            logger.warning(
                "expedia_com: __PLUGIN_STATE__ is %s, expected dict",
                type(parsed_any).__name__,
            )
            return None

        state: Dict[str, Any] = cast(Dict[str, Any], parsed_any)
        logger.info(
            "expedia_com: state extracted (%d top-level keys)", len(state),
        )
        return state

    # -----------------------------------------------------------------
    # context merge
    # -----------------------------------------------------------------

    def _merge_context(
        self,
        parsed: Dict[str, Any],
        plugin_state: Dict[str, Any],
    ) -> None:
        """
        Populate locale / currency / brand / site_id / seo_url.

        Two shapes exist:

          flat:   plugin_state["context"] = {locale, currency, site, ...}
          nested: plugin_state["context"]["context"] = {locale, ...}

        Current builds use nested; older builds use flat.
        """
        outer_any: Any = plugin_state.get("context")
        if not isinstance(outer_any, dict):
            return
        outer: Dict[str, Any] = cast(Dict[str, Any], outer_any)

        inner_any: Any = outer.get("context")
        ctx: Dict[str, Any]
        if isinstance(inner_any, dict):
            ctx = cast(Dict[str, Any], inner_any)
        else:
            ctx = outer

        locale = self._str_or_none(ctx.get("locale"))
        if locale:
            parsed["expedia_locale"] = locale

        currency = self._str_or_none(ctx.get("currency"))
        if currency:
            parsed["expedia_currency"] = currency

        site_any: Any = ctx.get("site")
        if isinstance(site_any, dict):
            site = cast(Dict[str, Any], site_any)
            brand = self._str_or_none(site.get("brand"))
            if brand:
                parsed["expedia_brand"] = brand
            site_id_any: Any = site.get("id")
            if isinstance(site_id_any, (int, float)):
                parsed["expedia_site_id"] = int(site_id_any)

        seo_any: Any = ctx.get("seoData")
        if isinstance(seo_any, dict):
            seo = cast(Dict[str, Any], seo_any)
            seo_url = self._str_or_none(seo.get("url"))
            if seo_url and not parsed.get("expedia_seo_url"):
                parsed["expedia_seo_url"] = seo_url

    # -----------------------------------------------------------------
    # property highlights extraction
    # -----------------------------------------------------------------

    def _extract_highlights(
        self, plugin_state: Dict[str, Any]
    ) -> List[Dict[str, str]]:
        """
        Collect ShoppingProductContentGraphicsItem nodes as a flat list.

        Expedia ships the highlights module as an ordered array of these
        nodes. Each carries a headline (`text`), a supporting sentence
        (`subText` or `subContent.text`), and a `leadingIcon.id`. We keep
        document order — it matches the rendered order on the page.
        """
        out: List[Dict[str, str]] = []
        seen: set[tuple[str, str]] = set()

        def _visit(node: Any) -> None:
            if isinstance(node, dict):
                node_dict = cast(Dict[str, Any], node)
                if (
                    node_dict.get("__typename")
                    == "ShoppingProductContentGraphicsItem"
                ):
                    title = self._str_or_none(node_dict.get("text"))
                    subtitle = self._str_or_none(node_dict.get("subText"))
                    if not subtitle:
                        sub_any: Any = node_dict.get("subContent")
                        if isinstance(sub_any, dict):
                            sub_dict = cast(Dict[str, Any], sub_any)
                            subtitle = self._str_or_none(
                                sub_dict.get("text")
                            )
                    icon_id: Optional[str] = None
                    icon_any: Any = node_dict.get("leadingIcon")
                    if isinstance(icon_any, dict):
                        icon_dict = cast(Dict[str, Any], icon_any)
                        icon_id = self._str_or_none(icon_dict.get("id"))

                    key = (title or "", subtitle or "")
                    if (title or subtitle) and key not in seen:
                        seen.add(key)
                        entry: Dict[str, str] = {}
                        if title:
                            entry["title"] = title
                        if subtitle:
                            entry["subtitle"] = subtitle
                        if icon_id:
                            entry["icon"] = icon_id
                        out.append(entry)

                # Recurse; keep insertion order.
                for v in node_dict.values():
                    _visit(v)
            elif isinstance(node, list):
                node_list = cast(List[Any], node)
                for item in node_list:
                    _visit(item)

        _visit(plugin_state)
        return out
    
    # -----------------------------------------------------------------
    # description extraction
    # -----------------------------------------------------------------

    def _extract_description(
        self, plugin_state: Dict[str, Any]
    ) -> Optional[str]:
        """
        Walk the state tree for the longest EGDSParagraph text field.

        Expedia ships the long-form property description as:

            {"__typename": "EGDSParagraph", "text": "..."}

        Picking the longest avoids section headings.
        """
        best: Optional[str] = None
        best_len: int = 0

        def _walk(node: Any) -> None:
            nonlocal best, best_len
            if isinstance(node, dict):
                node_dict = cast(Dict[str, Any], node)
                if node_dict.get("__typename") == "EGDSParagraph":
                    text = self._str_or_none(node_dict.get("text"))
                    if text and len(text) > best_len:
                        best = text
                        best_len = len(text)
                for v in node_dict.values():
                    _walk(v)
            elif isinstance(node, list):
                node_list = cast(List[Any], node)
                for item in node_list:
                    _walk(item)

        _walk(plugin_state)
        return best

    # -----------------------------------------------------------------
    # gallery extraction
    # -----------------------------------------------------------------

    def _extract_gallery(
        self, plugin_state: Dict[str, Any]
    ) -> List[str]:
        """
        Walk the state tree and collect every images.trvl-media.com URL
        found under a `ProductImage` node's `url` field.

        Returns a deduplicated, normalized list of 1200-wide URLs in
        document order.
        """
        out: List[str] = []
        seen: set[str] = set()

        def _visit(node: Any) -> None:
            if isinstance(node, dict):
                node_dict = cast(Dict[str, Any], node)
                if node_dict.get("__typename") == "ProductImage":
                    url_any: Any = node_dict.get("url")
                    if isinstance(url_any, str):
                        clean = self._normalize_trvl_image(url_any)
                        if clean and clean not in seen:
                            seen.add(clean)
                            out.append(clean)
                for v in node_dict.values():
                    _visit(v)
            elif isinstance(node, list):
                node_list = cast(List[Any], node)
                for item in node_list:
                    _visit(item)

        _visit(plugin_state)
        return out

    # -----------------------------------------------------------------
    # room-type extraction from gallery descriptions
    # -----------------------------------------------------------------

    def _extract_rooms_from_gallery(
        self, plugin_state: Dict[str, Any]
    ) -> List[Dict[str, Any]]:
        """
        Build room entries from the gallery's ProductImageInfo nodes.

        Expedia embeds the room type in each image's alt-description:

            "Presidential Suite | Hypo-allergenic bedding, minibar, ..."

        so we parse that into {name, amenities, images}. This is a
        partial room list — names, amenities, and images only, no rates.
        Rates are not present in the SSR payload and would require
        replaying Expedia's post-hydration GraphQL call.
        """
        by_room: Dict[str, Dict[str, Any]] = {}
        order: List[str] = []

        def _visit(node: Any) -> None:
            if isinstance(node, dict):
                node_dict = cast(Dict[str, Any], node)
                if node_dict.get("__typename") == "ProductImageInfo":
                    img_any: Any = node_dict.get("image")
                    if isinstance(img_any, dict):
                        img = cast(Dict[str, Any], img_any)
                        desc = self._str_or_none(img.get("description")) or ""
                        url = self._str_or_none(img.get("url"))
                        if desc and url:
                            m = self._RE_ROOM_IMAGE_DESC.match(desc)
                            if m:
                                room_name = m.group(1).strip()
                                amenities = m.group(2).strip()
                                clean = self._normalize_trvl_image(url)
                                if not clean:
                                    return
                                if room_name not in by_room:
                                    by_room[room_name] = {
                                        "name": room_name,
                                        "amenities": amenities or None,
                                        "images": [],
                                    }
                                    order.append(room_name)
                                bucket = by_room[room_name]
                                imgs: List[str] = bucket["images"]
                                if clean not in imgs:
                                    imgs.append(clean)
                                # Prefer the longest amenities string we
                                # see for a given room (some images only
                                # have partial text).
                                if amenities and (
                                    not bucket["amenities"]
                                    or len(amenities)
                                    > len(bucket["amenities"])
                                ):
                                    bucket["amenities"] = amenities
                for v in node_dict.values():
                    _visit(v)
            elif isinstance(node, list):
                node_list = cast(List[Any], node)
                for item in node_list:
                    _visit(item)

        _visit(plugin_state)
        return [by_room[name] for name in order]
    
    # -----------------------------------------------------------------
    # currentHotel merge
    # -----------------------------------------------------------------

    def _merge_current_hotel(
        self,
        parsed: Dict[str, Any],
        plugin_state: Dict[str, Any],
    ) -> None:
        controllers_any: Any = plugin_state.get("controllers")
        if not isinstance(controllers_any, dict):
            return
        controllers = cast(Dict[str, Any], controllers_any)

        stores_any: Any = controllers.get("stores")
        if not isinstance(stores_any, dict):
            return
        stores = cast(Dict[str, Any], stores_any)

        hotel_any: Any = stores.get("currentHotel")
        if not isinstance(hotel_any, dict):
            return
        hotel = cast(Dict[str, Any], hotel_any)

        # tealiumUtagData carries hotelName and starRating. Its `Geo`
        # block is *client* geo-IP — we deliberately do NOT read lat/lng
        # or city/country from it; those come from the meta block.
        payload_any: Any = hotel.get("detailsPayload")
        payload: Dict[str, Any]
        if isinstance(payload_any, dict):
            payload = cast(Dict[str, Any], payload_any)
        else:
            payload = {}

        utag_any: Any = payload.get("tealiumUtagData")
        utag: Dict[str, Any]
        if isinstance(utag_any, dict):
            utag = cast(Dict[str, Any], utag_any)
        else:
            utag = {}

        if not parsed.get("expedia_property_name"):
            name = self._str_or_none(utag.get("hotelName"))
            if not name:
                sc_any: Any = hotel.get("searchCriteria")
                if isinstance(sc_any, dict):
                    sc = cast(Dict[str, Any], sc_any)
                    name = self._str_or_none(sc.get("hotelName"))
            if name:
                parsed["expedia_property_name"] = name

        if parsed.get("expedia_star_rating") is None:
            stars_any: Any = utag.get("starRating")
            if isinstance(stars_any, (int, float)):
                parsed["expedia_star_rating"] = int(stars_any)


    @staticmethod
    def _normalize_trvl_image(url: str) -> Optional[str]:
        if "images.trvl-media.com" not in url:
            return None
        base = url.split("?", 1)[0]
        for suffix in ("_b.jpg", "_t.jpg", "_l.jpg"):
            if base.endswith(suffix):
                base = base[: -len(suffix)] + ".jpg"
                break
        return f"{base}?impolicy=resizecrop&rw=1200&ra=fit"

    # Unicode control / formatting characters that Expedia embeds in
    # text fields for bidi-locale rendering. They're invisible when
    # rendered, but pollute the raw JSON.
    _BIDI_CHARS_DELETE = (
    "\u200b", "\u200c", "\u200d", "\u200e", "\u200f",
    "\u202a", "\u202b", "\u202c", "\u202d", "\u202e",
    "\u2060", "\u2066", "\u2067", "\u2068", "\u2069",
    "\ufeff",
    )
    _BIDI_CHARS_TO_SPACE = (
        "\u00a0",  # NBSP
        "\u202f",  # NARROW NO-BREAK SPACE
        "\u2007",  # FIGURE SPACE
        "\u2009",  # THIN SPACE
    )

    @staticmethod
    def _str_or_none(value: object) -> Optional[str]:
        return clean_text(value)