"""The hand-written evaluation expectations and the parser must agree; if not, one of them is wrong."""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from eval import score as sc  # noqa: E402
from pathfinder import edmx  # noqa: E402
from conftest import FIXTURES  # noqa: E402


@pytest.mark.parametrize("cid,fname", [("business_partner_v2", "business_partner_v2.edmx"), ("product_v4", "product_v4.xml")])
def test_parser_matches_hand_written_expectations(cid, fname):
    expected = sc.load_expected(cid)
    derived = sc.answer_from_contract(edmx.parse_file(FIXTURES / fname))
    result = sc.score(derived, expected)
    assert result["points"] == result["total"], result["errors"]


def test_extract_and_score():
    exp = sc.load_expected("product_v4")
    text = "blah\n```json\n" + __import__("json").dumps({"entity_sets": {"Product": exp["entity_sets"]["Product"]}}) + "\n```"
    r = sc.score(sc.extract_answer(text), exp)
    assert r["points"] == 6 and r["parsed"] and any("missing" in e for e in r["errors"])
    assert sc.score(sc.extract_answer("no json"), exp)["parsed"] is False
