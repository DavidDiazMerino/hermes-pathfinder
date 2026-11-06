import json

import pytest

from pathfinder import gate, packs, tools

KEYWORDS = packs.load("sap")["gate_keywords"]


def skill_md(evidence=None, body="Inspect SAP OData $metadata with pathfinder_inspect."):
    meta = ""
    if evidence is not None:
        meta = ("metadata:\n  pathfinder:\n    domain: sap\n    interface: odata-v2\n"
                f"    evidence: [{', '.join(evidence)}]\n")
    return f"---\nname: sap-odata-inspection\ndescription: Inspect SAP OData contracts\n{meta}---\n\n# Proc\n{body}\n"


def create(content, name="sap-odata-inspection"):
    return {"operations": [{"action": "create", "name": name, "content": content}]}


def ev(args, runtime, mode="strict"):
    return gate.evaluate(args, runtime.ledger(), mode=mode, keywords=KEYWORDS)


@pytest.fixture
def verified_run(runtime):
    rid = json.loads(tools.inspect({"contract": "fixture:sap/business_partner_v2"}, runtime))["run_id"]
    out = json.loads(tools.lab({"run_id": rid, "claims": [
        {"type": "keys", "entity_set": "A_BusinessPartnerAddress", "expect": ["BusinessPartner", "AddressID"]}]},
        runtime))
    assert out["evidence_status"] == "verified"
    return rid


@pytest.fixture
def inspected_run(runtime):
    return json.loads(tools.inspect({"contract": "fixture:sap/product_v4"}, runtime))["run_id"]


def test_sap_skill_without_evidence_is_blocked(runtime):
    d = ev(create(skill_md()), runtime)
    assert not d["allow"]
    assert "no verified Pathfinder run" in d["message"] and "metadata.pathfinder" in d["message"]


def test_sap_skill_with_verified_run_is_allowed(runtime, verified_run):
    d = ev(create(skill_md([verified_run])), runtime)
    assert d["allow"], d["message"]
    assert d["verified"] == [verified_run]


def test_citing_run_without_metadata_block_is_blocked(runtime, verified_run):
    d = ev(create(skill_md(body=f"Evidence {verified_run}. SAP OData.")), runtime)
    assert not d["allow"] and "lacks a metadata.pathfinder block" in d["message"]


def test_invented_or_unverified_runs_are_blocked(runtime, verified_run, inspected_run):
    d = ev(create(skill_md(["pf-20991231-235959-abcdef"])), runtime)
    assert not d["allow"] and "unknown" in d["message"]
    d = ev(create(skill_md([verified_run, inspected_run])), runtime)
    assert not d["allow"] and inspected_run in d["message"]  # one weak citation spoils the batch


def test_failed_lab_does_not_count(runtime):
    rid = json.loads(tools.inspect({"contract": "fixture:sap/business_partner_v2"}, runtime))["run_id"]
    tools.lab({"run_id": rid, "claims": [{"type": "keys", "entity_set": "A_BusinessPartner", "expect": ["X"]}]}, runtime)
    d = ev(create(skill_md([rid])), runtime)
    assert not d["allow"] and "failed" in d["message"]


def test_unrelated_skill_is_untouched(runtime):
    content = "---\nname: git-tidy\ndescription: Tidy branches\n---\n\n# Git\nDelete merged branches.\n"
    assert ev(create(content, name="git-tidy"), runtime)["allow"]


def test_declared_mode_ignores_keywords(runtime):
    assert ev(create(skill_md()), runtime, mode="declared")["allow"]
    assert not ev(create(skill_md([])), runtime, mode="declared")["allow"]  # declares pathfinder, no runs


def test_off_mode(runtime):
    assert ev(create(skill_md()), runtime, mode="off")["allow"]


def test_delete_is_always_allowed(runtime):
    args = {"operations": [{"action": "delete", "name": "sap-odata-inspection"}]}
    assert ev(args, runtime)["allow"]


