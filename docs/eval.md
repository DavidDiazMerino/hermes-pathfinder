# Evaluation: Hermes with and without Pathfinder

Run on 2026-11-06 with Hermes v0.23.0, model `google/gemini-4-argon` (Nous provider), through real
`hermes chat` sessions. Reproduce with `eval/run_eval.py`.

## Summary

What the measurements support as of 2026-11-10:

- **Cost on a realistically sized contract (500 KB): about half the tokens.** 51% fewer with
  Gemini 4 Argon in the first round, and 52% to 65% fewer across four cheaper models in the
  repeated second round.
- **Cost on tiny contracts (3 KB): higher.** Between the same and about three times the tokens,
  depending on the model.
- **Accuracy: no gain claimed.** In the repeated second round all 33 scored plugin runs were perfect
  against 26 of 28 control runs. The sample is too small and too uneven to call that a difference.
- **Not measured yet:** the evidence gate, the source map, and questions about SAP that are not
  about a contract. A trap-question round from 2026-11-06 is in `eval/results/` but is not reported
  here: 26 of its 64 sessions read evaluation files, so it has to be repeated first.

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
- New contract and trap runs use session folders under the system temporary directory
  (`pf-eval/`), with `--work-dir` available for another location outside the repository.
  Transcripts and answers are archived in `eval/runs/`. The summaries report and exclude
  sessions whose transcript shows an ordinary tool call referencing a path in the repository or
  plugin installation outside the session's workspace. This check covers paths visible in tool
  arguments.

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

## Cheaper models (second round, repeated on 2026-11-10)

Same setup with four cheaper models from Nous Portal, the same model in both conditions, the three
contracts, 3 runs each. This round was first run on 2026-11-06 with session folders inside the
repository, and 17 of its 72 sessions read evaluation files. It was repeated on 2026-11-10 with
session folders outside the repository. The repeat is the one to read; the original is kept at the
end for the record.

Result file: [`eval/results/20261110-155101.json`](../eval/results/20261110-155101.json).
Estimated cost of the 72 sessions: $3.75, including the ones not scored.

### Which sessions were scored

| | Sessions |
|---|---:|
| Run | 72 |
| Failed with HTTP 429 (rate limit, eight parallel workers) | 6 |
| Flagged for reading evaluation files | 6 |
| In both groups | 1 |
| **Scored** | **61** (28 control, 33 plugin) |

