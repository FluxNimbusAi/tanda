# ADR-0013 — Gas sponsorship policy per settlement leg

Status: PROPOSED (Nimbus draft, V5 audit card 5; Flux ruling required: sponsor-on vs user-pays)
Date: 2026-11-26
Citations (live this pass): Pimlico Aug-2026 World App case study — "the promise
breaks at the first gas prompt"; median World Chain user-op confirmation ~1.5 s;
ecosystem bar = sponsored transactions at consumer volume.

## Problem
TandaBill's pitch line "zero fees, no custody" meets chain reality leg by leg.
Every state-changing call costs gas on 4801/mainnet; the app must DECIDE per leg
who pays, or the marketing sentence fails at first contact with a wallet popup.

## Legs and current architecture (trunk-verified)
| leg | function | payer today | candidates |
|-----|----------|-------------|------------|
| create bill | factory.createBill | creator wallet (EOA) | keep user-pays |
| seat join | registerSeat via factory.callBill forwarder | NOT WIRED for sponsorship | sponsor (relayer key) |
| fund escrow | token.approve+transfer to bill | funder wallet | keep user-pays (deposit = intent signal) |
| confirm/execute | callBill forwarder path | owner/creator | sponsor-eligible |
| claim payout | claim via forwarder | claimant wallet | SPONSOR — claim is the happy moment |
| drain/close | LATCH-2 auto on last claim | protocol | covered by claim leg |

## Options
- O1 USER-PAYS EVERYTHING: honest, simple, kills the pitch; Pimlico evidence says
  consumer drop-off at first prompt is the dominant failure mode for mini-apps.
- O2 SPONSOR-ON-CLAIM (recommended): relayer key (server custody, factory.callBill
  forwarder already exists in-contract — the trust anchor is the factory, no new
  contract needed) pays seat-join + claim legs. Cost bound: per-bill claims <= seats
  (5 typical) -> worst case ~3 claims x 120k gas x 0.1 gwei = dust on 4801; mainnet
  scale requires relayer budget cap + per-nullifier replay guard (already: NullifierUsed).
- O3 FULL SPONSORSHIP incl. deposits: enables dust-attack surface on funder intent;
  rejected for escrow legs.

## Ruling sought
1. O2 for seat-join + claim legs on 4801 dogfood (M4), revisit with real gas prices
   pre-mainnet; deposits and bill creation stay user-pays.
2. Relayer key custody: vault lane, NEVER in Vercel env plaintext for mainnet; on
   testnet the existing 0xa462 signer serves.
3. Copy law: tandabill.world says "zero fees" only where O2 is live for that leg —
   honest-copy standard (M5) extends to gas claims; otherwise "you pay gas only for
   funding; claiming is on us".

## Consequences
- No contract change needed (forwarder path is shipped + LATCH-2/guards merged);
  work = relayer wiring in miniapp server routes + budget cap + replay metrics in
  the indexer. Unblocks the exact sentence the landing page already implies.
