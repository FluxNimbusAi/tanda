# ⚠️ LINEAGE MARKER — read before touching any W5-named artifact

**Two byte-lineages of Tanda exist. Only one is live.** Mixing them caused err_code_5 loops on 2026-11-14/15.

## LIVE canonical — 0x8644095B9722a41281314158006d194C59ab9b12 (World Chain Sepolia, 4801)
- Source artifact: `.tip_28b63a6/out/TandaBill.sol/TandaBill.json` + repo `artifacts/tanda_bytecode.txt` (9,343 B file, no 0x prefix)
- **init 4,671 B** (tx input 4,703 B incl. 32 B ctor arg) | **runtime 4,508 B**
- init sha256 (bytes): `3946e26302bfc782…` | init-as-hex-string sha256: `5f1fbe5dba0a…` | init+ctor sha256: `50e7b01a3eb8…`
- runtime sha256 zeroed: `dcde760ef2478a76…` | baked+live: `6aa4c60ef2d13d6f…07d21188` (== DEPLOY_RECEIPT.runtime_sha256)
- ipfs metadata hash in runtime tail: `06aad1c0f8874401e204eddeb6882b7166aeb6bef82c83ebc05c1401313959ea64`-derived — rides the FULL source text **including all comments**
- Verify payload: `tanda_solc_json_input.verify.json` (sha `4a4329687f694482…`) / `TandaBill.verify.sol` (sha `7c4ddd39e8d8eb19…`) — proven byte-identical against tx `0x1d0037ff…499fa`

## SUPERSEDED — 0xf63c92456D68A97B75C86a72Aec092f091DD7bb2 (do NOT verify, cite, or diff against)
- Files bearing this lineage in this folder: `tanda_bytecode_W5.txt` (**init 8,058 B** / runtime **7,696 B**), `tanda_abi_W5.json`, `TandaBill_W5.sol` build outputs, `world_W5.json`-era drafts
- metadata tail hash `e3d2608f6c16c830…` — this is the value that misleads reconciliations when treated as "on-chain W5 ref"
- Deploy tx `0xbba0ba48…` — logged SUPERSEDED in DEPLOY_RECEIPT.json (wrong-artifact deploy of 2026-11-14 13:38Z)

## Rules
1. "W5 canon" in prose ALWAYS means the 4,671/4,508 tip build. A file named `*_W5.*` is the 8,058/7,696 variant. Names differ from meanings — check sizes first.
2. Never strip comments from the source before verification: metadata hash (ipfs) rides raw text; comments were in the deployed source.
3. Any reconciliation table must state which contract address its numbers came from.
4. Mainnet W9 (480): deploy from the same comment-bearing source with osaka/opt-200/ipfs settings; generate its standard-json fresh; expected lineage numbers differ by ctor arg (mainnet USDC `0x79A0…24D1`) — bytecode NOT byte-identical across chains, by law (b4b57e5).
