"""Command-line interface for individual profile generation."""
from __future__ import annotations

import argparse
import logging
import sys
from typing import List, Optional

from individual.runner import run_single
from individual.validator import validate
from profile_plugins.manager import list_known_domains
from utils.logging_utils import configure_logging, get_logger

logger = get_logger(__name__)


# Exit codes — small, stable, scriptable.
_EXIT_OK = 0
_EXIT_VALIDATION = 2
_EXIT_RUNTIME = 3


def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="individual_profile",
        description=(
            "Generate a single OTA profile by fetching a URL directly, "
            "using the same client + parser as the wildcard pipeline."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "Examples:\n"
            "  python3 individual_profile.py \\\n"
            "      -domain booking_com \\\n"
            "      -url https://www.booking.com/hotel/nl/soho.en-gb.html\n\n"
            "  python3 individual_profile.py \\\n"
            "      -domain expedia \\\n"
            "      -url 'https://www.expedia.nl/Hotel-Search?selected=17578&startDate=2026-12-06&endDate=2026-12-07'\n"
        ),
    )
    p.add_argument(
        "-domain", "--domain",
        required=True,
        metavar="NAME",
        help=(
            "Which OTA to use. Known: "
            + ", ".join(list_known_domains())
        ),
    )
    p.add_argument(
        "-url", "--url",
        required=True,
        metavar="URL",
        help="URL to fetch and parse. Must belong to the -domain OTA.",
    )
    p.add_argument(
        "-name", "--name",
        default=None,
        help=(
            "Optional human-readable property name to store as "
            "_property_name. If omitted, the parser's derived name is used."
        ),
    )
    p.add_argument(
        "-o", "--output-dir",
        default="./sub_profiles",
        help="Directory to write the JSONL file (default: ./sub_profiles).",
    )
    p.add_argument(
        "-t", "--timeout",
        type=float,
        default=15.0,
        help="HTTP timeout in seconds (default: 15).",
    )
    p.add_argument(
        "-v", "--verbose",
        action="store_true",
        help="Enable DEBUG logging.",
    )
    p.add_argument(
        "--dry-run",
        action="store_true",
        help="Validate inputs and print what would happen, but do not fetch.",
    )
    return p


def _print_usage_hint() -> None:
    print(
        "\nRun with -h for full help. "
        "Example: python3 individual_profile.py "
        "-domain booking_com "
        "-url https://www.booking.com/hotel/nl/soho.en-gb.html",
        file=sys.stderr,
    )


def main(argv: Optional[List[str]] = None) -> int:
    args = _build_parser().parse_args(argv)

    configure_logging(level=logging.DEBUG if args.verbose else logging.INFO)

    # ---- Validate --------------------------------------------------
    result = validate(args.domain, args.url)
    if not result.ok:
        for err in (result.errors or []):
            logger.error("validation: %s", err)
        _print_usage_hint()
        return _EXIT_VALIDATION

    assert result.url is not None
    assert result.domain is not None

    logger.info(
        "individual_profile: validated domain=%s url=%s",
        result.domain, result.url,
    )

    if args.dry_run:
        print(
            f"OK (dry-run)\n"
            f"  domain:  {result.domain}\n"
            f"  url:     {result.url}\n"
            f"  output:  {args.output_dir}"
        )
        return _EXIT_OK

    # ---- Run -------------------------------------------------------
    run_result = run_single(
        url=result.url,
        domain=result.domain,
        output_dir=args.output_dir,
        timeout=args.timeout,
        property_name=args.name,
    )

    if not run_result.ok:
        logger.error("individual_profile: %s", run_result.reason)
        return _EXIT_RUNTIME

    assert run_result.output_path is not None
    print(f"OK  wrote -> {run_result.output_path}")
    return _EXIT_OK


if __name__ == "__main__":
    sys.exit(main())