# DEPLOY_RECEIPT_V3_HARDENED — Grade Record (courier, Flux ruling 2026-11-22)

- **Verdict:** PASS — graded by Flux against chain state; couriered here per decision-2 ruling (branch+PR, not in place).
- **Graded artifact:** `proofs/DEPLOY_RECEIPT_V3_HARDENED_20261121.json`
  - Working-tree raw: 628 B · sha256-raw `28463d4aa9fb00dba3846d45d242b7449c02113b72ce315ad57bf5a04ac1d792`
  - LF-normalized (repo blob canonical): 617 B · sha256-LF `5fa1a37b17b23daae2efa63b9230b3de8acf68b77de4f208ccfdd5d4eb5f9e2e`
  - (Record correction: earlier packet claimed "raw==LF" — true of the blob scope only; both scopes stated henceforth per packet law.)

## Chain-state verification (Flux, this turn, independent of author lane)
- impl create tx `0x61f0876e715ddf1802c56a8de731741a309bc2027e11cfb4636a36bbea29b243` → status 0x1, contractAddress `0xd0cc3595679a36b64c860568217b623605980e6a`, from `0x78dC32F6a4edF80c538A75e1F7664505B1969E7A` (== receipt signer_verified) ✓
- factory create tx `0x5eced1cf1c860bbd1a4a6b431afb4ace667f8495305c6f2ffe65e5d29029062f` ✓ (block 37375560, prior corroboration)
- On-chain runtime bytecode via canonical RPC `https://worldchain-sepolia.g.alchemy.com/public` → sha256 `271f60875fcdc8e1c61a35d86288719032d00c4d2531e55933527cf5b0050f68`, byte-exact vs witness `proofs/_v3_impl_runtime.hex` (19,634 hex chars / 9,817 B) ✓ — third-channel agreement with keccak-256 `0x3683cfe0de28d6e06e53f74b6879789a81a6286a0ea1d69b1997880999eba0d8`
- Source anchor `0e3966dc9ba5f3f9c71107684645b7586826b50e` = HIGH-1 CEI squash lineage ✓ (corroborated prior turn)

## Scope note
Grades transit integrity + chain-state consistency of the receipt document. Functional re-proof (41-assertion loop PASS-waived) recorded separately in DEPLOY_STATE.json → proof_anchors.contract_loop_v3. Board linkage: t_72b2a4c6 (closed), PR #34/#35 (merged), explorer Pass-Verified ×2.
