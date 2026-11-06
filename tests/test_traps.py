import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from eval import traps  # noqa: E402


def t(tid):
    return next(x for x in traps.TRAPS if x["id"] == tid)


def test_good_and_bad_answers():
    good = ("No. AUFK is notToBeReleased in Public Edition; SAP's successor is I_ORDER. "
            "Source: https://raw.githubusercontent.com/SAP/abap-atc-cr-cv-s4hc/main/src/objectReleaseInfoLatest.json")
    r = traps.score(good, t("aufk-public"))
    assert r["correct"] and r["cites_official"]
    bad = "Yes, just SELECT from AUFK joined with AFIH."
    assert not traps.score(bad, t("aufk-public"))["correct"]


def test_maintenance_order_variants():
    for ok in ["Use API_MAINTENANCEORDER;v=2 (the original is deprecated)",
               "Use API_MaintenanceOrder_002; API_MaintenanceOrder is deprecated since 2308",
               "Use Maintenance Order (Version 2), API_MAINTENANCEORDER_0002"]:
        assert traps.score(ok, t("maint-order-api"))["correct"], ok
    assert not traps.score("Use API_MAINTENANCEORDER.", t("maint-order-api"))["correct"]


def test_official_citation_detection():
    assert not traps.score("see https://medium.com/x and https://github.com/SAPfan/x", t("sf-auth"))["cites_official"]
    assert traps.score("see https://help.sap.com/docs/x", t("sf-auth"))["cites_official"]
