"""Parse OData EDMX / CSDL metadata (v2 and v4) into a canonical contract.

The canonical contract is plain JSON-serialisable data. It only contains what
is present in the document: nothing is inferred from naming conventions.
Problems found while parsing go to ``issues`` instead of raising, so the agent
always gets a usable answer plus an explicit list of what could not be read.
"""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any

from defusedxml import ElementTree as SafeET
from defusedxml.common import DefusedXmlException

MAX_BYTES = 5 * 1024 * 1024

# EDMX wrapper namespaces
EDMX_V1 = "http://schemas.microsoft.com/ado/2007/06/edmx"
EDMX_V4 = "http://docs.oasis-open.org/odata/ns/edmx"
# CSDL schema namespaces (v2/v3 had several revisions)
EDM_V2 = {
    "http://schemas.microsoft.com/ado/2006/04/edm",
    "http://schemas.microsoft.com/ado/2007/05/edm",
    "http://schemas.microsoft.com/ado/2008/09/edm",
    "http://schemas.microsoft.com/ado/2009/11/edm",
}
EDM_V4 = "http://docs.oasis-open.org/odata/ns/edm"
DATASERVICES_META = "http://schemas.microsoft.com/ado/2007/08/dataservices/metadata"
SAP_V2 = "http://www.sap.com/Protocols/SAPData"

CAPABILITIES_NS = "Org.OData.Capabilities.V1"
CORE_NS = "Org.OData.Core.V1"
SAP_COMMON_NS = "com.sap.vocabularies.Common.v1"


class ContractError(Exception):
    """The file cannot be read as an EDMX document at all."""


