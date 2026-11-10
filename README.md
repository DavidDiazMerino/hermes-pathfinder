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
| `pathfinder_sources` | Where the truth lives: for the user's question, the source recipe (which official SAP source answers it and how to read it, never the answer itself), plus the questions to settle, the product matrix and pitfalls labelled `documented` or `practitioner`. |
| Live source trust | Hermes's own `web_search` and `web_extract` results about SAP arrive labelled official SAP / standard / SAP employee / community / unknown; official pages read become citable `source_id`s. |
| `pathfinder_read` | Reads large official documents live (for example SAP's Cloudification Repository, tens of MB) and returns only the entries asked for, recorded as evidence. |
| `pathfinder_inspect` | Deterministic parser for OData `$metadata` (V2 and V4): keys (including composite), types, lengths, nullability, create/update/delete restrictions (`sap:` attributes, Capabilities and Core vocabularies, inline or external), navigations resolved to their target. |
| Evidence ledger | Every inspection is stored with the file's SHA-256 and a `run_id` the agent cites. |
| `enterprise-pathfinder:method` skill | The working method: orient, inspect, answer with provenance, then learn. |
| `/pathfinder` | `/pathfinder <task>` starts a mission; `/pathfinder status` lists runs, their evidence status and the skills they back. |
| `pathfinder_lab` | Tests the agent's own claims about a contract (keys, operations, navigations, required fields, payloads it expects to be accepted or refused). A run is `verified` only when its latest lab passed with at least one claim. |
| Evidence gate | A `pre_tool_call` hook on `skill_manage`: an SAP-domain skill can be created only if it cites a verified run, and changed only with a newly verified run. Invented or failed run_ids are refused. The ledger and the skills folder are also guarded against writes that bypass the gate. Setting: `gate_mode` = `strict` (default), `declared` or `off`. |

The gate stops hallucinated or untested skills from being saved. It is not a sandbox: an agent
with unrestricted shell access running as your user could still work around it.

## Does it help?

Two real sessions, a PM expert and a SuccessFactors newcomer, are written up in [docs/scenarios.md](docs/scenarios.md).

On a 500 KB OData contract, Pathfinder used 51% fewer tokens with Gemini 4 Argon and 52% to 65%
fewer across four cheaper models. Tiny contracts generally cost more. Accuracy comparisons remain
inconclusive. The gate, source map and open-ended SAP questions remain unmeasured. We repeated
the second round after sessions read evaluation files and excluded affected runs from the rerun's
results. [Evaluation](docs/eval.md)

## Install

Once listed in the catalog

```bash
hermes plugins install enterprise-pathfinder
```

### Development install

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

- **Network.** `pathfinder_read` is enabled by default. On request, it starts an HTTPS GET at a URL
  the trust map rates official (such as SAP Help) or standard (OData / OASIS). It checks the final
  URL after redirects and reads up to 40 MB. Set `network: off` to disable network reads by Pathfinder.
- **Hooks.** `pre_tool_call` receives the arguments of every tool call. It checks `skill_manage`
  writes for evidence and can block other calls that reference plugin data paths or directly write
  SAP-domain skills under the skills directory. `post_tool_call` records which evidence backs a
  successful or staged skill write. `transform_tool_result` adds trust labels to Hermes's
  `web_search` and `web_extract` results about the domain. Set `source_tagging: false` to turn off
  tagging and recording pages read by `web_extract`.
- **Never calls SAP systems or APIs.** Pathfinder reads documentation and contracts. SAP's API Policy
  (v.4.2026a, section 2.2.2) restricts agentic AI use of SAP APIs to SAP-endorsed architectures; the
  SAP pack lists the governed paths SAP documents (API Management, SAP-managed MCP, the A2A Agent
  Gateway) so you can evaluate them with your system owner.
- `pathfinder_inspect` reads only the file you name; XML is parsed with `defusedxml` (no DTDs,
  entities or external references) and a 5 MB limit.
- **What is stored.** Each successful inspection saves the full parsed contract as JSON, with its
  hash, under `<HERMES_HOME>/plugin-data/enterprise-pathfinder/contracts/`. For each official or
  domain-related page read with `web_extract`, Pathfinder records the URL, title when available,
  trust tier, content hash and content length. `pathfinder_read` records source metadata and caches
  the downloaded document. Lab results and skill evidence links are stored in the same plugin data
  directory. Pathfinder keeps these records locally and does not read or store credentials. There is
  no automatic cleanup. Deleting `<HERMES_HOME>/plugin-data/enterprise-pathfinder/` clears the cache
  and permanently removes the evidence history.
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
