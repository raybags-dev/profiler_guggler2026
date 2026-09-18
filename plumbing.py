#!/usr/bin/env python3
"""
Bootstrap the pipeline on a fresh clone.

Checks / creates:

  1. Python version
  2. requirements.txt installed
  3. Directory structure (source dirs + runtime output dir)
  4. Required source files present
  5. Required curl session files present (cannot be auto-created)
  6. configs/config.py present (cannot be auto-created)
  7. All plugin modules import cleanly

Run from the project root:

    python3 plumbing.py
"""
from __future__ import annotations

import importlib
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parent
CURL_DIR = ROOT / "profile_plugins" / "curl_sessions"
SUB_PROFILES = ROOT / "sub_profiles"

# ---------------------------------------------------------------------
# Required inventory
# ---------------------------------------------------------------------

REQUIRED_DIRS = [
    ROOT / "individual",
    ROOT / "profile_plugins",
    ROOT / "profile_plugins" / "shared_client",
    ROOT / "profile_plugins" / "plugin_parsers",
    ROOT / "profile_plugins" / "curl_sessions",
    ROOT / "utils",
    ROOT / "configs",
    # Runtime output dir — created empty if missing.
    SUB_PROFILES,
]

REQUIRED_SOURCE_FILES = [
    ROOT / "google_profile_scraper.py",
    ROOT / "individual_profile.py",
    ROOT / "requirements.txt",
    ROOT / "individual" / "__init__.py",
    ROOT / "individual" / "cli.py",
    ROOT / "individual" / "runner.py",
    ROOT / "individual" / "validator.py",
    ROOT / "profile_plugins" / "__init__.py",
    ROOT / "profile_plugins" / "base_client.py",
    ROOT / "profile_plugins" / "base_parser.py",
    ROOT / "profile_plugins" / "curl_parser.py",
    ROOT / "profile_plugins" / "manager.py",
    ROOT / "profile_plugins" / "shared_client" / "__init__.py",
    ROOT / "profile_plugins" / "shared_client" / "booking_client.py",
    ROOT / "profile_plugins" / "shared_client" / "agoda_client.py",
    ROOT / "profile_plugins" / "shared_client" / "trip_client.py",
    ROOT / "profile_plugins" / "shared_client" / "expedia_client.py",
    ROOT / "profile_plugins" / "shared_client" / "tripadvisor_client.py",
    ROOT / "profile_plugins" / "plugin_parsers" / "__init__.py",
    ROOT / "profile_plugins" / "plugin_parsers" / "booking_parser.py",
    ROOT / "profile_plugins" / "plugin_parsers" / "agoda_parser.py",
    ROOT / "profile_plugins" / "plugin_parsers" / "trip_parser.py",
    ROOT / "profile_plugins" / "plugin_parsers" / "expedia_parser.py",
    ROOT / "profile_plugins" / "plugin_parsers" / "tripadvisor_parser.py",
    ROOT / "utils" / "__init__.py",
    ROOT / "utils" / "http_utils.py",
    ROOT / "utils" / "jsonl_utils.py",
    ROOT / "utils" / "logging_utils.py",
    ROOT / "utils" / "session_utils.py",
    ROOT / "utils" / "string_utils.py",
]

REQUIRED_CURLS = [
    "booking_com.curl",
    "agoda_com.curl",
    "trip_com.curl",
    "expedia_com.curl",
    "tripadvisor_com.curl",
]

REQUIRED_MODULES = [
    "individual.cli",
    "individual.runner",
    "individual.validator",
    "profile_plugins.manager",
    "profile_plugins.base_client",
    "profile_plugins.base_parser",
    "profile_plugins.curl_parser",
    "profile_plugins.shared_client.booking_client",
    "profile_plugins.shared_client.agoda_client",
    "profile_plugins.shared_client.trip_client",
    "profile_plugins.shared_client.expedia_client",
    "profile_plugins.shared_client.tripadvisor_client",
    "profile_plugins.plugin_parsers.booking_parser",
    "profile_plugins.plugin_parsers.agoda_parser",
    "profile_plugins.plugin_parsers.trip_parser",
    "profile_plugins.plugin_parsers.expedia_parser",
    "profile_plugins.plugin_parsers.tripadvisor_parser",
    "utils.http_utils",
    "utils.jsonl_utils",
    "utils.logging_utils",
    "utils.session_utils",
    "utils.string_utils",
]


def check_venv_active() -> bool:
    section("Virtual environment")
    in_venv = (
        hasattr(sys, "real_prefix")
        or (
            hasattr(sys, "base_prefix")
            and sys.base_prefix != sys.prefix
        )
    )
    if in_venv:
        log(True, f"active venv: {sys.prefix}")
        return True
    log(False, "no active virtualenv")
    print()
    print("  Activate the project venv before running plumbing:")
    print("    source venv/bin/activate      # or: source .venv/bin/activate")
    print("  Then re-run: python3 plumbing.py")
    print()
    print("  If you don't have a venv yet:")
    print("    python3 -m venv venv")
    print("    source venv/bin/activate")
    return False



# ---------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------

def log(ok: bool, msg: str) -> None:
    mark = "OK  " if ok else "MISS"
    print(f"  [{mark}] {msg}")


def section(title: str) -> None:
    print()
    print("=" * 72)
    print(title)
    print("=" * 72)


# ---------------------------------------------------------------------
# Steps
# ---------------------------------------------------------------------

