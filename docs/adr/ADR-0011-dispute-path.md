# ADR-0011 — Dispute-path options for TandaBill (options table ONLY — no spec change)
Status: PROPOSED (BS-8.2, Flux dispatch msg 57298) · Author: Nimbus · Date: 2026-11-25
Feeds: mainnet [HUMAN_GATE] decision (M6). Constraint set: no-upgrades law (factory
immutability), non-custodial invariant, P2-2 ruling of record (freeze-until-drained),
kill-pass history (escrow isolation > feature velocity).

## The gap this ADR exists for
refundSettlement is owner-only and reachable solely while fullyConfirmedAt == 0 (never-confirmed
case) + MAX_HOLD elapsed. Confirmed-but-stalled states (unclaimed share → LATCH-2 freeze persists;
bad-faith post-execute blacklisted wallet) have NO third-party recourse. Rehearsal-acceptable;
mainnet needs an explicit, stated story — even if the story is "by design, see cost below."

## Options table
| # | Model | Mechanism sketch | Trust added | Blast radius | Fits no-upgrades law? | Fits non-custodial invariant? | Cost/effort |
|---|-------|------------------|-------------|--------------|----------------------|-------------------------------|-------------|
| O1 | Status quo: time-gated honesty | Copy + falsifiable register ("the round isn't over until you claim"); MAX_HOLD is the only escape | none | none | yes | yes | 0 (copy only) |
| O2 | Owner recovery after N days (P2-2 option b) | owner may reclaim an unclaimed share X days post-execute | 1 party (owner) | HIGH — converts escrow promise toward custodial; ruled NOT-shipped 2026-11-24 | yes (new impl) | degraded — owner can move another seat's funds | M |
| O3 | Seat-quorum counterparty override | k-of-active-seats vote finalizes drain/dispute state (e.g., 2-of-3 unanimous for share-return) | social (circle itself) | M — mask math reuse; quorum rules interact with LATCH-2 predicate | yes | yes (peers, not platform, decide) | M-L |
| O4 | Optimistic dispute window | post-execute D-second window; any seat can flag irregular claim -> settlement pauses for external ruling | arbitrator (off-chain) | M-H | yes | partially — freeze extension | L |
| O5 | External arbitration protocol (Kleros-style) | contract calls out to court for stranded-share cases | third-party court | HIGH — oracle dependency, mainnet-only maturity, cost per case | yes | yes | XL, new dependencies |
| O6 | Upgradeable/governed escrow module | proxy-admin can patch dispute logic | DAO/multisig | MAX — kills the immutability guarantee that makes the escrow credible | NO — violates factory immutability law | no | L |

## Non-options already ruled
- Owner-recovery door (O2): declined as product pivot at P2-2 (Flux, 2026-11-24); this ADR does
  NOT reopen it — it preserves O2 in the table so the mainnet gate sees the full map.
- Reconsideration trigger of record: a DOGFOOD (M4) stranded-share incident WITH receipts fires
  O2/O3 back onto the decision table as its own spec card.

## Recommendation (pre-gate, for the mainnet [HUMAN_GATE] packet)
Ship O1 to mainnet v1: state the freeze semantics in app copy + this ADR; instrument the indexer
for a stranded-share counter (bills with settled settlements unclaimed > MAX_HOLD at claim-gate).
Data from M4/M5 legs decides whether O3 (quorum) earns a spec card. O4/O5 stay parked until real
dispute volume exists; O6 stays dead on principle.

## Open questions for @d3b0m3n (board-level, not engineering)
1. Is "no arbitration, documented" an acceptable brand posture for a money app, or does the
   World dev-rewards review bar expect a dispute story? (docs.world.org app guidelines: no
   dispute-mechanism requirement found as of 2026-11-24 — verified absence, not presence.)
2. If O3 ever ships: quorum definition belongs to the circle, the platform, or the bill creator?
