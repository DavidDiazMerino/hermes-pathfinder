# Changelog

## 0.2.0

- Added an SAP source trust map, question-based recipes and `pathfinder_read` for official documents.
- Added trust labels to Hermes web results and source IDs for citable pages.
- Moved evaluation workspaces outside the repository, flagged contaminated runs and documented the
  limits of the contract rerun (PF-00).
- Scoped the evidence gate to explicit SAP terms and the guard to plugin data paths and direct
  domain-skill writes (PF-03).
- Documented network access, hooks, data retention and the security reporting process (PF-04).
- Added CI, an updated demo script and a draft catalog entry (PF-20).
- Updated the method skill and the `/pathfinder` mission for source recipes, `pathfinder_read` and
  `source_id` evidence (PF-05).

## 0.1.0

- Added the SAP domain pack and a deterministic OData V2 and V4 metadata inspector.
- Added a lab for testing contract claims and a local ledger for inspection and lab evidence.
- Added an evidence gate for `skill_manage` and guards for plugin data and direct skill writes.
