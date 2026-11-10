"""Run the Pathfinder A/C evaluation through real Hermes sessions.

A = a Hermes profile without the plugin, C = a profile with it. Same model, same prompt, same contract
file under a neutral name in an empty folder. Each run's JSON answer is scored against hand-written
expectations (eval/expected/). Usage:

    python eval/run_eval.py --runs 3 --parallel 2

Sessions work outside the repository. Transcripts and answers go to eval/runs/<stamp>/ (gitignored);
the summary goes to eval/results/<stamp>.json.
"""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from eval import score as sc  # noqa: E402
from eval import gen_large, isolation  # noqa: E402

CONTRACTS = {
    "business_partner_v2": ROOT / "domains/sap/fixtures/business_partner_v2.edmx",
    "product_v4": ROOT / "domains/sap/fixtures/product_v4.xml",
}
CONDITIONS = {"A": "pathfinder-baseline", "C": "pathfinder"}
GENERATED: dict[str, dict] = {}  # contract_id -> {"path": Path, "expected": dict, "targets": [...]}

PROMPT = """I work with SAP. service_metadata.xml in this folder is the $metadata of an SAP OData service.
For every entity set, tell me: its key properties; whether create, update and delete are allowed;
the properties a create request must carry (Nullable=false and not set by the server; list them even
if the set itself does not allow create); and its navigation properties with target entity type and
whether they are to-many.{scope} Do not create or modify any skills.

End your answer with exactly one fenced ```json block in this shape:
{"entity_sets": {"<EntitySetName>": {"keys": ["..."], "create": true, "update": true, "delete": true,
 "required_on_create": ["..."], "navigations": {"<NavName>": {"target": "<EntityTypeName>", "many": true}}}}}"""


PRICING_CACHE = Path.home() / ".hermes" / "cache" / "endpoint_model_metadata.json"


def load_pricing() -> dict[str, dict]:
    """Per-token USD prices published by the inference endpoints, from Hermes's model metadata cache."""
    candidates = [PRICING_CACHE] + sorted((Path.home() / ".hermes" / "profiles").glob("*/cache/endpoint_model_metadata.json"))
    prices: dict[str, dict] = {}
    for path in candidates:
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        for endpoint in data.values():
            for model_id, meta in (endpoint.get("models") or {}).items():
                if isinstance(meta, dict) and meta.get("pricing"):
                    prices.setdefault(model_id, meta["pricing"])
    return prices


def cost_usd(tokens: dict | None, price: dict | None) -> float | None:
    if not tokens or not price:
        return None
    p = lambda k, d=0.0: float(price.get(k) or d)  # noqa: E731
    cache_read, cache_write = tokens.get("cache_read") or 0, tokens.get("cache_write") or 0
    fresh = max(0, (tokens.get("input") or 0) - cache_read - cache_write)
    return round(fresh * p("prompt") + cache_read * p("cache_read", p("prompt")) +
                 cache_write * p("cache_write", p("prompt")) + (tokens.get("output") or 0) * p("completion"), 5)


def run_one(stamp_dir: Path, condition: str, contract_id: str, n: int, max_turns: int, timeout: int,
            model: str | None = None, pricing: dict | None = None, *, archive_dir: Path,
            forbidden_roots: list[str]) -> dict:
    tag = (model or "default").replace("/", "_")
    ws = stamp_dir / tag / f"{condition}-{contract_id}-{n}"
    ws.mkdir(parents=True)
    gen = GENERATED.get(contract_id)
    shutil.copy(gen["path"] if gen else CONTRACTS[contract_id], ws / "service_metadata.xml")
    scope = (" Answer only for these entity sets: " + ", ".join(gen["targets"]) + ".") if gen else ""
    prompt = PROMPT.replace("{scope}", scope)
    cmd = ["hermes", "-p", CONDITIONS[condition], "chat", "-q", prompt, "--oneshot",
           "--in", str(ws), "--format", "stream-json", "--max-turns", str(max_turns)]
    if model:
        cmd += ["-m", model]
    retries = 0
    while True:
        t0 = time.time()
        try:
            proc = subprocess.run(cmd, cwd=ws, capture_output=True, text=True, timeout=timeout)
            out, code = proc.stdout, proc.returncode
        except subprocess.TimeoutExpired as exc:
            out, code = (exc.stdout or b"").decode() if isinstance(exc.stdout, bytes) else (exc.stdout or ""), "timeout"
        wall = round(time.time() - t0, 1)
        # Infrastructure, not the agent: the gateway pauses turns while Hermes syncs dependencies.
        if "Gateway draining" in (out or "") and retries < 5:
            retries += 1
            time.sleep(30)
            continue
        break
    tools, final, token_detail, duration, served, error = [], "", None, None, None, None
    for line in (out or "").splitlines():
        if not line.startswith("{"):
            continue
        try:
            ev = json.loads(line)
        except json.JSONDecodeError:
            continue
        if ev.get("type") == "system":
            served = ev.get("model") or served
        elif ev.get("type") == "tool_use":
            tools.append(ev.get("name"))
        elif ev.get("type") == "result":
            final = ev.get("text") or ev.get("result") or ""
            token_detail = ev.get("tokens") or {}
            duration = ev.get("duration_ms")
            error = ev.get("error")
    isolation.archive_session(archive_dir / ws.relative_to(stamp_dir), out or "", final)
    contaminated = isolation.contaminated(out or "", str(ws), forbidden_roots)
    tokens = (token_detail or {}).get("total")
    expected = gen["expected"] if gen else sc.load_expected(contract_id)
    result = sc.score(sc.extract_answer(final), expected)
    infra_error = "Gateway draining" in (out or "") or tokens in (None, 0)
    price = (pricing or {}).get(served or model or "")
    return {"model": model or served, "served_model": served, "condition": condition, "contract": contract_id,
            "run": n, "exit": code, "error": error, "wall_s": wall, "infra_error": infra_error, "retries": retries,
            "contaminated": contaminated,
            "duration_ms": duration, "tokens": tokens, "token_detail": token_detail,
            "cost_usd": cost_usd(token_detail, price), "tool_calls": len(tools), "tools": tools,
            "used_pathfinder": any(str(t).startswith("pathfinder_") for t in tools), **result}


