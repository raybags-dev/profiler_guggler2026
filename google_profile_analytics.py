from __future__ import annotations

import json
import logging
import statistics
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from utils.logging_utils import configure_logging, get_logger

configure_logging(level=logging.INFO)
logger = get_logger(__name__)


# ---------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------

INPUT_FILE: str = "json_data/google_profiles.jsonl"
OUTPUT_FILE: str = "google_profile_analytics.txt"

# Currencies we know the glyph for. Extend as needed.
CURRENCY_GLYPHS: Tuple[str, ...] = ("€", "$", "£", "¥", "₹", "₩")


# ---------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------

def _safe_div(numerator: float, denominator: float) -> Optional[float]:
    """Divide guarding against zero denominators."""
    if denominator == 0:
        return None
    return numerator / denominator


def _percentile(values: List[float], pct: float) -> Optional[float]:
    """Simple percentile (linear interpolation), tolerant of small samples."""
    if not values:
        return None
    if len(values) == 1:
        return float(values[0])
    try:
        return float(statistics.quantiles(values, n=100, method="inclusive")[int(pct) - 1])
    except Exception:
        # Fallback for tiny samples
        sorted_vals = sorted(values)
        idx = max(0, min(len(sorted_vals) - 1, int(round((pct / 100.0) * (len(sorted_vals) - 1)))))
        return float(sorted_vals[idx])


def _strip_currency_glyph(raw: Optional[str]) -> Optional[str]:
    """Return the currency glyph at the start of a raw price string."""
    if not raw:
        return None
    for glyph in CURRENCY_GLYPHS:
        if raw.startswith(glyph):
            return glyph
    return None


def _numeric_rates(room_rates: List[Dict[str, Any]]) -> List[int]:
    """Pull out the numeric rate values from a list of room rates."""
    out: List[int] = []
    for r in room_rates:
        rate = r.get("rate")
        if isinstance(rate, (int, float)) and rate > 0:
            out.append(int(rate))
    return out


def _numeric_prices(room_prices_by_provider: List[Dict[str, Any]]) -> List[int]:
    """Pull out numeric amounts from room_prices_by_provider."""
    out: List[int] = []
    for entry in room_prices_by_provider:
        price = entry.get("price") or {}
        amount = price.get("amount") if isinstance(price, dict) else None
        if isinstance(amount, (int, float)) and amount > 0:
            out.append(int(amount))
    return out


