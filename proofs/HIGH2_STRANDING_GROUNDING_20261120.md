# HIGH-2 stranding guard — pre-gate grounding brief (t_33f03aaf)

Nimbus recon, 2026-11-20 19:30-19:40 EST. **Design-gated card: NO execution yet.**
This file is input for Xixi card-2 (design) and the Flux GO packet.

## 1. Gate state (verified live)
- Xixi card-2 design: **NOT DELIVERED**. Bridge newest entries predate card creation
  (cards t_f8ade5da / t_33f03aaf created 11-20 19:26; newest bridge artifact = Track-B tick
  20:20Z file listing has no card-2/design file). `grep card-2` across bridge: no hits.
- Flux GO: **not recorded** (board events + FLUX_PENDING_GATES_20261119.json: no HIGH entries).
- Sibling t_f8ade5da (HIGH-1, same contract, same functions) running as run 280.

## 2. Ground truth on versions (this is the big correction)
- Xixi audit t_6f0ed4ed was run against `OneDrive/Documents/tanda/contracts/TandaBillV2.sol`
  sha256 b4c4c4cf… (17,127 B, 326 lines). Verified: that blob == `git show 4b2ad1f:…` (d230aad42 lineage)
  == **exactly what is deployed at 4801** (DEPLOY_RECEIPT_V2.json lineage: "sources = commit 4b2ad1f",
  impl 0x1Cb98A8Cd9FF8058DD327d505bc80eC73Cca27A5, worldscan-verified). Audit == deployed truth. Good.
- Repo HEAD (bfcd7a917, today) has **moved past both**: TandaBillV2.sol is now 475 lines /
  26,177 B LF git blob (disk copy 26,652 B = CRLF-mangled; canonical = git blob per lineage law).
  HEAD contains P0.1a pull-claim (e92bc6f56), split-lock + factory forwarder (61550c5df),
  Permit2 funding (250aff12a). **The fix must land on HEAD, not on the audited snapshot.**
- Audit line numbers (execute 254, refund 282, fundEscrow 167) do NOT map 1:1 to HEAD.
  F-3/HIGH-1's "execute push-loop CEI" is already dissolved on HEAD: executeSettlement only
  OPENS claims (L358-372); the push transfer loop lives only in the Fast twin now.

## 3. HEAD call-site inventory for the guard (canonical TandaBillV2.sol @ bfcd7a917)
| Line | Site | Current pattern |
|---|---|---|
| L5-8 | `interface IERC20` | declares `returns (bool)` on transfer/transferFrom |
| L242 | `fundEscrow` | `require(token.transferFrom(_caller(), address(this), amount), TokenTransferFailed())` — bool-require; CEI also inverted (escrowBalance after call) |
| L266 | `fundEscrowFromPermit2` | Permit2 `transferFrom` is **void** — no return checked at all; escrowBalance += unconditionally |
| L398 | `claimSettlement` (PULL-CLAIM LEG) | `require(token.transfer(seats[seatId].wallet, amount), TokenTransferFailed())`; claimedMask set before call (L397, CEI correct) |
| L415 | `refundSettlement` | `require(token.transfer(owner, s.totalAmount), …)` |
Fast twin `contracts/FastTandaBillV2.sol` (loop lane, impl 0x52d2…, factory 0x65ba0bb4…, token Circle Sepolia USDC 0x66145f38…): same pattern at L234 (transferFrom), L258 (Permit2 void), L358 (push-loop transfer), L381 (refund).

## 4. Risk classes made precise (why HEAD is WORSE for class A than audited version)
- **A. no-return-value token (USDT/ZRX-style)**: call through bool-returning interface → empty returndata →
  Solidity decode revert. On legacy `fundEscrow` this is caught at funding (DoS, no stranding). BUT
  `fundEscrowFromPermit2` (HEAD only!) funds successfully because Permit2's transferFrom is void.
  Then **every** `claimSettlement` reverts at L398; after execute, `refundSettlement` is blocked by
  `fullyConfirmedAt != 0` → **all seats' funds permanently stranded**. HEAD introduced this asymmetry;
  the audited W6 snapshot had no Permit2 leg. HIGH-2 severity at HEAD > audit's assessed HIGH-2.
- **B. fee-on-transfer token**: bool true passes all requires, but delivered < recorded. Escrow-in fee:
  escrowBalance overstates actual balance → last claims revert on token's own underflow → partial
  stranding, no escape (same refund guard). Escrow-out fee: seats silently underpaid; claimedMask says
  paid; residual dust unclaimable → violates "deterministic escrowBalance == 0" proof H2 (which held only
  under the standard-token assumption the audit flagged).
