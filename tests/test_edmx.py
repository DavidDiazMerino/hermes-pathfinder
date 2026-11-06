import pytest

from pathfinder import edmx
from conftest import FIXTURES

BP = "PATHFINDER_SAMPLE_BP_SRV"
PR = "pathfinder.sample.product.v0001"


@pytest.fixture(scope="module")
def v2():
    return edmx.parse_file(FIXTURES / "business_partner_v2.edmx")


@pytest.fixture(scope="module")
def v4():
    return edmx.parse_file(FIXTURES / "product_v4.xml")


def props(contract, type_name):
    return {p["name"]: p for p in contract["entity_types"][type_name]["properties"]}


def sets(contract):
    return {es["name"]: es for es in contract["entity_sets"]}


# ---------------- v2
def test_v2_version_and_clean(v2):
    assert v2["family"] == "v2"
    assert v2["odata_version"] == "2.0"
    assert v2["issues"] == []
    assert v2["summary"] == {"entity_types": 3, "entity_sets": 3, "navigations": 2, "associations": 2}


def test_v2_composite_key(v2):
    assert v2["entity_types"][f"{BP}.A_BusinessPartnerAddressType"]["keys"] == ["BusinessPartner", "AddressID"]


def test_v2_navigation_resolved_through_association(v2):
    navs = {n["name"]: n for n in v2["entity_types"][f"{BP}.A_BusinessPartnerType"]["navigations"]}
    nav = navs["to_BusinessPartnerAddress"]
    assert nav["via"] == "association"
    assert nav["target_type"] == f"{BP}.A_BusinessPartnerAddressType"
    assert nav["multiplicity"] == "*"


def test_v2_property_facets_and_sap_flags(v2):
    p = props(v2, f"{BP}.A_BusinessPartnerType")
    assert p["BusinessPartner"]["max_length"] == 10 and p["BusinessPartner"]["nullable"] is False
    assert p["CreationDate"]["creatable"] is False and p["CreationDate"]["updatable"] is False
    assert p["FirstName"]["creatable"] is None  # not stated in the contract: unknown, not "true"
    assert p["FirstName"]["label"] == "First Name"


def test_v2_entity_set_capabilities(v2):
    s = sets(v2)
    assert (s["A_BusinessPartner"]["creatable"], s["A_BusinessPartner"]["deletable"]) == (True, False)
    assert s["A_BusinessPartnerRole"]["updatable"] is False
    assert s["A_BusinessPartnerRole"]["capability_source"] == "sap:v2-attributes"


# ---------------- v4
def test_v4_version_and_clean(v4):
    assert v4["family"] == "v4"
    assert v4["odata_version"] == "4.0"
    assert v4["issues"] == []
    assert v4["associations"] == {}


def test_v4_alias_resolution(v4):
    assert sets(v4)["Product"]["entity_type"] == f"{PR}.ProductType"
    assert v4["aliases"]["Capabilities"] == "Org.OData.Capabilities.V1"


def test_v4_navigation_by_type(v4):
    navs = {n["name"]: n for n in v4["entity_types"][f"{PR}.ProductType"]["navigations"]}
    assert navs["_ProductPlant"]["via"] == "type"
    assert navs["_ProductPlant"]["target_type"] == f"{PR}.ProductPlantType"
    assert navs["_ProductPlant"]["multiplicity"] == "*"
    back = v4["entity_types"][f"{PR}.ProductPlantType"]["navigations"][0]
    assert back["multiplicity"] == "1" and back["partner"] == "_ProductPlant"


def test_v4_core_annotations(v4):
    p = props(v4, f"{PR}.ProductType")
    assert p["CreationDateTime"]["creatable"] is False and p["CreationDateTime"]["annotation_source"] == "Core.Computed"
    assert p["GrossWeight"]["precision"] == 13 and p["GrossWeight"]["scale"] == 3
    assert p["Product"]["label"] == "Product"
    plant = props(v4, f"{PR}.ProductPlantType")
    assert plant["Plant"]["updatable"] is False and plant["Plant"]["creatable"] is None


def test_v4_capabilities_inline_and_external(v4):
    s = sets(v4)
    assert s["Product"]["deletable"] is False          # inline annotation
    assert s["ProductPlant"]["creatable"] is False     # external <Annotations Target=...>
    assert s["ProductDescription"]["capability_source"] is None


def test_hash_is_stable():
    a = edmx.parse_file(FIXTURES / "product_v4.xml")["source"]["sha256"]
    b = edmx.parse_file(FIXTURES / "product_v4.xml")["source"]["sha256"]
    assert a == b and len(a) == 64


# ---------------- robustness
def test_rejects_entity_expansion():
    bomb = b'<?xml version="1.0"?><!DOCTYPE x [<!ENTITY a "aaaa"><!ENTITY b "&a;&a;">]><x>&b;</x>'
    with pytest.raises(edmx.ContractError, match="unsafe XML"):
        edmx.parse_bytes(bomb)


def test_rejects_external_entity():
    xxe = b'<?xml version="1.0"?><!DOCTYPE x [<!ENTITY e SYSTEM "file:///etc/passwd">]><x>&e;</x>'
    with pytest.raises(edmx.ContractError, match="unsafe XML"):
        edmx.parse_bytes(xxe)


def test_rejects_non_edmx():
    with pytest.raises(edmx.ContractError, match="expected <edmx:Edmx>"):
        edmx.parse_bytes(b"<html/>")


def test_rejects_broken_xml():
    with pytest.raises(edmx.ContractError, match="not well-formed"):
        edmx.parse_bytes(b"<edmx:Edmx")


def test_rejects_oversized(tmp_path, monkeypatch):
    f = tmp_path / "big.xml"
    f.write_bytes(b"x" * 100)
    monkeypatch.setattr(edmx, "MAX_BYTES", 10)
    with pytest.raises(edmx.ContractError, match="limit"):
        edmx.parse_file(f)


def test_unresolved_association_is_reported_not_raised():
    doc = b"""<edmx:Edmx Version="1.0" xmlns:edmx="http://schemas.microsoft.com/ado/2007/06/edmx">
      <edmx:DataServices><Schema Namespace="N" xmlns="http://schemas.microsoft.com/ado/2008/09/edm">
        <EntityType Name="T"><Key><PropertyRef Name="Id"/></Key><Property Name="Id" Type="Edm.String"/>
          <NavigationProperty Name="to_X" Relationship="N.Missing" FromRole="a" ToRole="b"/></EntityType>
      </Schema></edmx:DataServices></edmx:Edmx>"""
    c = edmx.parse_bytes(doc)
    assert [i["code"] for i in c["issues"]] == ["unresolved-association"]
    assert c["entity_types"]["N.T"]["navigations"][0]["target_type"] is None
