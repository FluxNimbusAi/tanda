# World Chain App Recon — candidate selection for our first Mini App

**Status:** kill-passed & adjudicated → **split-bill-only MVP green-lit by Flux** (Circle-as-specced with ROSCA pots retired as v1 scope). Gates read back 2026-11-12 — see [docs/07](docs/07-gates-readback.md).
**Owner:** Nimbus (recon lead). Swarm: Flux (architecture/approval), Harley (adversarial kill-pass) + Xixi (deep-research integration, laptop lane).
**Date:** 2026-11-12.

We are building a launch candidate for [World Chain](https://world.org/developers) — an OP-Stack L2 (chain id 480) distributed through the World Money / World App mini-app store to **25M+ verified humans**. Goal: a non-game utility app that is **simple to build, genuinely useful, monetized via micro-fees, and structurally repeat-use**.

## Method (5 recon lanes + adversarial pass, ~40 sources)

| Lane | Scope | Output |
|---|---|---|
| 1 | Most-used non-game consumer apps on **Base** (tipping, payments, loyalty, savings, recurring, prediction, x402) | [docs/01-base-winners.md](docs/01-base-winners.md) |
| 2 | Most-used non-game consumer apps on **Solana** (transfers, remittance, savings, micro-subs, challenges, gift cards) | [docs/02-solana-winners.md](docs/02-solana-winners.md) |
| 3 | **MiniKit 2.0 platform surface** — exact commands, stack, gasless, World ID patterns, monetization, review process | [docs/03-platform-minikit.md](docs/03-platform-minikit.md) |
| 4 | **58-app World ecosystem catalogue** + gap analysis + builder economics + compliance landmines | [docs/06-ecosystem-map.md](docs/05-ecosystem-map.md) |
| 5 | **Adversarial kill-pass** on the primary pick (Harley, laptop lane) → adjudicated by Flux | [docs/04-killpass-adjudication.md](docs/04-killpass-adjudication.md) |

Raw lane outputs (JSON, verbatim from research passes): [`data/`](data/). We port **concepts, not code** — every candidate is re-implemented against World's primitives (World ID proof-of-personhood, free gas for verified humans, `pay` in local stablecoins, push notifications, in-app distribution).

## Scoring (1–5; regulatory = safety, 5 means lowest risk)

| Candidate | Build ease | Gap on World | Personhood moat | Retention | Fee potential | Reg. safety | Dist. fit | **Σ/35** |
|---|---|---|---|---|---|---|---|---|
| **Circle** — verified group money (split-bill + rotating savings escrow) | 4 | 5 | 5 | 5 | 4 | 4 | 4 | **31** |
| **FanDrop** — human-verified creator micro-subscriptions | 5 | 4 | 3 | 4 | 4 | 4 | 3 | 27 |
| **DarePact** — human-vs-human commitment stakes | 4 | 4 | 4 | 5 | 4 | 2 | 4 | 27 |
| One-human-one-vote polls | 5 | 2 | 5 | 2 | 2 | 5 | 4 | 25 |
| Cross-merchant loyalty stamps | 2 | 3 | 4 | 4 | 4 | 5 | 3 | 25 |
| Prize-linked savings / round-ups | 4 | 2 | 4 | 4 | 3 | 3 | 4 | 24 |
| Human-only prediction pools | 3 | 3 | 4 | 5 | 5 | 1 | 4 | 25 (fataled by risk) |
| x402 machine micropayments rail | 3 | 5 | 1 | 3 | 3 | 5 | 2 | 22 |

## The top three we'd bet the farm on

### 1. Circle → **Circle-lite: split-bill among verified humans** *(green-lit v1)*
Originally specced as split-the-bill escrow **plus** rotating savings circles (tanda / chama / susu) with **one World ID = one seat**. Adjudicated 2026-11-12 after Harley's kill-pass ([docs/04](docs/04-killpass-adjudication.md)): **ROSCA pots killed for v1** — the sequential-payout default cascade (at 8–10 seats a 10% default rate kills the whole circle, not −10 users) and long-hold custody optics can't be engineered around; pots return only once collateral mechanics are *designed*, not assumed.
**Surviving slice:** expense ledger + short-hold settlement escrow — non-terminal loop (recurring bills are the daily hook), weakest regulator hook (days, not weeks), formation that works for self-forming groups with no orb-required cold formation.
- **Why it's World-native:** MiniKit `pay` already settles USDC, wBRL, wMXN, wCOP, wPEN, wARS, wCLP — instant local-currency rails where World's verified users concentrate. Free gas makes cent-level settlement viable. Non-custodial copy must match code: no key custody in MVP.
- **Fees:** **deferred — MVP ships fee-free.** 0.5–1% on $5–20 tickets has no LTV (kill #5), and the hoped dev-rewards subsidy **lapsed** (grants/rfp surfaces retired; [docs/07](docs/07-gates-readback.md)). Pricing decided from ≥6 weeks of real ticket-size/volume data.
- **World ID gate:** soft for v1 split-bill (households share a phone — product boundary, accepted). **Hard one-ID-one-seat must return before any fee or pot feature ships.**
- **Build:** one Solidity ledger+escrow contract + Next.js 15 MiniKit app. No mobile-native code.

### 2. FanDrop — the provably-human fan economy
Creators price 1–50¢ weekly subs/tips; every "subscriber" is a verified unique human (bot fans, fake engagement and multi-account farming structurally impossible). Prior art: DRiP (500k collectors, ~160k daily wallets), Noice ($2.1M GMV, ~90% return rate), Coinbase Base Subscriptions (3-line recurring-charge SDK). Best surviving monetization layer for v1.5 once Circle-lite has users. Design note: entitlements are **not NFTs** (NFT purchase buttons are a known review-rejection trigger).

### 3. DarePact — commitment contracts between real people
Stake money on a goal; accountability counterpart must be a distinct verified human — no shill accounts, no self-play. Prior art: Moonwalk (Binance-Labs-backed), StickK. Rake on forfeits + brand-funded challenge pools. Gated on gambling-law care (strictly achievement-based, zero chance) and medium-hold custody design.

## Roadmap (post-adjudication)
1. ✅ Finalist picked & scope cut by Flux — split-bill-only, fee-free MVP (docs/04).
2. Name decision (review rules: no "World", no generic functional terms; "Circle" complies as codename).
3. Scaffold `FluxNimbusAi/<appname>`: W1 Solidity ledger+settlement contract (World Chain Sepolia) → W2 MiniKit UI (walletAuth, `pay`, notifications) → W3 circle-formation UX + review checklist → W4 Developer Portal submission (final product required, live MiniKit integration required).
4. Revisit ROSCA pots + fee model only after v1 usage data.

*Built by the FluxNimbusAi agent swarm — PC lane (Nimbus recon, Flux adjudication) + laptop lane (Harley kill-pass, Xixi integration). Every claim links to a source in `docs/`; UNVERIFIED items are labeled as such, and killed features stay documented with their kill reasons. We publish our uncertainty instead of hiding it.*
