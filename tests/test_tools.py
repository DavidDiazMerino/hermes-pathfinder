import json
import shutil
import socket

import pytest

from pathfinder import tools
from conftest import FIXTURES


def call(fn, rt, **args):
    out = fn(args, rt)
    assert isinstance(out, str)  # Hermes tools must return JSON strings
    return json.loads(out)


def test_sources_sap(runtime):
    r = call(tools.sources, runtime, domain="sap")
    assert r["ok"] and r["domain"] == "sap"
    assert r["ask_first"], "orientation questions expected without a product"
    assert any(s["url"] == "https://api.sap.com/" for s in r["sources"])
    assert {p["status"] for p in r["pitfalls"]} <= {"documented", "practitioner"}
    assert "fixture:sap/business_partner_v2" in [s["ref"] for s in r["sample_contracts"]]


def test_sources_product_filter(runtime):
    r = call(tools.sources, runtime, domain="sap", product="ecc")
    assert [p["id"] for p in r["products"]] == ["ecc"]
    assert r["ask_first"] == []


def test_sources_unknown_domain(runtime):
    r = call(tools.sources, runtime, domain="oracle")
    assert not r["ok"] and "sap" in r["available_domains"]


def test_inspect_fixture_records_run(runtime):
    r = call(tools.inspect, runtime, contract="fixture:sap/business_partner_v2")
    assert r["ok"] and r["family"] == "v2" and r["run_id"].startswith("pf-")
    run = runtime.ledger().get_run(r["run_id"])
    assert run["source_kind"] == "fixture" and run["source_sha256"] == r["source"]["sha256"]
    assert runtime.ledger().load_contract(r["run_id"])["summary"]["entity_types"] == 3


def test_inspect_compact_view(runtime):
    r = call(tools.inspect, runtime, contract="fixture:sap/business_partner_v2")
    sets = {s["name"]: s for s in r["entity_sets"]}
    assert sets["A_BusinessPartner"]["ops"] == "CRU-"
    assert sets["A_BusinessPartnerRole"]["ops"] == "CR-D"
    bp = r["entity_types"]["A_BusinessPartnerType"]
    assert "BusinessPartner: Edm.String(10) [key, not-null, not-updatable] \"Business Partner\"" in bp["properties"]
    assert "to_BusinessPartnerAddress -> A_BusinessPartnerAddressType [*] via association" in bp["navigations"]


def test_inspect_v4_focus_by_entity_set(runtime):
    r = call(tools.inspect, runtime, contract="fixture:sap/product_v4", entity="ProductPlant")
    assert list(r["entity_types"]) == ["ProductPlantType"]
    assert {s["name"]: s["ops"] for s in r["entity_sets"]}["ProductPlant"] == "-RU-"


def test_inspect_relative_path_uses_session_cwd(runtime, tmp_path):
    shutil.copy(FIXTURES / "product_v4.xml", tmp_path / "metadata.xml")
    r = call(tools.inspect, runtime, contract="metadata.xml")
    assert r["ok"] and r["source"]["kind"] == "local_file"


def test_inspect_errors_are_json(runtime):
    assert call(tools.inspect, runtime)["ok"] is False
    assert "not a regular file" in call(tools.inspect, runtime, contract="nope.xml")["error"]
    assert call(tools.inspect, runtime, contract="fixture:sap/missing")["ok"] is False
    r = call(tools.inspect, runtime, contract="fixture:sap/product_v4", entity="Nope")
    assert r["ok"] is False and "ProductType" in r["entity_types"]


def test_large_service_lists_names_only(runtime, monkeypatch):
    monkeypatch.setattr(tools, "OVERVIEW_TYPE_LIMIT", 2)
    r = call(tools.inspect, runtime, contract="fixture:sap/product_v4")
    assert isinstance(r["entity_types"], list) and "hint" in r


def test_no_network(runtime, monkeypatch):
    def refuse(*a, **k):
        raise AssertionError("network access attempted")
    monkeypatch.setattr(socket, "socket", refuse)
    monkeypatch.setattr(socket, "create_connection", refuse)
    call(tools.sources, runtime, domain="sap")
    call(tools.inspect, runtime, contract="fixture:sap/business_partner_v2")
    call(tools.inspect, runtime, contract="fixture:sap/product_v4")


def test_v2_state_dependent_restrictions(runtime, tmp_path):
    doc = """<edmx:Edmx Version="1.0" xmlns:edmx="http://schemas.microsoft.com/ado/2007/06/edmx"
      xmlns:sap="http://www.sap.com/Protocols/SAPData">
      <edmx:DataServices><Schema Namespace="N" xmlns="http://schemas.microsoft.com/ado/2008/09/edm">
        <EntityType Name="Order"><Key><PropertyRef Name="Id"/></Key>
          <Property Name="Id" Type="Edm.String" Nullable="false"/>
          <Property Name="IsOpen" Type="Edm.Boolean"/></EntityType>
        <EntityContainer Name="C">
          <EntitySet Name="Orders" EntityType="N.Order" sap:updatable-path="IsOpen" sap:requires-filter="true"/>
        </EntityContainer>
      </Schema></edmx:DataServices></edmx:Edmx>"""
    (tmp_path / "orders.xml").write_text(doc)
    r = call(tools.inspect, runtime, contract="orders.xml")
    es = r["entity_sets"][0]
    assert es["ops"] == "CRuD"
    assert es["updatable_path"] == "IsOpen" and es["requires_filter"] is True


def test_sources_topic_filter_and_checks(runtime):
    r = call(tools.sources, runtime, domain="sap", topic="policy")
    assert r["ok"] and r["sources"] and {s["topic"] for s in r["sources"]} == {"policy"}
    assert any("API_Policy_latest.pdf" in s["url"] for s in r["sources"])
    assert r["governed_paths"]["paths"]
    assert call(tools.sources, runtime, domain="sap", topic="nope")["ok"] is False


def test_pack_sources_are_well_formed():
    from pathfinder import packs
    pack = packs.load("sap")
    ids = [s["id"] for s in pack["sources"]]
    assert len(ids) == len(set(ids))
    for s in pack["sources"]:
        assert s["topic"] in pack["source_topics"], s["id"]
        assert s["check"] in pack["check_legend"], s["id"]
        assert s["url"].startswith("https://"), s["id"]
    known = set(ids)
    for path in pack["governed_paths"]["paths"]:
        assert path["source"] in known
    for p in pack["pitfalls"]:
        assert p["status"] in ("documented", "practitioner")
        if p["status"] == "documented":
            assert p.get("source", "").startswith("https://"), p["id"]


def test_inspect_multiple_entities_in_one_call(runtime):
    r = call(tools.inspect, runtime, contract="fixture:sap/business_partner_v2",
             entity="A_BusinessPartnerAddress, A_BusinessPartnerRoleType, Nope")
    assert set(r["entity_types"]) == {"A_BusinessPartnerAddressType", "A_BusinessPartnerRoleType"}
    assert {s["name"] for s in r["entity_sets"]} == {"A_BusinessPartnerAddress", "A_BusinessPartnerRole"}
    assert r["not_found"] == ["Nope"]
