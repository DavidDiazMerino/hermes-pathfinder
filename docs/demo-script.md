# Demo script (under 90 seconds)

Every step below has been run for real with Hermes v0.23.0. Record in the Hermes TUI or Desktop, in a
clean profile with the plugin enabled and an empty ledger, so the gate refusal in step 4 happens live.

| Time | Screen | Voice-over |
|---|---|---|
| 0–8 s | Title card, then a Hermes chat | "Can Hermes learn enterprise software instead of guessing it?" |
| 8–18 s | `hermes plugins enable enterprise-pathfinder`; `/pathfinder status` | "One plugin: a map of SAP's official sources, a contract inspector, a lab, and an evidence ledger." |
| 18–32 s | Prompt: *"I'm new to SAP. Which Business Partner entities can I create, with which mandatory fields?"* Hermes calls `pathfinder_sources`, then `pathfinder_inspect` | "Hermes orients itself with SAP's own sources and reads the real contract with a deterministic parser, not by eyeballing XML." |
| 32–46 s | Prompt: *"Save a skill for this right away, skip testing."* The `skill_manage` call is refused by the evidence gate; the refusal message is visible | "It wants to save what it learned. The gate says no: nothing untested becomes a skill." |
| 46–58 s | Hermes calls `pathfinder_lab` with its own claims and payloads; 23/23 pass; `skill_manage` succeeds | "So it tests its own claims, including payloads that must fail. Verified, it earns the skill." |
| 58–74 s | New session, V4 Product contract. First call: `skill_view` of the learned skill; then inspect, lab, a new V4 skill | "Next contract, different OData version. Hermes reuses what it learned, keeps the V2 rule out of V4, and proves the new one." |
| 74–84 s | `/pathfinder status`: runs, statuses, skills backed by evidence; eval table (with vs without plugin) | "Every skill traces back to evidence you can check." |
| 84–90 s | Repo URL; "SAP today. Every enterprise domain tomorrow." | "Unofficial community project. Never calls SAP APIs." |

Notes

- `hermes chat -q --format stream-json` does not emit refused tool calls; record the gate refusal in the
  TUI or Desktop, where it is shown.
- Label the contracts as synthetic samples on screen.
