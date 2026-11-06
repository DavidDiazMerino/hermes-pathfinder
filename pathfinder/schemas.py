"""Tool schemas: what the model reads to decide when and how to call each tool."""

SOURCES = {
    "name": "pathfinder_sources",
    "description": (
        "Orientation map for an enterprise software domain (currently: sap). Returns the questions to "
        "settle first (product, edition, release, interface style, authorised access path), the "
        "official sources to use for each kind of question, the product matrix, known pitfalls "
        "labelled 'documented' or 'practitioner', and sample contracts you can inspect offline. "
        "Call this before researching or answering anything about an SAP API, so you start from "
        "trusted sources instead of guessing. Offline; makes no network calls."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "domain": {"type": "string", "description": "Domain pack id. Default 'sap'."},
            "product": {
                "type": "string",
                "description": "Optional product id to narrow the answer, e.g. 's4hana-cloud-public', "
                               "'s4hana-private-onprem', 'ecc', 'integration-suite'.",
            },
        },
        "required": [],
    },
}

INSPECT = {
    "name": "pathfinder_inspect",
    "description": (
        "Parse an OData service contract ($metadata EDMX, OData V2 or V4) with a deterministic parser "
        "and return its real structure: entity sets with allowed operations, entity types, keys "
        "(including composite keys), properties with type/length/nullability and create/update "
        "restrictions, and navigations resolved to their target type. Use it instead of reading the "
        "XML yourself whenever you need facts about a contract. Every call is recorded in the "
        "Pathfinder evidence ledger and returns a run_id you can cite. Accepts a local file path "
        "(relative to the session folder) or a bundled sample such as "
        "'fixture:sap/business_partner_v2'. Offline; reads only the given file."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "contract": {
                "type": "string",
                "description": "Path to an .edmx/.xml $metadata file, or fixture:<domain>/<id>.",
            },
            "domain": {"type": "string", "description": "Domain pack id. Default 'sap'."},
            "product": {
                "type": "string",
                "description": "Product the contract belongs to, if known (recorded with the evidence).",
            },
            "entity": {
                "type": "string",
                "description": "Optional entity type or entity set name to show in detail (use for large services).",
            },
        },
        "required": ["contract"],
    },
}
