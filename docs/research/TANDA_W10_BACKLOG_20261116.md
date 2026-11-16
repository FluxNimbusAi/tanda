# TandaBill — W10+ Value-Add Backlog (2026-11-16)

> Derived from `TANDA_VALUE_ADD_RESEARCH_20261116.md` (sha256 19cc95d42c7ac761…, 3-lane fan-out, 55 findings).
> Evidence citations reference TandaBillV2.sol @ main (17,127 B / 326 L) and the research doc line items.
> Status: PROPOSED — contract changes require Flux sign-off (architecture lane).

## P0 — Existential differentiation + hardening

### P0.1 Settlement leg: push-loop → per-seat pull-claim (HARDENING)
- Evidence: `TandaBillV2.sol` L254–276 `executeSettlement` pushes `token.transfer(seats[i].wallet, …)` in a loop (L268).
  W1 scaffold carries the same shape with a comment calling per-seat failure "not a concern".
- Failure mode: `refundSettlement` (L282–291) gates on `fullyConfirmedAt == 0` — once ALL seats confirm, the MAX_HOLD
  escape is closed. A seat wallet that reverts inbound ERC-20 (mis-set Safe/hooked contract) or is blacklisted by USDC
  then dead-locks the escrow permanently. Owner = bill creator (semi-trusted) keeps exploitability low, but this is a
  real accidental-funds-stuck user-error path.
- Fix (pick one, Flux decides):
  a) Pull model: settlement credits `claimable[seat]`; seats `claim()` their payout. (peanutsplit / OZ PaymentSplitter pattern — research lane 2 #13.)
  b) Minimal patch: allow owner to reassign a seat's payout wallet BEFORE executeSettlement (not after confirm-lock).
- Effort: a) contract V3 + tests + W6-style e2e suite ≈ 2 days lane time. b) ≈ 2 hours.

### P0.2 Position the escrow guarantee, not the split (FRONTEND/COPY)
- Why: World Chat ships first-party in-thread "Split with friends" tap-to-pay (lane 3 #1). Competing on plain splitting
  loses to the platform. Competing on *guarantee* (money pre-escrowed; settlement cannot be flaked on) is uncontested.
- Copy vector: "Funded means funded. Nobody can ghost your money." + explicit no-caps/no-ads contrast vs Splitwise (lane 1).
- Effort: W8 frontend copy pass + store listing blurb; ~0.5 day.

### P0.3 "No bots in your bill" — World ID as visible product feature (FRONTEND)
- Every seat = verified human (nullifier). Surface the verification badge per seat at roster time and on the settle screen.
- Precedent: Credit mini-app (70k users, sybil-proof lending), ORO ("verified humanity as the consumable"), World judging
  criterion "products that break without proof of human" (lane 3 #4/#8/#13).
- Effort: seat cards already carry nullifier data → UI badge + first-run explainer; ~1 day.

## P1 — Category-proven retention mechanics

### P1.1 Cadence nudge via MiniKit notifications
- Splitwise Pro's single most-cited retention driver is calendar-cadence reminders (lane 1 #5). Implement: weekly digest
  for open Bills with unsettled expenses + settlement-window countdown push (MiniKit notifications command).
- Effort: ~1 day (frontend + dev-portal notification permission flow).

### P1.2 Rounding-dust forgiveness before escrow
- Users care psychologically about cents-level fairness (lane 1 #6). Give creator a signed "forgive/adjust" that rounds
  payout vectors to clean USDC decimals pre-fund. Pure off-chain vector adjustment pre-escrow → no contract change.
- Effort: ~0.5 day.

### P1.3 Uneven per-seat weights at Bill creation
- "Couple counts double" is a loved, rarely-perfected feature (lane 1 #9, Settle Up). Seat roster → optional weight field;
  payouts vector already computed at settle — weight is an input to existing math.
- Effort: contract view test + frontend form; ~1 day (weights live in expense math, not storage — verify with Flux).

### P1.4 Explainable settlement vector
- Show per-seat payout WITH derivation (expenses × weights × who-paid) on confirm screen. Black-box netting erodes trust
  (lane 1 #10 Settle Up; Venmo Groups un-auditable netting is a named pain, lane 1 insight 3). On-chain data makes this
  free — render it.
- Effort: ~0.5 day frontend.

## P2 — Trip/group depth

### P2.1 Offline capture queue + batch sync
- Travel groups have spotty connectivity; Splid's offline-first + one-settlement-at-end-of-trip is the category ideal
  (lane 1 #15). Queue expense entries client-side (IndexedDB), replay `addExpense` on reconnect with idempotency keys
  (client nonce) so replays don't double-log.
- Effort: ~2 days frontend + nonce field in expense struct (Flux: contract touch).

### P2.2 FX pinned at escrow time for multi-currency trips
- Denominate all payouts in USDC; show native-currency estimate converted at escrow-time rate; both amounts visible
  (lane 1 #16 Splid). Uses external rate oracle snapshot stored off-chain at fund time (rate = input to payout vector,
  signed by creator) — no oracle dependency in contract.
- Effort: ~1 day.

### P2.3 Ledger export (CSV/JSON) — ledger-of-record retention
- Keep Bill history viewable/exportable post-settlement (lane 1 #8). Cheap and sticky; per-group one-time pricing of
  exports is the market-tolerated monetization model (lane 1 #11/#22) if ever needed.
- Effort: ~0.5 day.

## P3 — Growth loops & revenue floor (post-launch)

- P3.1 Invite loop: every Bill enrolls 3–8 humans; "add seat" = MiniKit share deep-link. Platform ships the referral
  playbook (lane 3 #11).
- P3.2 Dev Rewards floor: track verified-human usage toward the 10,000 threshold — WLD grants fund cold start
  independently of the zero-fee model (lane 3 #10; note WLD Dev Rewards exclude US residents — grants track stays
  US-open per W9 recon e17ece4).
- P3.3 Defaulter reputation (opt-in): on-chain log of confirm-latency per nullifier → "payment accountability score",
  the Credit-app precedent taken further (lane 3 #4). Careful: privacy + harassment vector; needs Xixi-grade ethics pass.

## Anti-patterns (do NOT)
1. Never meter/limit the core loop — paywalled entry created the category's only self-inflicted wound (lane 1 insight 1).
2. No lock-membership-behind-debt coercion — 72h refund escape is the humane opposite; keep it (lane 1 #19).
3. V2→V3 needs explicit migration story — Tricount burned decade-old goodwill on a regression overnight (lane 1 #14).
4. Don't rebuild rails: first-party wallet already does zero-fee USDC P2P by username (lane 3 #3). Value sits above rails.
5. Don't ship "wallet-with-ledger" reskinned — crypto splitter graveyard evidence (lane 2 #14).

## Suggested sequencing
W10: P0.1b hot-patch (2h) + P0.2 + P0.3 → reviewable app delta.
W11: P1.1 + P1.2 + P1.4 → retention mechanics live.
W12: P0.1a pull-claim V3 (Flux-approved) + P1.3 + P2.3.
W13+: P2.1/P2.2 trip depth, then P3 growth loop.
