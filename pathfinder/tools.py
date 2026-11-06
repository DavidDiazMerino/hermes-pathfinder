"""Tool handlers. Each returns a JSON string and never raises."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

from . import edmx, packs
from .ledger import Ledger

# Above this many entity types the overview lists names only and asks to zoom in.
OVERVIEW_TYPE_LIMIT = 25


@dataclass
class Runtime:
    """What handlers need from the host; Hermes supplies real ones, tests supply fakes."""
    ledger: Callable[[], Ledger]
    cwd: Callable[[], str]


def _ok(payload: dict[str, Any]) -> str:
    return json.dumps({"ok": True, **payload}, ensure_ascii=False)


def _err(message: str, **extra: Any) -> str:
    return json.dumps({"ok": False, "error": message, **extra}, ensure_ascii=False)


# ---------------------------------------------------------------- sources
def sources(args: dict[str, Any], rt: Runtime) -> str:
    domain = (args.get("domain") or "sap").strip().lower()
    try:
        pack = packs.load(domain)
    except packs.PackError as exc:
        return _err(str(exc), available_domains=packs.available())
    product = (args.get("product") or "").strip()
    products = pack["products"]
    if product:
        products = [p for p in products if p["id"] == product] or products
    return _ok({
        "domain": pack["id"],
        "pack_version": pack["pack_version"],
        "disclaimer": pack["disclaimer"],
        "source_policy": pack["source_policy"],
        "ask_first": pack["orientation_questions"] if not product else [],
        "products": products,
        "interface_formats": pack["interface_formats"],
        "sources": pack["sources"],
        "pitfalls": pack["pitfalls"],
        "sample_contracts": [
            {"ref": f"fixture:{domain}/{fx['id']}", "family": fx["family"], "description": fx["description"]}
            for fx in pack.get("fixtures", [])
        ],
        "status_legend": {
            "documented": "stated in the linked official source",
            "practitioner": "experienced-practitioner guidance; confirm against official docs for your release",
        },
    })


# ---------------------------------------------------------------- inspect
def _resolve(ref: str, domain: str, rt: Runtime) -> tuple[Path, str, str]:
    """Return (path, source_kind, display_ref)."""
    if ref.startswith("fixture:"):
        body = ref[len("fixture:"):]
        fx_domain, _, fx_id = body.partition("/")
        if not fx_id:
            fx_domain, fx_id = domain, fx_domain
        return packs.fixture_path(fx_domain, fx_id), "fixture", ref
    path = Path(ref).expanduser()
    if not path.is_absolute():
        path = Path(rt.cwd()) / path
    return path.resolve(), "local_file", str(path.resolve())


def _short(name: str | None) -> str | None:
    return name.rsplit(".", 1)[-1] if name else name


def _prop_line(p: dict[str, Any], keys: list[str]) -> str:
    t = p["type"] or "?"
    if p.get("max_length") is not None:
        t += f"({p['max_length']})"
    elif p.get("precision") is not None and p.get("scale") is not None:
        t += f"({p['precision']},{p['scale']})"
    flags = []
    if p["name"] in keys:
        flags.append("key")
    if p.get("nullable") is False:
        flags.append("not-null")
    if p.get("creatable") is False:
        flags.append("not-creatable")
    if p.get("updatable") is False:
        flags.append("not-updatable")
    line = f"{p['name']}: {t}"
    if flags:
        line += " [" + ", ".join(flags) + "]"
    if p.get("label"):
        line += f' "{p["label"]}"'
    return line


def _nav_line(n: dict[str, Any]) -> str:
    target = _short(n.get("target_type")) or "UNRESOLVED"
    return f"{n['name']} -> {target} [{n.get('multiplicity') or '?'}] via {n['via']}"


def _ops(es: dict[str, Any]) -> str:
    def flag(v: bool | None, letter: str, path_key: str = "") -> str:
        if path_key and es.get(path_key):
            return letter.lower()  # depends on each record's state
        return letter if v is not False else "-"
    return (flag(es["creatable"], "C") + "R" + flag(es["updatable"], "U", "updatable_path")
            + flag(es["deletable"], "D", "deletable_path"))


def _set_view(es: dict[str, Any]) -> dict[str, Any]:
    view = {"name": es["name"], "type": _short(es["entity_type"]), "ops": _ops(es),
            "restrictions_from": es["capability_source"]}
    for key in ("updatable_path", "deletable_path"):
        if es.get(key):
            view[key] = es[key]
    if es.get("requires_filter"):
        view["requires_filter"] = True
    return view


def view_type(contract: dict[str, Any], fq: str) -> dict[str, Any]:
    et = contract["entity_types"][fq]
    return {
        "keys": et["keys"],
        "properties": [_prop_line(p, et["keys"]) for p in et["properties"]],
        "navigations": [_nav_line(n) for n in et["navigations"]],
    }


def inspect(args: dict[str, Any], rt: Runtime) -> str:
    ref = (args.get("contract") or "").strip()
    if not ref:
        return _err("missing 'contract': a file path or fixture:<domain>/<id>")
    domain = (args.get("domain") or "sap").strip().lower()
    product = (args.get("product") or "").strip() or None
    focus = (args.get("entity") or "").strip()
    try:
        path, kind, display = _resolve(ref, domain, rt)
        contract = edmx.parse_file(path)
    except (packs.PackError, edmx.ContractError, OSError) as exc:
        return _err(str(exc), contract=ref)
    except Exception as exc:  # parser bug: report, don't crash the agent loop
        return _err(f"unexpected parser error: {type(exc).__name__}: {exc}", contract=ref)

    try:
        run_id = rt.ledger().record_inspection(domain=domain, product=product, source_kind=kind,
                                               source_ref=display, contract=contract)
    except Exception as exc:
        run_id = None
        contract["issues"].append({"severity": "warning", "code": "ledger-unavailable", "message": str(exc)})

    types = contract["entity_types"]
    out: dict[str, Any] = {
        "run_id": run_id,
        "evidence": "contract_parsed",
        "source": {"kind": kind, "ref": display, "sha256": contract["source"]["sha256"]},
        "family": contract["family"],
        "odata_version": contract["odata_version"],
        "summary": contract["summary"],
        "issues": contract["issues"],
        "entity_sets": [_set_view(es) for es in contract["entity_sets"]],
    }

    if focus:
        match = [fq for fq in types if _short(fq) == focus or fq == focus]
        if not match:
            set_types = [es["entity_type"] for es in contract["entity_sets"] if es["name"] == focus]
            match = [fq for fq in set_types if fq in types]
        if not match:
            return _err(f"no entity type or set named {focus!r}", run_id=run_id,
                        entity_types=[_short(t) for t in types])
        out["entity_types"] = {_short(fq): view_type(contract, fq) for fq in match}
    elif len(types) > OVERVIEW_TYPE_LIMIT:
        out["entity_types"] = sorted(_short(t) for t in types)
        out["hint"] = f"{len(types)} entity types: call again with entity=<name> to see one in detail."
    else:
        out["entity_types"] = {_short(fq): view_type(contract, fq) for fq in types}

    out["ops_legend"] = ("C=create R=read U=update D=delete; '-' = explicitly disallowed by the contract; "
                         "lowercase = depends on each record's state (see *_path); unstated = allowed by default")
    out["note"] = ("Everything above was read from the file by a deterministic parser; nothing was inferred. "
                   "This is not a test against a live SAP system.")
    return _ok(out)
