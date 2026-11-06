import io
import json

import pytest

from pathfinder import gate, packs, reader, tools, trust, webtrust

PACK = packs.load("sap")
TM = PACK["trust_map"]
KW = gate.keyword_regex(PACK["gate_keywords"])


@pytest.mark.parametrize("url,tier", [
    ("https://help.sap.com/docs/SAP_S4HANA_CLOUD/x/y.html", "official"),
    ("https://api.sap.com/api/API_BUSINESS_PARTNER/overview", "official"),
    ("https://userapps.support.sap.com/sap/support/knowledge/en/2215682", "official"),
    ("https://github.com/SAP/abap-atc-cr-cv-s4hc", "official"),
    ("https://raw.githubusercontent.com/SAP/abap-atc-cr-cv-s4hc/main/src/x.json", "official"),
    ("https://github.com/SAPcommunityfan/notes", "unknown"),  # not the SAP org
    ("https://github.com/oasis-tcs/odata-vocabularies", "standard"),
    ("https://community.sap.com/t5/technology-blog-posts-by-sap/x/ba-p/1", "sap-employee"),
    ("https://community.sap.com/t5/technology-blog-posts-by-members/x/ba-p/2", "community"),
    ("https://medium.com/@someone/sap-odata-tips", "unknown"),
    ("http://help.sap.com.evil.example/docs", "unknown"),
    ("not a url", "unknown"),
])
def test_classify(url, tier):
    assert trust.classify(url, TM)["tier"] == tier


def test_recipes_match_questions_without_answers():
    r = trust.match_recipes("Can I still read table AUFK in a clean core S/4HANA Cloud? What is the successor?", PACK)
    assert r and r[0]["id"] == "released-object"
    assert any("objectReleaseInfoLatest.json" in w["url"] for w in r[0]["where"])
    r = trust.match_recipes("EmpJob query misses employees hired next month in SuccessFactors", PACK)
    assert r[0]["id"] == "sf-api-behaviour"
    assert trust.match_recipes("what is the weather", PACK) == []


def test_sources_tool_with_question(runtime):
    out = json.loads(tools.sources({"domain": "sap", "question": "Is API_MaintenanceOrder deprecated?"}, runtime))
    assert out["ok"] and out["recipes"][0]["id"] == "api-status"
    out = json.loads(tools.sources({"domain": "sap", "question": "zzz"}, runtime))
    assert out["no_recipe"] and "site:help.sap.com" in out["next"]


def search_result(urls):
    return json.dumps({"success": True, "data": {"web": [{"title": u, "url": u, "description": "", "position": i}
                                                          for i, u in enumerate(urls)]}})


def test_search_results_are_tagged(runtime):
    res = search_result(["https://help.sap.com/a", "https://community.sap.com/t5/x-blog-posts-by-members/b"])
    out = json.loads(webtrust.annotate("web_search", {"query": "sap odata upsert"}, res, trust_map=TM,
                                       ledger=runtime.ledger(), kw_re=KW))
    assert [i["pathfinder_trust"] for i in out["data"]["web"]] == ["official", "community"]
    assert out["pathfinder"]["trust_counts"] == {"official": 1, "community": 1}


def test_search_without_official_gets_hint(runtime):
    res = search_result(["https://medium.com/x"])
    out = json.loads(webtrust.annotate("web_search", {"query": "SuccessFactors upsert purgeType"}, res,
                                       trust_map=TM, ledger=runtime.ledger(), kw_re=KW))
    assert "site:help.sap.com" in out["pathfinder"]["hint"]


def test_unrelated_search_is_untouched(runtime):
    res = search_result(["https://example.com/recipes"])
    assert webtrust.annotate("web_search", {"query": "best paella recipe"}, res, trust_map=TM,
                             ledger=runtime.ledger(), kw_re=KW) is None


def test_extract_records_official_source_as_evidence(runtime):
    res = json.dumps({"results": [
        {"url": "https://help.sap.com/docs/x/maintenance-order-deprecated", "title": "Maintenance Order (Deprecated)",
         "content": "API_MaintenanceOrder is deprecated. Successor: API_MaintenanceOrder_002.", "error": None},
        {"url": "https://example.com/blog", "title": "SAP tips", "content": "SAP OData tip", "error": None}]})
    out = json.loads(webtrust.annotate("web_extract", {}, res, trust_map=TM, ledger=runtime.ledger(), kw_re=KW))
    first, second = out["results"]
    assert first["pathfinder_trust"] == "official" and first["pathfinder_source_id"].startswith("src-")
    assert runtime.ledger().evidence_status(first["pathfinder_source_id"])["status"] == "documented"
    assert second["pathfinder_trust"] == "unknown"
    assert runtime.ledger().evidence_status(second["pathfinder_source_id"])["status"] == "weak-source"
    # same page, same content: same id
    again = json.loads(webtrust.annotate("web_extract", {}, res, trust_map=TM, ledger=runtime.ledger(), kw_re=KW))
    assert again["results"][0]["pathfinder_source_id"] == first["pathfinder_source_id"]


