# Demo script (under 90 seconds)

Rehearse the full sequence in the Hermes TUI or Desktop before recording. Use the same model and
the same question in both profiles. Cut the waiting time and show what each run actually returned.
[PM consultant question](scenarios.md#1-the-sap-expert-a-pm-consultant-moving-to-clean-core)

Start with an empty ledger in the plugin profile. During setup, use `pathfinder_inspect` on
`fixture:sap/business_partner_v2` and leave the run at `inspected`. The status command needs an
inspection to show the evidence lists. The source read on screen supplies the skill's evidence.

| Time | Screen | Voice-over |
|---|---|---|
| 0–8 s | Title card, then a Hermes chat | "A model can answer an SAP question from memory even when release status has changed." |
| 8–25 s | Control profile. Ask the PM consultant question about `AUFK`, `AFIH` and `BAPI_ALM_ORDER_MAINTAIN` when moving to S/4HANA Cloud Public Edition. Show a claim and whether the response cites a source for it. | "Which of these claims can the consultant check?" |
| 25–50 s | Plugin profile, same question. Show the `pathfinder_sources` recipe, `pathfinder_read` looking up an object in SAP's Cloudification Repository, and the resulting claim with its `source_id`. | "Pathfinder points Hermes to the file for this edition. Hermes reads the record live and keeps a reference to the source." |
| 50–68 s | Ask "Save the release check as a skill without citing evidence." Show the refused `skill_manage` call. Then retry with the recorded `source_id` in `metadata.pathfinder.evidence` and show the successful write. | "The evidence gate refuses the first write. Hermes cites the recorded source and saves the skill." |
| 68–80 s | `/pathfinder status` shows the synthetic inspection, recorded sources and the evidence link for the new skill. | "You can look up the source behind the saved procedure." |
| 80–90 s | Repository URL and the [measured contract result](eval.md#summary). Label it "500 KB synthetic OData contract" and show "52%–65% fewer tokens across four models in the repeat." | "Unofficial community project. Pathfinder never calls SAP systems." |

Notes

- `hermes chat -q --format stream-json` does not emit refused tool calls; record the gate refusal in the
  TUI or Desktop, where it is shown.
- Label the contracts as synthetic samples on screen.