- **A'. returns-false-without-reverting token**: bool-require reverts everywhere — no stranding (already guarded).
- Live 4801 lane is Circle USDC (standard, bool-true, no fee, no hooks — loop proof 41/41 through the
  bool-require path is behavioral proof). MVP product surface = World App mini-app; factory
  `createBill(token, roster)` accepts **any** token address → class A/B reachable by creator error
  even if UI "means USDC".

## 5. Design options for Xixi card-2 (inputs, not decisions)
- **O1 SafeERC20-style guard** (task body option): minimal internal lib — low-level call,
  `ok && (returndatasize == 0 || abi.decode(bool))`. Fixes A (works with USDT-style), does **NOT** fix B.
- **O2 Token allowlist / standardness attestation at initialize** (audit option a): pin canonical USDC
  per chain in factory/clone init, revert others. Kills A+B at the boundary, zero gas at payout legs,
  matches MVP (USDC-only World Chain). Cost: no multi-token future without a registry.
- **O3 Hybrid**: O1 + balance-delta accounting (balanceOf diff on escrow-in; delivered==payout check on
  claim) — complete A+B fix, +~4-6k gas/claim, no custody added.
- **O4 Owner sweep** (audit option b): ⚠️ collides with kill-pass invariant 1 ("No key custody: no
  upgrade, no pause, no recovery"). A residual-sweep function is a recovery key. Xixi card-2 should
  treat O4 as presumptively rejected unless invariant-1 wording is re-ruled.
- Open sub-gate carried from audit §G: "needs d3b0m3n ruling on invariant-1 wording" — per OWNER LAW
  11-19, Flux is approver of record; route inside the GO packet, not to owner.

## 6. HIGH-1 × HIGH-2 collision (same file, same functions)
Both fix cards touch `TandaBillV2.sol` fund/claim/refund lines. On HEAD, HIGH-1's remaining live
surface = `fundEscrow` CEI inversion (L241-242) (+Permit2 variant L263-268); audit's execute-loop F-3
is already gone on the full twin but IS live on the Fast twin (L344-360). Recommend: single PR per twin
folding CEI reorder + token guard, or HIGH-1 merges first and HIGH-2 rebases — never two open branches
editing the same 5 call sites. hotspot: contracts/TandaBillV2.sol and contracts/FastTandaBillV2.sol.

## 7. Execution checklist once gate clears (forge goldens + redeploy + re-proof)
1. New mocks in test/: `NoReturnToken` (void transfer/transferFrom, USDT-style), `FeeOnTransferToken`
   (bps fee), `ReturnFalseToken`. Existing: MockToken, BlockableToken, FailingToken, TestToken.
2. Goldens: full lifecycle A + B on BOTH twins; class-A Permit2-funded bill ⇒ claim reverts vs passes
   per chosen design; deterministic escrow invariant `sum(delivered deltas) + refund == accepted-balance delta`.
3. Factory lineage per tanda-forge-test-lineage skill: `new TandaBillFactory(address(new TandaBillV2()))`,
   pranked creator; never bare initialize from test contract.
4. Redeploy BOTH 4801 impls (full 0x1Cb9-replacement + fast 0x52d2-replacement), re-verify worldscan
   (blob-exact LF payload — CRLF metadata-hash pitfall already documented in DEPLOY_RECEIPT_V2),
   re-pin `docs/DEPLOY_STATE.json` + DEPLOY_RECEIPT_V2.json.
5. Re-run 41-assertion loop proof (lane per tanda-loop-lane-ops: :8096 indexer, RPC pair, EVENT_SIGS
   per-twin, receipts to proofs/ AND card attachments before completion — evidence law).
6. Sequencing vs t_f8ade5da (HIGH-1) per §6.

## Receipts (recomputed this turn)
- git blob HEAD contracts/TandaBillV2.sol: 26,177 B, `git hash-object` of disk copy 154caaee7ebafdca13e8d368c7d0832dc970ffce (CRLF-mangled disk copy, 26,652 B, sha256 2f72841312390208…)
- HEAD blob content = `git show HEAD:contracts/TandaBillV2.sol` (26,177 B)
- audited copy: 17,127 B sha256 b4c4c4cff582e57b5747ec099eb2a8038c238eb00c4ebfa7c475e239f67d1c28 == 4b2ad1f blob (deployed lineage) — MATCH
- deployed impl: 0x1Cb98A8Cd9FF8058DD327d505bc80eC73Cca27A5 @4801 runtime sha256 9bbc47ad…, verified
- loop token: 0x66145f38cBAC35Ca6F1Dfb4914dF98F1614aeA88 Circle USDC Sepolia (standard)
