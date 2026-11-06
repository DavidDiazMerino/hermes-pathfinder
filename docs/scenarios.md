# Two real sessions

Both run on 2026-11-06 with Hermes v0.23.0 and `google/gemini-4-argon`, in a profile with the plugin
enabled, through `hermes chat`. The prompts did not mention the plugin. Pathfinder held no answer to
either question: Hermes found them in official SAP sources, read live, and cited each one.

## 1. The SAP expert: a PM consultant moving to clean core

> "I have been a PM consultant for 10 years. A custom program reads tables AUFK and AFIH and creates
> orders with BAPI_ALM_ORDER_MAINTAIN. We are moving to S/4HANA Cloud Public Edition with clean core.
> What still works, what doesn't, and what do I use instead? Don't explain PM to me."

What Hermes did: asked `pathfinder_sources` for the recipe ("is this object released?" → SAP's
Cloudification Repository, one file per edition), read the files with `pathfinder_read` (10 MB JSON,
only the entries needed), and the Help Portal pages for the APIs with `web_extract`.

What it answered (each item checked afterwards against SAP's files):

- `AUFK`: not to be released; SAP's successor is `I_ORDER`.
- `AFIH`: not in the released list of either edition; said so instead of guessing.
- `BAPI_ALM_ORDER_MAINTAIN`: classified only as a classic API (usable for tier-2 wrappers on Private
  Edition / on-premise), not released for ABAP Cloud.
- Reading: the released maintenance-order model (`I_MAINTENANCEORDERTP`, `I_MAINTENANCEORDERBASIC`,
  operations, status, phase control) or `I_MAINTENANCEORDERDEX` for extraction.
- Writing: the RAP business object `I_MAINTENANCEORDERTP` with EML on-stack, or the published
  `API_MAINTENANCEORDER;v=2` for side-by-side, noting version 1 is deprecated.
- A detail it found on its own: `I_MAINTORDEROPCOMPONENTTP` is deprecated in Public Edition with
  successor `I_MAINTORDEROPCOMPONENTTP_2`, while still released in Private Edition.

Evidence: 14 sources recorded, all official (3 Cloudification Repository files, 11 Help Portal pages).
Cost about $0.49, 11 minutes, 33 tool calls.

## 2. The newcomer: Integration Suite learner on a SuccessFactors project

> "I'm learning SAP Integration Suite and was just put on an integration project with SuccessFactors.
> I don't even know what SuccessFactors is. I need to send new employees to another system. Where do I
> start?"

What Hermes did: the recipes sent it straight to the official documents (SuccessFactors reference
architecture, Compound Employee API guide, Integration Center guide, SAP Learning's Employee Central
OData API course). It made no web search at all.

What it answered:

- What SuccessFactors and Employee Central are, and the entities that hold an employee
  (`PerPerson`, `PerPersonal`, `EmpEmployment`, `EmpJob`).
- The trap that loses new hires: without `fromDate`/`toDate` the OData API returns only records valid
  today, so future-dated hires are missed.
- A detail it found on its own: with Onboarding, the employment exists before the hire is completed
  (`hiringNotCompleted = true`); filter it or you will send candidates.
- Options in the right order: prepackaged content on the Business Accelerator Hub first, then an iFlow
  with the OData V2 adapter, the Compound Employee API in delta mode, or hire events in real time.
- Five questions to settle before building, and what it had not verified.

Evidence: 9 sources recorded, all official. Cost about $0.38, 5 minutes.

Gap seen and fixed: it did not ask about the tenant's data center (API host), the technical user's
permissions or OAuth SAML Bearer, which a newcomer does not know to ask. Recipes now carry the
questions to settle before starting.
