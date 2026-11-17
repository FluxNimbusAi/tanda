# P0.1 Proposal — `rotateSeatWallet` hot-patch for TandaBillV2 (2026-11-16)

Status: **RATIFIED & SHIPPED** — ruled in docs/FLUX_RULING_P01_ROTATION_2026-11-16.md, merged via PR #2 @17a34e2 (origin/main), E2E 11/11 (docs/W10_E2E_RECEIPT_20261116.md). Author: Nimbus. Original draft text preserved below; see §Ratification delta for every divergence. (Synced 2026-11-17, Track A #1.)
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

## §Ratification delta — draft vs shipped (synced 2026-11-17, Track A #1)
Bases: FLUX ruling 2026-11-16; shipped `contracts/TandaBillV2.sol` @17a34e2 (L83 event, L98–102 errors, L186–213 body); W10 E2E receipt (gates C1–C9, 11/11, 4801).

| # | Draft said | Ratified / shipped | Verdict |
|---|---|---|---|
| Q1 | seat-self ∨ owner via `msg.sender` | Accepted as drafted; caller identity resolves through `_caller()` (trusted factory forwarder, audit correction #1) — forwarder and direct paths both proven (C1/C2) | as draft + forwarder |
| Q2 | rotation allowed until executed/refunded | Hardened to RATIFIED SPLIT-LOCK (RESOLUTION 2026-11-16b): owner-driven rotation dies at FULL CONFIRM — stricter than the ruling's window-end rule, signed off in chat; confirmed seat-self locked inside window; unconfirmed seat-self always free; `SeatRotationClosed` after executed/refunded (C6/C8) | superseded (stricter) |
| Q3 | sybil gate = frontend policy + event trail | Accepted per ruling; enforcement joins `seat_grants` (schema v2, correction #2), rotation alert N7 | as draft |
| Q4 | V2-era only | Accepted; W5 legacy 0x8644095B… runtime-hash-locked, untouched | as draft |
| Event | `SeatWalletRotated(seatId, indexed from, indexed to)` | Shipped **as drafted (3-arg)**; ruling spec had proposed a 4th param `uint64 at` — not shipped; indexer timestamps from block (`seat_grants.granted_at`) | deviation, documented |
| Errors | `NotSeatOrOwner`, `ZeroWallet`, `DuplicateSeat` | All shipped as drafted; **added** `SeatRotationClosed` + `RotationWindowLocked()` (bare, vs ruling spec's `(uint256 settlementId)`) | superset |
| Window scan | Ruling spec looped all settlements | Shipped inspects `settlements[last]` only — single-active-settlement MVP; concurrent pending settlements NOT audited for the lock | deviation, recorded |
| Test plan | 5 items incl. dead-lock repro on unpatched impl | Superseded by actuals: 74/74 unit @dff3e65, E2E 11/11 C1–C9 on 4801. Item 4 (dead-lock repro) NOT exercised on-chain — structural argument stands in ruling's verdict basis | partially replaced |
