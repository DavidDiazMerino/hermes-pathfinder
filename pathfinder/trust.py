"""Source trust: classify URLs against a domain pack's trust map and match source recipes.

Data-driven: the pack says where the truth lives; nothing here knows any SAP answer.
"""

from __future__ import annotations

import re
from typing import Any
from urllib.parse import urlparse

EVIDENCE_TIERS = ("official", "standard")


def classify(url: str, trust_map: dict[str, Any]) -> dict[str, Any]:
    """Return {'tier', 'host', 'note'?} for a URL; the first matching rule wins."""
    try:
        parsed = urlparse((url or "").strip())
    except ValueError:
        return {"tier": "unknown", "host": ""}
    host = (parsed.hostname or "").lower()
    path = (parsed.path or "/").lower()
    if parsed.scheme not in ("http", "https") or not host:
        return {"tier": "unknown", "host": host}
    for rule in trust_map.get("rules", []):
        if host != rule["host"].lower():
            continue
        if rule.get("path_prefix") and not path.startswith(rule["path_prefix"].lower()):
            continue
        if rule.get("path_contains") and rule["path_contains"].lower() not in path:
            continue
        out = {"tier": rule["tier"], "host": host}
        if rule.get("note"):
            out["note"] = rule["note"]
        return out
    return {"tier": "unknown", "host": host}


def is_evidence(tier: str) -> bool:
    return tier in EVIDENCE_TIERS


def _words(text: str) -> str:
    return " " + re.sub(r"[^a-z0-9_/$.-]+", " ", (text or "").lower()) + " "


def match_recipes(question: str, pack: dict[str, Any], limit: int = 3) -> list[dict[str, Any]]:
    """Recipes whose keywords appear in the question, best first, with their sources resolved."""
    text = _words(question)
    by_id = {s["id"]: s for s in pack.get("sources", [])}
    scored = []
    for recipe in pack.get("source_recipes", []):
        hits = [kw for kw in recipe.get("keywords", []) if _words(kw).strip() and _words(kw) in text
                or (len(kw) > 3 and kw.lower() in text)]
        if hits:
            scored.append((len(set(hits)), recipe, sorted(set(hits))))
    scored.sort(key=lambda x: -x[0])
    out = []
    for score, recipe, hits in scored[:limit]:
        where = []
        for w in recipe.get("where", []):
            if w.get("source") in by_id:
                s = by_id[w["source"]]
                where.append({"what": s["label"], "url": s["url"], "check": s.get("check")})
            else:
                where.append({"what": w.get("what"), "url": w.get("url")})
        out.append({"id": recipe["id"], "question": recipe["question"], "matched": hits,
                    "ask_before_starting": recipe.get("ask", []), "where": where,
                    "how": recipe.get("how"), "caveats": recipe.get("caveats", [])})
    return out