def test_non_json_or_other_tools_untouched(runtime):
    assert webtrust.annotate("read_file", {}, "{}", trust_map=TM, ledger=None, kw_re=KW) is None
    assert webtrust.annotate("web_search", {}, "plain text", trust_map=TM, ledger=None, kw_re=KW) is None


# ---------------- reader (no real network)
class FakeResp(io.BytesIO):
    def __init__(self, body, url, ctype="application/json"):
        super().__init__(body)
        self._url, self.headers = url, {"Content-Type": ctype}

    def geturl(self):
        return self._url

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


CR_URL = "https://raw.githubusercontent.com/SAP/abap-atc-cr-cv-s4hc/main/src/objectReleaseInfoLatest.json"
CR_BODY = json.dumps({"formatVersion": "1", "objectReleaseInfo": [
    {"objectType": "TABL", "objectKey": "AUFK", "state": "notToBeReleased",
     "successors": [{"objectType": "CDS_STOB", "objectKey": "I_ORDER"}]},
    {"objectType": "CDS_STOB", "objectKey": "I_EQUIPMENT", "state": "released"}]}).encode()


def test_reader_finds_records_and_records_source(runtime, tmp_path):
    opener = lambda req, timeout: FakeResp(CR_BODY, req.full_url)  # noqa: E731
    out = reader.read(CR_URL, ["AUFK", "BAPI_NOPE"], trust_map=TM, cache_dir=tmp_path, ledger=runtime.ledger(),
                      field="objectKey", opener=opener)
    assert out["kind"] == "json" and out["hits"]["AUFK"][0]["state"] == "notToBeReleased"
    assert out["not_found"] == ["BAPI_NOPE"]
    assert runtime.ledger().evidence_status(out["source_id"])["status"] == "documented"


def test_reader_refuses_non_official_hosts_and_redirects(runtime, tmp_path):
    with pytest.raises(reader.ReadError, match="not an official"):
        reader.fetch("https://example.com/x.json", TM, tmp_path)
    with pytest.raises(reader.ReadError, match="not an official"):
        reader.fetch("http://help.sap.com/x", TM, tmp_path)  # plain http
    evil = lambda req, timeout: FakeResp(b"{}", "https://evil.example/x.json")  # noqa: E731
    with pytest.raises(reader.ReadError, match="redirected"):
        reader.fetch("https://help.sap.com/doc/x.json", TM, tmp_path / "c2", opener=evil)


def test_reader_text_search():
    hits = reader.search_text("a\nAPI_MaintenanceOrder is deprecated\nb", ["deprecated"])
    assert "API_MaintenanceOrder" in hits["deprecated"][0]


# ---------------- gate accepts documented sources
def test_gate_accepts_official_source_evidence(runtime):
    res = json.dumps({"results": [{"url": "https://help.sap.com/docs/x", "title": "t",
                                   "content": "SAP OData doc", "error": None}]})
    sid = json.loads(webtrust.annotate("web_extract", {}, res, trust_map=TM, ledger=runtime.ledger(),
                                       kw_re=KW))["results"][0]["pathfinder_source_id"]
    content = ("---\nname: sap-recipe-api-status\ndescription: where SAP API status is documented\nmetadata:\n"
               f"  pathfinder:\n    domain: sap\n    kind: recipe\n    evidence: [{sid}]\n---\n# Recipe\nSAP APIs...\n")
    d = gate.evaluate({"operations": [{"action": "create", "name": "sap-recipe-api-status", "content": content}]},
                      runtime.ledger(), mode="strict", keywords=PACK["gate_keywords"])
    assert d["allow"], d["message"]


def test_gate_refuses_community_only_evidence(runtime):
    res = json.dumps({"results": [{"url": "https://community.sap.com/t5/x-blog-posts-by-members/y", "title": "t",
                                   "content": "SAP tip", "error": None}]})
    sid = json.loads(webtrust.annotate("web_extract", {}, res, trust_map=TM, ledger=runtime.ledger(),
                                       kw_re=KW))["results"][0]["pathfinder_source_id"]
    content = ("---\nname: sap-tip\ndescription: x\nmetadata:\n  pathfinder:\n    domain: sap\n"
               f"    evidence: [{sid}]\n---\n# Tip\nSAP...\n")
    d = gate.evaluate({"operations": [{"action": "create", "name": "sap-tip", "content": content}]},
                      runtime.ledger(), mode="strict", keywords=PACK["gate_keywords"])
    assert not d["allow"] and "weak-source" in d["message"]


def test_recipes_carry_questions_to_settle(runtime):
    out = json.loads(tools.sources({"domain": "sap", "question":
                                    "Integration Suite: replicate employees from SuccessFactors to another system"}, runtime))
    rec = next(r for r in out["recipes"] if r["id"] == "sf-integration-option")
    asks = " ".join(rec["ask_before_starting"])
    assert "data center" in asks and "permissions" in asks and "SAML" in asks
