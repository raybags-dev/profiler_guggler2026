#!/usr/bin/env bash
#
# Bootstrap wrapper around plumbing.py.
#
# Usage:
#   ./plumbing.sh              # activate venv (create if missing) and run
#   ./plumbing.sh --fresh      # force-recreate the venv before running
#   ./plumbing.sh --no-venv    # skip venv activation entirely
#
# What it does:
#   1. Locates the project root (this script's directory).
#   2. Ensures a venv exists at ./venv.
#   3. Activates it.
#   4. Runs python3 plumbing.py.

set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$ROOT"

VENV_DIR="$ROOT/venv"
FRESH=0
SKIP_VENV=0

for arg in "$@"; do
    case "$arg" in
        --fresh)   FRESH=1 ;;
        --no-venv) SKIP_VENV=1 ;;
        -h|--help)
            sed -n '2,14p' "${BASH_SOURCE[0]}"
            exit 0
            ;;
        *)
            echo "unknown argument: $arg" >&2
            exit 2
            ;;
    esac
done

# --- venv management -------------------------------------------------
if [[ $SKIP_VENV -eq 0 ]]; then
    if [[ $FRESH -eq 1 && -d "$VENV_DIR" ]]; then
        echo "==> removing existing venv at $VENV_DIR"
        rm -rf "$VENV_DIR"
    fi

    if [[ ! -d "$VENV_DIR" ]]; then
        echo "==> creating venv at $VENV_DIR"
        # Prefer system python if available; fall back to whatever python3
        # is on PATH (which may be conda — that's fine).
        if [[ -x /usr/bin/python3 ]]; then
            /usr/bin/python3 -m venv "$VENV_DIR"
        else
            python3 -m venv "$VENV_DIR"
        fi
    fi

    # Deactivate any pre-existing venv so we don't stack.
    if [[ -n "${VIRTUAL_ENV:-}" && "${VIRTUAL_ENV}" != "$VENV_DIR" ]]; then
        echo "==> deactivating current venv ($VIRTUAL_ENV)"
        deactivate 2>/dev/null || true
    fi

    # shellcheck disable=SC1091
    source "$VENV_DIR/bin/activate"

    echo "==> using python: $(command -v python3)"
    echo
fi

# --- run plumbing ----------------------------------------------------
if [[ ! -f "$ROOT/plumbing.py" ]]; then
    echo "error: plumbing.py not found at $ROOT/plumbing.py" >&2
    exit 1
fi

exec python3 "$ROOT/plumbing.py"