All six flagged sessions were Gemini 3.8 Flash control runs on the two small contracts, so that
model has no control result for them. No plugin session was flagged. See
[How the control found the answers](#how-the-control-found-the-answers).

### Accuracy and use of the plugin

| Model | Control runs | Control checks | Plugin runs | Plugin checks | Called Pathfinder in plugin runs |
|---|---:|---:|---:|---:|---:|
| GPT-6 Luna | 9 | 216/216 | 7 | 162/162 | 6/7 |
| GPT-6.1 Terra | 8 | 192/198 | 9 | 216/216 | 9/9 |
| Gemini 3.8 Flash | 2 | 68/72 | 9 | 216/216 | 9/9 |
| GLM 5.3 Flash | 9 | 216/216 | 8 | 180/180 | 8/8 |
| Total | 28 | 692/702 | 33 | 774/774 | 32/33 |

The two imperfect control runs: Terra returned `null` instead of `true` for operations the Product
V4 contract does not restrict (12/18), and Gemini Flash listed only the key as required on create
for four entity sets of the large contract (32/36).

### Large contract (500 KB), mean per scored run

| Model | Runs A / C | Tokens A → C | Cost A → C | Time A → C | Tool calls A → C |
|---|---:|---|---|---|---|
| GPT-6 Luna | 3 / 2 | 433 k → 205 k (−53%) | $0.0137 → $0.0083 (−39%) | 84 s → 60 s | 12.3 → 8.5 |
| GPT-6.1 Terra | 3 / 3 | 221 k → 106 k (−52%) | $0.0757 → $0.0494 (−35%) | 63 s → 48 s | 14.0 → 5.3 |
| Gemini 3.8 Flash | 2 / 3 | 804 k → 349 k (−57%) | $0.1665 → $0.1200 (−28%) | 222 s → 186 s | 25.0 → 11.3 |
| GLM 5.3 Flash | 3 / 2 | 673 k → 236 k (−65%) | $0.0220 → $0.0093 (−58%) | 231 s → 128 s | 23.3 → 8.5 |

One of Luna's two plugin runs on this contract did not call Pathfinder; it is included.

### Small contracts (3 KB), the two samples pooled, mean per scored run

| Model | Runs A / C | Tokens A → C | Cost A → C |
|---|---:|---|---|
| GPT-6 Luna | 6 / 5 | 46 k → 131 k (2.8x) | $0.0029 → $0.0050 (1.7x) |
| GPT-6.1 Terra | 5 / 6 | 73 k → 76 k (1.0x) | $0.0368 → $0.0357 (1.0x) |
| Gemini 3.8 Flash | 0 / 6 | no control → 140 k | no control → $0.0589 |
| GLM 5.3 Flash | 6 / 6 | 91 k → 200 k (2.2x) | $0.0041 → $0.0082 (2.0x) |

### What this round shows

- **The saving on a large contract holds across models.** All four used 52% to 65% fewer tokens
  with the plugin, and 28% to 58% less money. This matches the first round (51% fewer tokens with
  Gemini 4 Argon). Tool calls fell too: the agent can ask the inspector for the entity sets it
  needs instead of paging through the XML.
- **On tiny contracts the plugin still costs more** for Luna and GLM, about two to three times the
  tokens. For Terra it made no difference.
- **Every scored plugin run was perfect** (33 of 33), against 26 of 28 control runs. We do not
  claim an accuracy gain from this: see the limits below.
- **The plugin was used in 32 of 33 plugin runs.** When the task hands the agent a `$metadata`
  file, the models find the inspector. This says nothing about open questions without a file.

### Limits of this round

- The exclusions left unequal cells: two or three runs per cell, and no Gemini control on the small
  contracts. Read the percentages as sizes of effect, not as precise figures.
- One generated large contract and two hand-written small ones, all synthetic.
- The plugin condition also held skills learned earlier with the plugin.
- Costs come from the endpoint's published per-token prices and Hermes's token counts, which
  include prompt caching.
- This benchmark does not measure the evidence trail, the skill gate or the SAP source map
  (editions, released APIs, communication arrangements, API policy).

### How the control found the answers

Moving the session folders out of the repository was not enough. In one flagged session, Gemini 3.8
Flash without the plugin searched the user's home directory for a field name from the requested
JSON shape (`grep -rn "required_on_create" /home/...`), found this repository, read
`eval/expected/business_partner_v2.json` and other sessions' archived answers, and ran
`eval/score.py` on its own candidate answer before replying. The other five flagged sessions read
the same kind of files.

The detector caught these because the paths appear in the tool arguments. It would not catch a
read through a relative path or a shell variable. A repeat that cannot be gamed needs the sessions
to run in a sandbox that cannot see the repository at all.

### Original round of 2026-11-06 (contaminated, kept for the record)

**Contamination notice.** 17 of the 72 sessions accessed evaluation files. The affected control
sessions were 9 Gemini 3.8 Flash runs and 3 GPT-6.1 Terra runs. With the plugin enabled, 4 Gemini 3.8
Flash runs and 1 GLM 5.3 Flash run were affected. The tables below are the results as first
published. Result file: `eval/results/20261106-115900.json`, about $3.39.

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

What we wrote about this round and how it compares with the repeat:

| Observation in the original round | In the repeat |
|---|---|
| Cost on the large contract fell about 31% for Terra and Gemini Flash | Held: 35% and 28% in money, 52% and 57% in tokens |
| Cost rose 25% for GLM, driven by one run that looped through 32 tool calls | Did not repeat: GLM cost fell 58% |
| Luna used Pathfinder in 4 of 9 plugin runs | 6 of 7 |
| GLM missed restrictions declared in external `<Annotations>` blocks without the plugin (32/36), and two GLM runs returned no JSON in both conditions | Did not repeat: GLM scored 216/216 without the plugin and 180/180 with it |
| Luna with the plugin once left a key out of the required fields | Did not repeat |
| Gemini Flash without the plugin wrote and ran its own XML-parsing scripts | Its control sessions also searched for and read the expected answers; that is why they are excluded |
