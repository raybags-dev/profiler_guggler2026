# OTA Profile Aggregator - Developer Guide

A two-path pipeline for extracting structured hotel profiles from Online Travel Agencies (OTAs). Both paths share the same clients, parsers, HTTP layer, and JSONL output format.

---

## Table of Contents

1. [Architecture Overview](#architecture-overview)
2. [Directory Layout](#directory-layout)
3. [The Two Entrypoints](#the-two-entrypoints)
4. [Core Abstractions](#core-abstractions)
5. [The Registry](#the-registry)
6. [Adding a New OTA](#adding-a-new-ota)
7. [Session Management (curl files)](#session-management-curl-files)
8. [Response Validation and Retries](#response-validation-and-retries)
9. [Output Format](#output-format)
10. [Debugging](#debugging)
11. [Notes](#notes)
12. [Appendix - Full Flow for One Property](#appendix--full-flow-for-one-property)

---

## Architecture Overview

The pipeline has two entrypoints that converge on the same client-parser-executor logic:

```
                    +----------------------------------+
                    |  Google Travel Search (wildcard) |
                    +----------------+-----------------+
                                     |
                                     | profile["providers"] = [
                                     |   {name, deeplink, logo_url}, ...
                                     | ]
                                     v
  +----------------------+   +-----------------------+
  | individual_profile.py|   | google_profile_*.py   |
  |  (single URL, CLI)   |   |  (wildcard, batch)    |
  +----------+-----------+   +----------+------------+
             |                          |
             |             +------------v------------+
             |             |     PluginManager       |
             |             |  .process_profile(...)  |
             |             +------------+------------+
             |                          |
             |                          |
             +----------+---------------+
                        |
                        v
              +------------------+
              |   Registry       |  name -> {client_cls, parser_cls, output_name, aliases}
              +--------+---------+
                       |
        +--------------+--------------+--------------+
        v              v              v              v
   BookingClient  AgodaClient   TripClient    ExpediaClient
   BookingParser  AgodaParser   TripParser    ExpediaParser
        |              |              |              |
        +--------------+------+-------+--------------+
                              |
                              v
                    sub_profiles/<ota>.jsonl
```

**Key invariant:** the individual path and the wildcard path produce *identical* JSONL rows for the same property. Only one field differs - `_source` - which records which entrypoint wrote the row.

---

## Directory Layout

```
.
|-- google_profile_scraper.py       # wildcard entrypoint (existing)
|-- individual_profile.py           # single-URL CLI entrypoint (new)
|
|-- individual/
|   |-- __init__.py
|   |-- cli.py                      # argparse, exit codes, dry-run
|   |-- runner.py                   # drives one client+parser against one URL
|   `-- validator.py                # input validation (domain, URL, host)
|
|-- profile_plugins/
|   |-- base_client.py              # BaseOtaClient (HTTP, cookies, retries)
|   |-- base_parser.py              # BaseOtaParser (parse, follow-ups)
|   |-- manager.py                  # registry + PluginManager (wildcard)
|   |-- curl_parser.py              # parses captured browser curl files
|   |
|   |-- shared_client/              # one client per OTA
|   |   |-- booking_client.py
|   |   |-- agoda_client.py
|   |   |-- trip_client.py
|   |   `-- expedia_client.py
|   |
|   |-- plugin_parsers/             # one parser per OTA
|   |   |-- booking_parser.py
|   |   |-- agoda_parser.py
|   |   |-- trip_parser.py
|   |   `-- expedia_parser.py
|   |
|   `-- curl_sessions/              # captured browser sessions
|       |-- booking_com.curl
|       |-- agoda_com.curl
|       |-- trip_com.curl
|       `-- expedia_com.curl
|
|-- utils/
|   |-- logging_utils.py            # centralized logger factory
|   |-- http_utils.py               # retry policy, size thresholds
|   |-- session_utils.py            # session-expiry detection + flag files
|   |-- jsonl_utils.py              # append_jsonl helper
|   `-- string_utils.py             # clean_text (bidi stripping, whitespace)
|
`-- sub_profiles/                   # output
    |-- booking_com.jsonl
    |-- agoda.jsonl
    |-- trip_com.jsonl
    `-- expedia_com.jsonl
```

---

## The Two Entrypoints

### 1. Wildcard: `google_profile_scraper.py`

Given a Google Travel Search URL or keyword, crawls Google's results, extracts a `providers[]` array (one entry per OTA), and dispatches each provider to the matching plugin via `PluginManager`.

```bash
python3 google_profile_scraper.py
```

Reads target keywords from configuration, or accepts a Google URL. This is the batch path you use for full property research.

### 2. Individual: `individual_profile.py`

Given a single URL and an OTA name, fetches the page directly and writes one JSONL row. No Google involvement.

```bash
python3 individual_profile.py -domain booking_com \
    -url "https://www.booking.com/hotel/nl/soho.en-gb.html"
```

#### Options

| Flag | Purpose |
|---|---|
| `-domain NAME` | Which OTA plugin to use. Aliases and TLD-qualified names accepted (`booking`, `booking.de`, `Booking.com`, ...). |
| `-url URL` | The URL to fetch. Must belong to the selected OTA. |
| `-name NAME` | Optional override for `_property_name`. If omitted, uses the parser's derived name. |
| `-o DIR` | Output directory (default `./sub_profiles`). |
| `-t SECONDS` | HTTP timeout (default 15.0). |
| `-v` | DEBUG logging. |
| `--dry-run` | Validate inputs and print what would happen; do not fetch. |

#### Exit Codes

| Code | Meaning |
|---|---|
| `0` | Success, one row written |
| `2` | Input validation failed (unknown domain, malformed URL, host mismatch) |
| `3` | Runtime failure (network, HTTP error, parser exception) |

Both entrypoints call the same `_process_one`-equivalent logic. Any field produced by the wildcard path is produced by the individual path.

---


## Pre-flight

Before running the pipeline for the first time (or after a `git pull` that
touched dependencies), run the pre-flight check. It verifies the
environment, creates missing directories, installs missing dependencies,
and tells you exactly which captured sessions you still need to provide.

### One-shot bootstrap

```bash
./plumbing.sh
```

That command:

1. Creates `venv/` at the project root if it doesn't exist.
2. Activates it.
3. Runs `plumbing.py`, which:
   - Confirms a virtualenv is active.
   - Checks the Python version (3.10+ required).
   - Installs anything missing from `requirements.txt`.
   - Creates the directory tree: `sub_profiles/`, `curl_sessions/`, etc.
   - Verifies every source file the pipeline imports.
   - Parses each `curl_sessions/*.curl` and reports header/cookie counts.
   - Checks `configs/config.py` is present.
   - Imports every plugin module to catch syntax or dependency errors.
   - Confirms the plugin registry contains all five OTAs.

If everything is present, the script exits with code `0` and prints:

```
Pipeline is ready. Try:
  python3 individual_profile.py -domain booking_com \
      -url 'https://www.booking.com/hotel/nl/soho.en-gb.html'
```

If anything is missing, the script exits with code `1` and lists the
failing items with instructions on how to fix each one.

### Options

| Command | What it does |
|---|---|
| `./plumbing.sh` | Activate or create `venv/`, then run pre-flight. |
| `./plumbing.sh --fresh` | Delete `venv/` first, recreate it from scratch, then run pre-flight. Use after a Python version change or when a venv is corrupted. |
| `./plumbing.sh --no-venv` | Skip venv management. Run `plumbing.py` against whatever `python3` is on `PATH`. Useful in CI or Docker where the environment is managed externally. |
| `./plumbing.sh --help` | Print the usage banner. |

### Reading the output

Each check prints one of:

- `[OK  ]` - item present or resolved.
- `[MISS]` - item missing; instructions follow.

Sections are grouped and always print in the same order:

```
Virtual environment       - is a venv active?
Python version            - is python 3.10+?
Dependencies              - are requirements.txt packages installed?
Directory structure       - do all required dirs exist?
Source files              - is every imported module on disk?
Captured curl sessions    - do the five .curl files parse?
configs/config.py         - is the config module present?
Module imports            - do all plugins import without error?
Plugin registry           - are all five OTAs registered?
Summary                   - one line per section, [OK] or [FAIL]
```

### What `plumbing.sh` handles automatically

- **Creates `venv/`** if absent.
- **Activates the venv** so `pip install` writes to the right place.
- **Installs `requirements.txt`** if any dependency is missing.
- **Creates missing directories** including `sub_profiles/`.

You never have to `mkdir` or `pip install` manually before running the
pipeline.

### What `plumbing.sh` cannot handle

Two items require human action, because they depend on browser state or
environment-specific values:

1. **Captured curl sessions.** Each OTA sits behind a WAF that requires
   a real browser session. See
   [Capturing a session](#capturing-a-session) below. The pre-flight
   will tell you which ones are missing but cannot create them.

2. **`configs/config.py`.** Contains environment-specific values
   (paths, timeouts, API keys). The pre-flight checks that it exists
   and is importable; it cannot generate one for you.

When either is missing, the pre-flight prints step-by-step recovery
instructions and exits non-zero.

### First-run checklist

For a new contributor, the full sequence is:

```bash
# 1. Clone
git clone <repo-url>
cd <repo>

# 2. Pre-flight - creates venv, installs deps, reports what's missing
./plumbing.sh

# 3. Capture the curl sessions the pre-flight flagged as [MISS].
#    Instructions are printed inline. Save each to:
#      profile_plugins/curl_sessions/<ota>_com.curl
#
#    The five you need:
#      booking_com.curl
#      agoda_com.curl
#      trip_com.curl
#      expedia_com.curl
#      tripadvisor_com.curl

# 4. Re-run pre-flight to confirm all green
./plumbing.sh

# 5. Run the pipeline
python3 individual_profile.py -domain booking_com \
    -url "https://www.booking.com/hotel/nl/soho.en-gb.html"

# or the full wildcard run
python3 google_profile_scraper.py
```

### Re-running pre-flight

Safe to run anytime. It is idempotent - running it on a ready environment
takes ~2 seconds and changes nothing. Run it:

- After `git pull` to confirm dependencies still resolve.
- After editing `requirements.txt`.
- When a session file goes stale (the pipeline writes a
  `<ota>.session_expired` flag; the pre-flight will show the file still
  parses, but the pipeline itself will fail - see
  [Session rotation](#session-rotation)).
- Before opening a bug report, so you can attach the pre-flight output.

### CI / headless use

In a CI runner where the environment is managed externally (Docker image,
GitHub Actions, etc.), use:

```bash
./plumbing.sh --no-venv
```

The script will skip venv creation/activation and run the checks against
the active interpreter. Useful for:

```yaml
# .github/workflows/ci.yml
- name: Pre-flight
  run: ./plumbing.sh --no-venv
```

The exit code is `0` when the environment is complete, `1` when
something is missing - usable as a gate before the actual test suite.


### Cleaning up

To reset the working directory without deleting source:

```bash
./cleanup.sh              # remove runtime output, caches, temp dumps
./cleanup.sh --dry-run    # print what would be removed, do nothing
./cleanup.sh --hard       # also remove venv/
```

| Mode | Removes |
|---|---|
| default | `sub_profiles/*.jsonl`, `sub_profiles/*.session_expired`, `__pycache__/`, `*.pyc`, `.pytest_cache/`, `.mypy_cache/`, `.ruff_cache/`, `/tmp/expedia_followup.html`, `*.log` |
| `--dry-run` | same as default, but only prints the actions |
| `--hard` | all of the above, plus `venv/` |

`cleanup.sh` never touches `curl_sessions/*.curl`, `configs/config.py`,
`requirements.txt`, or any tracked source file.

### Recovery recipes

A few common situations and their fixes:

**`[FAIL] venv` - no active virtualenv**

```bash
source venv/bin/activate
./plumbing.sh
```

**`[FAIL] deps` - a package is missing or fails to install**

```bash
./plumbing.sh --fresh    # rebuild venv, reinstall everything
```

**`[FAIL] curl` - a session file is missing or unreadable**

Recapture from a browser. See [Capturing a session](#capturing-a-session).

**`[FAIL] imports` - a module raises on import**

Read the traceback printed by the pre-flight. Usually a missing entry in
`requirements.txt` or a typo in a new file.

**`[FAIL] registry` - an OTA isn't registered**

Check `profile_plugins/manager.py`'s `_build_registry()`. If a
`try/except ImportError` block is failing silently, import the offending
client directly to see the real error:

```bash
python3 -c "from profile_plugins.shared_client.<ota>_client import <Ota>Client"
```

**`[FAIL] config` - `configs/config.py` missing**

Copy from a teammate, or reconstruct from `configs/config.example.py` if
your repo provides one. Never commit secrets.

### What the pre-flight does not check

- **Live network access.** It does not fetch any URLs. A successful
  pre-flight means the environment is ready, not that the OTAs are
  reachable or that the sessions are fresh.
- **Session validity.** It parses each curl file to verify it's
  well-formed but cannot test whether the cookies are still accepted
  by the OTA. That's a runtime concern; see
  [Session rotation](#session-rotation).
- **Downstream consumers.** It checks that the pipeline can start. It
  doesn't verify anything that consumes `sub_profiles/*.jsonl`.

### Exit codes

| Code | Meaning |
|---|---|
| `0` | All checks passed. Pipeline ready. |
| `1` | One or more checks failed. See the summary section. |
| `2` | Invalid argument to `plumbing.sh`. |


## Core Abstractions

### BaseOtaClient (profile_plugins/base_client.py)

Everything network-related. One subclass per OTA.

#### Required overrides

| Attribute / method | Purpose |
|---|---|
| `name: str` | Short identifier, e.g. `"booking_com"`. Used in logs and by the registry. |
| `normalize_url(raw) -> str` | Transform the incoming URL into one the client can GET. Most OTAs just `.strip()`. |

#### Optional overrides

| Attribute | Default | Purpose |
|---|---|---|
| `curl_file: Optional[str]` | `None` | Path to a captured browser session file. |
| `extra_headers: Dict[str, str]` | `{}` | Per-OTA headers merged into defaults. |
| `min_response_bytes: int` | `50_000` | Anything smaller is considered a challenge page. |
| `accepts_hosts: Tuple[str, ...]` | `()` | Regex patterns for valid hostnames (used by the individual CLI validator). |
| `session_expired_markers: Tuple[str, ...]` | `()` | Substrings that indicate "your session is stale" rather than "transient failure". |
| `flag_dir: Path` | `./sub_profiles` | Where to write `<client>.session_expired` flag files. |

#### What `fetch(url)` does

1. Normalizes the URL.
2. Sends the request with headers + cookies from the curl session.
3. Retries on 202 / 429 / 503 / too-short body. Retry delay honors `Retry-After` when present, otherwise 1.5 s.
4. Rejects the response if status is non-2xx or the body is under `min_response_bytes`.
5. Classifies the failure as session-expired (if `session_expired_markers` matches) or generic-challenge.
6. Returns the HTML, or `None` on failure. **Never raises.**

### BaseOtaParser (profile_plugins/base_parser.py)

Everything parse-related. One subclass per OTA.

#### Required overrides

| Method | Purpose |
|---|---|
| `parse(html, source_url) -> Dict[str, Any]` | Extract fields from the primary page. Always returns a dict, `parse_ok` set to `True`. |

#### Optional overrides

| Method | Default | Purpose |
|---|---|---|
| `follow_up_urls(parsed) -> List[str]` | `[]` | URLs to fetch after the primary. |
| `merge_follow_up(parsed, url, html) -> None` | no-op | Merge data from a follow-up page into the parsed dict. |

#### Naming convention

Every parsed dict carries a `<ota>_` prefix on its OTA-specific fields:

- `booking_property_name`
- `trip_property_id`, `trip_star_rating`
- `agoda_price`, `agoda_rooms`
- `expedia_locale`, `expedia_highlights`

This keeps cross-OTA joins unambiguous.

---

## The Registry

Defined in `profile_plugins/manager.py`. This is the single source of truth for "which OTAs does this pipeline support".

```python
registry["Booking.com"] = {
    "client_cls": BookingClient,
    "parser_cls": BookingParser,
    "output_name": "booking_com",
    "aliases": ("booking", "booking.com"),
}
```

| Key | Type | Purpose |
|---|---|---|
| registry key | str | Canonical display name, matches `providers[].name` in Google profiles. |
| `client_cls` | Type | The `BaseOtaClient` subclass. |
| `parser_cls` | Type | The `BaseOtaParser` subclass. |
| `output_name` | str | Filename stem for JSONL output (`<output_name>.jsonl`). |
| `aliases` | tuple[str, ...] | Lowercase alternatives for the CLI `-domain` flag and for Google's provider names. |

### Public accessors

```python
from profile_plugins.manager import (
    get_registry,              # -> Dict[str, entry]
    get_registry_entry,        # exact-name lookup -> entry or None
    list_registered_providers, # -> sorted list of exact registry keys
    resolve_registry_entry,    # alias/TLD-aware lookup -> entry or None
    list_known_domains,        # -> every alias the resolver accepts
)
```

The registry is built lazily and cached. Every `try/except ImportError` block means a missing client/parser module degrades gracefully - the OTA simply isn't registered, and the wildcard path logs `no plugin for <name>` and skips it.

**Both entrypoints use `resolve_registry_entry`.** This means Google can emit any of `"Expedia.nl"`, `"Expedia.com"`, `"expedia"`, or `"expedia.dk"` and all four resolve to the same client+parser. Adding an OTA to the registry makes it resolvable everywhere with zero further changes.

---

## Adding a New OTA

Say you want to add Tripadvisor. You touch exactly four places - nothing in `individual/` needs to change.

### Step 1 - Create the client

`profile_plugins/shared_client/tripadvisor_client.py`:

```python
"""Tripadvisor OTA client."""
from __future__ import annotations

from pathlib import Path

from profile_plugins.base_client import BaseOtaClient


class TripadvisorClient(BaseOtaClient):
    name = "tripadvisor_com"

    accepts_hosts = (
        r'^(?:www\.)?tripadvisor\.[a-z]{2}$',
        r'^(?:www\.)?tripadvisor\.com$',
        r'^(?:www\.)?tripadvisor\.co\.uk$',
    )

    min_response_bytes = 30_000

    curl_file = str(
        Path(__file__).resolve().parents[1]
        / "curl_sessions"
        / "tripadvisor_com.curl"
    )

    session_expired_markers = (
        "captcha",
        "are you a human",
        "access denied",
    )

    def normalize_url(self, raw_deeplink: str) -> str:
        return raw_deeplink.strip()
```

### Step 2 - Create the parser

`profile_plugins/plugin_parsers/tripadvisor_parser.py`:

```python
"""Tripadvisor OTA parser."""
from __future__ import annotations

from typing import Any, Dict

from profile_plugins.base_parser import BaseOtaParser


class TripadvisorParser(BaseOtaParser):
    name = "tripadvisor_com"

    def parse(self, html: str, source_url: str) -> Dict[str, Any]:
        # ... your extraction logic ...
        return {
            "source_url": source_url,
            "title": self.parse_title(html),
            "html_length": len(html),

            "tripadvisor_property_id": None,
            "tripadvisor_property_name": None,
            "tripadvisor_star_rating": None,
            "tripadvisor_address": None,
            "tripadvisor_description": None,
            "tripadvisor_gallery": None,

            "parse_ok": True,
        }
```

### Step 3 - Register it

`profile_plugins/manager.py`, inside `_build_registry()`:

```python
    # --- Tripadvisor ---
    try:
        from profile_plugins.shared_client.tripadvisor_client import TripadvisorClient
        from profile_plugins.plugin_parsers.tripadvisor_parser import TripadvisorParser

        registry["Tripadvisor"] = {
            "client_cls": TripadvisorClient,
            "parser_cls": TripadvisorParser,
            "output_name": "tripadvisor_com",
            "aliases": ("tripadvisor", "tripadvisor.com"),
        }
    except ImportError:
        logger.debug("Tripadvisor plugin not installed")
```

### Step 4 - Capture a curl session

See [Session Management](#session-management-curl-files) below. Save it to `curl_sessions/tripadvisor_com.curl`.

### Result

Both entrypoints pick it up automatically:

- Wildcard: Google profiles that include `"name": "Tripadvisor"` (or any alias) will dispatch to it.
- Individual: `python3 individual_profile.py -domain tripadvisor -url "https://www.tripadvisor.com/Hotel_Review-..."`

### Checklist

| # | File | Action |
|---|---|---|
| 1 | `shared_client/tripadvisor_client.py` | Create class, set `name`, `accepts_hosts`, `curl_file`, `session_expired_markers` |
| 2 | `plugin_parsers/tripadvisor_parser.py` | Create class, implement `parse` (and optionally `follow_up_urls`/`merge_follow_up`) |
| 3 | `manager.py` -> `_build_registry()` | Add one `try/except` block |
| 4 | `curl_sessions/tripadvisor_com.curl` | Capture from a real browser session |

**Do not touch** `individual/runner.py`, `individual/validator.py`, `individual/cli.py`, or `individual_profile.py`. The registry-driven resolver means the new OTA becomes discoverable automatically.

---

## Session Management (curl files)

Most OTAs sit behind a WAF. A cold `httpx` request gets a 403, 429, or a JS challenge. The fix is to replay a real browser session.

### Capturing a session

1. Open the OTA in a browser.
2. Navigate to the URL you want to scrape.
3. Open DevTools -> Network.
4. Right-click the top-level document request -> Copy as cURL (bash).
5. Paste the entire command into a file: `profile_plugins/curl_sessions/<ota>_<tld>.curl`.

The parser (`curl_parser.py`) reads the headers and cookies from that file. The URL in the curl is ignored.

### What the client loads

- Every `-H 'Key: Value'` becomes a request header.
- Every cookie in `-H 'Cookie: a=b; c=d'` becomes a cookie.
- Cookies are sent as a raw `Cookie:` header, not via httpx's `cookies=` param. This preserves byte-for-byte fidelity with the browser session and avoids httpx silently dropping cookies with characters that RFC 6265 forbids (`+`, `/`, `:` in session tokens).

### Session expiry

When a session goes stale, the OTA usually returns a small body with a distinctive marker:

| OTA | Signal |
|---|---|
| Booking | HTTP 202, ~4 KB shell |
| Expedia | HTTP 429 or a ~25 KB challenge page |
| Agoda | Small body from `/partnersearch.aspx` |
| Trip | Shell missing `__NFES_DATA__` |

Each client declares `session_expired_markers`. When a rejected response's body matches one of them, the client calls `SessionExpiryTracker.record_expiry()`. After 3 consecutive expiries, a flag file is written:

```
sub_profiles/<ota>.session_expired
```

and one ERROR line is logged. That's your signal to recapture the curl file. The flag is cleared automatically on the next successful fetch.

### Rotation policy

Manual rotation is the recommended approach. Automating it means keeping a headless browser logged in, storing credentials, bypassing 2FA, and - for Booking and Expedia - explicitly violating their Terms of Service. In practice a captured session is valid for hours to days. The 3-strike flag tells you exactly when to act.

When the flag appears:

1. Recapture the curl from a browser (see above).
2. Overwrite `curl_sessions/<ota>.curl`.
3. Delete the flag file (`rm sub_profiles/<ota>.session_expired`).

---

## Response Validation and Retries

All retry logic lives in `BaseOtaClient.fetch()`. No parser or runner needs to know about it.

### Retry triggers

A response is retried if:

- Status is `202` (Booking's "still warming up"), `429`, or `503`.
- Status is 2xx but body length is under `min_response_bytes`.

### Retry delay

The retry delay is chosen in this order:

1. **`Retry-After` header** - if the server sent one, honor it exactly.
2. **Default 1.5 s** - if there's no header, use the fixed default.

See [Notes → Backoff strategy](#backoff-strategy) for the recommended upgrade to exponential-with-jitter if you start seeing sustained 429s.

### Rejection conditions

- Status not in `[200, 300)`.
- Body length under `min_response_bytes`.

Each rejection is logged with the status, byte count, URL, and final URL (after redirects) so you can diagnose without rerunning.

### Per-OTA thresholds

| Client | `min_response_bytes` | Rationale |
|---|---|---|
| Booking | `50_000` (default) | Real pages are 1.8–5 MB. |
| Agoda | `50_000` (default) | Real pages are ~315 KB. |
| Trip | `50_000` (default) | Real pages are 500 KB–2 MB. |
| Expedia | `30_000` | Real pages are 1.2–2.2 MB; challenge pages are ~25 KB. |

---

## Output Format

Every parsed dict is appended as one line of JSON to `sub_profiles/<output_name>.jsonl`.

### Common fields (every OTA)

| Field | Type | Source |
|---|---|---|
| `source_url` | str | The URL that was fetched. |
| `title` | str or null | Page `<title>`. |
| `og_site_name` | str or null | `og:site_name` meta. |
| `html_length` | int | Byte length of the primary page. |
| `parse_ok` | bool | Always `true` for a successfully parsed row. |
| `_property_name` | str | Human-readable name. Wildcard: from Google. Individual: parser-derived or `-name` override. |
| `_provider_name` | str or null | Provider identifier (`"Booking.com"`, `"Expedia.nl"`, etc.). |
| `_provider_logo_url` | str or null | From the Google profile; null in the individual path. |
| `_follow_up_status` | str | `"ok"` / `"failed"` / `"merge_error"` / `"not_scheduled"`. |
| `_source` | str | `"individual_cli"` for the individual path; absent for the wildcard path. |

### OTA-specific fields

Each parser declares its own fields with a `<ota>_` prefix. Examples:

- Booking: `booking_property_id`, `booking_property_name`, `booking_star_rating`, `booking_gallery`, `booking_rooms`, ...
- Expedia: `expedia_property_id`, `expedia_locale`, `expedia_currency`, `expedia_price_nightly`, `expedia_highlights`, `expedia_rooms`, ...

### Appending semantics

The JSONL files are append-only. Running the same URL twice produces two rows. Deduplication is the consumer's responsibility - join on `(source_url, _source)` or on the OTA-specific `*_property_id`.

### Downstream notes

- Fields prefixed with `_` are metadata, not property data.
- Nulls are explicit - a field with no extracted value is present as `null`, not omitted. This makes schema validation easier.
- All strings pass through `clean_text()` (`utils/string_utils.py`), which strips HTML entities, bidi control characters, and collapses whitespace.

---

## Debugging

### Enable verbose logging

Both entrypoints accept `-v`:

```bash
python3 individual_profile.py -domain expedia -url "..." -v
```

Or set the level programmatically:

```python
from utils.logging_utils import configure_logging
import logging
configure_logging(level=logging.DEBUG)
```

### Common failure modes

| Symptom | Likely cause | Fix |
|---|---|---|
| `curl file not found` | `curl_sessions/<ota>.curl` missing | Capture from browser |
| `response too short to be a real page` | Session expired OR wrong URL shape | Recapture curl; check URL is the property page |
| `HTTP 202` on Booking | Session expired | Recapture `booking_com.curl` |
| `HTTP 429` on Expedia | Burst rate limit or cross-locale cookie | Honor `Retry-After`; space requests; ensure curl domain matches URL domain |
| `HTTP 403` | Cloudflare / WAF | Session expired, or TLS fingerprint rejection |
| `no plugin for <name>` in wildcard | OTA not registered under that name | Add alias to registry entry |
| `unknown -domain` in CLI | Alias not in registry | Add alias to the registry entry |
| `host does not belong to domain` | URL/plugin mismatch | Check `accepts_hosts` patterns, or use the correct URL |
| Parser returns null for a field | Page shape changed | Inspect the saved HTML dump, update the parser |

### Dumping pages for inspection

Several parsers write the raw HTML to `/tmp` for offline inspection:

| Parser | Dump path | Toggle |
|---|---|---|
| Expedia | `/tmp/expedia_followup.html` | `_DEBUG_DUMP_FOLLOWUP` |

For others, add a temporary dump at the top of `parse()`:

```python
from pathlib import Path
Path("/tmp/debug_booking.html").write_text(html, encoding="utf-8")
```

Or use the individual CLI with `-o /tmp` to isolate output from production.

### Testing a single parser

```python
from profile_plugins.plugin_parsers.expedia_parser import ExpediaParser

html = open("/tmp/expedia_followup.html", encoding="utf-8").read()
parser = ExpediaParser()
parsed = parser.parse(html, "https://www.expedia.nl/en/h17578.Hotel-Information")
print(parsed)
```

### Testing the validator

```python
from individual.validator import validate

r = validate("expedia.dk", "https://www.expedia.dk/en/h17578.Hotel-Information")
print(r.ok, r.domain, r.registry_key, r.errors)

r = validate("booking_com", "https://www.expedia.nl/x")
print(r.ok, r.errors)
```

### Testing the registry

```python
from profile_plugins.manager import (
    list_registered_providers,
    list_known_domains,
    resolve_registry_entry,
)

print(list_registered_providers())
print(list_known_domains())

entry = resolve_registry_entry("expedia.dk")
print(entry["output_name"])  # -> "expedia_com"
```

### Pylance / type checking

The codebase is written to pass `basedpyright` with `reportUnknown*` enabled. Rules of thumb when adding code:

- Never leave a bare `Any` at a module boundary.
- Use `cast(Dict[str, Any], x)` after `isinstance(x, dict)` so downstream calls have known types.
- Type every function signature and every class attribute.
- Module-level mutables must be lowercase (`_cache`, not `_CACHE`) to avoid `reportConstantRedefinition`.
- Helpers used by another module must be public (no leading underscore) or you'll hit `reportPrivateUsage`.

---

## Notes

Operational notes, gotchas, and follow-ups that don't fit neatly into the sections above.

### Turn off debug dumps in production

`expedia_parser.py` has a module-level flag that writes the full follow-up HTML to disk on every parse:

```python
# Flip to True to dump the follow-up HTML to /tmp for inspection.
_DEBUG_DUMP_FOLLOWUP = True
```

While enabled, every Expedia property overwrites `/tmp/expedia_followup.html`. That's fine during development - it's the fastest way to inspect the current page shape - but it's noise in production:

- It slows down each Expedia parse by ~50–100 ms (writing 1.5–2.2 MB to disk).
- It leaves a stale file on disk between runs that can mislead debugging.
- On systems with limited `/tmp`, repeated large writes can fill the volume.

**Set it to `False` before shipping:**

```python
_DEBUG_DUMP_FOLLOWUP = False
```

Flip it back to `True` only when you're actively debugging a parser shape change. If you want per-parser dumps without editing source, wrap it in an env var:

```python
import os
_DEBUG_DUMP_FOLLOWUP = os.environ.get("EXPEDIA_DUMP_HTML") == "1"
```

Then `EXPEDIA_DUMP_HTML=1 python3 ...` for a one-off debug run.

### Booking.com session drift

A freshly-rotated `booking_com.curl` is valid for **hours to days**, not minutes. Booking's session cookies (`bkng`, `_ga_*`, `AWSALB*`) expire on a rolling window that's typically measured in hours of *activity* rather than wall-clock time - so a session that's used every few minutes outlasts one that sits idle for a day.

You'll know the session has gone stale when the `.session_expired` flag file appears:

```
sub_profiles/booking_com.session_expired
```

That file is written by `SessionExpiryTracker` after **3 consecutive session-expiry events** from the same client instance. It means Booking has been answering with the small 202 shell repeatedly - a fresh curl is required. The flag is cleared automatically the first time a fetch succeeds after rotation.

**When the flag appears:**

1. Open Booking.com in a browser.
2. Navigate to any hotel page or search result.
3. Copy the document request as cURL (DevTools → Network → right-click → Copy as cURL).
4. Overwrite `profile_plugins/curl_sessions/booking_com.curl`.
5. Delete the flag file: `rm sub_profiles/booking_com.session_expired`.
6. Next run: `booking_com: loaded curl session - N headers, M cookies` and normal fetches resume.

Same pattern applies to any OTA - the flag filename is always `<output_name>.session_expired`.

### Backoff strategy

The current retry logic uses a **fixed 1.5 s delay** between attempts, honoring `Retry-After` when the server sends it. That's adequate for isolated 429s and 202 warm-up hops. It is **not** adequate when you're being rate-limited hard, which happens on Expedia when you run many properties back-to-back.

Here's the professional approach, in three layers. Adopt them in order - the earlier layers are cheaper.

#### Layer 1 - Always honor `Retry-After`

Already implemented in `utils/http_utils.py::retry_after_seconds`. When Booking, Expedia, or Agoda returns a 429 or 503, they usually include a `Retry-After: <seconds>` header. Our retry delay reads it. Never override it with a fixed guess.

If you see a 429 without a `Retry-After`, that's the signal to move to Layer 2.

#### Layer 2 - Exponential backoff with jitter

Replace the fixed delay with `min(cap, base * 2^attempt) ± jitter`:

```python
import random

def backoff_seconds(attempt: int, base: float = 2.0,
                    cap: float = 60.0, jitter: float = 0.25) -> float:
    """
    Exponential backoff with jitter.

    attempt=0 -> ~2s, attempt=1 -> ~4s, attempt=2 -> ~8s, ...
    Capped at `cap` seconds. Jitter is ±25% to avoid thundering herd
    when multiple clients retry the same URL.
    """
    raw = min(cap, base * (2 ** attempt))
    delta = raw * jitter
    return raw + random.uniform(-delta, delta)
```

Then in `BaseOtaClient.fetch`:

```python
delay = retry_after_seconds(resp, backoff_seconds(attempt))
sleep_before_retry(delay)
```

**Why jitter?** If you ever run multiple scrapers concurrently, fixed backoff makes them all retry at the same moment and re-trigger the rate limit together. Jitter staggers them.

**Why cap at 60 s?** Beyond a minute, you're better off giving up and letting the caller decide (retry the property later, or accept the miss). A hung retry loop is worse than a failed fetch.

#### Layer 3 - Inter-property pacing

The manager processes properties sequentially. Between properties, insert a small pause so a 30-property run doesn't hammer any single OTA:

```python
# In PluginManager.process_profile, after each property's _process_one:
import time
time.sleep(1.5)
```

`1.5 s × 30 properties = 45 s` of added wall-clock time. That's the cheapest insurance against burst limits - far cheaper than 5-minute hard pauses. Tune it:

| OTA behaviour | Recommended inter-property sleep |
|---|---|
| No rate limits observed | 0.5 s |
| Occasional 429s on long runs | 1.5 s |
| Frequent 429s | 3.0 s |
| Persistent 429s | 5.0 s, plus investigate your session |

#### What NOT to do

**Do not hardcode "wait until 5 minutes have passed."** This is a common instinct and it's wrong because:

1. It burns 5 minutes even when the server would have accepted the next request after 6 seconds.
2. It ignores the server's own signal (`Retry-After`). If the server says "retry in 30 seconds," waiting 5 minutes wastes 4.5 minutes.
3. It doesn't scale. If you run 100 properties and hit a rate limit every 5 properties, you've added 100 × 5 min = 8.3 hours to a job that should take 20 minutes.
4. It masks the underlying problem. A rate limit means your request pattern is wrong, not that you need to wait longer.

**Do this instead:**

1. Read `Retry-After`. Wait exactly that long.
2. If no header, use exponential backoff with jitter.
3. If you're still hitting limits, add inter-property pacing. That's a one-line change with predictable cost.

#### When to reconsider the session

If you see the same 429 across multiple runs separated by hours, and `Retry-After` isn't being sent, the session itself may be flagged. That's a different problem - recapture the curl file, and see [Booking.com session drift](#bookingcom-session-drift) above.

### Verifying that the resolver picked up a name change

Google occasionally renames provider entries (e.g. `"Expedia"` → `"Expedia.nl"` → `"Expedia.com"`). The resolver handles this transparently, but if you ever see a property missing an OTA:

```bash
python3 google_profile_scraper.py 2>&1 | tee /tmp/run.log
grep "no plugin for" /tmp/run.log
```

The manager now logs `no plugin for 'X' (have: Agoda, Booking.com, Expedia.com, Trip.com)` at INFO level, so you don't need to enable DEBUG to find it. If a new name appears, add it to the entry's `aliases` tuple in `_build_registry()` - no other change required.

### Cleaning up scratch artifacts

During debugging, you accumulate temporary files. Before/after a big run:

```bash
# Expedia follow-up dump
rm -f /tmp/expedia_followup.html

# General scratch
rm -f /tmp/run.log /tmp/expedia_debug.html /tmp/debug_booking.html

# Isolated test output
rm -rf /tmp/scratch_profiles
```

Nothing here is required for production, but keeping `/tmp` clean makes it easier to spot a real dump when you actually need one.

---

## Appendix - Full Flow for One Property

### Wildcard path

```
google_profile_scraper.py
  -> fetch google.com/travel/search?q=...
  -> extract providers[] = [{name: "Booking.com", deeplink: "..."}, ...]
  -> PluginManager.process_profile(profile)
     -> for each provider:
        _process_one(provider, entry, ...)
           -> client = BookingClient(timeout)
           -> html = client.fetch(deeplink)
           -> parsed = BookingParser().parse(html, deeplink)
           -> for follow_url in parser.follow_up_urls(parsed):
                follow_html = client.fetch(follow_url)
                parser.merge_follow_up(parsed, follow_url, follow_html)
           -> append_jsonl("sub_profiles/booking_com.jsonl", parsed)
```

### Individual path

```
individual_profile.py -domain booking_com -url ...
  -> individual/cli.py:main
     -> validate(domain, url)  # registry lookup + host pattern check
     -> run_single(url, domain, ...)
        -> resolve_registry_entry(domain)
        -> client = entry["client_cls"](timeout)
        -> parser = entry["parser_cls"]()
        -> html = client.fetch(url)
        -> parsed = parser.parse(html, url)
        -> for follow_url in parser.follow_up_urls(parsed):
             follow_html = client.fetch(follow_url)
             parser.merge_follow_up(parsed, follow_url, follow_html)
        -> append_jsonl("sub_profiles/<output_name>.jsonl", parsed)
```

Both converge at:

```
client.fetch  ->  parser.parse  ->  optional follow-ups  ->  append_jsonl
```

## NOTES:

### URL rewriting in client `normalize_url`

Two OTAs need their deeplink rewritten before fetching, because Google
emits a URL shape that renders a reduced page:

- **Expedia**: Google sends `expedia.nl` (or `.de`, `.co.uk`, ...) URLs.
  `ExpediaClient.normalize_url` rewrites the host to `www.expedia.com`,
  so one curl file covers every locale. `source_url` in the JSONL stays
  the original deeplink.

- **Tripadvisor**: Google sends `/HotelHighlight?detail=...` shells
  that render without the `LodgingBusiness` JSON-LD. `TripadvisorClient`
  reads the canonical URL from the shell response and refetches the
  `/Hotel_Review-...` form, which ships the full SSR payload.

If a future OTA shows the same symptom - Google's deeplink works but
returns a stripped page - the fix lives in `normalize_url` (single
fetch) or a `fetch()` override (two-fetch). Both patterns are
established; copy whichever fits.