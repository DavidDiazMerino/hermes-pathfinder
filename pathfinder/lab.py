"""Deterministic lab: checks a parsed contract and the agent's claims about it.

Two kinds of checks run against a canonical contract (see ``edmx.py``):

* integrity checks, always run: does the contract hold together?
* claim checks, supplied by the agent: is what the agent believes about the contract true?
  A payload claim states whether a request body should be accepted ("valid") or refused
  ("invalid"); the check passes when the lab agrees with the agent.

Same contract + same claims -> same results. No network, no clock, no randomness.
"""

from __future__ import annotations

import re
from decimal import Decimal, InvalidOperation
from typing import Any

INT_RANGES = {
    "Edm.Byte": (0, 255),
    "Edm.SByte": (-128, 127),
    "Edm.Int16": (-(2**15), 2**15 - 1),
    "Edm.Int32": (-(2**31), 2**31 - 1),
    "Edm.Int64": (-(2**63), 2**63 - 1),
}
_V2_DATE = re.compile(r"^/Date\(-?\d+([+-]\d{4})?\)/$")
_ISO_LOCAL = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}(:\d{2}(\.\d+)?)?$")
_ISO_OFFSET = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}(:\d{2}(\.\d+)?)?(Z|[+-]\d{2}:\d{2})$")
_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_TIME_OF_DAY = re.compile(r"^\d{2}:\d{2}(:\d{2}(\.\d+)?)?$")
_GUID = re.compile(r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$")

CLAIM_TYPES = ("keys", "operation", "navigation", "required_fields", "payload")


def _short(name: str | None) -> str | None:
    return name.rsplit(".", 1)[-1] if name else name


def _result(check_id: str, passed: bool, detail: str, **extra: Any) -> dict[str, Any]:
    return {"id": check_id, "status": "passed" if passed else "failed", "detail": detail, **extra}


class Lab:
    def __init__(self, contract: dict[str, Any]):
        self.c = contract
        self.types = contract["entity_types"]
        self.sets = {es["name"]: es for es in contract["entity_sets"]}

    # ------------------------------------------------------------ lookup
    def find_type(self, name: str) -> str | None:
        if name in self.types:
            return name
        hits = [fq for fq in self.types if _short(fq) == name]
        return hits[0] if len(hits) == 1 else None

    def resolve_target(self, claim: dict[str, Any]) -> tuple[dict | None, str | None, str]:
        """Return (entity_set or None, fq type or None, label) for a claim naming a set or a type."""
        if claim.get("entity_set"):
            es = self.sets.get(claim["entity_set"])
            if es is None:
                return None, None, claim["entity_set"]
            return es, es["entity_type"], es["name"]
        if claim.get("entity_type"):
            fq = self.find_type(claim["entity_type"])
            return None, fq, claim["entity_type"]
        return None, None, "?"

    # ------------------------------------------------------------ integrity
    def integrity(self) -> list[dict[str, Any]]:
        out = []
        errors = [i for i in self.c.get("issues", []) if i["severity"] == "error"]
        out.append(_result("contract.parsed_clean", not errors,
                           "no parse errors" if not errors else f"{len(errors)} parse error(s): "
                           + "; ".join(i["message"] for i in errors)))

        bad = [es["name"] for es in self.c["entity_sets"] if es["entity_type"] not in self.types]
        out.append(_result("contract.entityset_types", not bad,
                           "every entity set points to a defined entity type" if not bad
                           else f"entity sets with unknown type: {', '.join(bad)}"))

        missing = []
        no_key = []
        for fq, et in self.types.items():
            names = {p["name"] for p in et["properties"]}
            if not et["keys"]:
                no_key.append(_short(fq))
            missing += [f"{_short(fq)}.{k}" for k in et["keys"] if k not in names]
        out.append(_result("contract.keys_exist", not missing and not no_key,
                           "every key refers to a declared property" if not (missing or no_key)
                           else f"missing key properties: {missing}; types without key: {no_key}"))

        unresolved = [f"{_short(fq)}.{n['name']}" for fq, et in self.types.items()
                      for n in et["navigations"] if not n.get("target_type") or n["target_type"] not in self.types]
        out.append(_result("contract.navigation_resolves", not unresolved,
                           "every navigation resolves to a defined entity type" if not unresolved
                           else f"unresolved navigations: {', '.join(unresolved)}"))
        return out

    # ------------------------------------------------------------ claims
    def check_claim(self, i: int, claim: dict[str, Any]) -> dict[str, Any]:
        kind = claim.get("type")
        cid = f"claim.{i}.{kind or 'unknown'}"
        if kind not in CLAIM_TYPES:
            return _result(cid, False, f"unknown claim type {kind!r}; use one of {', '.join(CLAIM_TYPES)}")
        es, fq, label = self.resolve_target(claim)
        if fq is None or fq not in self.types:
            return _result(cid, False, f"{label!r} is not an entity set or entity type of this contract")
        return getattr(self, f"_claim_{kind}")(cid, claim, es, fq)

    def _claim_keys(self, cid, claim, es, fq):
        actual = self.types[fq]["keys"]
        expect = list(claim.get("expect") or [])
        ok = sorted(actual) == sorted(expect)
        return _result(cid, ok, f"keys of {_short(fq)} are {actual}" + ("" if ok else f", not {expect}"))

    def _claim_operation(self, cid, claim, es, fq):
        if es is None:
            return _result(cid, False, "operation claims need an entity_set")
        op = claim.get("op")
        field = {"create": "creatable", "update": "updatable", "delete": "deletable"}.get(op or "")
        if field is None:
            return _result(cid, False, "op must be create, update or delete")
        value = es[field]
        path = es.get(f"{field}_path")  # only updatable_path / deletable_path exist
        actual: Any = "depends-on-record" if path else (value is not False)
        expect = claim.get("expect")
        ok = actual == expect
        why = f"state-dependent via {path}" if path else (
            f"explicitly {'allowed' if value else 'disallowed'} ({es['capability_source']})" if value is not None
            else "not restricted, allowed by default")
        return _result(cid, ok, f"{op} on {es['name']}: {actual} — {why}")

    def _claim_navigation(self, cid, claim, es, fq):
        name = claim.get("name")
        navs = {n["name"]: n for n in self.types[fq]["navigations"]}
        if name not in navs:
            return _result(cid, claim.get("expect_exists") is False,
                           f"{_short(fq)} has no navigation {name!r}; navigations: {sorted(navs)}")
        nav = navs[name]
        problems = []
        if claim.get("target") and _short(nav["target_type"]) != _short(claim["target"]):
            problems.append(f"target is {_short(nav['target_type'])}, not {claim['target']}")
        if claim.get("multiplicity") and nav.get("multiplicity") != claim["multiplicity"]:
            problems.append(f"multiplicity is {nav.get('multiplicity')}, not {claim['multiplicity']}")
        if claim.get("expect_exists") is False:
            problems.append("navigation exists")
        return _result(cid, not problems,
                       f"{_short(fq)}.{name} -> {_short(nav['target_type'])} [{nav.get('multiplicity')}]"
                       + ("" if not problems else ": " + "; ".join(problems)))

    def required_for_create(self, fq: str) -> list[str]:
        return [p["name"] for p in self.types[fq]["properties"]
                if p.get("nullable") is False and p.get("creatable") is not False]

    def _claim_required_fields(self, cid, claim, es, fq):
        actual = self.required_for_create(fq)
        expect = list(claim.get("expect") or [])
        ok = sorted(actual) == sorted(expect)
        return _result(cid, ok, f"fields a create payload must carry for {_short(fq)}: {actual}"
                       + ("" if ok else f" (claimed {expect})"),
                       note="Contract-level only: Nullable=false and not marked non-creatable. Business "
                            "configuration can make more fields mandatory at runtime.")

    def _claim_payload(self, cid, claim, es, fq):
        op = claim.get("operation", "create")
        payload = claim.get("payload")
        expect = claim.get("expect")
        if expect not in ("valid", "invalid"):
            return _result(cid, False, "payload claims need expect: 'valid' or 'invalid'")
        if not isinstance(payload, dict):
            return _result(cid, False, "payload must be a JSON object")
        violations: list[str] = []
        if es is not None and op in ("create", "update"):
            field = "creatable" if op == "create" else "updatable"
            if es[field] is False:
                violations.append(f"{es['name']} does not allow {op} ({es['capability_source']})")
        violations += self.validate_payload(fq, payload, op, path=_short(fq) or "")
        verdict = "invalid" if violations else "valid"
        ok = verdict == expect
        return _result(cid, ok, f"lab says {verdict}, claim said {expect}",
                       violations=violations, operation=op)

    # ------------------------------------------------------------ payloads
    def validate_payload(self, fq: str, payload: dict[str, Any], op: str, path: str) -> list[str]:
        et = self.types[fq]
        props = {p["name"]: p for p in et["properties"]}
        navs = {n["name"]: n for n in et["navigations"]}
        out: list[str] = []
        for key, value in payload.items():
            if key.startswith("@") or key == "__metadata":
                continue
            where = f"{path}.{key}"
            if key in props:
                out += self.check_value(props[key], value, where, op, is_key=key in et["keys"])
            elif key in navs:
                out += self.check_nested(navs[key], value, where, op)
            else:
                out.append(f"{where}: not a property or navigation of {_short(fq)}")
        if op == "create":
            for name in self.required_for_create(fq):
                if name not in payload:
                    out.append(f"{path}.{name}: required (Nullable=false) but missing")
        return out

    def check_nested(self, nav: dict[str, Any], value: Any, where: str, op: str) -> list[str]:
        target = nav.get("target_type")
        if target not in self.types:
            return [f"{where}: navigation target cannot be resolved"]
        if op != "create":
            return [f"{where}: nested entities are only checked for create (deep insert)"]
        if nav.get("multiplicity") == "*":
            if isinstance(value, dict) and isinstance(value.get("results"), list):
                value = value["results"]  # OData V2 JSON wraps collections
            if not isinstance(value, list):
                return [f"{where}: to-many navigation expects a list"]
            out = []
            for n, item in enumerate(value):
                if not isinstance(item, dict):
                    out.append(f"{where}[{n}]: expected an object")
                else:
                    out += self.validate_payload(target, item, "create", f"{where}[{n}]")
            return out
        if not isinstance(value, dict):
            return [f"{where}: to-one navigation expects an object"]
        return self.validate_payload(target, value, "create", where)

    def check_value(self, prop: dict[str, Any], value: Any, where: str, op: str, is_key: bool) -> list[str]:
        out = []
        if op == "create" and prop.get("creatable") is False:
            out.append(f"{where}: not creatable (set by the server)")
        if op == "update" and (prop.get("updatable") is False or is_key):
            out.append(f"{where}: not updatable" + (" (key)" if is_key else ""))
        if value is None:
            if prop.get("nullable") is False:
                out.append(f"{where}: null not allowed")
            return out
        t = prop.get("type") or ""
        if t == "Edm.String":
            if not isinstance(value, str):
                out.append(f"{where}: expected string")
            elif isinstance(prop.get("max_length"), int) and len(value) > prop["max_length"]:
                out.append(f"{where}: length {len(value)} exceeds MaxLength {prop['max_length']}")
        elif t == "Edm.Boolean":
            if not isinstance(value, bool):
                out.append(f"{where}: expected true/false")
        elif t in INT_RANGES:
            lo, hi = INT_RANGES[t]
            num = value
            if t == "Edm.Int64" and isinstance(value, str) and re.fullmatch(r"-?\d+", value):
                num = int(value)  # V2 JSON serialises Int64 as string
            if isinstance(num, bool) or not isinstance(num, int):
                out.append(f"{where}: expected integer ({t})")
            elif not lo <= num <= hi:
                out.append(f"{where}: {num} out of range for {t}")
        elif t == "Edm.Decimal":
            out += self._check_decimal(prop, value, where)
        elif t in ("Edm.Double", "Edm.Single"):
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                out.append(f"{where}: expected number")
        elif t == "Edm.DateTime":
            if not (isinstance(value, str) and (_V2_DATE.match(value) or _ISO_LOCAL.match(value))):
                out.append(f"{where}: expected /Date(ms)/ or yyyy-mm-ddThh:mm:ss")
        elif t == "Edm.DateTimeOffset":
            if not (isinstance(value, str) and (_ISO_OFFSET.match(value) or _V2_DATE.match(value))):
                out.append(f"{where}: expected ISO 8601 with offset, e.g. 2026-11-06T10:00:00Z")
        elif t == "Edm.Date":
            if not (isinstance(value, str) and _DATE.match(value)):
                out.append(f"{where}: expected yyyy-mm-dd")
        elif t == "Edm.TimeOfDay":
            if not (isinstance(value, str) and _TIME_OF_DAY.match(value)):
                out.append(f"{where}: expected hh:mm:ss")
        elif t == "Edm.Guid":
            if not (isinstance(value, str) and _GUID.match(value)):
                out.append(f"{where}: expected a GUID")
        # Other types (Binary, Stream, complex, enums) are not checked; not reported as errors.
        return out

    def _check_decimal(self, prop: dict[str, Any], value: Any, where: str) -> list[str]:
        if isinstance(value, bool) or not isinstance(value, (int, float, str)):
            return [f"{where}: expected decimal number or numeric string"]
        try:
            dec = Decimal(str(value))
        except InvalidOperation:
            return [f"{where}: {value!r} is not a decimal"]
        if not dec.is_finite():
            return [f"{where}: not a finite decimal"]
        sign, digits, exp = dec.as_tuple()
        scale_used = max(0, -exp)
        int_digits = max(0, len(digits) + exp)
        out = []
        precision, scale = prop.get("precision"), prop.get("scale")
        if isinstance(scale, int) and scale_used > scale:
            out.append(f"{where}: {scale_used} decimals exceed Scale {scale}")
        if isinstance(precision, int):
            max_int = precision - (scale if isinstance(scale, int) else 0)
            if int_digits > max_int:
                out.append(f"{where}: {int_digits} integer digits exceed Precision {precision}/Scale {scale}")
        return out


def run(contract: dict[str, Any], claims: list[dict[str, Any]] | None) -> dict[str, Any]:
    lab = Lab(contract)
    results = lab.integrity()
    for i, claim in enumerate(claims or []):
        if not isinstance(claim, dict):
            results.append(_result(f"claim.{i}.invalid", False, "each claim must be an object"))
            continue
        results.append(lab.check_claim(i, claim))
    failed = [r for r in results if r["status"] == "failed"]
    return {
        "passed": not failed,
        "counts": {"total": len(results), "passed": len(results) - len(failed), "failed": len(failed),
                   "claims": len(claims or [])},
        "results": results,
    }
