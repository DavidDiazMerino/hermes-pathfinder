"""Scoring for the Pathfinder evaluation: compare an agent's JSON answer with hand-written expectations."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

EXPECTED_DIR = Path(__file__).resolve().parent / "expected"
FIELDS = ("keys", "create", "update", "delete", "required_on_create", "navigations")
_JSON_BLOCK = re.compile(r"```(?:json)?\s*(\{.*?\})\s*```", re.DOTALL)


def load_expected(contract_id: str) -> dict[str, Any]:
    return json.loads((EXPECTED_DIR / f"{contract_id}.json").read_text(encoding="utf-8"))


def extract_answer(text: str) -> dict[str, Any] | None:
    """Last JSON object in a fenced block that has 'entity_sets'; else None."""
    for raw in reversed(_JSON_BLOCK.findall(text or "")):
        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            continue
        if isinstance(data, dict) and isinstance(data.get("entity_sets"), dict):
            return data
    return None


def _short(name: Any) -> str:
    return str(name).rsplit(".", 1)[-1] if name is not None else ""


def _norm_navs(navs: Any) -> dict[str, tuple[str, bool]] | None:
    if not isinstance(navs, dict):
        return None
    out = {}
    for name, nav in navs.items():
        if not isinstance(nav, dict):
            return None
        out[str(name)] = (_short(nav.get("target")), bool(nav.get("many")))
    return out


def score(answer: dict[str, Any] | None, expected: dict[str, Any]) -> dict[str, Any]:
    exp_sets = expected["entity_sets"]
    total = len(exp_sets) * len(FIELDS)
    if answer is None:
        return {"points": 0, "total": total, "ratio": 0.0, "parsed": False, "errors": ["no JSON answer found"]}
    got_sets = answer.get("entity_sets") or {}
    points, errors = 0, []
    for name, exp in exp_sets.items():
        got = got_sets.get(name)
        if not isinstance(got, dict):
            errors.append(f"{name}: missing")
            continue
        checks = {
            "keys": sorted(map(str, got.get("keys") or [])) == sorted(exp["keys"]),
            "create": got.get("create") is exp["create"],
            "update": got.get("update") is exp["update"],
            "delete": got.get("delete") is exp["delete"],
            "required_on_create": sorted(map(str, got.get("required_on_create") or [])) == sorted(exp["required_on_create"]),
            "navigations": _norm_navs(got.get("navigations")) == _norm_navs(exp["navigations"]),
        }
        for field, ok in checks.items():
            if ok:
                points += 1
            else:
                errors.append(f"{name}.{field}: got {json.dumps(got.get(field))}, expected {json.dumps(exp[field])}")
    extra = sorted(set(got_sets) - set(exp_sets))
    if extra:
        errors.append(f"unexpected entity sets: {extra}")
    return {"points": points, "total": total, "ratio": round(points / total, 3), "parsed": True, "errors": errors}


def answer_from_contract(contract: dict[str, Any]) -> dict[str, Any]:
    """The same answer shape derived from a parsed contract (used to cross-check the expectations)."""
    sets = {}
    for es in contract["entity_sets"]:
        et = contract["entity_types"][es["entity_type"]]
        sets[es["name"]] = {
            "keys": et["keys"],
            "create": es["creatable"] is not False,
            "update": es["updatable"] is not False,
            "delete": es["deletable"] is not False,
            "required_on_create": [p["name"] for p in et["properties"]
                                   if p.get("nullable") is False and p.get("creatable") is not False],
            "navigations": {n["name"]: {"target": _short(n["target_type"]), "many": n.get("multiplicity") == "*"}
                            for n in et["navigations"]},
        }
    return {"entity_sets": sets}
