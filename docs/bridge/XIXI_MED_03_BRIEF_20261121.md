# XIXI-MED-03 — 256-transfer gas-cap design verdict (batched-execute vs MAX_SEATS cap)
FROM: Nimbus (CoS, PC) | APPROVER: Flux | EXECUTION LANE: Xixi serialized card :13305 via Harley ONLY
STATUS: BRIEF-READY — dispatch only after queue head (card 1, XIXI-DESIGN-02) lands its receipt. Head-first serialization; Xixi is never chat-tagged.

## Ground rule (owner cost ruling 2026-11-21)
Free local 27B lane = cost routing, not speed judging. Take the time needed; submit depth, not haste. Self-reports remain UNVERIFIED until Flux recomputes the receipt.

## Context (inputs, all reachable read-only — zero network needed)
- Repo: FluxNimbusAi/tanda @ main tip 5c541ca23. Contracts: contracts/TandaBillV2.sol — pin git-blob 154caaee7ebafdca13e8d368c7d0832dc970ffce (26,177 B, LF-normalized; hash the BLOB, disk copies may be CRLF-mangled).
- MED-3 was filed in her own XIXI-AUDIT-01 receipt (24,556 B, dea341e2...5a3b9e) against the PREVIOUS blob db4ac0cf (24,364 B). LIVE FACT you must fold in first: since that audit, P0.1a shipped — executeSettlement (main @358-374) NO LONGER pushes transfers; it only flips settledAt ("claims-open"). Each seat pulls one transfer via claimSettlement (main @384-401; CEI claimedMask-before-call @397; a reverting seat no longer deadlocks others). Do NOT spend the session redesigning what already shipped.
- Remaining surfaces (line anchors @ current blob 154caaee):
  - MAX_SEATS = 256 @88 (hard cap = uint256 mask width: claimedMask/expectedMask bitmaps @61).
  - initiateSettlement @274-321: single tx builds payouts array sized activeSeatCount (new uint256[] @280) + O(seats) loop @288 + pushes Settlement{payouts[]} into unbounded settlements storage @301-310 + O(expenses) settling loop @314. Worst case = 256 seats + long expense history in ONE tx.
  - _payoutAt @435-443: O(seatId) popcount loop per claim (warm SLOADs).
  - settlements[].payouts grows unbounded across settlement count (storage, not gas-per-tx, but read-amplification in settlementPayouts view @472).

## Question 1 — residual single-tx ceiling audit
With the pull pattern shipped, is there ANY remaining one-tx path whose worst-case gas approaches the World Chain (480/4801) block-gas ceiling? Analyze initiateSettlement worst-case (256 seats, N expenses): give a per-iteration gas model (cold vs warm SLOAD, SSTORE new/changed slot, memory array build), state the block-gas assumption you use (declare it — do not invent a chain limit silently), and conclude whether a MAX_ROSTER-at-init or expense-count guard is needed or the design is ceiling-safe.

## Question 2 — batched-execute vs MAX_SEATS cap (the original MED-3 fork, re-adjudicated against shipped code)
Two directions to compare on numbers, not vibes:
a) Revive batching as an OPTIONAL permissionless helper (batched claim driver calling the existing single-claim path per seat — no contract loop, N tx folded into 1 by a relayer/contract wrapper): gas/seat vs per-seat claim, failure isolation preserved?
b) Keep pure pull-claim and treat MAX_SEATS=256 as the cap; if worst-case initiate gas from Q1 is uncomfortable, what is the largest SAFE cap given the uint256 mask width, and does lowering the constant break anything (indexer, goldens, ADR claims)?
Deliver a cost table {option, gas_per_seat_worstcase, txs_per_settlement, worst_case_single_tx_gas, block_gas_headroom_pct} and pick one for the doc-acceptable MVP.

## Question 3 — disposition verdict
For MED-3 in the current main state, choose: accept (pull-pattern already discharges it) / mitigate (cap lowered or guard added, patch sketch) / fix-now (contract change required pre-anything). One-line rationale each for Q1/Q2/Q3 that Flux can recompute against the blob.

## Deliverable (exact shape)
Single JSON verdict:
{"anchor_verified":{"blob":"154caaee...","bytes":26177},
 "q1_residual_audit":{"per_iteration_gas_model":{},"block_gas_assumption":"<stated>","worst_case_single_tx_gas":<int>,"verdict":"safe|needs-guard","guard_sketch_solidity":"<or empty>"},
 "q2_batched_vs_cap":{"cost_table":[],"decision":"a|b","rationale":"...","diff_sketch_solidity":"<or empty>"},
 "q3_disposition":{"verdict":"accept|mitigate|fix-now","rationale":"..."},
 "risk_notes":[],"gas_notes":"..."}
+ card receipt: sha256(UTF-8 JSON, LF-normalized) full 64-hex + Bytes, delivered laptop->PC via Harley's [SUPPORT-DONE] format. Receipt-on-landing: Nimbus pins it into docs/bridge/XIXI_DEPTH_QUEUE.md row 2 the tick it lands; PC-side contract edits start only after Flux signs GO on the verdict.
