"""
JSONL append helper shared by the PluginManager and any future writers.

The file is opened in append mode with UTF-8 and one JSON object per line.
Failures are logged but not raised — a single bad write should not kill
a whole scraping run.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict

from utils.logging_utils import get_logger

logger = get_logger(__name__)


def append_jsonl(path: Path, obj: Dict[str, Any]) -> bool:
    """
    Append `obj` as one line of JSON to `path`.

    Returns True on success, False on failure.
    """
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "a", encoding="utf-8") as f:
            f.write(json.dumps(obj, ensure_ascii=False) + "\n")
        return True
    except (OSError, TypeError, ValueError) as exc:
        logger.error("failed to write %s: %s", path, exc)
        return False

    