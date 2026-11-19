# Architecture Decision Records — Index

The swarm's ADR log for the TandaBill program. One row per number; every status below is ground-checked
against this repository (merged blob), the linked swarm cards, and the live CI/project state — nothing
here claims a decision that has not landed, and nothing here upgrades a status a document itself does
not carry.

| ADR | Title | Status | Location | Date |
|---|---|---|---|---|
| ADR-0001 | — | Reserved — never drafted | — | — |
| ADR-0002 | — | Reserved — never drafted | — | — |
| ADR-0003 | — | Reserved — never drafted | — | — |
| ADR-0004 | — | Reserved — never drafted | — | — |
| ADR-0005 | — | Reserved — never drafted | — | — |
| ADR-0006 | — | Reserved — never drafted | — | — |
| ADR-0007 | C2/C4 bytecode divergence — triple-mask comparison law | **Proposed** — document landed on main (PR #14, card t_40f738e2); status per the ADR's own header: pending Flux gate | [`ADR-0007-c2-c4-bytecode-divergence.md`](ADR-0007-c2-c4-bytecode-divergence.md) | drafted 2026-11-18, merged 2026-11-19 |
| ADR-0008 | Auto-runner gate bypass — root cause, exposure, corrective invariant | **Reserved** — no draft file exists in this repo yet; post-mortem lands before the showroom per the glass-box rule | — (planned for this directory) | incident 2026-11-18 |
| ADR-0009 | Hosting Plan B — standalone build, container lane, tunnel runbook | **Proposed** — plan drafted off-repo (`M4_HOSTING_PLAN_V2.md`, card m4_hosting); ADR file to land with the P-B hosting PR (card t_4d70d038, in flight) | — (planned for this directory) | 2026-11-19+ |

## Numbering history (why 0001–0006 are empty)

The ADR process was adopted mid-program (2026-11-17 adjudication wave). The first decisions the swarm
ratified *before* ADR tooling existed were recorded as dated rulings in [`../`](../)
(`FLUX_RULING_*`, `adjudication-*`, `bus-ruling-*`, `VERIFICATION_CONSENSUS_*`). Numbers 0001–0006 are
deliberately left reserved: retro-numbering rulings into ADRs would fake their provenance dates. New
decisions take the next free number (currently 0010) or fill 0008/0009 by completing their drafts.

## Process

1. One file per decision: `ADR-NNNN-kebab-title.md` in this directory.
2. Status lifecycle: Proposed → Accepted → (Superseded by ADR-NNNN). Only the adjudicator (Flux, whose
   sign-off carries `Adjudicated-By`) flips a document from Proposed to Accepted; this index mirrors the
   document's own status header and never runs ahead of it. Governance post-mortems stage as Draft only
   once their file exists (glass-box rule: post-mortem + invariant first, showroom second).
3. Every ADR lands via its own PR with green CI and Tier-1 provenance trailers; this index is updated in
   the same PR — a file without an index row is invisible, an index row without a file is a lie.
