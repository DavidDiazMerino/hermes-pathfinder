"""Annotate Hermes's own web tool results with source trust, and record pages read as evidence.

Runs from the ``transform_tool_result`` hook. Results unrelated to the domain are left untouched.
"""

from __future__ import annotations

import json
import re
from typing import Any

from . import trust

SEARCH_TOOLS = {"web_search"}
READ_TOOLS = {"web_extract"}
GUIDANCE = {
    "official": "official SAP source: counts as documented evidence; cite its source_id",
    "standard": "standards body: counts as evidence for protocol rules",
    "sap-employee": "SAP employee blog: useful context; confirm product commitments in official docs",
    "community": "community/partner content: not evidence; corroborate with an official SAP source",
    "unknown": "not in the Pathfinder trust map: unverified; prefer an official SAP source",
}


def _relevant(text: str, kw_re: re.Pattern | None) -> bool:
    return bool(kw_re and kw_re.search(text or ""))


def annotate(tool_name: str, args: dict[str, Any], result: Any, *, trust_map: dict[str, Any], ledger,
             kw_re: re.Pattern | None) -> str | None:
    if tool_name not in SEARCH_TOOLS | READ_TOOLS or not isinstance(result, str):
        return None
    try:
        data = json.loads(result)
    except (json.JSONDecodeError, TypeError):
        return None
    if not isinstance(data, dict):
        return None
    if tool_name in SEARCH_TOOLS:
        return _annotate_search(args, data, trust_map, kw_re)
    return _annotate_read(data, trust_map, ledger, kw_re)


def _annotate_search(args, data, trust_map, kw_re) -> str | None:
    items = ((data.get("data") or {}).get("web")) if isinstance(data.get("data"), dict) else None
    if not isinstance(items, list) or not items:
        return None
    query = str((args or {}).get("query") or "")
    tiers = []
    for item in items:
        if not isinstance(item, dict):
            continue
        c = trust.classify(str(item.get("url") or ""), trust_map)
        item["pathfinder_trust"] = c["tier"]
        tiers.append(c["tier"])
    known = [t for t in tiers if t != "unknown"]
    if not known and not _relevant(query, kw_re):
        for item in items:  # nothing domain-related: leave the result as it was
            if isinstance(item, dict):
                item.pop("pathfinder_trust", None)
        return None
    counts = {t: tiers.count(t) for t in GUIDANCE if t in tiers}
    data["pathfinder"] = {
        "trust_counts": counts,
        "guidance": "Read official SAP results first. Community or unknown results are not evidence; "
                    "corroborate them with an official source before relying on them.",
        "legend": {t: GUIDANCE[t] for t in counts},
    }
    if not counts.get("official"):
        data["pathfinder"]["hint"] = ("No official SAP source in these results. Search again restricted to "
                                      "official sites, e.g. site:help.sap.com or site:api.sap.com, or ask "
                                      "pathfinder_sources(question=...) where this is documented.")
    return json.dumps(data, ensure_ascii=False, indent=1)


def _annotate_read(data, trust_map, ledger, kw_re) -> str | None:
    results = data.get("results")
    if not isinstance(results, list) or not results:
        return None
    touched = False
    for item in results:
        if not isinstance(item, dict) or item.get("error"):
            continue
        url = str(item.get("url") or "")
        c = trust.classify(url, trust_map)
        content = str(item.get("content") or "")
        if c["tier"] == "unknown" and not _relevant(url + " " + str(item.get("title") or "") + " " + content[:4000], kw_re):
            continue
        item["pathfinder_trust"] = c["tier"]
        item["pathfinder_note"] = GUIDANCE[c["tier"]]
        if ledger is not None and content:
            try:
                item["pathfinder_source_id"] = ledger.record_source(
                    url=url, tier=c["tier"], title=item.get("title"), content=content, tool="web_extract")
            except Exception as exc:  # never break the read because of the ledger
                item["pathfinder_note"] += f" (not recorded: {exc})"
        touched = True
    if not touched:
        return None
    data["pathfinder"] = {"guidance": "Cite pathfinder_source_id for facts taken from official pages. "
                                      "Community or unknown pages are not evidence."}
    return json.dumps(data, ensure_ascii=False, indent=1)
