# Enterprise Pathfinder for Hermes Agent

**Give Hermes a map to enterprise software, and a way to prove what it learns there.**

Enterprise Pathfinder is a native [Hermes Agent](https://github.com/NousResearch/hermes-agent) plugin.
Its first domain pack covers **SAP** (OData V2 and V4 contracts).

> Unofficial community project. Not affiliated with or endorsed by SAP SE or Nous Research.

## Who it is for

- **Someone landing in SAP.** Hermes knows where to look (Business Accelerator Hub, Help Portal,
  the right spec for the right edition), asks the questions that matter first (product, edition,
  release, access path), and warns about the classic traps before they cost a day.
- **An SAP consultant starting with Hermes.** Hand it your system's `$metadata` and get exact
  entity sets, keys, field facets and restrictions on day one, each fact backed by a run you can
  cite. Then let Hermes turn the procedures that worked into skills of its own.

## What it adds beyond a prompt

| Piece | What it does |
|---|---|
| `pathfinder_sources` | Orientation map for the domain: questions to settle, official sources per question, product matrix, pitfalls labelled `documented` or `practitioner`. |
| `pathfinder_inspect` | Deterministic parser for OData `$metadata` (V2 and V4): keys (including composite), types, lengths, nullability, create/update/delete restrictions (`sap:` attributes, Capabilities and Core vocabularies, inline or external), navigations resolved to their target. |
| Evidence ledger | Every inspection is stored with the file's SHA-256 and a `run_id` the agent cites. |
| `enterprise-pathfinder:method` skill | The working method: orient, inspect, answer with provenance, then learn. |
| `/pathfinder` | `/pathfinder <task>` starts a mission; `/pathfinder status` lists runs, their evidence status and the skills they back. |

| `pathfinder_lab` | Tests the agent's own claims about a contract (keys, operations, navigations, required fields, payloads it expects to be accepted or refused). A run is `verified` only when its latest lab passed with at least one claim. |
| Evidence gate | A `pre_tool_call` hook on `skill_manage`: an SAP-domain skill can be created only if it cites a verified run, and changed only with a newly verified run. Invented or failed run_ids are refused. The ledger and the skills folder are also guarded against writes that bypass the gate. Setting: `gate_mode` = `strict` (default), `declared` or `off`. |

The gate stops hallucinated or untested skills from being saved. It is not a sandbox: an agent
with unrestricted shell access running as your user could still work around it.

## Install (development)

```bash
git clone https://github.com/DavidDiazMerino/hermes-pathfinder
ln -s "$PWD/hermes-pathfinder" ~/.hermes/plugins/enterprise-pathfinder   # or your profile's plugins/ dir
hermes plugins enable enterprise-pathfinder
```

Try it with the bundled synthetic samples:

```text
/pathfinder Which Business Partner entities can I create and what fields are mandatory? Use fixture:sap/business_partner_v2
```

## Safety and disclosures

- **Offline.** No network calls. `pathfinder_inspect` reads only the file you name.
- **Never calls SAP APIs.** Pathfinder works on contracts you supply. SAP's API Policy (v.4.2026a,
  section 2.2.2) restricts agentic AI use of SAP APIs to SAP-endorsed architectures; the SAP pack
  lists the governed paths SAP documents (API Management, SAP-managed MCP, the A2A Agent Gateway)
  so you can evaluate them with your system owner.
- XML is parsed with `defusedxml` (no DTDs, entities or external references) and a 5 MB limit.
- Evidence is written to Hermes's per-plugin data directory (`<HERMES_HOME>/plugin-data/enterprise-pathfinder/`).
- No credentials are read or stored.
- Bundled contracts are synthetic, written from scratch from the public OData CSDL format. They
  are not the metadata of any real SAP service.

## Development

```bash
~/.hermes/hermes-agent/venv/bin/python -m pytest -q
hermes plugins doctor . --ci
```

`hermes chat -q` runs turns inside the running gateway, which keeps the plugin code it loaded.
After changing the code, reload it there:

```bash
hermes plugins disable enterprise-pathfinder && hermes plugins enable enterprise-pathfinder
```

## License

MIT
