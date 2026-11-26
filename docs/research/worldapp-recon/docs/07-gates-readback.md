# Gates read-back — 2026-11-12 (Nimbus, live fetches)

Flux's adjudication set two gates before the week-1 split-bill MVP spec. Both read back from the live World properties on 2026-11-12:

## Gate 1 — dev-rewards funding continuation: NOT LIVE as previously advertised
- `world.org/rfp` now serves **World One**: a 3-month San Francisco **residency** for up to 5 *solo* builders, $10k/month, "no deliverables, no assigned roadmap", requires SF colocation. (https://world.org/rfp → https://world.org/one)
- `world.org/grants` (the 50M WLD Foundation Mini App Grants referenced in docs) **redirects to world.org/one** — the grants surface is dead-ended as of today.
- `docs.world.org/mini-apps/more/community-tools-perks` shows only the (now dead) grants card; no weekly-pool leaderboard anywhere in the docs index.
- The Sept-2025 "$100K/week Dev Rewards pilot" announcement (https://world.org/blog/announcements/dev-rewards-pilot-increases-to-100k-per-week-as-the-world-ecosystem-surpasses-500-mini-apps) appears to have **lapsed after Dec 31, 2025** with the program surfaces retired.
- **Consequence for the build:** MVP economics are user-growth-first. Combined with kill #5 (per-settle fees have no LTV at $5–20 tickets), the MVP ships **fee-free**, monetization decided from real ticket-size/volume data at 6+ weeks of usage. Do not budget any grant/reward income.
- Side intel: World One developer stories (Divine, Toktokhan.dev, **tbd.vote**) corroborate our lane-4 catalogue — tbd.vote = the "Answer Polls/Predict" entry.

## Gate 2 — review rules confirmed from live App Review Guidelines
(https://docs.world.org/mini-apps/guidelines/policy, fetched 2026-11-12)
- **Naming: don't use "World" in the name; don't use generic functional terms ("Earn", "Swap", etc.) as the Mini App name; don't use descriptions as names; keep names short and memorable.** → "Split Bill" is a banned generic; our codename **Circle** complies (final name TBD by Flux).
- Approval requires a **meaningful MiniKit integration** — World ID and/or Wallet access commands, not a plain webview. ✔ by design (pay + sendTransaction + walletAuth).
- Prohibited: impersonating TFH/Worldcoin, NSFW (incl. AI generators that can produce it), false/fake-functionality apps, "objectionable content" — none of which touch our slice.
- App must be a final product, not beta/demo — submission plan must include a polished onboarding flow (QR scan funnel) from day one.

## Status
Both gates cleared with one red flag: **funding assumption removed** from the README scoring's fee column going forward (score history preserved above line).
