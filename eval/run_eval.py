"""Run the Pathfinder A/C evaluation through real Hermes sessions.

A = a Hermes profile without the plugin, C = a profile with it. Same model, same prompt, same contract
file under a neutral name in an empty folder. Each run's JSON answer is scored against hand-written
expectations (eval/expected/). Usage:

    python eval/run_eval.py --runs 3 --parallel 2

Raw transcripts go to eval/runs/<stamp>/ (gitignored); the summary to eval/results/<stamp>.json.
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

CONTRACTS = {
    "business_partner_v2": ROOT / "domains/sap/fixtures/business_partner_v2.edmx",
    "product_v4": ROOT / "domains/sap/fixtures/product_v4.xml",
}
CONDITIONS = {"A": "pathfinder-baseline", "C": "pathfinder"}

PROMPT = """I work with SAP. service_metadata.xml in this folder is the $metadata of an SAP OData service.
For every entity set, tell me: its key properties; whether create, update and delete are allowed;
the properties a create request must carry (Nullable=false and not set by the server; list them even
if the set itself does not allow create); and its navigation properties with target entity type and
whether they are to-many. Do not create or modify any skills.

End your answer with exactly one fenced ```json block in this shape:
{"entity_sets": {"<EntitySetName>": {"keys": ["..."], "create": true, "update": true, "delete": true,
 "required_on_create": ["..."], "navigations": {"<NavName>": {"target": "<EntityTypeName>", "many": true}}}}}"""


def run_one(stamp_dir: Path, condition: str, contract_id: str, n: int, max_turns: int, timeout: int) -> dict:
    ws = stamp_dir / f"{condition}-{contract_id}-{n}"
    ws.mkdir(parents=True, exist_ok=True)
    shutil.copy(CONTRACTS[contract_id], ws / "service_metadata.xml")
    cmd = ["hermes", "-p", CONDITIONS[condition], "chat", "-q", PROMPT, "--oneshot",
           "--format", "stream-json", "--max-turns", str(max_turns)]
    t0 = time.time()
    try:
        proc = subprocess.run(cmd, cwd=ws, capture_output=True, text=True, timeout=timeout)
        out, code = proc.stdout, proc.returncode
    except subprocess.TimeoutExpired as exc:
        out, code = (exc.stdout or b"").decode() if isinstance(exc.stdout, bytes) else (exc.stdout or ""), "timeout"
    wall = round(time.time() - t0, 1)
    (ws / "transcript.jsonl").write_text(out or "", encoding="utf-8")

    tools, final, tokens, duration = [], "", None, None
    for line in (out or "").splitlines():
        if not line.startswith("{"):
            continue
        try:
            ev = json.loads(line)
        except json.JSONDecodeError:
            continue
        if ev.get("type") == "tool_use":
            tools.append(ev.get("name"))
        elif ev.get("type") == "result":
            final = ev.get("text") or ev.get("result") or ""
            tokens = (ev.get("tokens") or {}).get("total")
            duration = ev.get("duration_ms")
    result = sc.score(sc.extract_answer(final), sc.load_expected(contract_id))
    return {"condition": condition, "contract": contract_id, "run": n, "exit": code, "wall_s": wall,
            "duration_ms": duration, "tokens": tokens, "tool_calls": len(tools), "tools": tools,
            "used_pathfinder": any(str(t).startswith("pathfinder_") for t in tools), **result}


def summarise(rows: list[dict]) -> list[dict]:
    out = []
    for cond in CONDITIONS:
        for cid in CONTRACTS:
            rs = [r for r in rows if r["condition"] == cond and r["contract"] == cid]
            if not rs:
                continue
            avg = lambda k: round(sum((r.get(k) or 0) for r in rs) / len(rs), 1)  # noqa: E731
            out.append({"condition": cond, "contract": cid, "runs": len(rs),
                        "score_mean": round(sum(r["ratio"] for r in rs) / len(rs), 3),
                        "perfect_runs": sum(r["points"] == r["total"] for r in rs),
                        "tokens_mean": avg("tokens"), "wall_s_mean": avg("wall_s"),
                        "tool_calls_mean": avg("tool_calls")})
    return out


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--runs", type=int, default=3)
    ap.add_argument("--parallel", type=int, default=2)
    ap.add_argument("--conditions", default="A,C")
    ap.add_argument("--contracts", default=",".join(CONTRACTS))
    ap.add_argument("--max-turns", type=int, default=25)
    ap.add_argument("--timeout", type=int, default=900)
    ap.add_argument("--runs-dir", default=str(ROOT / "eval" / "runs"))
    args = ap.parse_args()

    stamp = time.strftime("%Y%m%d-%H%M%S")
    stamp_dir = Path(args.runs_dir) / stamp
    jobs = [(c, k, n) for n in range(1, args.runs + 1) for k in args.contracts.split(",")
            for c in args.conditions.split(",")]
    rows = []
    with ThreadPoolExecutor(max_workers=args.parallel) as pool:
        futures = [pool.submit(run_one, stamp_dir, c, k, n, args.max_turns, args.timeout) for c, k, n in jobs]
        for f in futures:
            r = f.result()
            rows.append(r)
            print(f"{r['condition']} {r['contract']:<20} run {r['run']}: {r['points']}/{r['total']} "
                  f"tokens={r['tokens']} wall={r['wall_s']}s tools={r['tool_calls']} pathfinder={r['used_pathfinder']}",
                  flush=True)
    results_dir = ROOT / "eval" / "results"
    results_dir.mkdir(exist_ok=True)
    report = {"stamp": stamp, "prompt": PROMPT, "conditions": CONDITIONS, "summary": summarise(rows), "runs": rows}
    (results_dir / f"{stamp}.json").write_text(json.dumps(report, indent=1), encoding="utf-8")
    print(json.dumps(report["summary"], indent=1))


if __name__ == "__main__":
    main()
