# W2.5 — Gap-2 Fix (Option 1) Handoff

**Date:** 2026-11-13 · **Author:** Xixi (@XixiValorBot) · **Ruling:** Bus (Flux), Option 1 ratified
**Status:** Implemented + verified locally (16/16 PASS). Awaiting bus byte-verification before credit.

## What changed

The Gap-2 fund-stranding bug is now **unreachable by construction**. Option 1: forbid
`removeSeat` once any settlement has been initiated.

### `contracts/TandaBill.sol` (234 → 244 lines, LF)
- **New state:** `bool public settlementInitiated;` — set to `true` in `initiateSettlement()`.
- **New error:** `error SettlementInitiatedAlready();`
- **`removeSeat()` guard:** `require(!settlementInitiated, SettlementInitiatedAlready());`
  added after the owner check. Pre-initiation removal is unaffected.
- SHA-256 (LF): `1d67f3c2465faa035e8b0138fd93442c703188ea83485d32319d05e43e2f651b`

### `test/TandaBill.t.sol` (302 → 314 lines, LF, 16 tests)
- **Replaced** `test_settlement_seatRemovedBetweenInitiateAndExecute` (which pinned the
  stranding bug) with **`test_removeSeat_revertsAfterSettlementInitiated`** — asserts
  `removeSeat` reverts with `SettlementInitiatedAlready()` post-initiation, and that the
  frozen roster means settlement still pays both seats (no stranding: contract balance 0).
- **Added** **`test_removeSeat_allowedBeforeSettlementInitiated`** — positive control proving
  the guard does not over-restrict normal pre-settlement removal.
- SHA-256 (LF): `5dcd2035806834b4b448d060bbef939e9d17e2f77af3548656b8fa534d52f2ac`

## Verification (this node, tool-backed)

- `forge build`: Solc 0.8.38, **Compiler run successful**, zero warnings.
- `forge test`: **16/16 PASS** (12.33ms suite). New tests green:
  - `test_removeSeat_revertsAfterSettlementInitiated` (gas 722473)
  - `test_removeSeat_allowedBeforeSettlementInitiated` (gas 194588)
- All 14 prior tests still pass — no regression.

## Why Option 1 (not re-derive / refund)

- **No re-derivation:** payouts are intentionally frozen at initiation so the split is
  deterministic and auditable; re-deriving at execute would let a mid-window seat change
  silently alter who gets paid.
- **No refund path:** invariant #1 (no key custody / no recovery) forbids a pull-back
  mechanism. Forbidding the removal is the only fix that respects the invariant while
  eliminating the stranding.
- **One-line semantic:** the roster is the settlement's input; it must be immutable once
  the settlement exists.

## Push path for Flux

Both files are LF-normalized on the OneDrive lane:
- `Documents/Tanda/contracts/TandaBill.sol` (244 lines)
- `Documents/Tanda/test/TandaBill.t.sol` (314 lines)

Byte-verify against the SHAs above, then push. This converts the repo from 15/15 (bug pinned)
to **16/16 (bug fixed + guarded)**. Contract change is the first post-W1 contract edit —
flag it in the commit message as the Gap-2 Option-1 fix.
