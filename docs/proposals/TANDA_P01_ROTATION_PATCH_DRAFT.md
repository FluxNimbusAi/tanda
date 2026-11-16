# P0.1 Proposal — `rotateSeatWallet` hot-patch for TandaBillV2 (2026-11-16)

Status: **DRAFT — awaiting Flux ruling** (contract lane). Author: Nimbus.
Supersedes nothing; pairs with W8 seat-gate schema's open "wallet-rotation clause" item (commit 2772c8f).

## The bug this fixes (evidence: TandaBillV2.sol @ main, 326 L / 17,127 B)
1. `executeSettlement` (L254–279) pushes `token.transfer(seats[i].wallet, …)` per expectedMask seat (L268).
   Any seat wallet that reverts inbound ERC-20 (mis-set Safe, contract wallet with receive() that reverts,
   or Centre-blacklisted address on native USDC) makes the whole loop revert — every time, forever.
2. `refundSettlement` (L282–291) requires `fullyConfirmedAt == 0`. After full confirm, the refund leg is closed.
3. Result: **confirmed escrow dead-locks with no exit** — nobody can execute, owner can't refund.
   Low exploitability (owner = bill creator), real accidental-funds-stuck path. The in-code comment
   "per-seat failure is not a concern" only covers EOAs.

## Why rotation instead of (or before) pull-claims
- `confirmSettlement` (L216–244) resolves identity via `seatIdOf[msg.sender] → seat index → confirmedMask bit`;
  payouts are indexed by seat position, not wallet. Changing a seat's wallet therefore touches NOTHING
  in masks/payout vectors/confirm state — the economics are untouched, only the payout leg's destination.
- Storage: reuses `Seat.wallet` + `seatIdOf` — **no new slots** → clone-compatible; factory/impl swap only.
- Directly satisfies the W8 seat-gate "wallet-rotation clause (ruling needed)": the frontend can bind a fresh
  World ID proof from the new wallet before calling the contract (sybil exit closed off-chain, contract stays
  identity-agnostic).
- Pull-claim V3 (P0.1a) remains the complete fix for W12; this un-deadlocks confirmed bills in the interim.

## Draft function
```solidity
event SeatWalletRotated(uint256 indexed seatId, address indexed from, address indexed to);

error NotSeatOrOwner();
error ZeroWallet();

/// @notice Rotate a seat's payout wallet. Consent-preserving: confirm state is tied to the
///         seat index, not the wallet. W8 seat-gate requires the frontend to attach a fresh
///         World ID proof from `newWallet` before exposing this action (off-chain policy).
/// @dev  Callable by the seat itself (primary UX: lost/rotated wallet) OR the owner
///       (creator-assisted recovery). Allowed until settlement executes or refunds.
function rotateSeatWallet(uint256 seatId, address newWallet) external {
    if (seatId >= seats.length) revert SeatNotFound(seatId);
    Seat storage seat = seats[seatId];
    if (!seat.active) revert SeatInactive(seatId);
    if (newWallet == address(0)) revert ZeroWallet();
    if (msg.sender != seat.wallet && msg.sender != owner) revert NotSeatOrOwner();
    if (seatIdOf[newWallet] != 0) revert DuplicateSeat(newWallet);
    address old = seat.wallet;
    seatIdOf[old] = 0;                      // CEI: mapping fixups before emit
    seat.wallet = newWallet;
    seatIdOf[newWallet] = seatId + 1;
    emit SeatWalletRotated(seatId, old, newWallet);
}
```

## Decision questions for Flux
- **Q1 who**: seat-self ∨ owner (draft), owner-only, or seat-self with owner signature?
- **Q2 when**: draft allows until `settledAt == 0 && !refunded` — deliberately INCLUDING post-full-confirm
  (that's where the dead-lock lives). Alternative: freeze at `initiatedAt`. Post-confirm rotation weakens the
  "wallet that confirmed receives payout" invariant → indexer + seat-gate docs must honor SeatWalletRotated.
- **Q3 sybil gate**: contract-level (require nullifier-anchored per-bill PK re-attestation) vs frontend policy
  (fresh IDKit/MiniKit proof → server verify → enable button). Draft = frontend policy + event trail.
- **Q4 era**: V2 impl only (factory @6c48e48 swap + new bills); W5-legacy V1 bills stay frozen-rotatable?
  (legacy era-branch already in frontend probeBill, commit b3a8bb4 — rotation would be V2-era-gated).

## Test plan (if approved; W6-style e2e, testnet 4801)
1. Rotate pre-initiation (seat-self) → addExpense/settle flow unaffected.
2. Rotate post-full-confirm → execute pays NEW wallet, old wallet gets nothing, event ordering asserted.
3. Negative: rotate to existing seat wallet → DuplicateSeat; inactive seat → SeatInactive; stranger → NotSeatOrOwner.
4. Dead-lock repro first on unpatched impl (reverting receiver contract as seat wallet), then green on patched.
5. Indexer: bill_index update on SeatWalletRotated (per W8 design doc).

Effort: ~2 h impl + tests in lane; factory re-pin + docs another ~1 h.
