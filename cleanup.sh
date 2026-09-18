#!/usr/bin/env bash
#
# Clean up generated artifacts.
#
# Usage:
#   ./cleanup.sh              # remove runtime output, caches, temp files
#   ./cleanup.sh --hard       # also remove venv
#   ./cleanup.sh --dry-run    # print what would be removed, do nothing
#   ./cleanup.sh --help
#
# What it removes (safe mode):
#   - sub_profiles/*.jsonl          (parsed output)
#   - sub_profiles/*.session_expired
#   - __pycache__/ everywhere
#   - *.pyc, *.pyo
#   - .pytest_cache/, .mypy_cache/, .ruff_cache/
#   - /tmp/expedia_followup.html
#   - /tmp/expedia_debug.html
#   - /tmp/debug_booking.html
#   - *.log in the project root
#
# What it removes (hard mode, additional):
#   - venv/  (or .venv/ if present)

set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$ROOT"

DRY=0
HARD=0

for arg in "$@"; do
    case "$arg" in
        --hard)    HARD=1 ;;
        --dry-run) DRY=1 ;;
        -h|--help)
            sed -n '2,22p' "${BASH_SOURCE[0]}"
            exit 0
            ;;
        *)
            echo "unknown argument: $arg" >&2
            exit 2
            ;;
    esac
done

# Print and optionally execute an rm.
do_rm() {
    local target="$1"
    if [[ ! -e "$target" ]]; then
        return
    fi
    if [[ $DRY -eq 1 ]]; then
        echo "  would remove: $target"
        return
    fi
    echo "  removing: $target"
    rm -rf -- "$target"
}

# Find and remove files by name recursively.
do_rm_glob() {
    local name="$1"
    while IFS= read -r -d '' path; do
        do_rm "$path"
    done < <(find "$ROOT" \
        -path "$ROOT/venv" -prune -o \
        -path "$ROOT/.venv" -prune -o \
        -name "$name" -print0 2>/dev/null)
}

echo "Cleanup in: $ROOT"
[[ $DRY -eq 1 ]] && echo "  (dry-run — nothing will actually be removed)"
echo

# --- runtime output --------------------------------------------------
echo "==> runtime output"
if [[ -d "$ROOT/sub_profiles" ]]; then
    # Remove only generated files, keep the directory.
    while IFS= read -r -d '' path; do
        do_rm "$path"
    done < <(find "$ROOT/sub_profiles" \
        \( -name '*.jsonl' -o -name '*.session_expired' \) \
        -print0 2>/dev/null)
fi

# --- python caches ---------------------------------------------------
echo
echo "==> python caches"
do_rm_glob "__pycache__"
do_rm_glob "*.pyc"
do_rm_glob "*.pyo"
do_rm_glob ".pytest_cache"
do_rm_glob ".mypy_cache"
do_rm_glob ".ruff_cache"
do_rm_glob ".pytype"
do_rm_glob ".hypothesis"

# --- editor / OS cruft ----------------------------------------------
echo
echo "==> editor and OS cruft"
do_rm_glob ".DS_Store"
do_rm_glob "Thumbs.db"
do_rm_glob "*.swp"
do_rm_glob "*.swo"

# --- debug dumps in /tmp --------------------------------------------
echo
echo "==> /tmp debug dumps"
for f in \
    /tmp/expedia_followup.html \
    /tmp/expedia_debug.html \
    /tmp/debug_booking.html \
    /tmp/trip_okura_highlight.html \
    /tmp/trip_okura_canonical.html \
    /tmp/trip_okura_review.html
do
    do_rm "$f"
done

# --- logs in the project root ---------------------------------------
echo
echo "==> logs"
if [[ -d "$ROOT" ]]; then
    while IFS= read -r -d '' path; do
        do_rm "$path"
    done < <(find "$ROOT" -maxdepth 1 -name '*.log' -print0 2>/dev/null)
fi

# --- hard mode: venv -------------------------------------------------
if [[ $HARD -eq 1 ]]; then
    echo
    echo "==> venv (hard mode)"
    do_rm "$ROOT/venv"
    do_rm "$ROOT/.venv"
fi

# --- done ------------------------------------------------------------
echo
if [[ $DRY -eq 1 ]]; then
    echo "Dry-run complete. Re-run without --dry-run to execute."
else
    echo "Cleanup complete."
    if [[ $HARD -eq 1 ]]; then
        echo "Run ./plumbing.sh to rebuild the venv and re-verify."
    fi
fi