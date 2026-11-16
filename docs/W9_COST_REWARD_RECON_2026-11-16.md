# W9 MAINNET (480) COST & REWARD RECON — Nimbus, 2026-11-16 (pre-execution gate)

Mission: Flux directive "stablecoin gas + World coin reward eligibility on 480 — cheap recon,
prevents a compliance surprise at launch." All numbers live-measured or source-cited; nothing estimated from memory.

## 1. Gas economics (live @ worldchain-mainnet.g.alchemy.com/public, verified chainId 480)
- eth_gasPrice: **0.0015 gwei** (priority 0.001 gwei) — sub-cent anything.
- Per-op execution cost (gas figures pinned from W6-V2 live receipts, EVM cost identical):
  - createBill clone: 208,530 gas ≈ **0.00000031 ETH**
  - ERC-20 USDC transfer ≈ 65,000 gas ≈ 0.0000001 ETH
  - settle execute (est): 150,000 gas ≈ 0.00000022 ETH
- Full W9 deploy budget (impl 1,619,087 + factory 270,412 + 50 rehearsal bills 250k avg):
  **≈ 0.000022 ETH + 2× margin for op-stack L1 data fees ≈ 0.00005 ETH (<$0.20).**
- Users pay ZERO gas in-app: World App paymaster covers MiniKit sendTransaction (official FAQ).

## 2. Mainnet USDC — LIVE byte-probed (not docs-trust)
- `0x79A02482A880bCe3F13E09da970dc34dB4cD24D1`: code present, **1,852 B, Circle Central Bankers shape**,
  name()/symbol() = "USDC" (short-string encoded). = native USDC, NOT USDC.e bridge variant.
  Matches Circle address tables + launch doc. W9 bakes this as factory/impl immutable.

## 3. Reward eligibility — ⚠️ THE FINDING
- Mini App **Developer Rewards** program: ACTIVE, usage-based, paid **in WLD**
  (pilot Apr 2025 $25K/wk → Sep–Dec 2025 $100K/wk → 2026 rolling pool per grantedai listing + World channels).
- Official disclaimer, verbatim across all program pages:
  > "WLD are not available to, or intended for, people, companies or organizations who are **residents of,
  > or are located or incorporated in the United States** or certain other restricted territories
  > (or have beneficial ownership in the United States...)."
- **d3b0m3n is US-resident (FL) → the WLD Dev-Rewards stream is NOT collectable under his own name.**
  The APP itself is fine: "World ID and TFH's World App remain available in the United States."
  Not a launch blocker — a reward-channel constraint.
- Alternatives: **Mini App Grants Program explicitly opened to US builders** (World Dev Summer post);
  non-US corporate structure with no US beneficial ownership would restore WLD eligibility (owner call, legal-adjacent).

## 4. Verdict
Gas/deploy: negligible, no funding gate worth mentioning (dust ETH suffices; keep 0.001 ETH headroom).
Token: canonical USDC confirmed on-chain.
Compliance: **launch-safe, reward-restricted** — plan grant-track funding (US-eligible) instead of
usage-rewards in the business case; flag legal review before any non-US-entity workaround.
