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

## Cheaper models (second round)

Same setup with four cheaper models from Nous Portal, the same model in both conditions, the three
contracts, 3 runs each: 72 sessions, about $3.39 in total at the endpoint's published prices.
Result file: `eval/results/20261106-115900.json`.

| Model | Condition | Checks correct | Perfect runs | Cost (9 runs) | Tokens (9 runs) | Used the plugin |
|---|---|---|---|---|---|---|
| GPT-6 Luna | A, no plugin | 216/216 | 9/9 | $0.059 | 1.26 M | – |
| GPT-6 Luna | C, plugin | 215/216 | 8/9 | $0.059 | 1.39 M | 4/9 runs |
| GPT-6.1 Terra | A | 216/216 | 9/9 | $0.460 | 1.08 M | – |
| GPT-6.1 Terra | C | 216/216 | 9/9 | $0.411 | 0.90 M | 9/9 |
| Gemini 3.8 Flash | A | 216/216 | 9/9 | $1.284 | 4.71 M | – |
| Gemini 3.8 Flash | C | 216/216 | 9/9 | $0.940 | 3.01 M | 9/9 |
| GLM 5.3 Flash | A | 194/216 | 7/9 | $0.070 | 1.83 M | – |
| GLM 5.3 Flash | C | 197/216 | 7/9 | $0.103 | 2.70 M | 8/9 |

Large contract only (mean per run):

| Model | Cost A → C | Tokens A → C | Time A → C |
|---|---|---|---|
| GPT-6 Luna | $0.0134 → $0.0112 | 334 k → 278 k | 57 s → 45 s |
| GPT-6.1 Terra | $0.0764 → $0.0527 (−31%) | 197 k → 107 k | 50 s → 42 s |
| Gemini 3.8 Flash | $0.2865 → $0.1984 (−31%) | 1.21 M → 0.74 M | 190 s → 167 s |
| GLM 5.3 Flash | $0.0159 → $0.0198 (+25%) | 444 k → 586 k | 118 s → 137 s |

What this round adds:

- **Accuracy is still essentially equal.** Current cheap models read OData metadata well. The one
  failure of the kind the plugin targets appeared once: GLM without the plugin missed four
  restrictions declared in external `<Annotations>` blocks (32/36); with the plugin it missed one
  (35/36), copying a value wrongly from the inspector's output. Two GLM runs returned no JSON in
  both conditions (format, not understanding). Luna with the plugin once left a key out of the
  required fields.
- **Cost on the large contract fell about 31% for Terra and Gemini Flash**, less for Luna (which
  mostly did not use the plugin), and rose for GLM, driven by one run that looped through 32 tool
  calls.
- **Weaker models do not always pick up the tools.** Luna used Pathfinder in 4 of 9 runs even
  with the plugin enabled; Gemini Flash without the plugin wrote and ran its own XML-parsing
  scripts. Tool discoverability matters as much as the tools.
- What this benchmark does not measure: the evidence trail, the skill gate, and the SAP source map
  (editions, released APIs, communication arrangements, API policy). Those need their own
  evaluation.
