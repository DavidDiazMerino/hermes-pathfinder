"""Generate a large synthetic OData V4 $metadata with SAP-like size and annotation density, plus the
ground truth for a set of target entity sets. Ground truth comes from construction, not from the
plugin's parser. Deterministic for a given seed.

    python eval/gen_large.py OUT_DIR [--seed 7] [--types 48]
"""

from __future__ import annotations

import argparse
import json
import random
from pathlib import Path
from xml.sax.saxutils import quoteattr

NS = "pathfinder.sample.largeservice.v0001"
ALIAS = "SVC"
WORDS = ("Order Item Partner Plant Material Batch Delivery Invoice Payment Contract Schedule Price Tax Text "
         "Address Contact Bank Account Cost Center Profit Asset Equipment Notice Task Project Stock "
         "Handling Unit Shipment Route Quota Commission Claim Warranty Serial Revision Document").split()
FIELD_WORDS = ("Code Type Status Category Group Indicator Date Amount Currency Quantity Unit Weight Volume "
               "Region Country City Street Postal Language Description Name Reason Priority Version Number "
               "Owner Responsible Organization Division Channel Area Level Class Flag Reference").split()
CORE = "Org.OData.Core.V1"
CAP = "Org.OData.Capabilities.V1"


def build(seed: int, n_types: int):
    rnd = random.Random(seed)
    names = []
    while len(names) < n_types:
        n = "".join(rnd.sample(WORDS, 2))
        if n not in names:
            names.append(n)
    types = {}
    # Parents are the first third; every other type is a child of one parent (composite key).
    parents = names[: n_types // 3]
    for i, name in enumerate(names):
        parent = None if name in parents else parents[i % len(parents)]
        keys = [f"{name}ID"] if parent is None else [f"{parent}ID", f"{name}ID"]
        props = []
        for k in keys:
            props.append({"name": k, "type": "Edm.String", "max": 10, "nullable": False,
                          "computed": (k == keys[-1] and rnd.random() < 0.4), "immutable": k != keys[-1]})
        used = set(keys)
        for _ in range(rnd.randint(25, 60)):
            fname = "".join(rnd.sample(FIELD_WORDS, 2))
            if fname in used:
                continue
            used.add(fname)
            t = rnd.choice(["Edm.String"] * 5 + ["Edm.Decimal", "Edm.Date", "Edm.DateTimeOffset", "Edm.Boolean", "Edm.Int32"])
            props.append({"name": fname, "type": t, "max": rnd.choice([1, 2, 3, 4, 10, 20, 40, 80]) if t == "Edm.String" else None,
                          "nullable": rnd.random() > 0.12, "computed": rnd.random() < 0.08, "immutable": False})
        for audit in ("CreatedByUser", "CreationDateTime", "LastChangedByUser", "LastChangeDateTime"):
            props.append({"name": audit, "type": "Edm.DateTimeOffset" if "Time" in audit else "Edm.String",
                          "max": None if "Time" in audit else 12, "nullable": rnd.random() < 0.5, "computed": True,
                          "immutable": False})
        types[name] = {"keys": keys, "props": props, "parent": parent, "navs": {}}
    for name, t in types.items():
        if t["parent"]:
            p = t["parent"]
            types[p]["navs"][f"_{name}"] = (name, True)
            t["navs"][f"_{p}"] = (p, False)
    # Restrictions: some inline on the set, some in a far-away external <Annotations> block.
    caps = {}
    for name in names:
        c = {"create": True, "update": True, "delete": True, "where": None}
        roll = rnd.random()
        if roll < 0.2:
            c.update(create=False, where="external")
        elif roll < 0.35:
            c.update(delete=False, where="inline")
        elif roll < 0.45:
            c.update(update=False, delete=False, where="external")
        caps[name] = c
    return names, types, caps


def render(names, types, caps) -> str:
    out = ['<?xml version="1.0" encoding="utf-8"?>',
           "<!-- SYNTHETIC large test contract for Hermes Pathfinder evaluation. Not a real SAP service. -->",
           '<edmx:Edmx Version="4.0" xmlns:edmx="http://docs.oasis-open.org/odata/ns/edmx">']
    for ns, alias in ((CORE, "Core"), (CAP, "Capabilities"), ("com.sap.vocabularies.Common.v1", "Common")):
        out.append(f'  <edmx:Reference Uri="https://example.invalid/{ns}.xml"><edmx:Include Namespace="{ns}" Alias="{alias}"/></edmx:Reference>')
    out.append(f'  <edmx:DataServices><Schema Namespace="{NS}" Alias="{ALIAS}" xmlns="http://docs.oasis-open.org/odata/ns/edm">')
    for name in names:
        t = types[name]
        out.append(f'    <EntityType Name="{name}Type"><Key>' + "".join(f'<PropertyRef Name="{k}"/>' for k in t["keys"]) + "</Key>")
        for p in t["props"]:
            attrs = f'Name="{p["name"]}" Type="{p["type"]}"'
            if not p["nullable"]:
                attrs += ' Nullable="false"'
            if p["max"]:
                attrs += f' MaxLength="{p["max"]}"'
            if p["type"] == "Edm.Decimal":
                attrs += ' Precision="15" Scale="3"'
            label = quoteattr(" ".join(p["name"][i:i + 6] for i in range(0, len(p["name"]), 6)))
            inner = f'<Annotation Term="Common.Label" String={label}/><Annotation Term="Common.QuickInfo" String={label}/>'
            if p["computed"]:
                inner += '<Annotation Term="Core.Computed"/>'
            if p["immutable"]:
                inner += '<Annotation Term="Core.Immutable"/>'
            out.append(f"      <Property {attrs}>{inner}</Property>")
        for nav, (target, many) in t["navs"].items():
            typ = f"Collection({ALIAS}.{target}Type)" if many else f"{ALIAS}.{target}Type"
            extra = "" if many else ' Nullable="false"'
            out.append(f'      <NavigationProperty Name="{nav}" Type="{typ}"{extra}/>')
        out.append("    </EntityType>")
    out.append('    <EntityContainer Name="Container">')
    for name in names:
        t, c = types[name], caps[name]
        out.append(f'      <EntitySet Name="{name}" EntityType="{ALIAS}.{name}Type">')
        for nav, (target, _) in t["navs"].items():
            out.append(f'        <NavigationPropertyBinding Path="{nav}" Target="{target}"/>')
        if c["where"] == "inline":
            out.append('        <Annotation Term="Capabilities.DeleteRestrictions"><Record><PropertyValue Property="Deletable" Bool="false"/></Record></Annotation>')
        out.append("      </EntitySet>")
    out.append("    </EntityContainer>")
    for name in names:
        c = caps[name]
        if c["where"] != "external":
            continue
        out.append(f'    <Annotations Target="{ALIAS}.Container/{name}">')
        if not c["create"]:
            out.append('      <Annotation Term="Capabilities.InsertRestrictions"><Record><PropertyValue Property="Insertable" Bool="false"/></Record></Annotation>')
        if not c["update"]:
            out.append('      <Annotation Term="Capabilities.UpdateRestrictions"><Record><PropertyValue Property="Updatable" Bool="false"/></Record></Annotation>')
        if not c["delete"]:
            out.append('      <Annotation Term="Capabilities.DeleteRestrictions"><Record><PropertyValue Property="Deletable" Bool="false"/></Record></Annotation>')
        out.append("    </Annotations>")
    out.append("  </Schema></edmx:DataServices>\n</edmx:Edmx>\n")
    return "\n".join(out)


def truth(names, types, caps, targets):
    sets = {}
    for name in targets:
        t, c = types[name], caps[name]
        sets[name] = {
            "keys": t["keys"], "create": c["create"], "update": c["update"], "delete": c["delete"],
            "required_on_create": [p["name"] for p in t["props"] if not p["nullable"] and not p["computed"]],
            "navigations": {nav: {"target": f"{tg}Type", "many": many} for nav, (tg, many) in t["navs"].items()},
        }
    return {"_note": "Ground truth from the generator's construction (eval/gen_large.py).", "entity_sets": sets}


def pick_targets(names, types, caps, rnd, k=6):
    """Prefer the hard cases: external restrictions, computed keys, children with composite keys."""
    hard = [n for n in names if caps[n]["where"] == "external"]
    computed_key = [n for n in names if types[n]["props"][len(types[n]["keys"]) - 1]["computed"]]
    pool = list(dict.fromkeys(hard[:3] + computed_key[:2] + names))
    return pool[:k]


def generate(out_dir: Path, seed: int = 7, n_types: int = 48):
    names, types, caps = build(seed, n_types)
    targets = pick_targets(names, types, caps, random.Random(seed + 1))
    out_dir.mkdir(parents=True, exist_ok=True)
    xml = render(names, types, caps)
    (out_dir / "large_v4.xml").write_text(xml, encoding="utf-8")
    exp = truth(names, types, caps, targets)
    (out_dir / "large_v4.expected.json").write_text(json.dumps(exp, indent=1), encoding="utf-8")
    return out_dir / "large_v4.xml", exp, targets


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("out_dir")
    ap.add_argument("--seed", type=int, default=7)
    ap.add_argument("--types", type=int, default=48)
    a = ap.parse_args()
    path, exp, targets = generate(Path(a.out_dir), a.seed, a.types)
    print(path, path.stat().st_size, "bytes; targets:", targets)
