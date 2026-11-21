# XIXI-DESIGN-02 — Contract hardening design verdict (CEI reordering + token-stranding guard)
FROM: Nimbus (CoS, PC) | APPROVER: Flux | EXECUTION LANE: Xixi serialized card :13305 via Harley ONLY
STATUS: DRAFT-AWAITING-HARLEY-SERIALIZATION — laptop card creation is Harley's action; Xixi is never chat-tagged.

## Context (inputs, all reachable read-only)
- Repo: FluxNimbusAi/tanda @ main cdb6b4fae36d (contracts/TandaBillV2.sol; canonical git-blob anchor db4ac0cf, 24364 B LF — disk copies may be CRLF-mangled, hash the blob).
- Prior audit: XIXI-AUDIT-01 receipt (PC mirror bridge/t_6f0ed4ed_xixi_supportdone.md, 24,556 B dea341e2...5a3b9e) — both HIGHs originate there; state machine otherwise sound, rounding lossless.
- ADR-0010 (Permit2 single-tap funding), docs/adr/ADR-0010*.
- Testnet proof context: phases 1-11 green (41/41 run 266, FastTandaBillV2 twin; main-ABI bill 0x2032cc...).

## Question 1 — CEI-in-execute (HIGH-1)
execute() currently performs external interactions before all state writes. Design the corrected ordering:
a) full state-transition-first (marks/deltas) then effects; or b) two-pass (validate+snapshot, then interact). 
Rule out reentrancy gaps in the per-seat pull-claim loop (claimedMask updates, escrowBalance decrement ordering); state gas impact (<=+? sstore ordering, warm slots); what test evidence closes it (forge goldens + invariant that escrowBalance >= sum(unclaimed) at every internal point).

## Question 2 — non-standard-token stranding (HIGH-2)
transferFrom/transfer on tokens without return values or with fee-on-transfer can strand settlement funds. Compare designs:
a) SafeERC20-style internal (low-level call + success/return-data check) — vendored vs hand-rolled minimal; 
b) explicit supported-token allowlist + admin-gated extension; 
c) push-claim amount reconciliation (accept delivered amount vs claimed). 
Pick for mainnet-class USDC/CCTP compatibility (World Chain 480 architecture) and say what it does NOT protect against.

## Deliverable (exact shape)
Single JSON verdict: {decision_q1, rationale_q1, diff_sketch_solidity_q1, test_plan_q1, decision_q2, rationale_q2, diff_sketch_solidity_q2, test_plan_q2, risk_notes[], gas_notes}
+ card receipt: sha256(UTF-8 JSON, LF-normalized) full 64-hex + Bytes, delivered laptop->PC via Harley's [SUPPORT-DONE] format.
PC-side execution (t_f8ade5da / t_33f03aaf, pre-work attached to both cards) starts only after Flux signs GO on the verdict.
