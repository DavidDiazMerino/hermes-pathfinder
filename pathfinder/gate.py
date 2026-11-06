"""Evidence gate for skill writes.

Hermes's ``pre_tool_call`` hook hands us every ``skill_manage`` call before it runs. A write that
creates or changes a *domain skill* is allowed only when the batch cites at least one
Pathfinder run whose latest lab passed with tested claims. Cited runs must exist and be verified:
evidence cannot be invented. Changing a skill that is already backed by evidence needs a newly
verified run, so a correction is re-tested instead of riding on the old proof.

Pure logic: no Hermes imports. The ledger is passed in.
"""

from __future__ import annotations

import re
from typing import Any

RUN_ID_RE = re.compile(r"\bpf-\d{8}-\d{6}-[0-9a-f]{6}(?:-\d+)?\b")
_FRONTMATTER_RE = re.compile(r"\A\s*---\s*\n(.*?)\n---\s*(?:\n|\Z)", re.DOTALL)
_PATHFINDER_BLOCK_RE = re.compile(r"^\s+pathfinder\s*:", re.MULTILINE)

WRITE_ACTIONS = {"create", "patch", "edit", "write_file"}
MODES = ("strict", "declared", "off")


def operations(args: dict[str, Any]) -> list[dict[str, Any]]:
    ops = args.get("operations")
    if isinstance(ops, list):
        default = args.get("name")
        return [dict(op, name=op.get("name") or default) for op in ops if isinstance(op, dict)]
    if args.get("action"):
        return [args]  # legacy flat shape
    return []


def op_text(op: dict[str, Any]) -> str:
    return "\n".join(str(op.get(k) or "") for k in ("content", "new_string", "file_content"))


def declares_pathfinder(text: str) -> bool:
    m = _FRONTMATTER_RE.match(text or "")
    return bool(m and _PATHFINDER_BLOCK_RE.search(m.group(1)))


def keyword_regex(keywords: list[str]) -> re.Pattern | None:
    if not keywords:
        return None
    parts = []
    for kw in keywords:
        esc = re.escape(kw)
        # Short all-caps acronyms (SAP, BAPI) match case-sensitively as whole words.
        parts.append(rf"(?-i:\b{esc}\b)" if kw.isupper() and len(kw) <= 5 else rf"{esc}")
    return re.compile("|".join(parts), re.IGNORECASE)


def evaluate(args: dict[str, Any], ledger, *, mode: str = "strict",
             keywords: list[str] | None = None) -> dict[str, Any]:
    """Return {'allow': bool, 'message': str, 'domain_skills': [...], 'cited': [...], 'verified': [...]}."""
    decision: dict[str, Any] = {"allow": True, "message": "", "domain_skills": [], "cited": [], "verified": []}
    if mode == "off":
        return decision
    ops = operations(args)
    writes = [op for op in ops if op.get("action") in WRITE_ACTIONS]
    if not writes:
        return decision

    kw_re = keyword_regex(keywords or []) if mode == "strict" else None
    batch_text = "\n".join(op_text(op) for op in ops)
    cited = sorted(set(RUN_ID_RE.findall(batch_text)))
    decision["cited"] = cited

    domain_ops = []
    for op in writes:
        name = op.get("name") or ""
        text = op_text(op)
        reasons = []
        if declares_pathfinder(text):
            reasons.append("declares metadata.pathfinder")
        if name and ledger.skill_links(name):
            reasons.append("already backed by Pathfinder evidence")
        if kw_re is not None and (kw_re.search(text) or kw_re.search(name.replace("-", " "))):
            reasons.append("its content is about the SAP domain")
        if reasons:
            domain_ops.append((op, reasons))
    if not domain_ops:
        return decision
    decision["domain_skills"] = sorted({op.get("name") or "?" for op, _ in domain_ops})

    statuses = {rid: ledger.evidence_status(rid) for rid in cited}
    bad = {rid: st for rid, st in statuses.items() if st["status"] != "verified"}
    verified = [rid for rid, st in statuses.items() if st["status"] == "verified"]
    decision["verified"] = verified

    problems: list[str] = []
    if bad:
        problems.append("cited runs that are not verified: " + "; ".join(
            f"{rid} ({st['status']}: {st['reason']})" for rid, st in sorted(bad.items())))
    if not verified:
        problems.append("no verified Pathfinder run is cited")
    for op, reasons in domain_ops:
        name = op.get("name") or "?"
        if op.get("action") == "create" or (op.get("action") in ("patch", "edit") and op.get("content")):
            if not declares_pathfinder(op_text(op)):
                problems.append(f"skill '{name}': SKILL.md frontmatter lacks a metadata.pathfinder block")
        linked = {link["run_id"] for link in ledger.skill_links(name)} if name != "?" else set()
        if linked and verified and not (set(verified) - linked):
            problems.append(f"skill '{name}' is already backed by {sorted(linked)}; a change needs a newly "
                            "verified run that tests what changed")

    if not problems:
        return decision
    why = "; ".join(sorted({r for _, rs in domain_ops for r in rs}))
    decision["allow"] = False
    decision["message"] = (
        "Pathfinder evidence gate: this skill write was not applied.\n"
        f"Domain skill(s): {', '.join(decision['domain_skills'])} ({why}).\n"
        "Problems:\n- " + "\n- ".join(problems) + "\n"
        "To fix: inspect the contract with pathfinder_inspect, test the claims this skill makes with "
        "pathfinder_lab until it passes, then cite the verified run_id(s) in the SKILL.md frontmatter:\n"
        "metadata:\n  pathfinder:\n    domain: sap\n    product: <product id or unknown>\n"
        "    interface: <odata-v2|odata-v4|...>\n    evidence: [<run_id>]\n"
        "Only verified runs count; each run's status is shown by /pathfinder status."
    )
    return decision