def _local(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def _ns(tag: str) -> str:
    return tag[1:].split("}", 1)[0] if tag.startswith("{") else ""


def _bool(value: str | None) -> bool | None:
    if value is None:
        return None
    return value.strip().lower() == "true"


def _int(value: str | None) -> int | str | None:
    if value is None:
        return None
    try:
        return int(value)
    except ValueError:
        return value  # e.g. MaxLength="max", Scale="variable"


def load_bytes(path: Path) -> bytes:
    if not path.is_file():
        raise ContractError(f"not a regular file: {path}")
    size = path.stat().st_size
    if size > MAX_BYTES:
        raise ContractError(f"file is {size} bytes; limit is {MAX_BYTES}")
    return path.read_bytes()


def parse_file(path: str | Path) -> dict[str, Any]:
    path = Path(path)
    data = load_bytes(path)
    contract = parse_bytes(data)
    contract["source"] = {"path": str(path), "sha256": hashlib.sha256(data).hexdigest(), "bytes": len(data)}
    return contract


def parse_bytes(data: bytes) -> dict[str, Any]:
    try:
        root = SafeET.fromstring(data, forbid_dtd=True, forbid_entities=True, forbid_external=True)
    except DefusedXmlException as exc:
        raise ContractError(f"unsafe XML refused: {type(exc).__name__}") from exc
    except SafeET.ParseError as exc:
        raise ContractError(f"not well-formed XML: {exc}") from exc

    if _local(root.tag) != "Edmx":
        raise ContractError(f"root element is <{_local(root.tag)}>, expected <edmx:Edmx>")
    edmx_ns = _ns(root.tag)
    if edmx_ns == EDMX_V1:
        return _Parser(root, family="v2").run()
    if edmx_ns == EDMX_V4:
        return _Parser(root, family="v4").run()
    raise ContractError(f"unknown EDMX namespace: {edmx_ns or '(none)'}")


class _Parser:
    def __init__(self, root, family: str):
        self.root = root
        self.family = family
        self.issues: list[dict[str, str]] = []
        self.aliases: dict[str, str] = {}  # alias -> namespace
        self.entity_types: dict[str, dict[str, Any]] = {}
        self.entity_sets: list[dict[str, Any]] = []
        self.associations: dict[str, dict[str, Any]] = {}
        self.containers: list[str] = []

    # ---------- helpers ----------
    def issue(self, code: str, message: str, severity: str = "warning") -> None:
        self.issues.append({"severity": severity, "code": code, "message": message})

    def qualify(self, name: str | None) -> str | None:
        """Turn 'Alias.Type' into 'Namespace.Type'."""
        if not name:
            return name
        head, _, tail = name.rpartition(".")
        if head in self.aliases:
            return f"{self.aliases[head]}.{tail}"
        return name

    def term(self, term: str) -> str:
        return self.qualify(term) or term

    # ---------- main ----------
    def run(self) -> dict[str, Any]:
        version = self.root.get("Version")
        odata_version = None
        data_services = None
        for child in self.root:
            if _local(child.tag) == "DataServices":
                data_services = child
            elif _local(child.tag) == "Reference":
                for inc in child:
                    if _local(inc.tag) == "Include" and inc.get("Alias"):
                        self.aliases[inc.get("Alias")] = inc.get("Namespace", "")
        if data_services is None:
            raise ContractError("no <edmx:DataServices> element")

        if self.family == "v2":
            odata_version = data_services.get(f"{{{DATASERVICES_META}}}DataServiceVersion") or "2.0"
        else:
            odata_version = version or "4.0"

        schemas = [s for s in data_services if _local(s.tag) == "Schema"]
        if not schemas:
            self.issue("no-schema", "DataServices contains no Schema", "error")
        for schema in schemas:
            ns = schema.get("Namespace", "")
            if schema.get("Alias"):
                self.aliases[schema.get("Alias")] = ns
            self.check_schema_ns(schema)

        # Types first, then containers (sets reference types), then annotations.
        for schema in schemas:
            ns = schema.get("Namespace", "")
            for el in schema:
                kind = _local(el.tag)
                if kind == "EntityType":
                    self.read_entity_type(el, ns)
                elif kind == "Association":
                    self.read_association(el, ns)
        for schema in schemas:
            ns = schema.get("Namespace", "")
            for el in schema:
                if _local(el.tag) == "EntityContainer":
                    self.read_container(el, ns)
        for schema in schemas:
            for el in schema:
                if _local(el.tag) == "Annotations":
                    self.read_external_annotations(el)

        self.resolve_v2_navigations()

        return {
            "format": "edmx",
            "family": self.family,
            "edmx_version": version,
            "odata_version": odata_version,
            "namespaces": [s.get("Namespace", "") for s in schemas],
            "aliases": self.aliases,
            "containers": self.containers,
            "entity_types": self.entity_types,
            "entity_sets": self.entity_sets,
            "associations": self.associations,
            "issues": self.issues,
            "summary": {
                "entity_types": len(self.entity_types),
                "entity_sets": len(self.entity_sets),
                "navigations": sum(len(t["navigations"]) for t in self.entity_types.values()),
                "associations": len(self.associations),
            },
        }

    def check_schema_ns(self, schema) -> None:
        ns = _ns(schema.tag)
        if self.family == "v2" and ns not in EDM_V2:
            self.issue("schema-namespace", f"v2 EDMX with unexpected Schema namespace {ns}")
        if self.family == "v4" and ns != EDM_V4:
            self.issue("schema-namespace", f"v4 EDMX with unexpected Schema namespace {ns}")

    # ---------- entity types ----------
    def read_entity_type(self, el, ns: str) -> None:
        name = el.get("Name", "")
        fq = f"{ns}.{name}"
        keys: list[str] = []
        props: list[dict[str, Any]] = []
        navs: list[dict[str, Any]] = []
        for child in el:
            kind = _local(child.tag)
            if kind == "Key":
                keys = [ref.get("Name", "") for ref in child if _local(ref.tag) == "PropertyRef"]
            elif kind == "Property":
                props.append(self.read_property(child))
            elif kind == "NavigationProperty":
                navs.append(self.read_navigation(child))
        if el.get("BaseType"):
            self.issue("base-type", f"{fq} derives from {el.get('BaseType')}; inherited members are not merged")
        self.entity_types[fq] = {
            "name": name,
            "namespace": ns,
            "keys": keys,
            "properties": props,
            "navigations": navs,
            "label": el.get(f"{{{SAP_V2}}}label"),
        }

    def read_property(self, el) -> dict[str, Any]:
        prop: dict[str, Any] = {
            "name": el.get("Name", ""),
            "type": self.qualify(el.get("Type")),
            "nullable": _bool(el.get("Nullable")) if el.get("Nullable") is not None else True,
            "max_length": _int(el.get("MaxLength")),
            "precision": _int(el.get("Precision")),
            "scale": _int(el.get("Scale")),
            "label": None,
            "creatable": None,
            "updatable": None,
            "annotation_source": None,
        }
        if self.family == "v2":
            prop["label"] = el.get(f"{{{SAP_V2}}}label")
            prop["creatable"] = _bool(el.get(f"{{{SAP_V2}}}creatable"))
            prop["updatable"] = _bool(el.get(f"{{{SAP_V2}}}updatable"))
            if prop["creatable"] is not None or prop["updatable"] is not None:
                prop["annotation_source"] = "sap:v2-attributes"
        else:
            for ann in el:
                if _local(ann.tag) == "Annotation":
                    self.apply_property_annotation(prop, ann)
        return prop

    def apply_property_annotation(self, prop: dict[str, Any], ann) -> None:
        term = self.term(ann.get("Term", ""))
        flag = _bool(ann.get("Bool")) if ann.get("Bool") is not None else True
        if term == f"{CORE_NS}.Computed" and flag:
            prop["creatable"] = False
            prop["updatable"] = False
            prop["annotation_source"] = "Core.Computed"
        elif term == f"{CORE_NS}.Immutable" and flag:
            prop["updatable"] = False
            prop["annotation_source"] = prop["annotation_source"] or "Core.Immutable"
        elif term == f"{SAP_COMMON_NS}.Label":
            prop["label"] = ann.get("String")

    def read_navigation(self, el) -> dict[str, Any]:
        nav: dict[str, Any] = {"name": el.get("Name", "")}
        if self.family == "v2":
            nav.update(
                via="association",
                relationship=self.qualify(el.get("Relationship")),
                from_role=el.get("FromRole"),
                to_role=el.get("ToRole"),
                target_type=None,  # filled by resolve_v2_navigations
                multiplicity=None,
            )
        else:
            raw = el.get("Type", "")
            is_coll = raw.startswith("Collection(") and raw.endswith(")")
            inner = raw[len("Collection("):-1] if is_coll else raw
            nullable = el.get("Nullable")
            nav.update(
                via="type",
                target_type=self.qualify(inner),
                multiplicity="*" if is_coll else ("1" if nullable == "false" else "0..1"),
                partner=el.get("Partner"),
            )
        return nav

    # ---------- v2 associations ----------
    def read_association(self, el, ns: str) -> None:
        fq = f"{ns}.{el.get('Name', '')}"
        ends = {}
        for child in el:
            if _local(child.tag) == "End":
                ends[child.get("Role", "")] = {
                    "type": self.qualify(child.get("Type")),
                    "multiplicity": child.get("Multiplicity"),
                }
        self.associations[fq] = {"ends": ends}

    def resolve_v2_navigations(self) -> None:
        if self.family != "v2":
            return
        for type_name, et in self.entity_types.items():
            for nav in et["navigations"]:
                assoc = self.associations.get(nav.get("relationship") or "")
                if assoc is None:
                    self.issue(
                        "unresolved-association",
                        f"{type_name}/{nav['name']} references association {nav.get('relationship')} which is not defined",
                    )
                    continue
                end = assoc["ends"].get(nav.get("to_role") or "")
                if end is None:
                    self.issue("unresolved-role", f"{type_name}/{nav['name']} ToRole {nav.get('to_role')} not in association")
                    continue
                nav["target_type"] = end["type"]
                nav["multiplicity"] = end["multiplicity"]

    # ---------- containers ----------
    def read_container(self, el, ns: str) -> None:
        cname = el.get("Name", "")
        self.containers.append(f"{ns}.{cname}")
        for child in el:
            if _local(child.tag) != "EntitySet":
                continue
            es: dict[str, Any] = {
                "name": child.get("Name", ""),
                "container": f"{ns}.{cname}",
                "entity_type": self.qualify(child.get("EntityType")),
                "creatable": None,
                "updatable": None,
                "deletable": None,
                "capability_source": None,
                "navigation_bindings": {},
            }
            if self.family == "v2":
                for attr in ("creatable", "updatable", "deletable"):
                    es[attr] = _bool(child.get(f"{{{SAP_V2}}}{attr}"))
                # State-dependent restrictions: a Boolean property decides per record.
                for attr in ("updatable", "deletable"):
                    path = child.get(f"{{{SAP_V2}}}{attr}-path")
                    if path:
                        es[f"{attr}_path"] = path
                if _bool(child.get(f"{{{SAP_V2}}}requires-filter")):
                    es["requires_filter"] = True
                if any(es[a] is not None for a in ("creatable", "updatable", "deletable")) or \
                        es.get("updatable_path") or es.get("deletable_path"):
                    es["capability_source"] = "sap:v2-attributes"
            else:
                for sub in child:
                    kind = _local(sub.tag)
                    if kind == "NavigationPropertyBinding":
                        es["navigation_bindings"][sub.get("Path", "")] = sub.get("Target")
                    elif kind == "Annotation":
                        self.apply_set_annotation(es, sub)
            self.entity_sets.append(es)

    def apply_set_annotation(self, es: dict[str, Any], ann) -> None:
        term = self.term(ann.get("Term", ""))
        mapping = {
            f"{CAPABILITIES_NS}.InsertRestrictions": ("Insertable", "creatable"),
            f"{CAPABILITIES_NS}.UpdateRestrictions": ("Updatable", "updatable"),
            f"{CAPABILITIES_NS}.DeleteRestrictions": ("Deletable", "deletable"),
        }
        if term not in mapping:
            return
        prop_name, field = mapping[term]
        for record in ann:
            if _local(record.tag) != "Record":
                continue
            for pv in record:
                if _local(pv.tag) == "PropertyValue" and pv.get("Property") == prop_name:
                    es[field] = _bool(pv.get("Bool"))
                    es["capability_source"] = "Capabilities vocabulary"

    def read_external_annotations(self, el) -> None:
        target = el.get("Target", "")
        # Targets look like 'Namespace.Container/EntitySet' (alias allowed).
        container, _, set_name = target.partition("/")
        container = self.qualify(container)
        anns = [a for a in el if _local(a.tag) == "Annotation"]
        if not set_name:
            return
        for es in self.entity_sets:
            if es["name"] == set_name and es["container"] == container:
                for ann in anns:
                    self.apply_set_annotation(es, ann)
                return
        # A target that is a property path (Type/Prop) is applied to properties.
        type_name = self.qualify(container)
        et = self.entity_types.get(type_name or "")
        if et is not None:
            for prop in et["properties"]:
                if prop["name"] == set_name:
                    for ann in anns:
                        self.apply_property_annotation(prop, ann)
                    return
        self.issue("unresolved-annotation-target", f"Annotations target {target} not found")