def _unique_by_provider_name(providers: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Deduplicate providers by name (first occurrence wins)."""
    seen: set[str] = set()
    out: List[Dict[str, Any]] = []
    for p in providers:
        name = (p or {}).get("name")
        if not name or name in seen:
            continue
        seen.add(name)
        out.append(p)
    return out


# ---------------------------------------------------------------------
# Analytical blocks
# ---------------------------------------------------------------------

def analyse_room_rates(profile: Dict[str, Any]) -> Dict[str, Any]:
    """Compute statistics over `room_rates`."""
    room_rates: List[Dict[str, Any]] = profile.get("room_rates") or []
    rates = _numeric_rates(room_rates)

    if not rates:
        return {
            "room_rate_count": 0,
            "cheapest_rate": None,
            "most_expensive_rate": None,
            "average_rate": None,
            "median_rate": None,
            "rate_range": None,
            "rate_std_dev": None,
            "currency": None,
            "distinct_room_types": 0,
            "top_5_cheapest": [],
            "top_5_most_expensive": [],
        }

    # Collect distinct room types
    distinct_room_types: set[str] = set()
    for r in room_rates:
        rt = r.get("room_type")
        if isinstance(rt, str) and rt:
            distinct_room_types.add(rt)

    # Currency from first rate
    currency = None
    for r in room_rates:
        currency = r.get("currency")
        if currency:
            break

    # Top 5 cheapest (unique room_type + rate)
    sorted_rates = sorted(rates)
    cheapest_lookup = sorted(room_rates, key=lambda r: r.get("rate") or 0)
    expensive_lookup = sorted(room_rates, key=lambda r: r.get("rate") or 0, reverse=True)

    def _summary(entry: Dict[str, Any]) -> Dict[str, Any]:
        return {
            "room_type": entry.get("room_type"),
            "rate": entry.get("rate"),
            "currency": entry.get("currency"),
            "board_type": entry.get("board_type"),
            "cancellation_policy": entry.get("cancellation_policy"),
        }

    top5_cheapest = [_summary(e) for e in cheapest_lookup[:5]]
    top5_most_expensive = [_summary(e) for e in expensive_lookup[:5]]

    return {
        "room_rate_count": len(room_rates),
        "cheapest_rate": sorted_rates[0],
        "most_expensive_rate": sorted_rates[-1],
        "average_rate": round(statistics.mean(rates), 2),
        "median_rate": round(statistics.median(rates), 2),
        "rate_range": sorted_rates[-1] - sorted_rates[0],
        "rate_std_dev": round(statistics.pstdev(rates), 2) if len(rates) > 1 else 0.0,
        "currency": currency,
        "distinct_room_types": len(distinct_room_types),
        "top_5_cheapest": top5_cheapest,
        "top_5_most_expensive": top5_most_expensive,
    }


def analyse_rates_by_board_type(profile: Dict[str, Any]) -> Dict[str, Any]:
    """Bucket room rates by board_type and summarise."""
    room_rates: List[Dict[str, Any]] = profile.get("room_rates") or []
    buckets: Dict[str, List[int]] = {}

    for r in room_rates:
        board = r.get("board_type") or "Unknown"
        rate = r.get("rate")
        if isinstance(rate, (int, float)) and rate > 0:
            buckets.setdefault(board, []).append(int(rate))

    summary: Dict[str, Any] = {}
    for board, values in buckets.items():
        summary[board] = {
            "count": len(values),
            "min": min(values),
            "max": max(values),
            "avg": round(statistics.mean(values), 2),
        }
    return summary


def analyse_rates_by_cancellation(profile: Dict[str, Any]) -> Dict[str, Any]:
    """Bucket room rates by cancellation policy category."""
    room_rates: List[Dict[str, Any]] = profile.get("room_rates") or []

    buckets: Dict[str, List[int]] = {
        "Free cancellation": [],
        "Non-refundable": [],
        "Unknown": [],
    }

    for r in room_rates:
        rate = r.get("rate")
        if not isinstance(rate, (int, float)) or rate <= 0:
            continue
        policy = (r.get("cancellation_policy") or "Unknown").lower()
        if "free cancellation" in policy:
            buckets["Free cancellation"].append(int(rate))
        elif "non" in policy or "nonrefundable" in policy or "non-refundable" in policy:
            buckets["Non-refundable"].append(int(rate))
        else:
            buckets["Unknown"].append(int(rate))

    result: Dict[str, Any] = {}
    for category, values in buckets.items():
        if values:
            result[category] = {
                "count": len(values),
                "min": min(values),
                "max": max(values),
                "avg": round(statistics.mean(values), 2),
            }
        else:
            result[category] = {"count": 0, "min": None, "max": None, "avg": None}
    return result


def analyse_providers(profile: Dict[str, Any]) -> Dict[str, Any]:
    """Compute analytics on `providers`."""
    providers: List[Dict[str, Any]] = profile.get("providers") or []
    unique = _unique_by_provider_name(providers)

    # Count by domain (rough grouping)
    by_domain: Dict[str, int] = {}
    for p in unique:
        link = p.get("deeplink") or ""
        domain = "unknown"
        try:
            from urllib.parse import urlparse
            parsed = urlparse(link)
            domain = parsed.netloc or "unknown"
        except Exception:
            pass
        by_domain[domain] = by_domain.get(domain, 0) + 1

    # Percentage of providers whose deeplink is a real URL (not a redirect)
    real_url_count = sum(
        1
        for p in unique
        if isinstance(p.get("deeplink"), str) and p["deeplink"].startswith("http")
    )
    real_url_ratio = _safe_div(real_url_count, len(unique)) if unique else None

    return {
        "total_provider_links": len(providers),
        "unique_providers": len(unique),
        "provider_names": sorted(p.get("name", "") for p in unique if p.get("name")),
        "provider_count_by_domain": by_domain,
        "resolved_url_ratio": round(real_url_ratio, 4) if real_url_ratio is not None else None,
    }


def analyse_room_prices_by_provider(profile: Dict[str, Any]) -> Dict[str, Any]:
    """Compute analytics on room_prices_by_provider."""
    entries: List[Dict[str, Any]] = profile.get("room_prices_by_provider") or []
    amounts = _numeric_prices(entries)

    if not amounts:
        return {
            "entry_count": 0,
            "cheapest": None,
            "most_expensive": None,
            "average": None,
            "median": None,
        }

    return {
        "entry_count": len(entries),
        "cheapest": min(amounts),
        "most_expensive": max(amounts),
        "average": round(statistics.mean(amounts), 2),
        "median": round(statistics.median(amounts), 2),
    }


def analyse_amenities(profile: Dict[str, Any]) -> Dict[str, Any]:
    """Compute analytics on amenities."""
    amenities: List[str] = profile.get("amenities") or []

    category_map: Dict[str, List[str]] = {
        "Internet": ["Wi-Fi", "Free Wi-Fi", "Paid Wi-Fi", "WiFi", "Internet"],
        "Parking": ["Parking", "Free parking", "Paid parking", "Valet parking"],
        "Food & drink": ["Breakfast", "Restaurant", "Bar", "Room service"],
        "Wellness": ["Pool", "Fitness center", "Gym", "Spa", "Massage"],
        "Comfort": ["Air conditioning", "Heating", "Non-smoking", "Smoke-free property"],
        "Services": ["Front desk", "Concierge", "Laundry service", "Baggage storage"],
        "Family": ["Children", "Kid-friendly", "Babysitting", "Cribs"],
    }

    hits: Dict[str, List[str]] = {cat: [] for cat in category_map}
    for a in amenities:
        for cat, members in category_map.items():
            if a in members:
                hits[cat].append(a)

    return {
        "total_amenities": len(amenities),
        "by_category": {cat: items for cat, items in hits.items() if items},
        "uncategorized": sorted(
            a for a in amenities
            if not any(a in members for members in category_map.values())
        ),
    }


def analyse_data_quality(profile: Dict[str, Any]) -> Dict[str, Any]:
    """Compute a data-completeness score and list missing fields."""
    tracked_fields: List[str] = [
        "property_name",
        "property_name_alt",
        "rating",
        "review_count",
        "address",
        "phone",
        "check_in",
        "check_out",
        "hotel_feature_id",
        "place_id",
        "property_url",
        "property_profile_urls",
        "providers",
        "room_prices_by_provider",
        "multi_night_pricing",
        "amenities",
        "room_rates",
    ]

    missing: List[str] = []
    for field in tracked_fields:
        value = profile.get(field)
        if value is None or value == [] or value == {} or value == "":
            missing.append(field)

    present_count = len(tracked_fields) - len(missing)
    completeness = _safe_div(present_count, len(tracked_fields)) or 0.0

    return {
        "fields_tracked": len(tracked_fields),
        "fields_present": present_count,
        "fields_missing": missing,
        "completeness_score": round(completeness, 4),
    }


def analyse_pricing_gaps(profile: Dict[str, Any]) -> Dict[str, Any]:
    """
    Cross-check `room_rates` and `room_prices_by_provider` to compute
    a "price spread" between the cheapest visible rate and the cheapest
    provider price — useful as a signal of how much room there is
    between top-of-page and lowest available.
    """
    room_rates = profile.get("room_rates") or []
    room_prices = profile.get("room_prices_by_provider") or []

    rate_amounts = _numeric_rates(room_rates)
    provider_amounts = _numeric_prices(room_prices)

    cheapest_rate = min(rate_amounts) if rate_amounts else None
    cheapest_provider = min(provider_amounts) if provider_amounts else None

    spread: Optional[int] = None
    spread_pct: Optional[float] = None
    if cheapest_rate is not None and cheapest_provider is not None:
        spread = cheapest_provider - cheapest_rate
        if cheapest_rate > 0:
            spread_pct = round((spread / cheapest_rate) * 100.0, 2)

    return {
        "cheapest_room_rate": cheapest_rate,
        "cheapest_provider_price": cheapest_provider,
        "absolute_spread": spread,
        "percentage_spread": spread_pct,
    }


def analyse_cancellation_mix(profile: Dict[str, Any]) -> Dict[str, Any]:
    """What fraction of room rates are refundable vs not."""
    room_rates = profile.get("room_rates") or []
    total = len(room_rates)
    if total == 0:
        return {
            "total_room_rates": 0,
            "free_cancellation": 0,
            "non_refundable": 0,
            "unknown": 0,
            "free_cancellation_ratio": None,
        }

    free = sum(
        1 for r in room_rates
        if "free cancellation" in (r.get("cancellation_policy") or "").lower()
    )
    non_ref = sum(
        1 for r in room_rates
        if "non" in (r.get("cancellation_policy") or "").lower()
    )
    unknown = total - free - non_ref

    return {
        "total_room_rates": total,
        "free_cancellation": free,
        "non_refundable": non_ref,
        "unknown": unknown,
        "free_cancellation_ratio": round(_safe_div(free, total) or 0.0, 4),
    }


# ---------------------------------------------------------------------
# Aggregator
# ---------------------------------------------------------------------

def build_analytics(profile: Dict[str, Any]) -> Dict[str, Any]:
    """Build the full analytical superset for one profile."""
    return {
        "meta": {
            "generated_at": datetime.utcnow().isoformat() + "Z",
            "source_url": profile.get("source_url"),
            "property_name": profile.get("property_name"),
            "place_id": profile.get("place_id"),
        },
        "identity": {
            "property_name": profile.get("property_name"),
            "property_name_alt": profile.get("property_name_alt"),
            "address": profile.get("address"),
            "phone": profile.get("phone"),
            "rating": profile.get("rating"),
            "rating_string": profile.get("rating_string"),
            "review_count": profile.get("review_count"),
            "check_in": profile.get("check_in"),
            "check_out": profile.get("check_out"),
            "hotel_feature_id": profile.get("hotel_feature_id"),
            "place_id": profile.get("place_id"),
            "property_url": profile.get("property_url"),
        },
        "room_rate_analysis": analyse_room_rates(profile),
        "rate_by_board_type": analyse_rates_by_board_type(profile),
        "rate_by_cancellation": analyse_rates_by_cancellation(profile),
        "cancellation_mix": analyse_cancellation_mix(profile),
        "provider_analysis": analyse_providers(profile),
        "provider_price_analysis": analyse_room_prices_by_provider(profile),
        "amenity_analysis": analyse_amenities(profile),
        "pricing_gap_analysis": analyse_pricing_gaps(profile),
        "data_quality": analyse_data_quality(profile),
    }


# ---------------------------------------------------------------------
# I/O
# ---------------------------------------------------------------------

def read_profiles(input_file: str) -> List[Dict[str, Any]]:
    """Read jsonl profile file, one JSON object per line."""
    path = Path(input_file)
    if not path.exists():
        raise FileNotFoundError(f"Input file not found: {input_file}")

    profiles: List[Dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as f:
        for lineno, line in enumerate(f, 1):
            stripped = line.strip()
            if not stripped:
                continue
            try:
                profiles.append(json.loads(stripped))
            except json.JSONDecodeError as e:
                logger.warning(f"Skipping malformed JSON on line {lineno}: {e}")
    return profiles


def write_analytics(output_file: str, analytics: List[Dict[str, Any]]) -> None:
    """Write analytics objects to file with visual dividers."""
    path = Path(output_file)
    with path.open("w", encoding="utf-8") as f:
        f.write(f"# Google Travel property analytics\n")
        f.write(f"# Generated at: {datetime.utcnow().isoformat()}Z\n")
        f.write(f"# Property count: {len(analytics)}\n")
        f.write("=" * 80 + "\n\n")

        for idx, entry in enumerate(analytics, 1):
            f.write("=" * 80 + "\n")
            f.write(f"# PROPERTY {idx} / {len(analytics)}\n")
            f.write("=" * 80 + "\n")
            f.write(json.dumps(entry, indent=2, ensure_ascii=False))
            f.write("\n\n")


# ---------------------------------------------------------------------
# Entry
# ---------------------------------------------------------------------

def main() -> None:
    logger.info(f"Reading profiles from: {INPUT_FILE}")
    profiles = read_profiles(INPUT_FILE)
    logger.info(f"Loaded {len(profiles)} profile(s)")

    analytics: List[Dict[str, Any]] = []
    for profile in profiles:
        name = profile.get("property_name") or "(unknown)"
        logger.info(f"Analysing: {name}")
        try:
            analytics.append(build_analytics(profile))
        except Exception as e:
            logger.error(f"Failed to analyse '{name}': {e}")
            analytics.append({
                "meta": {
                    "generated_at": datetime.utcnow().isoformat() + "Z",
                    "property_name": name,
                    "error": str(e),
                }
            })

    logger.info(f"Writing analytics to: {OUTPUT_FILE}")
    write_analytics(OUTPUT_FILE, analytics)
    logger.info(f"Done. Wrote {len(analytics)} analytic object(s).")


if __name__ == "__main__":
    main()