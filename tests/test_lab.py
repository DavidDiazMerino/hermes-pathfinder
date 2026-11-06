import json

import pytest

from pathfinder import edmx, lab, tools
from conftest import FIXTURES


@pytest.fixture(scope="module")
def v2():
    return edmx.parse_file(FIXTURES / "business_partner_v2.edmx")


@pytest.fixture(scope="module")
def v4():
    return edmx.parse_file(FIXTURES / "product_v4.xml")


def one(contract, claim):
    out = lab.run(contract, [claim])
    return out["results"][-1]


# ---------------- integrity
def test_integrity_passes_on_both_fixtures(v2, v4):
    for c in (v2, v4):
        out = lab.run(c, [])
        assert out["passed"], out["results"]
        assert out["counts"]["claims"] == 0


def test_integrity_catches_unresolved_navigation():
    doc = b"""<edmx:Edmx Version="4.0" xmlns:edmx="http://docs.oasis-open.org/odata/ns/edmx"><edmx:DataServices>
      <Schema Namespace="N" xmlns="http://docs.oasis-open.org/odata/ns/edm">
        <EntityType Name="A"><Key><PropertyRef Name="Id"/></Key><Property Name="Id" Type="Edm.String"/>
          <NavigationProperty Name="_B" Type="N.Missing"/></EntityType>
      </Schema></edmx:DataServices></edmx:Edmx>"""
    out = lab.run(edmx.parse_bytes(doc), [])
    failed = {r["id"] for r in out["results"] if r["status"] == "failed"}
    assert failed == {"contract.navigation_resolves"}


# ---------------- claims
def test_key_claims(v2):
    assert one(v2, {"type": "keys", "entity_set": "A_BusinessPartnerAddress",
                    "expect": ["AddressID", "BusinessPartner"]})["status"] == "passed"
    r = one(v2, {"type": "keys", "entity_set": "A_BusinessPartnerAddress", "expect": ["AddressID"]})
    assert r["status"] == "failed" and "BusinessPartner" in r["detail"]


def test_operation_claims_v2_and_v4(v2, v4):
    assert one(v2, {"type": "operation", "entity_set": "A_BusinessPartner", "op": "delete", "expect": False})["status"] == "passed"
    assert one(v2, {"type": "operation", "entity_set": "A_BusinessPartnerRole", "op": "update", "expect": True})["status"] == "failed"
    # V4: restriction only in an external <Annotations> block
    assert one(v4, {"type": "operation", "entity_set": "ProductPlant", "op": "create", "expect": False})["status"] == "passed"
    # V4: nothing stated -> allowed by default
    assert one(v4, {"type": "operation", "entity_set": "ProductDescription", "op": "delete", "expect": True})["status"] == "passed"


def test_navigation_claims(v2, v4):
    assert one(v2, {"type": "navigation", "entity_type": "A_BusinessPartnerType", "name": "to_BusinessPartnerRole",
                    "target": "A_BusinessPartnerRoleType", "multiplicity": "*"})["status"] == "passed"
    assert one(v4, {"type": "navigation", "entity_set": "ProductPlant", "name": "_Product",
                    "multiplicity": "0..1"})["status"] == "failed"
    assert one(v4, {"type": "navigation", "entity_set": "Product", "name": "_Nope",
                    "expect_exists": False})["status"] == "passed"


def test_required_fields(v2, v4):
    # AddressID is Nullable=false but sap:creatable=false: the server assigns it.
    assert one(v2, {"type": "required_fields", "entity_set": "A_BusinessPartnerAddress",
                    "expect": ["BusinessPartner", "Country"]})["status"] == "passed"
    assert one(v4, {"type": "required_fields", "entity_set": "Product",
                    "expect": ["Product", "ProductType", "BaseUnit"]})["status"] == "passed"


def test_unknown_target_and_type_fail_cleanly(v2):
    assert one(v2, {"type": "keys", "entity_set": "Nope", "expect": []})["status"] == "failed"
    assert one(v2, {"type": "guess"})["status"] == "failed"
    assert lab.run(v2, ["not a dict"])["passed"] is False


# ---------------- payloads
BP_OK = {"BusinessPartner": "1000042", "BusinessPartnerCategory": "1", "FirstName": "Ada", "LastName": "Lovelace"}