def test_patch_of_backed_skill_needs_new_evidence(runtime, verified_run):
    led = runtime.ledger()
    led.link_skill("sap-odata-inspection", [verified_run], "applied")
    patch = {"operations": [{"action": "patch", "name": "sap-odata-inspection",
                             "old_string": "x", "new_string": f"y (evidence {verified_run})"}]}
    d = ev(patch, runtime)
    assert not d["allow"] and "newly verified run" in d["message"]

    rid2 = json.loads(tools.inspect({"contract": "fixture:sap/product_v4"}, runtime))["run_id"]
    tools.lab({"run_id": rid2, "claims": [
        {"type": "operation", "entity_set": "ProductPlant", "op": "create", "expect": False}]}, runtime)
    patch["operations"][0]["new_string"] = f"V4: read Capabilities annotations ({rid2})"
    assert ev(patch, runtime)["allow"]


def test_patch_without_keywords_on_backed_skill_is_still_gated(runtime, verified_run):
    runtime.ledger().link_skill("my-proc", [verified_run], "applied")
    patch = {"operations": [{"action": "patch", "name": "my-proc", "old_string": "a", "new_string": "b"}]}
    assert not ev(patch, runtime)["allow"]


def test_write_file_into_domain_skill_is_gated(runtime):
    args = {"operations": [{"action": "write_file", "name": "sap-notes", "file_path": "references/x.md",
                            "file_content": "BAPI list for SAP ECC"}]}
    assert not ev(args, runtime)["allow"]


def test_legacy_flat_shape(runtime):
    assert not ev({"action": "create", "name": "sap-x", "content": skill_md()}, runtime)["allow"]


def test_keyword_matching():
    rx = gate.keyword_regex(KEYWORDS)
    assert rx.search("Call the SAP Gateway") and rx.search("odata v4") and rx.search("read $metadata")
    assert not rx.search("sapling growth") and not rx.search("asap please")


DATA = "/home/u/.hermes/plugin-data/enterprise-pathfinder"
ROOTS = ["/home/u/.hermes/skills"]


def guard(tool, args, runtime, mode="strict"):
    return gate.guard_other_tool(tool, args, runtime.ledger(), data_dir=DATA, skills_roots=ROOTS,
                                 mode=mode, keywords=KEYWORDS)


def test_guard_blocks_ledger_tampering(runtime):
    assert guard("terminal", {"command": f"sqlite3 {DATA}/ledger.db 'insert into labs ...'"}, runtime)
    assert guard("execute_code", {"code": "from pathfinder.ledger import Ledger"}, runtime)
    assert guard("write_file", {"path": "/tmp/x.py", "content": "import pathfinder\n"}, runtime)
    assert guard("terminal", {"command": "rm ledger.db"}, runtime)


def test_guard_allows_reads_and_unrelated_work(runtime):
    assert guard("read_file", {"path": f"{DATA}/ledger.db"}, runtime) is None
    assert guard("terminal", {"command": "git status"}, runtime) is None
    assert guard("write_file", {"path": "/home/u/notes.md", "content": "SAP notes"}, runtime) is None
    assert guard("pathfinder_lab", {"run_id": "x"}, runtime) is None


def test_guard_blocks_direct_domain_skill_writes(runtime):
    msg = guard("write_file", {"path": "/home/u/.hermes/skills/sap-x/SKILL.md", "content": skill_md()}, runtime)
    assert msg and "skill_manage" in msg
    assert guard("patch", {"path": "/home/u/.hermes/skills/enterprise/sap-y/SKILL.md", "old_string": "a",
                           "new_string": "use the OData $metadata"}, runtime)
    ok = "---\nname: git-tidy\ndescription: x\n---\n# Git\n"
    assert guard("write_file", {"path": "/home/u/.hermes/skills/git-tidy/SKILL.md", "content": ok}, runtime) is None


def test_guard_off_mode(runtime):
    assert guard("terminal", {"command": f"cat {DATA}/ledger.db"}, runtime, mode="off") is None
