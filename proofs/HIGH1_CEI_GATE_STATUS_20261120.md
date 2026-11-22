# HIGH-1 (CEI in execute) — gate status + landing matrix — Nimbus, 2026-11-20 ~19:40 EST
Card: t_f8ade5da. Sibling: t_33f03aaf (HIGH-2). Audit origin: t_6f0ed4ed (XIXI-AUDIT-01, done 11-19),
bridge/t_6f0ed4ed_xixi_supportdone.md (Bytes:24499 | Receipt:ec693d40ee2c180f0a910732fbdb7c06834893569b67e304954f5ceffc428cbf).

## 1. Gate verdict (fresh probes this run, 19:35-19:40 EST)
- **Xixi card-2 serialized design verdict: NOT ON PC.** Bridge newest = NIMBUS_TRACKB_FLAGS.md 15:20 (pre-card).
  No card-2 artifact in OneDrive\Documents\Tanda\bridge, AppData\Local\hermes\bridge, or courier (no courier payloads since 11-16).
  No design task on board (tasks grep: only audit t_6f0ed4ed).
- **Flux GO: NOT RECORDED.** approvals/pending empty; approvals/decisions newest 13:10 (fix cards created ~19:06);
  flux_gate.log = transport registrations only (13:29, 14:15, 19:26, 19:35); FLUX_PENDING_GATES_20261119.json has no HIGH entries.
- => GATE CLOSED. Execution not started. Nothing touched: git branch/log since 17:00 shows zero fix branches/commits.

## 2. Landing matrix (what the eventual execution must do)
| Leg | Main-tree source | Live 4801 | Remaining work at gate-open |
|---|---|---|---|
| TandaBillV2.executeSettlement | FIXED (e92bc6f56 P0.1a: claims-open only, writes settledAt, NO ext calls; claimSettlement = CEI: claimedMask|=bit before transfer) | impl 0x1Cb98A8Cd9FF8058DD327d505bc80eC73Cca27A5 = PRE-P0.1a (DEPLOY_RECEIPT_V2 lineage: sources=commit 4b2ad1f, runtime sha256 9bbc47ad9c3cc738885d92244d06bdec264830bff1aad689b1414fd399a2a3d4; pinned by docs/DEPLOY_STATE.json @76d869062 from bee7347 receipt) | REDEPLOY + re-pin + loop re-proof only (code already landed 11-17; PR #5 f2433c849) |
| FastTandaBillV2.executeSettlement | **STILL CEI-INVERTED** (push loop `token.transfer` per seat BEFORE `s.settledAt`; comment 265-266 leans on hookless-USDC assumption) | impl 0x52d2b14c5f312a1547097df9c266b2047595efc7 (fast twin, loop lane; today 11:57 fasttwin_receipt re-probed claimSettlement/claimablePayout ABSENT) | CODE FIX (per Xixi card-2 design) + forge tests + redeploy + re-pin + loop re-proof |

Attempt-1 hypothesis "close as superseded-landed-on-evidence (no redeploy)" is INVALIDATED:
e92bc6f56 (11-17 11:55) is NOT an ancestor of bee7347 (11-15 22:18) => deployed canonical impl predates the fix.
Verify at gate-open if still needed: eth_getCode @0x1Cb98A8C should differ from a `forge build` of main; claimSettlement selector should eth_call-revert on both live impls.

## 3. Design state (what's known so far, audit card only — NOT card-2)
Audit HIGH-1 suggested fix (card 1, static-only): "settle-effects-first: write s.settledAt before the transfer loop (+ local executing flag). Cheap, no redesign. Mandatory."
Repo main took the P0.1a pull-claim route for the canonical twin instead (backlog option (a)) — the two-family question (does the fast twin adopt pull-claim parity or settle-effects-first?) is exactly the card-2 verdict the gate waits for.
Do NOT pre-implement either route; that is the gated decision.

## 4. Execution checklist when gate opens (staged; ~1 working session)
1. FastTandaBillV2.executeSettlement reorder per card-2 verdict (+ TandaBillV2 regression goldens if verdict touches it).
2. `forge test --match-contract` green on both twins (factory-lineage rule per tanda-forge-test-lineage skill).
3. Redeploy both impls on 4801 (pipe-only mnemonic flow; deployer 0x78dC32F6a4edF80c538A75e1F7664505B1969E7A; alchemy+thirdweb preflight chainId 4801; blob-exact LF source verification on worldscan).
4. docs/DEPLOY_STATE.json re-pin (new impl addresses + runtime sha256 + tx + block), commit via PR.
5. Re-run 41-assertion loop proof (scripts/contract_loop_proof.py lane; EVENT_SIGS per twin flavor — full-twin vs fast-twin SettlementInitiated differ);
   persist receipt+run.log to proofs/ + kanban_attach BEFORE completing (evidence law 11-20).
6. Hotspot: contracts/TandaBillV2.sol + contracts/FastTandaBillV2.sol shared with HIGH-2 (t_33f03aaf) — sequence: one folded PR per twin or HIGH-1 merges first and HIGH-2 rebases.
