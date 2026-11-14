# TANDA — Launch Realities & Milestone Decision (2026-11-14, Nimbus recon)

Sources: docs.world.org mini-apps FAQ + App Review Guidelines + quick-start (fetched live 15:0xZ), Circle address tables, our repo/chain state.

## Where we are (verified)
- Canonical W5 contract LIVE on World Chain Sepolia (4801): `0x8644095B9722a41281314158006d194C59ab9b12`
  - tx 0x1d0037ff…, block 37059680, gasUsed 1,051,887, status 1
  - runtime 4508B ≡ tip_28b63a6 artifact; 3 immutable slots bake USDC 0x6614…ea88
  - owner()/token()/SETTLEMENT_WINDOW() live-green — 3 independent paths (Harley RPC+cast, my receipts)
- Repo main @ 89ea41b: canon bytecode, filled world.json, DEPLOY_RECEIPT.json (with supersession), corrected rehearsal docs, standard-json verify artifact
- First deploy 0xf63c…7bb2: SUPERSEDED (wrong artifact lineage — logged in receipt)
- Explorer source-verify: BLOCKED on Etherscan V2 API key or logged-in worldscan session (d3b0m3n: answer A=key / B=browser / C=leave for admin)

## The hard gates (world.org, non-negotiable)
1. **Mini Apps do NOT support testnet.** Development/testing/launch of a World App mini app happens on **World Chain mainnet (480)**. Our Sepolia deploy is a rehearsal asset, not the launch contract.
2. **Contract + token interactions must be pre-whitelisted in the Developer Portal** (developer.worldcoin.org) per app — prevents unauthorized transfers; applies to our `approve/transferFrom` USDC flow.
3. **World ID verification moved to IDKit** (MiniKit 1.x `verify` is deprecated → IDKit 4.0, works in mini-apps + desktop; Selfie Check). Our contract devdoc still says "World ID verification happens off-chain (MiniKit walletAuth)" — stale wording, docs-only fix, no contract change (proof validation must occur in backend/contract — ours: owner gate + logic-only escrow already satisfies "smart contract validation" limb).
4. **Review requires a FINAL app**, not demo/beta: live MiniKit/IDKit integration, complete copy, support email, offline/resilience handling, app-store compliance, review team must be able to access the URL.
5. Hosting: public HTTPS URL (ratified site ladder #1: Next.js + Tailwind + Vercel Hobby $0) + icon must be a real hosted asset (`/assets/tanda-icon.png` currently local-only).

## Milestone proposal (ranked, waiting for Flux lead call)
- **W8 — MiniKit 2.0 shell** (recommend FIRST): `npx @worldcoin/create-mini-app` (Next 15 template), MiniKitProvider, IDKit seat-join gate, Wallet Auth, `sendTransaction` wired to the **Sepolia** contract via ABI in world.json; portal app URL + ngrok tunnel testing loop. UI-only, zero real money, unblocks demo video + review-readiness early.
- **W9 — Mainnet (480) canonical deploy**: same tip artifact, USDC mainnet `0x79A02482A880bCe3F13E09da970dc34dB4cD24D1` (Circle native, verified). Cost: WC mainnet gas negligible; **escrow holds REAL USDC by design once live** — flag to d3b0m3n as the first real-money execution. Deployer needs mainnet ETH (faucet-less; small real purchase).
- **W10 — Portal submission**: whitelist contract+USDC address, app copy, support email, submit for World App listing review.
- Distribution note (non-target): ETHGlobal Cannes ran Apr 3–5 (World $20K tracks incl. MiniKit 2.0 $4K) — watch next ETHGlobal event; Tanda's shape (World-ID-gated fee-free split escrow on World Chain) fits their tracks cleanly.

## Open asks
- d3b0m3n: explorer verify A/B/C (above) + Developer Portal account confirmation (is there an existing World developer account? whose email?)
- Flux: lead W8 architecture (IDKit flow + seat model mapping) — I stage template, recon, and verification legs
- Harley/Xixi: no Tanda assignments this round (focus lock: Strata submissions)
