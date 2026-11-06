"""Domain packs: data-only folders under ``domains/<id>/domain.json``."""

from __future__ import annotations

import json
import re
from functools import lru_cache
from pathlib import Path
from typing import Any

DOMAINS_DIR = Path(__file__).resolve().parent.parent / "domains"
_ID_RE = re.compile(r"^[a-z0-9][a-z0-9_-]{0,40}$")


class PackError(Exception):
    pass


def available() -> list[str]:
    if not DOMAINS_DIR.is_dir():
        return []
    return sorted(p.name for p in DOMAINS_DIR.iterdir() if (p / "domain.json").is_file() and not p.name.startswith("_"))


@lru_cache(maxsize=16)
def load(domain: str) -> dict[str, Any]:
    if not _ID_RE.match(domain or ""):
        raise PackError(f"invalid domain id {domain!r}")
    path = DOMAINS_DIR / domain / "domain.json"
    if not path.is_file():
        raise PackError(f"unknown domain {domain!r}; available: {', '.join(available()) or 'none'}")
    return json.loads(path.read_text(encoding="utf-8"))


def fixture_path(domain: str, fixture_id: str) -> Path:
    pack = load(domain)
    for fx in pack.get("fixtures", []):
        if fx["id"] == fixture_id:
            return DOMAINS_DIR / domain / fx["file"]
    ids = ", ".join(fx["id"] for fx in pack.get("fixtures", []))
    raise PackError(f"unknown fixture {fixture_id!r} in domain {domain!r}; available: {ids}")