@pytest.mark.parametrize("payload,expect,needle", [
    (BP_OK, "valid", None),
    ({k: v for k, v in BP_OK.items() if k != "BusinessPartnerCategory"}, "invalid", "BusinessPartnerCategory: required"),
    ({**BP_OK, "FirstName": "x" * 41}, "invalid", "exceeds MaxLength 40"),
    ({**BP_OK, "CreatedByUser": "ME"}, "invalid", "not creatable"),
    ({**BP_OK, "IsMarkedForArchiving": "false"}, "invalid", "expected true/false"),
    ({**BP_OK, "Colour": "blue"}, "invalid", "not a property"),
    ({**BP_OK, "to_BusinessPartnerAddress": {"results": [{"BusinessPartner": "1000042", "Country": "ES", "CityName": "Madrid"}]}}, "valid", None),
    ({**BP_OK, "to_BusinessPartnerAddress": [{"BusinessPartner": "1000042", "CityName": "Madrid"}]}, "invalid", "Country: required"),
    ({**BP_OK, "to_BusinessPartnerAddress": {"BusinessPartner": "1"}}, "invalid", "expects a list"),
])
def test_v2_create_payloads(v2, payload, expect, needle):
    r = one(v2, {"type": "payload", "entity_set": "A_BusinessPartner", "payload": payload, "expect": expect})
    assert r["status"] == "passed", r
    if needle:
        assert any(needle in v for v in r["violations"]), r["violations"]


def test_v2_update_rules(v2):
    r = one(v2, {"type": "payload", "entity_set": "A_BusinessPartner", "operation": "update",
                 "payload": {"BusinessPartner": "1", "FirstName": "Ada"}, "expect": "invalid"})
    assert r["status"] == "passed" and any("not updatable" in v for v in r["violations"])
    r = one(v2, {"type": "payload", "entity_set": "A_BusinessPartnerRole", "operation": "update",
                 "payload": {"ValidTo": "2030-01-01T00:00:00Z"}, "expect": "invalid"})
    assert any("does not allow update" in v for v in r["violations"])


def test_v4_payloads(v4):
    ok = {"Product": "P-100", "ProductType": "FERT", "BaseUnit": "PC", "GrossWeight": "12.345"}
    assert one(v4, {"type": "payload", "entity_set": "Product", "payload": ok, "expect": "valid"})["status"] == "passed"
    r = one(v4, {"type": "payload", "entity_set": "Product", "payload": {**ok, "GrossWeight": "1.2345"}, "expect": "invalid"})
    assert any("exceed Scale 3" in v for v in r["violations"])
    r = one(v4, {"type": "payload", "entity_set": "Product", "payload": {**ok, "GrossWeight": 12345678901.0}, "expect": "invalid"})
    assert any("Precision" in v for v in r["violations"])
    r = one(v4, {"type": "payload", "entity_set": "Product",
                 "payload": {**ok, "CreationDateTime": "2026-11-06T10:00:00Z"}, "expect": "invalid"})
    assert any("not creatable" in v for v in r["violations"])  # Core.Computed
    r = one(v4, {"type": "payload", "entity_set": "ProductPlant",
                 "payload": {"Product": "P-100", "Plant": "1010"}, "expect": "invalid"})
    assert any("does not allow create" in v for v in r["violations"])  # external Capabilities annotation


def test_wrong_expectation_fails_the_claim(v2):
    r = one(v2, {"type": "payload", "entity_set": "A_BusinessPartner",
                 "payload": {"FirstName": "Ada"}, "expect": "valid"})
    assert r["status"] == "failed" and r["violations"]


def test_deterministic(v4):
    claims = [{"type": "payload", "entity_set": "Product", "payload": {"Product": "X"}, "expect": "invalid"}]
    assert json.dumps(lab.run(v4, claims), sort_keys=True) == json.dumps(lab.run(v4, claims), sort_keys=True)


# ---------------- tool + ledger
def call(fn, rt, **args):
    return json.loads(fn(args, rt))


def test_lab_tool_and_evidence_status(runtime):
    run_id = call(tools.inspect, runtime, contract="fixture:sap/business_partner_v2")["run_id"]
    led = runtime.ledger()
    assert led.evidence_status(run_id)["status"] == "inspected"

    r = call(tools.lab, runtime, run_id=run_id)
    assert r["passed"] and r["evidence_status"] == "inspected"  # no claims tested yet

    r = call(tools.lab, runtime, run_id=run_id, claims=[
        {"type": "keys", "entity_set": "A_BusinessPartner", "expect": ["Wrong"]}])
    assert not r["passed"] and r["evidence_status"] == "failed" and r["failed"]

    r = call(tools.lab, runtime, run_id=run_id, claims=[
        {"type": "keys", "entity_set": "A_BusinessPartner", "expect": ["BusinessPartner"]}])
    assert r["passed"] and r["evidence_status"] == "verified" and r["lab_id"].endswith("/lab3")


def test_lab_tool_errors(runtime):
    assert call(tools.lab, runtime)["ok"] is False
    assert call(tools.lab, runtime, run_id="pf-nope")["ok"] is False
    run_id = call(tools.inspect, runtime, contract="fixture:sap/product_v4")["run_id"]
    assert call(tools.lab, runtime, run_id=run_id, claims="nope")["ok"] is False