def summarise(rows: list[dict]) -> list[dict]:
    out = []
    keys = sorted({(r.get("model") or "", r["condition"], r["contract"]) for r in rows})
    for model, cond, cid in keys:
        group = [r for r in rows if (r.get("model") or "") == model and r["condition"] == cond
                 and r["contract"] == cid]
        rs = [r for r in group if not r.get("infra_error") and not r.get("contaminated")]
        excluded = sum(bool(r.get("contaminated")) for r in group)
        counts = {"model": model, "condition": cond, "contract": cid, "runs": len(rs),
                  "excluded_contaminated": excluded}
        if not rs:
            if excluded:
                out.append(counts)
            continue
        avg = lambda k: round(sum((r.get(k) or 0) for r in rs) / len(rs), 4)  # noqa: E731
        out.append({**counts,
                    "score_mean": round(sum(r["ratio"] for r in rs) / len(rs), 3),
                    "perfect_runs": sum(r["points"] == r["total"] for r in rs),
                    "answered_runs": sum(r["parsed"] for r in rs),
                    "tokens_mean": round(avg("tokens")), "cost_usd_mean": avg("cost_usd"),
                    "wall_s_mean": round(avg("wall_s"), 1), "tool_calls_mean": round(avg("tool_calls"), 1),
                    "used_pathfinder_runs": sum(r["used_pathfinder"] for r in rs)})
    return out


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--runs", type=int, default=3)
    ap.add_argument("--parallel", type=int, default=2)
    ap.add_argument("--conditions", default="A,C")
    ap.add_argument("--contracts", default=",".join(CONTRACTS), help="also: large_v4 (generated)")
    ap.add_argument("--models", default="", help="comma-separated model ids; empty = each profile's default")
    ap.add_argument("--seed", type=int, default=7)
    ap.add_argument("--max-turns", type=int, default=25)
    ap.add_argument("--timeout", type=int, default=900)
    ap.add_argument("--work-dir", "--runs-dir", default=str(isolation.default_work_dir()),
                    help="workspace base outside the repository (default: %(default)s)")
    args = ap.parse_args()

    stamp = time.strftime("%Y%m%d-%H%M%S")
    try:
        stamp_dir = isolation.round_workspace(ROOT, args.work_dir, stamp)
    except ValueError as exc:
        ap.error(str(exc))
    stamp_dir.mkdir(parents=True)
    archive_dir = ROOT / "eval" / "runs" / stamp
    archive_dir.mkdir(parents=True)
    forbidden_roots = isolation.evaluation_roots(ROOT)
    if "large_v4" in args.contracts.split(","):
        path, expected, targets = gen_large.generate(archive_dir / "_generated", seed=args.seed)
        GENERATED["large_v4"] = {"path": path, "expected": expected, "targets": targets}
        CONTRACTS.setdefault("large_v4", path)
    models = [m for m in args.models.split(",") if m] or [None]
    pricing = load_pricing()
    jobs = [(m, c, k, n) for n in range(1, args.runs + 1) for m in models for k in args.contracts.split(",")
            for c in args.conditions.split(",")]
    rows = []
    results_dir = ROOT / "eval" / "results"
    results_dir.mkdir(exist_ok=True)

    def save() -> None:
        report = {"stamp": stamp, "prompt": PROMPT, "seed": args.seed, "conditions": CONDITIONS,
                  "models": models, "summary": summarise(rows), "runs": rows}
        (results_dir / f"{stamp}.json").write_text(json.dumps(report, indent=1), encoding="utf-8")

    with ThreadPoolExecutor(max_workers=args.parallel) as pool:
        futures = [pool.submit(run_one, stamp_dir, c, k, n, args.max_turns, args.timeout, m, pricing,
                               archive_dir=archive_dir, forbidden_roots=forbidden_roots)
                   for m, c, k, n in jobs]
        for f in futures:
            r = f.result()
            rows.append(r)
            save()  # partial results survive an interruption
            print(f"{(r['model'] or '-'):<24} {r['condition']} {r['contract']:<20} run {r['run']}: "
                  f"{r['points']}/{r['total']} tokens={r['tokens']} cost=${r['cost_usd']} wall={r['wall_s']}s "
                  f"tools={r['tool_calls']} pathfinder={r['used_pathfinder']}" + (f" error={r['error']}" if r['error'] else ""),
                  flush=True)
    save()
    print(json.dumps(summarise(rows), indent=1))


if __name__ == "__main__":
    main()
