#!/usr/bin/env python3
"""
Entrypoint for the individual profile generator.

Usage:
    python3 individual_profile.py -domain booking_com \
        -url "https://www.booking.com/hotel/nl/soho.en-gb.html"

    python3 individual_profile.py -domain expedia_com \
        -url "https://www.expedia.nl/Hotel-Search?selected=17578&startDate=2026-12-06&endDate=2026-12-07&..."

Reuses the same client + parser classes as the wildcard (Google profile)
pipeline, so any field the wildcard path produces, this produces too.
"""
import sys

from individual.cli import main

if __name__ == "__main__":
    sys.exit(main())