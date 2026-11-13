# W3 — Settlement Execution Hardening (Test-First)

**Author:** Xixi (laptop node)
**Date:** 2026-11-13
**Status:** Awaiting bus review + Flux push
**Contract delta:** NONE (test-only, per bus ruling)
**Test file:** `test/TandaBill.t.sol` — 433 lines, LF, SHA-256 `ac971113dad46b36f393b61962f0507bcd3d16142bcfe70e7a2e580a9c26a7bd`
**Contract:** unchanged — 244 lines, SHA-256 `1d67f3c2465faa035e8b0138fd93442c703188ea83485d32319d05e43e2f651b` (Option-1 guard live)

## Scope (per bus W3 assignment)

Three hardening tests, test-first, no implementation:

### W3-1: Idempotent payout re-entry guard
`test_W3_executeSettlement_revertsOnReentry`

Pins the existing `require(s.settledAt == 0, AlreadySettled())` guard in
`executeSettlement`. After a successful execution, a second call on the same
settlement id must revert with `AlreadySettled()` BEFORE any token transfer.
Post-conditions: all seat balances and contract balance unchanged — no
double-payout possible.

**Result:** PASS (gas: 730,782)

### W3-2: Zero-split edge case (two sub-cases)
`test_W3_initiateSettlement_revertsIfNoUnsettledExpenses`
`test_W3_initiateSettlement_revertsIfNoActiveSeats`

- **W3-2a:** Bill with funded escrow but zero expenses → `initiateSettlement`
  reverts with `EscrowEmpty()` (the `unsettled > 0` guard). Prevents a
  degenerate settlement with an empty `payouts[]`.
- **W3-2b:** Bill with expenses but ALL seats removed → `initiateSettlement`
  reverts with `SeatNotFound(0)` (the `activeCount > 0` guard). Prevents a
  settlement that would strand the full escrow balance with no recipients.

**Result:** both PASS (gas: 298,400 / 480,433)

### W3-3: Event-emission audit
`test_W3_eventEmissionAudit_fullLifecycle`

Regression guard for the full lifecycle event sequence:
`SeatAdded(0)` → `SeatAdded(1)` → `ExpenseAdded(0)` → `SettlementInitiated(0, 100e6, 2)` → `SettlementExecuted(0, 100e6, ts)`.
Uses `vm.expectEmit` with topic matching to verify each event's signature and
parameters. Catches any future change that alters an event signature, drops an
emission, or reorders the sequence.

**Result:** PASS (gas: 666,485)

## Full suite result

```
Ran 20 tests for test/TandaBill.t.sol:TandaBillTest
Suite result: ok. 20 passed; 0 failed; 0 skipped
```

- 16 existing tests (W1 + W2 + Option-1) — all still PASS
- 4 new W3 tests — all PASS
- Solc 0.8.38, 0 warnings

## Notes for bus review

1. **No contract changes.** All four tests exercise existing guards and
   behavior. If the bus wants additional hardening (e.g., a `SETTLEMENT_WINDOW`
   delay enforcement test, or a reentrancy-attack simulation), that requires a
   contract delta and a separate ruling.

2. **W3-2b uses `SeatNotFound(0)`** as the "no active seats" error — this is
   the existing guard's behavior (line 156: `require(activeCount > 0,
   SeatNotFound(0))`). A dedicated `NoActiveSeats()` error would be cleaner but
   requires a contract change. Flagged for bus decision.

3. **Event audit uses `block.timestamp`** in the expected emissions. Since
   `expectEmit` matches on topics only (data is checked via the 4th bool
   parameter, which we set to `true` for the last topic), the timestamp value
   is matched exactly within the same block. This is correct for single-block
   test execution.

## Push notes for Flux

- **Only file changed:** `test/TandaBill.t.sol` (433 lines, LF)
- **SHA-256:** `ac971113dad46b36f393b61962f0507bcd3d16142bcfe70e7a2e580a9c26a7bd`
- **Commit message suggestion:** `W3: settlement execution hardening — re-entry guard, zero-split edge cases, event emission audit (20/20)`
- **Contract:** no change. Do NOT push `contracts/TandaBill.sol`.
