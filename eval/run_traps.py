"""Run the trap-question evaluation through real Hermes sessions, with (C) and without (A) the plugin.

    python eval/run_traps.py --models openai/gpt-6-luna,... --parallel 4

Both conditions have Hermes's normal web tools; only the plugin differs. Summary in eval/results/traps-<stamp>.json.
Sessions work outside the repository; transcripts and answers go to eval/runs/traps-<stamp>/.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from eval import isolation, traps  # noqa: E402
from eval.run_eval import CONDITIONS, cost_usd, load_pricing  # noqa: E402


def run_trap(stamp_dir: Path, model: str | None, condition: str, trap: dict, n: int, max_turns: int,
             timeout: int, pricing: dict, *, archive_dir: Path, forbidden_roots: list[str]) -> dict:
    ws = stamp_dir / (model or "default").replace("/", "_") / f"{condition}-{trap['id']}-{n}"
    ws.mkdir(parents=True)
    cmd = ["hermes", "-p", CONDITIONS[condition], "chat", "-q", trap["question"] + traps.SUFFIX, "--oneshot",
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
            out = exc.stdout.decode() if isinstance(exc.stdout, bytes) else (exc.stdout or "")
            code = "timeout"
        wall = round(time.time() - t0, 1)
        if "Gateway draining" in (out or "") and retries < 5:
            retries += 1
            time.sleep(30)
            continue
        break
    tools, final, tokens, served, error = [], "", {}, None, None
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
            final, tokens, error = ev.get("text") or "", ev.get("tokens") or {}, ev.get("error")
    isolation.archive_session(archive_dir / ws.relative_to(stamp_dir), out or "", final)
    contaminated = isolation.contaminated(out or "", str(ws), forbidden_roots)
    res = traps.score(final, trap)
    return {"model": model or served, "condition": condition, "trap": trap["id"], "run": n, "exit": code,
            "error": error, "wall_s": wall, "retries": retries,
            "infra_error": "Gateway draining" in (out or "") or not tokens.get("total"),
            "contaminated": contaminated,
            "tokens": tokens.get("total"), "cost_usd": cost_usd(tokens, pricing.get(served or model or "")),
            "tool_calls": len(tools), "tools": tools,
            "used_pathfinder": any(str(t).startswith("pathfinder_") for t in tools),
            "web_calls": sum(str(t).startswith("web_") for t in tools), **res}


def summarise(rows: list[dict]) -> list[dict]:
    out = []
    for model in sorted({r["model"] or "" for r in rows}):
        for cond in CONDITIONS:
            group = [r for r in rows if (r["model"] or "") == model and r["condition"] == cond]
            rs = [r for r in group if not r.get("infra_error") and not r.get("contaminated")]
            excluded = sum(bool(r.get("contaminated")) for r in group)
            counts = {"model": model, "condition": cond, "runs": len(rs), "excluded_contaminated": excluded}
            if not rs:
                if excluded:
                    out.append(counts)
                continue
            out.append({**counts,
                        "correct": sum(r["correct"] for r in rs),
                        "checks": f"{sum(r['checks_passed'] for r in rs)}/{sum(r['checks_total'] for r in rs)}",
                        "cites_official": sum(r["cites_official"] for r in rs),
                        "used_pathfinder": sum(r["used_pathfinder"] for r in rs),
                        "cost_usd": round(sum(r["cost_usd"] or 0 for r in rs), 4),
                        "wall_s_mean": round(sum(r["wall_s"] for r in rs) / len(rs), 1)})
    return out


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--models", default="")
    ap.add_argument("--conditions", default="A,C")
    ap.add_argument("--traps", default=",".join(t["id"] for t in traps.TRAPS))
    ap.add_argument("--runs", type=int, default=1)
    ap.add_argument("--parallel", type=int, default=4)
    ap.add_argument("--max-turns", type=int, default=25)
    ap.add_argument("--timeout", type=int, default=900)
    ap.add_argument("--work-dir", default=str(isolation.default_work_dir()),
                    help="workspace base outside the repository (default: %(default)s)")
    args = ap.parse_args()
    stamp = time.strftime("%Y%m%d-%H%M%S")
    run_name = f"traps-{stamp}"
    try:
        stamp_dir = isolation.round_workspace(ROOT, args.work_dir, run_name)
    except ValueError as exc:
        ap.error(str(exc))
    stamp_dir.mkdir(parents=True)
    archive_dir = ROOT / "eval" / "runs" / run_name
    archive_dir.mkdir(parents=True)
    forbidden_roots = isolation.evaluation_roots(ROOT)
    chosen = [t for t in traps.TRAPS if t["id"] in args.traps.split(",")]
    models = [m for m in args.models.split(",") if m] or [None]
    pricing = load_pricing()
    jobs = [(m, c, t, n) for n in range(1, args.runs + 1) for t in chosen for m in models
            for c in args.conditions.split(",")]
    rows: list[dict] = []
    results = ROOT / "eval" / "results"
    results.mkdir(exist_ok=True)

    def save():
        (results / f"traps-{stamp}.json").write_text(json.dumps(
            {"stamp": stamp, "suffix": traps.SUFFIX, "traps": chosen, "models": models,
             "summary": summarise(rows), "runs": rows}, indent=1), encoding="utf-8")

    with ThreadPoolExecutor(max_workers=args.parallel) as pool:
        futures = [pool.submit(run_trap, stamp_dir, m, c, t, n, args.max_turns, args.timeout, pricing,
                               archive_dir=archive_dir, forbidden_roots=forbidden_roots)
                   for m, c, t, n in jobs]
        for f in futures:
            r = f.result()
            rows.append(r)
            save()
            print(f"{(r['model'] or '-'):<24} {r['condition']} {r['trap']:<22} "
                  f"{'OK ' if r['correct'] else 'XX '}{r['checks_passed']}/{r['checks_total']} "
                  f"official={r['cites_official']} pathfinder={r['used_pathfinder']} web={r['web_calls']} "
                  f"cost=${r['cost_usd']} wall={r['wall_s']}s" + (f" missing={r['failed_checks']}" if r['failed_checks'] else ""),
                  flush=True)
    save()
    print(json.dumps(summarise(rows), indent=1))


if __name__ == "__main__":
    main()