def check_python_version() -> bool:
    section("Python version")
    major, minor = sys.version_info[:2]
    log(True, f"python {major}.{minor}.{sys.version_info.micro}")
    if (major, minor) < (3, 10):
        print("  !! Python 3.10+ required")
        return False
    return True


def install_requirements() -> bool:
    section("Dependencies")
    req = ROOT / "requirements.txt"
    if not req.is_file():
        log(False, "requirements.txt not found")
        return False

    # Check whether httpx and curl_cffi are already importable.
    missing: list[str] = []
    for mod in ("httpx", "curl_cffi"):
        try:
            importlib.import_module(mod)
        except ImportError:
            missing.append(mod)

    if not missing:
        log(True, "requirements already satisfied")
        return True

    log(False, f"missing modules: {', '.join(missing)}")
    print("  running: pip install -r requirements.txt")
    try:
        subprocess.check_call(
            [sys.executable, "-m", "pip", "install", "-r", str(req)],
        )
    except subprocess.CalledProcessError as exc:
        print(f"  !! pip install failed with exit {exc.returncode}")
        return False
    log(True, "requirements installed")
    return True


def create_directories() -> bool:
    section("Directory structure")
    ok = True
    for d in REQUIRED_DIRS:
        try:
            d.mkdir(parents=True, exist_ok=True)
            log(True, str(d.relative_to(ROOT)) + "/")
        except OSError as exc:
            log(False, f"{d}: {exc}")
            ok = False
    return ok


def check_source_files() -> bool:
    section("Source files")
    ok = True
    for f in REQUIRED_SOURCE_FILES:
        if f.is_file():
            log(True, str(f.relative_to(ROOT)))
        else:
            log(False, str(f.relative_to(ROOT)))
            ok = False
    return ok


def check_curl_files() -> bool:
    section("Captured curl sessions")
    try:
        from profile_plugins.curl_parser import PluginCurlParser  # noqa: WPS433
    except Exception as exc:  # noqa: BLE001
        log(False, f"cannot import curl parser: {exc}")
        return False

    ok = True
    for name in REQUIRED_CURLS:
        path = CURL_DIR / name
        if not path.is_file() or path.stat().st_size == 0:
            log(False, f"{name} (missing)")
            ok = False
            continue
        try:
            session = PluginCurlParser.parse(str(path))
            log(
                True,
                f"{name} "
                f"({len(session.headers)} headers, "
                f"{len(session.cookies)} cookies)",
            )
        except Exception as exc:  # noqa: BLE001
            log(False, f"{name}: unreadable ({type(exc).__name__}: {exc})")
            ok = False

    if not ok:
        print()
        print("  Capture missing/unreadable files from a real browser session:")
        print("    1. Open the OTA in Chrome.")
        print("    2. Navigate to any real property page.")
        print("    3. DevTools -> Network -> reload.")
        print("    4. Right-click the top-level request")
        print("       -> Copy -> Copy as cURL (bash).")
        print(f"    5. Save to {CURL_DIR.relative_to(ROOT)}/<name>.curl")
    return ok

def check_config() -> bool:
    section("configs/config.py")
    cfg = ROOT / "configs" / "config.py"
    if not cfg.is_file():
        log(False, str(cfg.relative_to(ROOT)))
        print()
        print("  configs/config.py is missing. If your pipeline imports it,")
        print("  create it from your team's template (values are typically")
        print("  environment-specific and not committed).")
        return False
    log(True, str(cfg.relative_to(ROOT)))
    return True


def check_imports() -> bool:
    section("Module imports")
    # Make the project root importable even when cwd is different.
    sys.path.insert(0, str(ROOT))
    ok = True
    for m in REQUIRED_MODULES:
        try:
            importlib.import_module(m)
            log(True, m)
        except Exception as exc:  # noqa: BLE001
            log(False, f"{m}: {type(exc).__name__}: {exc}")
            ok = False
    return ok


def check_registry() -> bool:
    section("Plugin registry")
    try:
        from profile_plugins.manager import (  # noqa: WPS433
            list_registered_providers,
        )
    except Exception as exc:  # noqa: BLE001
        log(False, f"import failed: {exc}")
        return False
    providers = list_registered_providers()
    expected = {"Agoda", "Booking.com", "Expedia.com", "Trip.com", "Tripadvisor"}
    got = set(providers)
    missing = expected - got
    if missing:
        log(False, f"missing registrations: {sorted(missing)}")
        return False
    log(True, f"registered: {', '.join(providers)}")
    return True


# ---------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------

def main() -> int:
    print()
    print("Bootstrap check for the OTA profile pipeline")
    print(f"Project root: {ROOT}")

    results: list[tuple[str, bool]] = [
        ("venv",    check_venv_active()),
        ("python",  check_python_version()),
        ("deps",    install_requirements()),
        ("dirs",    create_directories()),
        ("source",  check_source_files()),
        ("curl",    check_curl_files()),
        ("config",  check_config()),
        ("imports", check_imports()),
        ("registry", check_registry()),
    ]

    section("Summary")
    all_ok = True
    for name, ok in results:
        mark = "OK  " if ok else "FAIL"
        print(f"  [{mark}] {name}")
        if not ok:
            all_ok = False

    print()
    if all_ok:
        print("Pipeline is ready. Try:")
        print("  python3 individual_profile.py -domain booking_com \\")
        print("      -url 'https://www.booking.com/hotel/nl/soho.en-gb.html'")
        return 0
    print("Fix the FAIL items above, then re-run: python3 plumbing.py")
    return 1


if __name__ == "__main__":
    sys.exit(main())