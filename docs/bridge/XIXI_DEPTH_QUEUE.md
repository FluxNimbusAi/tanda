# XIXI DEPTH-QUEUE (standing, serialized :13305 via Harley courier — one card at a time, head first)
Owner cost ruling 2026-11-21: free local 27B = $0/card; route ALL non-SLA depth-class work here.
Harley pulls HEAD when :13305 is idle, marks IN-FLIGHT, posts verdict JSON + full-64-hex receipt to bridge,
then Flux validates on recompute. Never chat-wake Xixi; never intake; self-reports unverified until recomputed.

| # | Card | Class | Inputs (repo-side, zero network) | Deliverable | Est. her sessions |
|---|------|-------|----------------------------------|-------------|-------------------|
| 1 | XIXI-DESIGN-02 — CEI reordering + token-stranding guard designs | adversarial design | FluxNimbusAi/tanda docs/bridge/XIXI_DESIGN_02_BRIEF_20261121.md (sha256 adc7e5924466ed58fc786e17e28d20d7e1a1e30c5fda07da0cb5c0442e5c9bb6) | JSON verdict {decision/rationale/diff_sketch/test_plan per Q} | IN QUEUE (Harley) |
| 2 | MED-3 256-transfer gas cap — batched-execute vs MAX_SEATS cap design | adversarial design | tanda contracts/TandaBillV2.sol execute() payout loop @ main; her own card-1 receipt (24,556 B dea341e2...5a3b9e) | JSON: two-option cost model (gas/seat, worst-case block gas), doc-acceptable-MVP verdict, patch sketch | 1 |
| 3 | Roster-freedom / event-ordering MEDs full disposition | deep audit | same receipt lines; ADR-0001..0010 index (tanda#23) | JSON per-MED: accept/mitigate/fix-now with rationale | 1 |
| 4 | #5226 defect-locus second opinion (RESERVED — do not start before probe data) | contested adjudication | probe_5226_results_ON/OFF JSON + thread datapoints (sauris 11-13/11-16) | JSON: model-side vs reader-side locus call with reasoning chain | 0.5 |
| 5 | Indexer-hardening pre-flight kill-pass | design pre-review | services/bill_index.py @ cdb6b4fae36d; overlap-guard + last_indexed_block spec (t_0222f1e6 notes) | JSON: defect classes in proposed re-poll logic BEFORE cloud lanes execute | 1 |
| 6 | Strata fold vs upstream drift semantic review | forensics | fork main ebfefb586ce2 vs Niko main tip; parserdrift token in relief probe | JSON: any semantic collision class in the 277-commit drift touching frontend.py/tool_parser.py | 1 |
| 7 | Cross-skill law-consistency sweep post-11-20/21 amendments | consistency audit | hermes skills trees (root + profiles/nimbus) — 20+ laws edited in 48h; ghost-triage, two-tier hex, transport, ladder | JSON: contradicting rule pairs + stale-clause candidates; mechanical recheck by Nimbus after | 1 |
| 8 | TandaBill full test-suite audit (forge + unittest + vitest goldens) | long-file forensics | tanda-sync tests/, proofs/, miniapp src/**/__tests__ | JSON: coverage gaps vs ADR claims; pinned-test drift list | 2 |

RULES OF ENGAGEMENT
- Head-of-queue only; card body must be self-contained (repo anchors + deliverable shape) or Harley rejects at serialization.
- Card-2 brief already satisfies this; cards 2-8 briefs are Nimbus-authored on demand (10-min each, cloud-cheap) BEFORE Harley pulls.
- Cost ledger: each card ≈ a 10-30k-token cloud job done for $0.5 savings at Flash rates; queue depth is the point.
- Slot 4 stays BLOCKED until probe lands — marking it reserved prevents a misfire.
