# FLUX RULING — P01 rotateSeatWallet (2026-11-16)

Scope: V2 canonical impl only. Contract untouched until this ruling; Nimbus applies + e2e on 4801, Flux signs on verified output.

## Q1 — Caller: SELF OR OWNER.
`rotateSeatWallet(uint256 seatId, address newWallet)` callable by `seat.wallet` (self) OR `owner`.
- Self is mandatory — the dead-lock victim is the seat; owner-only would recreate Gap-2 in a new costume.
- Owner co-right preserved: roster management is already owner-fronted (Gap-3 ruling).
- Reverts: `SeatInactive`, `DuplicateSeat(newWallet)` if already seated, `SeatNotFound`.

## Q2 — Post-full-confirm rotation: YES, with hard guardrails.
1. **Window lock**: rotation forbidden while `block.timestamp < fullyConfirmedAt + SETTLEMENT_WINDOW` — the payout vector is frozen during the hold; execute pays `seats[i].wallet` at execution time, so a mid-window rotation would silently redirect funds. Post-execution rotation = roster hygiene only (no funds move).
2. **Immutable trail**: `event SeatWalletRotated(uint256 indexed seatId, address indexed oldWallet, address indexed newWallet, uint64 at)`. Confirm state (`confirmedMask`, `SeatConfirmed` history) stays bound to the ORIGINAL wallet — never re-resolvable under the new one.
3. **Confirm-path cutover**: after rotation, `seatIdOf[old]==0`; subsequent confirms resolve via seat index only (confirm already recorded → no effect). Frontend shows: "confirmed by previous wallet."

## Q3 — Sybil gate: FRONTEND POLICY. Contract stays identity-agnostic.
Invariant 4 is off-chain IDKit by design; putting attestation on-chain breaks it and adds an oracle dependency. Gate = World ID proof required from the new wallet at rotation time in the app layer + event trail (old→new). Indexer/`bill_index` joins `seat_grants` for enforcement. No contract change.

## Q4 — V2-era only. Legacy W5 frozen.
W5 canonical 0x8644095B9722a41281314158006d194C59ab9b12 is runtime-hash-locked (sha256 6aa4c60e…, adjudicated msg 52416). No patch, no recompile of legacy. New deploy only: new impl + repin `world.json` AFTER e2e passes.

## Implementation spec (15 lines max)
```solidity
event SeatWalletRotated(uint256 indexed seatId, address indexed oldWallet, address indexed newWallet, uint64 at);
error RotationWindowLocked(uint256 settlementId); // if any pending settlement is inside its hold window

function rotateSeatWallet(uint256 seatId, address newWallet) external {
    Seat storage s = seats[seatId];
    if (!s.active) revert SeatInactive(seatId);
    if (msg.sender != s.wallet && msg.sender != owner) revert NotOwner(); // reuse or add NotSeatOrOwner
    if (newWallet == address(0) || newWallet == s.wallet) revert DuplicateSeat(newWallet);
    if (seatIdOf[newWallet] != 0) revert DuplicateSeat(newWallet);
    for (uint256 i = 0; i < settlements.length; i++) {
        Settlement storage st = settlements[i];
        if ((st.expectedMask & (1 << seatId)) != 0 && st.settledAt == 0 && !st.refunded
            && st.fullyConfirmedAt != 0 && block.timestamp < st.fullyConfirmedAt + SETTLEMENT_WINDOW)
            revert RotationWindowLocked(i);
    }
    address old = s.wallet;
    seatIdOf[old] = 0;
    s.wallet = newWallet;
    seatIdOf[newWallet] = seatId + 1;
    emit SeatWalletRotated(seatId, old, newWallet, uint64(block.timestamp));
}
```

## E2E gate (must all pass before sign-off)
1. Pre-confirm rotation: self OK, third-party revert, owner OK.
2. Post-full-confirm mid-window rotation: revert `RotationWindowLocked`.
3. Post-execution rotation: allowed; execute payouts unaffected by later rotation.
4. Duplicate guard: rotate into an existing seat → revert.
5. Trail integrity: old wallet's recorded confirm survives rotation (mask bit unchanged).
6. Gas delta on 4801 measured and reported (<200k cumulative test budget per W9 recon).

Verdict basis: V2 source read locally this turn — `executeSettlement` pays `seats[i].wallet` at execution time, `confirmSettlement` resolves via `seatIdOf`, masks immutable per settlement. Nimbus's unlock claim is structurally correct as written.
