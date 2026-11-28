# ADR-0014 — APP-5 MAINNET package: audit freeze, entrypoints whitelist, funded deploy, sponsorship

Status: PACKAGE DELIVERED — gate execution awaits external hands (Flux rulings + owner funding)
Date: 2026-11-27 | Card: t_40503cdc | Origin: owner directive 58131 + Flux verdict 2026-11-27
Proof companion: proofs/APP5_MAINNET_FREEZE_20261127.json (PR #231)

## 1. Audit freeze (pinned, reproducible)
- Freeze point: tanda main tip `cc104d69fae25887dafb3358a6deb58a1ebb7b3d`;
  contracts/ byte-unchanged since the ENGINE-66 census (923e4af51) — freeze valid.
- Build arm: foundry.toml-pinned production (optimizer=true, runs=200),
  forge 1.9.0, solc 0.8.38 — 300/300 tests, 29 suites, rc=0 (2026-11-28T01:34Z run).
- TandaBillV2.sol sha256_LF `79d7b124fd6ccd3fac1b9274ca95b009c31f81666ed7958a1784e3bc24dfdda7`.
- Anchors (deploy-verification targets):
  - impl runtime 11,069 B, sha256 `02aafaf635d0675377e53c904ad49bd10d63e8b7a653e2829c006d189e8913e6`,
    keccak256 `0x3ea7b47c2e4811efce6bd40d3f6a2abded8aacddf5ee06ad882d6f713ad0f040` (EIP-170 margin 13,507 B)
  - factory runtime 1,402 B, sha256 `605767c50de72a2933f65623f8deed248fcce3a610d615b696b16fd29c893f79`,
    keccak256 `0x7631c75daddcb9582b203f79e81b804a69a2fd972accc5f8a98fbaaf625a7f28`
- The deployed 4801 impl (0xd0cc…, keccak 3683cfe0, 9,817 B) predates #195 — STALE.
  A fresh deploy is mandatory on any chain; mainnet has never held Tanda code.

## 2. Chain facts, World Chain mainnet 480 (attested 2/2 providers: alchemy public + thirdweb)
- block 38,248,645; gas price 1,500,000 wei (0.0015 gwei).
- USDC: `0x79A02482A880bCe3F13E09da970dC34dB4cD24D1` — code 1,852 B, symbol USDC,
  decimals 6, live-checked on both RPCs; Circle multi-chain docs concur.
- Permit2 `0x000000000022D473030F116dDEE9F6B43aC78BA3` present (9,152 B) — ADR-0010 arm valid on mainnet.
- Zero Tanda code on 480 (as expected). Deployer + current RP signer: 0 ETH.
- Zero-key simulation (`forge script TandaDeployV2 --rpc-url 480 --sender 0x78dC…9E7A`):
  maxFee quote for both deploys = 874,161,700 wei (< 0.001 ETH).

## 3. Deploy runbook (owner hands — this is the ONE human-money boundary)
1. Fund deployer `0x78dC32F6a4edF80c538A75e1F7664505B1969E7A` with **0.01 ETH on 480**
   (~11,000× the measured maxFee quote; covers deploy + first E2E legs).
2. Deploy: set `USDC_ADDRESS=0x79A02482A880bCe3F13E09da970dC34dB4cD24D1`,
   `forge script script/TandaDeployV2.s.sol --rpc-url <480> --broadcast --verify`
   — pipe-only key flow per DEPLOY_RECEIPT_V2 precedent (zero secret bytes on disk/logs/chat).
   Order in-script: impl first, factory second with impl as ctor arg (factory-first ruling
   in the script header refers to receipt ordering; the lineage assert is
   `factory.implementation() == impl`).
3. Anchor check: live bytecodes MUST match §1 keccaks (3ea7b47c impl, 7631c75d factory).
4. Receipt: addresses + tx hashes → DEPLOY_RECEIPT json + ADR amend + PR #231 merge.
5. Indexer + miniapp env flip to 480 is a downstream card, not this gate.

## 4. Portal Contract Entrypoints whitelist (Flux lane — portal ops are FLUX-only)
- Target: app `app_d3f03e8bce15b7c4580069bf4ea882c2` / rp `rp_4fbd445435612f67`,
  signer `0xaB7dFA7a9DB86bcf78EA0E468862F9A5ed6Ff228` (ADR-0012 rotation).
- File the §3-produced mainnet factory address as the whitelisted entrypoint;
  MiniKit `to` law: static allowlist = factory only (Flux verdict 11-27, "entrypoint law").
- Two flags gate the verify legs, both pre-deploy and both external:
  - **F1 sync-ticket (LIVE)**: `synced=false/false` since the 11-26 rotation, past
    ADR-0012's 24 h window → the portal support-ticket clause is the standing remedy.
    No production verify leg until synced flips true on both environments.
  - **F2 action-string divergence (OPEN)**: portal config echoes action string `verify`
    on both action_v4 ids while client + ADR-0012 law is `tanda_bill_settlement`.
    A dummy-proof probe could not discriminate which string the endpoint honors
    (schema validation on `proof` fires first for all three candidates).
    Adjudication = World support answer or a valid-proof test after F1 clears.

## 5. Gas sponsorship (inherits ADR-0013; O2 extends to mainnet by this ADR)
- O2 (recommended, Awaiting Flux ruling): sponsor seat-join + claim legs via the
  existing factory.callBill forwarder; create + fund legs stay user-pays.
- Mainnet economics (0.0015 gwei): worst case ~3 claims × 120 k gas ≈ 5.4e-7 ETH per bill — dust;
  relayer budget cap + NullifierUsed replay guard already shipped in-contract.
- Relayer key custody: vault lane; NEVER Vercel env plaintext on mainnet (ADR-0013 ruling item 2).
- Copy law: tandabill.world may say "zero fees" only for legs where sponsorship is live.

## 6. Gate verdict
**Technically READY.** Everything within agent reach is done and pinned: freeze,
anchors, chain facts, runbook, whitelist content, sponsorship policy.
Unmet inputs are external by construction — that IS the gate:
1. Owner hands: 0.01 ETH funding + broadcast key (0.01 ETH is the ONLY money this gate needs).
2. Flux: O2 ruling (ADR-0013), portal whitelist filing, F1/F2 adjudication.
3. World support: synced flip (F1) — ticket clause live.
Sequencing law SATISFIED as of this pass: Flux merged APP-1 shell
(tanda-miniapp #73) at 2026-11-28T01:35:35Z — the required pre-480 shell/entry-flow
review is complete; the gate now holds only on the three external inputs above.
