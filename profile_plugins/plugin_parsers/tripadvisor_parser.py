"""
Tripadvisor OTA parser.

Extracts the property profile from a Tripadvisor hotel page. The page
ships three independent sources of structured data:

  1. JSON-LD in two <script type="application/ld+json"> blocks:
       - a LodgingBusiness block with name / address / geo / rating /
         amenities / image,
       - a BreadcrumbList block with location hierarchy.
  2. Microdata in the page <head>: og:title, og:image, canonical.
  3. Human-readable HTML in a handful of stable containers:
       - <h1 id="HEADING"> for the display name,
       - <div data-automation="aboutTabDescription"> for the long
         description,
       - sub-score bars (Sleep Quality, etc.).

We prefer JSON-LD whenever present, then fall back to the HTML
containers. Price and room rates are NOT in the SSR HTML — Tripadvisor
defers them to partner checkout — so they are not extracted here.
"""
from __future__ import annotations

import html as html_module
import json
import re
from typing import Any, Dict, List, Optional, Tuple, cast

from profile_plugins.base_parser import BaseOtaParser
from utils.logging_utils import get_logger
from utils.string_utils import clean_text

logger = get_logger(__name__)


class TripadvisorParser(BaseOtaParser):
    name = "tripadvisor_com"

    # ---- Regexes ---------------------------------------------------

    # Canonical URL carries the location + property IDs:
    #   /Hotel_Review-g188590-d5062367-Reviews-...
    # Or the /HotelHighlight variant. Both shapes accepted.
    _RE_IDS = re.compile(
        r'-(g\d+)-(d\d+)-',
    )

    # Ranking lives in the meta description:
    #   "…ranked #22 of 349 B&Bs / inns in Amsterdam and rated 3 of 5…"
    _RE_RANKING = re.compile(
        r'ranked\s+#(\d+)\s+of\s+(\d+)\s+([^,]+?)\s+in\s+([^,]+?)'
        r'\s+and rated',
        re.IGNORECASE,
    )

    # A sub-score block looks like:
    #   <div class="Ygqck o q W">Sleep Quality</div>
    #   …<div class="dhZAW" style="width:78.039216%"></div>
    #   …<div class="biGQs _P SewaP biKBZ navcl">3.9</div>
    _RE_SUBSCORE = re.compile(
        r'class="Ygqck[^"]*">([^<]+)</div>'
        r'.{0,400}?'
        r'style="width:([0-9.]+)%"'
        r'.{0,400}?'
        r'class="biGQs _P SewaP biKBZ navcl">([0-9.]+)</div>',
        re.DOTALL,
    )

    # <script type="application/ld+json">…</script>
    _RE_LD_JSON = re.compile(
        r'<script[^>]*type="application/ld\+json"[^>]*>(.*?)</script>',
        re.DOTALL,
    )

    # <h1 id="HEADING" …>Name</h1>
    _RE_H1_HEADING = re.compile(
        r'<h1[^>]*id="HEADING"[^>]*>([^<]+)</h1>',
        re.IGNORECASE,
    )

    # <meta property="og:image" content="…">
    _RE_OG_IMAGE = re.compile(
        r'<meta\s+property="og:image"\s+content="([^"]+)"',
        re.IGNORECASE,
    )

    # <meta name="description" content="…">
    _RE_META_DESC = re.compile(
        r'<meta\s+name="description"\s+content="([^"]*)"',
        re.IGNORECASE,
    )

    # <link rel="canonical" href="…">
    _RE_CANONICAL = re.compile(
        r'<link\s+rel="canonical"\s+href="([^"]+)"',
        re.IGNORECASE,
    )

    # Long-form description container.
    _RE_ABOUT_DESC = re.compile(
        r'data-automation="aboutTabDescription".*?'
        r'<div class="biGQs _P VImYz AWdfh">(.*?)</div>',
        re.DOTALL,
    )

    # ---------------------------------------------------------------
    # Phase 1
    # ---------------------------------------------------------------

    def parse(self, html: str, source_url: str) -> Dict[str, Any]:
        # Tripadvisor serves the whole page in one request; follow-up
        # fetch (follow_up_urls) is unused.
        ld_blocks = self._extract_ld_json_blocks(html)
        lodging = self._pick_lodging_block(ld_blocks)

        property_id, location_id = self._extract_ids(html, source_url)

        name = self._pick_name(html, lodging)
        address = self._pick_address(lodging)
        geo = self._pick_geo(lodging)
        rating = self._pick_rating(lodging)
        review_count = self._pick_review_count(lodging)
        amenities = self._pick_amenities(lodging)
        price_range = self._pick_price_range(lodging)

        description = self._extract_description(html)
        ranking = self._extract_ranking(html)
        sub_scores = self._extract_sub_scores(html)

        canonical = self._extract_canonical(html)
        og_image = self._extract_og_image(html)

        logger.info(
            "tripadvisor_com: parsed id=%s name=%r rating=%s reviews=%s",
            property_id, name, rating, review_count,
        )

        return {
            "source_url": source_url,
            "title": self.parse_title(html),
            "og_site_name": self.parse_og_site_name(html),
            "html_length": len(html),

            "tripadvisor_property_id": property_id,
            "tripadvisor_location_id": location_id,
            "tripadvisor_property_name": name,
            "tripadvisor_property_url": canonical,
            "tripadvisor_rating": rating,
            "tripadvisor_review_count": review_count,
            "tripadvisor_star_rating": self._extract_star_rating(html),
            "tripadvisor_price_range": price_range,
            "tripadvisor_address": (
                address.get("streetAddress") if address else None
            ),
            "tripadvisor_city": (
                address.get("addressLocality") if address else None
            ),
            "tripadvisor_postal_code": (
                address.get("postalCode") if address else None
            ),
            "tripadvisor_country": (
                address.get("country") if address else None
            ),
            "tripadvisor_lat": geo.get("latitude") if geo else None,
            "tripadvisor_lng": geo.get("longitude") if geo else None,
            "tripadvisor_description": description,
            "tripadvisor_amenities": amenities or None,
            "tripadvisor_ranking": ranking,
            "tripadvisor_sub_scores": sub_scores or None,
            "tripadvisor_primary_image": og_image,

            "parse_ok": True,
        }

    # ---------------------------------------------------------------
    # JSON-LD
    # ---------------------------------------------------------------

    def _extract_ld_json_blocks(
        self, html: str
    ) -> List[Dict[str, Any]]:
        """Return every parsed ld+json block whose value is a dict."""
        out: List[Dict[str, Any]] = []
        for m in self._RE_LD_JSON.finditer(html):
            raw = m.group(1).strip()
            if not raw:
                continue
            try:
                parsed: Any = json.loads(raw)
            except json.JSONDecodeError:
                continue
            if isinstance(parsed, dict):
                out.append(cast(Dict[str, Any], parsed))
        return out

    def _pick_lodging_block(
        self, blocks: List[Dict[str, Any]]
    ) -> Dict[str, Any]:
        """
        Return the LodgingBusiness block, or an empty dict.

        The page also ships Organization, WebSite, BreadcrumbList, and
        sometimes a Review block. We want the LodgingBusiness one.
        """
        for block in blocks:
            t = block.get("@type")
            if t == "LodgingBusiness":
                return block
        return {}

    # ---------------------------------------------------------------
    # Identity
    # ---------------------------------------------------------------

    def _extract_ids(
        self, html: str, source_url: str
    ) -> Tuple[Optional[str], Optional[str]]:
        """
        Return (property_id, location_id).

        Tripadvisor uses two stable numeric IDs:
          - `d` prefix = property (hotel) ID
          - `g` prefix = location (city/region) ID

        Both appear in the canonical URL. Fall back to scanning the
        page HTML for the same pattern.
        """
        source = self._extract_canonical(html) or source_url
        m = self._RE_IDS.search(source)
        if m:
            return m.group(2), m.group(1)
        m = self._RE_IDS.search(html)
        if m:
            return m.group(2), m.group(1)
        return None, None

    def _pick_name(
        self, html: str, lodging: Dict[str, Any]
    ) -> Optional[str]:
        # 1. JSON-LD name
        name = clean_text(lodging.get("name"))
        if name:
            return name
        # 2. <h1 id="HEADING">
        m = self._RE_H1_HEADING.search(html)
        if m:
            name = clean_text(m.group(1))
            if name:
                return name
        # 3. og:title (strip " - Tripadvisor" suffix)
        og = self._extract_og_title(html)
        if og:
            return re.sub(r'\s*-\s*Tripadvisor\s*$', '', og).strip()
        return None

    def _extract_og_title(self, html: str) -> Optional[str]:
        m = re.search(
            r'<meta\s+property="og:title"\s+content="([^"]+)"',
            html, re.IGNORECASE,
        )
        return clean_text(m.group(1)) if m else None

    # ---------------------------------------------------------------
    # Address / geo
    # ---------------------------------------------------------------

    def _pick_address(
        self, lodging: Dict[str, Any]
    ) -> Optional[Dict[str, Optional[str]]]:
        addr = lodging.get("address")
        if not isinstance(addr, dict):
            return None
        a = cast(Dict[str, Any], addr)
        country_any: Any = a.get("addressCountry")
        country: Optional[str] = None
        if isinstance(country_any, dict):
            country = clean_text(
                cast(Dict[str, Any], country_any).get("name")
            )
        elif isinstance(country_any, str):
            country = clean_text(country_any)
        return {
            "streetAddress": clean_text(a.get("streetAddress")),
            "addressLocality": clean_text(a.get("addressLocality")),
            "postalCode": clean_text(a.get("postalCode")),
            "country": country,
        }

    def _pick_geo(
        self, lodging: Dict[str, Any]
    ) -> Optional[Dict[str, float]]:
        geo = lodging.get("geo")
        if not isinstance(geo, dict):
            return None
        g = cast(Dict[str, Any], geo)
        try:
            return {
                "latitude": float(g["latitude"]),
                "longitude": float(g["longitude"]),
            }
        except (KeyError, TypeError, ValueError):
            return None

    # ---------------------------------------------------------------
    # Rating / reviews
    # ---------------------------------------------------------------

    def _pick_rating(
        self, lodging: Dict[str, Any]
    ) -> Optional[float]:
        agg = lodging.get("aggregateRating")
        if not isinstance(agg, dict):
            return None
        val = cast(Dict[str, Any], agg).get("ratingValue")
        try:
            return float(val) if val is not None else None
        except (TypeError, ValueError):
            return None

    def _pick_review_count(
        self, lodging: Dict[str, Any]
    ) -> Optional[int]:
        agg = lodging.get("aggregateRating")
        if not isinstance(agg, dict):
            return None
        val = cast(Dict[str, Any], agg).get("reviewCount")
        try:
            return int(val) if val is not None else None
        except (TypeError, ValueError):
            return None

    def _extract_star_rating(self, html: str) -> Optional[int]:
        """
        The official star classification appears as
        "3 of 5 stars" inside a span with data-automation="affiliateStarRating".
        """
        m = re.search(
            r'data-automation="affiliateStarRating".*?'
            r'<span[^>]*>(\d+)\s+of\s+5\s+stars</span>',
            html, re.DOTALL,
        )
        if not m:
            return None
        try:
            return int(m.group(1))
        except ValueError:
            return None

    # ---------------------------------------------------------------
    # Amenities / price hint
    # ---------------------------------------------------------------

    def _pick_amenities(
        self, lodging: Dict[str, Any]
    ) -> List[str]:
        raw = lodging.get("amenityFeatures")
        if not isinstance(raw, list):
            return []
        out: List[str] = []
        seen: set[str] = set()
        for item in cast(List[Any], raw):
            if not isinstance(item, dict):
                continue
            d = cast(Dict[str, Any], item)
            name = clean_text(d.get("name"))
            if name and name not in seen:
                seen.add(name)
                out.append(name)
        return out

    def _pick_price_range(
        self, lodging: Dict[str, Any]
    ) -> Optional[str]:
        return clean_text(lodging.get("priceRange"))

    # ---------------------------------------------------------------
    # Description / ranking / sub-scores
    # ---------------------------------------------------------------

    def _extract_description(self, html: str) -> Optional[str]:
        m = self._RE_ABOUT_DESC.search(html)
        if not m:
            return None
        # Inner HTML — may contain entities and tags. Strip tags first,
        # then unescape entities, then clean.
        raw = m.group(1)
        raw = re.sub(r'<[^>]+>', '', raw)
        # html_module.unescape is called inside clean_text; but the
        # description block often has &#x27; etc. — clean_text handles it.
        return clean_text(raw)

    def _extract_ranking(
        self, html: str
    ) -> Optional[Dict[str, Any]]:
        """
        Parse the meta description to extract ranking:
          "ranked #22 of 349 B&Bs / inns in Amsterdam"
        """
        m = self._RE_META_DESC.search(html)
        if not m:
            return None
        desc = html_module.unescape(m.group(1))
        r = self._RE_RANKING.search(desc)
        if not r:
            return None
        try:
            rank = int(r.group(1))
            total = int(r.group(2))
        except ValueError:
            return None
        return {
            "rank": rank,
            "total": total,
            "category": clean_text(r.group(3)),
            "location": clean_text(r.group(4)),
        }

    def _extract_sub_scores(
        self, html: str
    ) -> Dict[str, float]:
        """
        Return {category_name: score} for the sub-rating bars.

        Categories seen: Location, Cleanliness, Service, Value,
        Sleep Quality, Rooms, etc. Values are on a 1–5 scale.
        """
        out: Dict[str, float] = {}
        for m in self._RE_SUBSCORE.finditer(html):
            name = clean_text(m.group(1))
            raw_score = m.group(3)
            if not name:
                continue
            try:
                score = float(raw_score)
            except ValueError:
                continue
            if name not in out:
                out[name] = score
        return out

    # ---------------------------------------------------------------
    # Head metadata
    # ---------------------------------------------------------------

    def _extract_canonical(self, html: str) -> Optional[str]:
        m = self._RE_CANONICAL.search(html)
        return clean_text(m.group(1)) if m else None

    def _extract_og_image(self, html: str) -> Optional[str]:
        m = self._RE_OG_IMAGE.search(html)
        return clean_text(m.group(1)) if m else None

    # ---------------------------------------------------------------
    # Follow-up hooks
    # ---------------------------------------------------------------

    def follow_up_urls(self, parsed: Dict[str, Any]) -> List[str]:
        # Tripadvisor ships everything in the primary page. No follow-up.
        return []

    def merge_follow_up(
        self,
        parsed: Dict[str, Any],
        url: str,
        html: str,
    ) -> None:
        # No follow-up URL is ever scheduled, so this is a no-op.
        return None