# TandaBill — Deep Research & Value-Add Path (Flux, 2026-11-16)

## 1. Ground truth: what exists today
- Contracts: TandaBillV2 (clonable split-bill ledger, short-hold escrow, seat bitmap confirmation, MAX_HOLD 72h refund escape), factory-deployed on World Chain Sepolia (4801); W9 mainnet cutover recon done.
- Shell: Next.js 15 minikit template — wallet auth + verify + pay + sendTransaction components; config pinned to factory/impl/USDC; eruda debug provider still wired (must be off in production).
- Backend: W8 bill_index indexer design exists (userOpHash → tx → BillCreated decode); not yet implemented as a running service.

## 2. Platform facts that shape the path (verified from docs.world.org)
- MiniKit state at init gives FREE signal: walletAddress, verificationStatus (orb/document), preferredCurrency, pendingNotifications, launch location. `getPermissions()` explicitly — cached permissions are incomplete.
- Pay command supports WLD + all local stablecoins → bill payment can be in the user's preferred currency, not hardcoded USDC.
- Backend verification of pay must go through developer.world.org API v2 (nonce reference + transaction check) — nonce/confirm endpoints are NOT yet in the shell.
- Notifications command is "(soon)" — build notification UX as in-app push fallback now; hook MiniKit notifications when the command ships. Chat/share commands exist NOW: `MiniKit.chat({message, to:[username]})` and `MiniKit.share()` — these are native growth loops inside World App.
- Review gate: meaningful MiniKit integration required; mobile-first (bottom tab nav, no footers/hamburger, one task per page, CTAs visible); load ≤2-3s initial, <1s actions; iOS scroll-bounce fix (overscroll-behavior:none / 100dvh); app icon square non-white; content card 345x240 PNG 3x, bottom 94px clear.
- Policy hard lines: no chance-based RNG prizes, no membership-for-yield, no token pre-sales, no "World"/"official" in name, no World logo, usernames not wallet addresses in UI, localization for EN/ES/TH/JA/KO/PT boosts performance.

## 3. What winners in the ecosystem do (miniapps.world stats, 7d)
- Top apps are NOT utility-first — they are habit loops: ORO (65k unique/7d, opens/user ≈ 4.2x), Eggs Vault, Pebbler, AgentBank, 5minX — engagement/reward mechanics with high repeat opens per user. Pure-utility apps sit low on the board.
- Implication for TandaBill: bill-splitting is inherently low-frequency (once per event). The retention engine must be the social settlement moment, not the ledger.

## 4. Competitive field (Splitwise/Tricount/Settle Up/Splid/Kittysplit/Cashinator)
Feature gaps Tanda currently lacks vs the category leaders:
1. Debt minimization (minimum transfers to settle — graph simplification). Splitwise's headline feature. V2 settles per-seat equally; no min-transfer optimization.
2. Receipt OCR / item-level splitting with unequal shares (Splitwise Pro, Cashinator).
3. Recurring expenses (rent, subscriptions) — Tricount/Cashinator.
4. Multi-currency + FX at settlement — Settle Up's core wedge. preferredCurrency is already in MiniKit state; free win.
5. No-account join (Cashinator/Tricount/Splid allow group creation without accounts). Tanda requires wallet auth — acceptable inside World App, but seat invite friction matters.
6. Offline sync / pending-expense reconciliation.

## 5. Value-add path for TandaBill (priority order)
P0 (approval + launch blockers):
- A. Implement W8 indexer as a live service; UI never guesses bill address.
- B. Pay-nonce + backend verification endpoints (/api/generate-nonce, /api/confirm-payment per official docs) before treating payment as final.
- C. Mobile-first shell compliance: bottom tab nav, 100dvh + overscroll fix, keyboard-aware CTA (24px), toast below header; UI Kit components already installed — use them.
- D. Remove Eruda in production; localization scaffold EN/ES first (largest World user bases).

P1 (differentiators the platform uniquely enables):
- E. Verified-human settlement trust: show orb-verified badge per seat from MiniKit verificationStatus at init — "everyone in this bill is a real, verified human" is a message no Splitwise can run. Anti-sybil group ledger.
- F. Debt minimization (greedy min-transfer settlement) — client-side computation, on-chain execute; category-parity feature.
- G. Native growth loop via MiniKit.chat invite + share sheet: bill invite lands in World chat with one tap. Distribution inside the app itself.
- H. preferredCurrency-aware payment: offer WLD/local stablecoin path alongside USDC where Pay supports it.

P2 (retention engine, policy-safe):
- I. Habit loop without RNG prizes (policy bans chance-based): skill/behavior-based — settlement streaks, on-time settlement badges, group history stats. No paid tiers that boost financial returns.
- J. Notifications architecture ready for the "(soon)" command: permission request via getPermissions(), pendingNotifications counter shown in UI, in-app fallback now.

## 6. Business-case note (from W9 recon)
WLD developer rewards are NOT collectable under a US-resident name; grant track (US-eligible) is the funding path. Launch-safe, reward-restricted.

## 7. Path forward
1. Ship P0 A–D → submit for app review.
2. P1 E–H as v1 feature story (trust + settlement + native distribution).
3. P2 after first real groups; measure opens/user against the ecosystem board.