# ---------------------------------------------------------------- other tools
READ_ONLY_TOOLS = {"read_file", "search_files", "skill_view", "skills_list", "tool_search", "tool_describe"}
FILE_WRITE_TOOLS = {"write_file", "patch"}
_IMPORT_RE = re.compile(r"(?:from|import)\s+pathfinder\b|pathfinder\.(?:ledger|lab|tools|gate|edmx)\b")


def guard_other_tool(tool_name: str, args: dict[str, Any], ledger, *, data_dir: str, skills_roots: list[str],
                     mode: str = "strict", keywords: list[str] | None = None) -> str | None:
    """Block message for a non-Pathfinder tool call that would touch the evidence ledger or write a
    domain skill around skill_manage; None to let it run. Not a sandbox: it closes the obvious paths."""
    if mode == "off" or tool_name.startswith("pathfinder_") or tool_name == "skill_manage":
        return None
    if tool_name in READ_ONLY_TOOLS:
        return None
    import json as _json
    blob = _json.dumps(args or {}, ensure_ascii=False, default=str)
    markers = [m for m in (data_dir, "plugin-data/enterprise-pathfinder", "ledger.db") if m]
    if any(m in blob for m in markers) or _IMPORT_RE.search(blob):
        return ("Pathfinder: the evidence ledger is written only by the pathfinder_* tools. Use "
                "pathfinder_inspect and pathfinder_lab instead of reading or changing the ledger or the "
                "plugin's internals directly. If a pathfinder tool is missing, tell the user.")
    if tool_name in FILE_WRITE_TOOLS:
        path = str((args or {}).get("path") or "")
        root = next((r for r in skills_roots if r and path.startswith(r.rstrip("/") + "/")), None)
        if root:
            rel = path[len(root.rstrip("/")) + 1:].split("/")
            skill_dir = rel[-2] if rel[-1] == "SKILL.md" and len(rel) >= 2 else rel[0]
            text = (args or {}).get("content") or (args or {}).get("new_string") or ""
            probe = {"operations": [{"action": "write_file", "name": skill_dir, "file_path": rel[-1],
                                     "file_content": text}]}
            decision = evaluate(probe, ledger, mode=mode, keywords=keywords)
            if decision["domain_skills"]:
                return (f"Pathfinder: '{skill_dir}' is an SAP-domain skill. Write it with skill_manage so the "
                        "evidence gate can check it; direct file writes into the skills folder are refused.")
    return None
