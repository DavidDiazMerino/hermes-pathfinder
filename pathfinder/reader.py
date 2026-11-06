"""pathfinder_read: fetch a large document from an official source and find entries in it.

Only URLs whose host the trust map rates official or standard are fetched (redirects included).
The download is cached in the plugin data dir by hash and recorded in the ledger as a source read.
Generic: it searches JSON records or text lines for the terms asked; it knows no domain answers.
"""

from __future__ import annotations

import hashlib
import json
import time
import urllib.request
from pathlib import Path
from typing import Any

from . import trust

MAX_BYTES = 40 * 1024 * 1024
TIMEOUT_S = 60
MAX_HITS = 25
USER_AGENT = "hermes-enterprise-pathfinder/0.1 (+https://github.com/DavidDiazMerino/hermes-pathfinder)"


class ReadError(Exception):
    pass


def fetch(url: str, trust_map: dict[str, Any], cache_dir: Path, *, max_age_s: int = 6 * 3600,
          opener=urllib.request.urlopen) -> tuple[bytes, str, str]:
    """Return (body, final_url, content_type). Refuses anything not official/standard."""
    tier = trust.classify(url, trust_map)["tier"]
    if not url.lower().startswith("https://") or not trust.is_evidence(tier):
        raise ReadError(f"refused: {url} is not an official or standard source in the trust map (tier {tier})")
    cache_dir.mkdir(parents=True, exist_ok=True)
    key = hashlib.sha256(url.encode()).hexdigest()[:24]
    body_path, meta_path = cache_dir / f"{key}.bin", cache_dir / f"{key}.json"
    if body_path.is_file() and meta_path.is_file() and time.time() - body_path.stat().st_mtime < max_age_s:
        meta = json.loads(meta_path.read_text())
        return body_path.read_bytes(), meta["final_url"], meta["content_type"]
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, "Accept": "*/*"})
    with opener(req, timeout=TIMEOUT_S) as resp:
        final_url = resp.geturl()
        final_tier = trust.classify(final_url, trust_map)["tier"]
        if not trust.is_evidence(final_tier):
            raise ReadError(f"refused: redirected to {final_url} (tier {final_tier})")
        ctype = resp.headers.get("Content-Type", "")
        body = resp.read(MAX_BYTES + 1)
    if len(body) > MAX_BYTES:
        raise ReadError(f"document larger than {MAX_BYTES} bytes")
    body_path.write_bytes(body)
    meta_path.write_text(json.dumps({"url": url, "final_url": final_url, "content_type": ctype}))
    return body, final_url, ctype


def _records(obj: Any, path: str = "$"):
    """Yield (path, dict) for every dict that holds at least one scalar value."""
    if isinstance(obj, dict):
        if any(isinstance(v, (str, int, float, bool)) for v in obj.values()):
            yield path, obj
        for k, v in obj.items():
            yield from _records(v, f"{path}.{k}")
    elif isinstance(obj, list):
        for i, v in enumerate(obj):
            yield from _records(v, f"{path}[{i}]")


def search_json(data: Any, terms: list[str], field: str | None = None) -> dict[str, list]:
    wanted = {t.lower(): t for t in terms}
    hits: dict[str, list] = {t: [] for t in terms}
    for path, rec in _records(data):
        values = {k: v for k, v in rec.items() if isinstance(v, (str, int, float))}
        candidates = [values[field]] if field and field in values else list(values.values())
        for v in candidates:
            t = wanted.get(str(v).lower())
            if t is not None and len(hits[t]) < MAX_HITS:
                hits[t].append(rec)
                break
    return hits


def search_text(text: str, terms: list[str], context: int = 1) -> dict[str, list]:
    lines = text.splitlines()
    hits: dict[str, list] = {t: [] for t in terms}
    for i, line in enumerate(lines):
        low = line.lower()
        for t in terms:
            if t.lower() in low and len(hits[t]) < MAX_HITS:
                hits[t].append("\n".join(lines[max(0, i - context): i + context + 1])[:1200])
    return hits


def read(url: str, terms: list[str], *, trust_map: dict[str, Any], cache_dir: Path, ledger,
         field: str | None = None, opener=urllib.request.urlopen) -> dict[str, Any]:
    body, final_url, ctype = fetch(url, trust_map, cache_dir, opener=opener)
    text = body.decode("utf-8", "replace")
    tier = trust.classify(final_url, trust_map)["tier"]
    source_id = ledger.record_source(url=final_url, tier=tier, title=None, content=text, tool="pathfinder_read")
    try:
        data = json.loads(text)
        kind, hits = "json", search_json(data, terms, field)
    except json.JSONDecodeError:
        kind, hits = "text", search_text(text, terms)
    return {"source_id": source_id, "url": final_url, "tier": tier, "kind": kind, "bytes": len(body),
            "sha256": hashlib.sha256(body).hexdigest(), "content_type": ctype, "hits": hits,
            "not_found": [t for t, h in hits.items() if not h]}
