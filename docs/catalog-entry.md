# Hermes catalog submission draft

Set `sha` to the full commit SHA selected for submission, then copy the entry to
`plugin-catalog/enterprise-pathfinder.yaml` in Hermes Agent.

```yaml
name: enterprise-pathfinder
title: Enterprise Pathfinder
repo: https://github.com/DavidDiazMerino/hermes-pathfinder
sha: "<delivery-commit-sha>"
version: "0.2.0"
description: >-
  Routes SAP questions to documented sources and reads official references on request.
  Parses OData metadata, tests contract claims and checks evidence before saving SAP skills.
  Disclosure — pre_tool_call checks skill writes and can block tool calls involving plugin data
  paths or direct SAP skill writes. post_tool_call records skill evidence links and
  transform_tool_result labels Hermes web results and records relevant page reads.
  pathfinder_read starts HTTPS GET requests at official or standards sources and checks the final URL.
  Set network to off to disable it. Parsed contracts, hashes, lab results, source metadata, skill
  evidence links and downloaded documents are stored under plugin-data/enterprise-pathfinder.
  Pathfinder does not read credentials or call SAP systems or APIs.
maintainer: DavidDiazMerino
tier: community
category: tools
requires_hermes: ">=0.23.0"
capabilities:
  provides_tools:
    - pathfinder_sources
    - pathfinder_inspect
    - pathfinder_lab
    - pathfinder_read
  provides_hooks:
    - pre_tool_call
    - post_tool_call
    - transform_tool_result
  provides_middleware: []
  requires_env: []
```

## Pull request draft

Enterprise Pathfinder gives Hermes a source map for SAP questions, a deterministic OData metadata
inspector, a lab for testing contract claims and a local evidence ledger. It registers the
`/pathfinder` command, a method skill and the four Pathfinder tools declared above.

**Disclosure**

- `pre_tool_call` receives tool arguments, checks `skill_manage` writes and can block calls
  involving plugin data paths or direct writes to SAP skills. `post_tool_call` links evidence to
  applied or staged skill writes. `transform_tool_result` adds trust labels to domain-related
  `web_search` and `web_extract` results and records relevant page reads.
- On request, `pathfinder_read` starts HTTPS GET requests at official or standards URLs and checks
  the final URL after redirects. Network reads are enabled by default and can be switched off with
  `network: off`.
- The plugin keeps full parsed contracts and their hashes, lab results, source records, cached
  downloads and skill evidence links under `<HERMES_HOME>/plugin-data/enterprise-pathfinder/`.
  Source records include URL, title when available, trust tier, hash and content length. There is
  no automatic cleanup.
- Pathfinder does not read credentials or call SAP systems or APIs.
