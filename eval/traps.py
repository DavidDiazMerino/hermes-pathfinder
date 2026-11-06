"""Trap questions: SAP questions where a plausible answer from memory is wrong or outdated.

Every expected answer was checked against an official SAP source on 2026-11-06 (see `verified_in`).
Scoring is deterministic: each check is a regex that must (or must not) match the final answer.
"""

from __future__ import annotations

import re
from typing import Any

SUFFIX = ("\n\nAnswer concisely. Say what you are not sure about, and cite the sources you relied on "
          "(with URLs).")

OFFICIAL_URL = re.compile(
    r"https?://(?:help\.sap\.com|api\.sap\.com|userapps\.support\.sap\.com|me\.sap\.com|support\.sap\.com|"
    r"learning\.sap\.com|developers\.sap\.com|architecture\.learning\.sap\.com|roadmaps\.sap\.com|"
    r"(?:raw\.githubusercontent|github)\.com/SAP[/-])", re.IGNORECASE)

TRAPS: list[dict[str, Any]] = [
    {
        "id": "maint-order-api",
        "question": "We are building a new side-by-side integration with SAP S/4HANA Cloud Public Edition 2608 that "
                    "creates maintenance orders. Which published OData API should we use? Give its technical name.",
        "checks": [
            ("recommends the current version 2 API, not the deprecated original",
             r"API_MAINTENANCEORDER(?:_0*2\b|\s*;\s*v\s*=\s*2)|Maintenance Order \(Version 2\)"),
        ],
        "verified_in": "SAP Help Portal, Maintenance Order (Deprecated) and Maintenance Order (Version 2) pages",
    },
    {
        "id": "aufk-public",
        "question": "In SAP S/4HANA Cloud Public Edition with ABAP Cloud, can a custom program read table AUFK "
                    "directly? If not, what does SAP provide instead?",
        "checks": [
            ("says it is not allowed / not released", r"not (?:be )?released|notToBeReleased|not (?:allowed|permitted|possible)|cannot|can't|can not|no[,.]"),
            ("names SAP's successor I_ORDER", r"\bI_ORDER\b"),
        ],
        "verified_in": "SAP Cloudification Repository, objectReleaseInfoLatest.json (AUFK: notToBeReleased, successor I_ORDER)",
    },
    {
        "id": "bapi-public",
        "question": "Is BAPI_ALM_ORDER_MAINTAIN released for ABAP Cloud in SAP S/4HANA Cloud Public Edition? "
                    "What should new code use to create maintenance orders there?",
        "checks": [
            ("says it is not released for ABAP Cloud", r"not released|isn'?t released|not (?:allowed|permitted|available)|cannot|no[,.]"),
            ("knows it is a classic API (tier 2 / private / on-premise)", r"classic\s*API|classicAPI|tier[- ]?2|private edition|on-?premise"),
            ("names the released RAP business object", r"I_MAINTENANCEORDERTP"),
        ],
        "verified_in": "SAP Cloudification Repository: objectClassifications_SAP.json (classicAPI) and objectReleaseInfoLatest.json (I_MAINTENANCEORDERTP released)",
    },
    {
        "id": "component-deprecated",
        "question": "In SAP S/4HANA Cloud Public Edition, can I use the CDS view I_MAINTORDEROPCOMPONENTTP in new "
                    "ABAP Cloud code?",
        "checks": [
            ("says it is deprecated", r"deprecat"),
            ("names the successor _2", r"I_MAINTORDEROPCOMPONENTTP_2"),
        ],
        "verified_in": "SAP Cloudification Repository, objectReleaseInfoLatest.json (deprecated, successor I_MAINTORDEROPCOMPONENTTP_2)",
    },
    {
        "id": "sf-future-hires",
        "question": "Our SAP Cloud Integration iFlow queries EmpJob from the SuccessFactors OData API every day "
                    "with only a $filter on startDate to pick up new hires, but hires that start next month never "
                    "show up. Why, and how do we fix it?",
        "checks": [
            ("explains effective dating / default as-of today", r"asOfDate|as-of|effective[- ]dat|today"),
            ("uses fromDate/toDate", r"fromDate|toDate"),
        ],
        "verified_in": "SAP SuccessFactors API Reference Guide (OData V2): asOfDate and fromDate/toDate queries; KBA 2148752",
    },
    {
        "id": "sf-auth",
        "question": "What authentication should a new SAP Cloud Integration iFlow use to call the SAP "
                    "SuccessFactors OData API?",
        "checks": [
            ("OAuth", r"OAuth"),
            ("SAML bearer assertion", r"SAML"),
        ],
        "verified_in": "SAP SuccessFactors API Reference Guide (OData V2): OAuth 2.0 SAML Bearer token flow",
    },
    {
        "id": "sf-compound-write",
        "question": "Can we use the SuccessFactors Compound Employee API to create new employees in Employee Central?",
        "checks": [
            ("says it is read-only", r"read[- ]only|only (?:reads|read|retriev|extract)|cannot (?:be used to )?(?:create|write)|not (?:for|support) (?:creat|writ)|no[,.]"),
            ("points to the OData API for writing", r"OData"),
        ],
        "verified_in": "Employee Central Compound Employee API guide: read-only SOAP replication API",
    },
    {
        "id": "agent-api-policy",
        "question": "Can I let my AI agent call our SAP S/4HANA Cloud APIs directly with a technical user, so it "
                    "plans and executes the steps on its own?",
        "checks": [
            ("cites SAP's API Policy", r"API Policy"),
            ("knows the agentic clause / endorsed paths", r"2\.2\.2|endorsed|autonomous|agentic"),
            ("names a governed path", r"Integration Suite|API Management|MCP|Agent Gateway|Joule"),
        ],
        "verified_in": "SAP API Policy v.4.2026a, section 2.2.2",
    },
]


def score(answer: str, trap: dict[str, Any]) -> dict[str, Any]:
    text = answer or ""
    results = [(label, bool(re.search(rx, text, re.IGNORECASE))) for label, rx in trap["checks"]]
    passed = sum(ok for _, ok in results)
    return {
        "correct": passed == len(results),
        "checks_passed": passed,
        "checks_total": len(results),
        "failed_checks": [label for label, ok in results if not ok],
        "cites_official": bool(OFFICIAL_URL.search(text)),
        "answered": bool(text.strip()),
    }
