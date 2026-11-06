# Evaluation: Hermes with and without Pathfinder

Run on 2026-11-06 with Hermes v0.23.0, model `google/gemini-4-argon` (Nous provider), through real
`hermes chat` sessions. Reproduce with `eval/run_eval.py`.

## Setup

- **A (control):** a Hermes profile cloned from the same user profile, same model and config, **without**
  the plugin and without any SAP skill.
- **C:** the same profile **with** Enterprise Pathfinder enabled (it also held two skills Hermes had
  learned earlier with the plugin).
- **Task, identical for both:** an empty folder with the contract saved as `service_metadata.xml`.
  For each entity set, report keys, whether create/update/delete are allowed, the fields a create
  must carry, and navigations with target and cardinality, as a fixed JSON shape. The prompt does
  not mention the plugin and forbids creating skills.
- **Scoring:** 6 checks per entity set against expected answers that do **not** come from the
  plugin: hand-written for the two sample contracts (`eval/expected/`), and taken from the
  generator's construction for the large contract (`eval/gen_large.py`). Tests cross-check both
  against the parser.
- **Contracts:** the two bundled samples (3 entity sets each, about 3 KB), and a generated OData V4
  service at realistic size (500 KB, 48 entity types, 2,280 properties, SAP-like label annotations,
  restrictions in external `<Annotations>` blocks at the end of the file). For the large contract
  the question covers 6 entity sets chosen for their hard cases.
- 3 runs per condition and contract. Runs refused by the gateway for infrastructure reasons
  (`Gateway draining` while Hermes synced dependencies) were retried and are not counted.

## Results

| Contract | Condition | Perfect runs | Tokens (mean, range) | Wall time (mean) | Tool calls |
|---|---|---|---|---|---|
| Business Partner V2 (3 KB) | A, no plugin | 3/3 | 44,349 (44,212–44,458) | 56 s | 1.0 |
| Business Partner V2 (3 KB) | C, plugin | 3/3 | 108,066 (94,122–125,328) | 76 s | 6.0 |
| Product V4 (3 KB) | A, no plugin | 3/3 | 43,680 (43,577–43,773) | 69 s | 1.0 |
| Product V4 (3 KB) | C, plugin | 3/3 | 108,031 (105,265–111,059) | 78 s | 7.3 |
| Large V4 (500 KB) | A, no plugin | 3/3 | 251,222 (228,326–278,788) | 182 s | 6.3 |
| Large V4 (500 KB) | C, plugin v0.1 | 3/3 | 154,679 (138,165–183,365) | 118 s | 11.0 |
| Large V4 (500 KB) | C, plugin + multi-entity inspect | 3/3 | 121,979 (118,440–125,201) | 120 s | 6.3 |

## What this shows

- **Accuracy was the same.** This model answered every check correctly with or without the plugin,
  on small and large contracts alike. We do not claim an accuracy gain.
- **On small contracts the plugin costs more**, about 2.5x the tokens: the agent orients, inspects
  and runs the lab where reading 3 KB of XML once was enough.
- **On a realistically sized contract the plugin is cheaper and faster:** about 51% fewer tokens
  and 34% less time than reading and searching the raw XML, while every run also produced a
  verified lab record the answer can cite.
- The control has no evidence trail: its answers cannot be checked without redoing the work.

## Limits

- One model, 3 runs per cell, synthetic contracts. A weaker or smaller model may behave differently
  in either direction; that is worth testing next.
- The plugin condition also had previously learned skills, so the comparison measures the plugin
  as it is used, not the tools in isolation.
- Token counts include prompt caching as reported by Hermes; wall times depend on provider load.

Raw per-run data: `eval/results/*.json` (the first file's built-in summary predates the
infrastructure-error filter; the table above recomputes it from valid runs only).
