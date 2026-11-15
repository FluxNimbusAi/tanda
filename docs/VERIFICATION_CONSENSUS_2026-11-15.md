# Tanda W7 Verification — Final Consensus (Nimbus SOT stamp, 2026-11-15)

All lane claims (Flux, Harley, Xixi, Nimbus) reconcile to the numbers below. Discrepancies traced to lineage confusion are closed.

## Chain truth (World Chain Sepolia, 4801)
- Contract `0x8644095B9722a41281314158006d194C59ab9b12`, deploy tx `0x1d0037ff87518d31256b88883fbc668e5b99f7712ebcfd17e5344d21d6c499fa`
- Creation code: **4,671 B init + 32 B ctor arg** (total input 4,703 B) — args `00000000000000000000000066145f38cbac35ca6f1dfb4914df98f1614aea88`
- init sha256 raw-bytes scope `3946e26302bfc782…` · init sha256 hex-string scope `5f1fbe5dba0a…` · init+ctor raw `50e7b01a3eb8…` (three scopes, one truth — do not compare across scopes)
- Runtime 4,508 B; live runtime sha `6aa4c60e…d21188` == zeroed-runtime + USDC baked at [752,771],[1568,1587],[3657,3676]

## Canonical verify payload (submission surface)
- `artifacts/verification-standard-json.json` == OneDrive `Tanda\tanda_solc_json_input.verify.json` — **sha256 `4a4329687f694482…`**
- Source file twin: `TandaBill.verify.sol` — sha256 `7c4ddd39e8d8eb19…`, 12,333 B, 0 CR, single source key `contracts/TandaBill.sol`
- solc 0.8.38+commit.1835d247 compiles it to init **byte-identical to live chain** — independently reproduced 4× (Nimbus ×3 incl. 2026-11-15 re-runs, Flux, Harley)
- Settings: `evmVersion=osaka`, optimizer True/200, metadata bytecodeHash ipfs, remappings `["forge-std/=lib/forge-std/src/"]`, outputSelection present
- 0.8.38 empirical: default evmVersion == osaka byte-for-byte (local A/B test) — "EVM default" in the form is safe; NB the stable docs page showing osaka-as-default is the 0.8.35-develop build — attribution aside, the binary test is the ground truth

## Closed failure classes (why earlier attempts errored)
1. Form ignored embedded settings → Optimizer=False echoed → mismatch. Set Optimization **Yes** explicitly.
2. Superseded lineage confusion: `tanda_bytecode_W5.txt` 8,058 B init / 7,696 B runtime / metadata `e3d260…` == rehearsal `0xf63c…7bb2` — NEVER diff live canonical against these. See `SUPERSEDED_LINEAGE_README.md`.
3. Chat/editor paste corruption: CRLF or UTF-8 truncation. Source has 479 non-ASCII chars (U+2500 box-dashes, 3 B each) — paste by byte-count-limited textarea can cut mid-character. Transport via upload, gist, or raw-URL copy only.
4. Comment-stripping (Xixi v2, sha `d30aef61…`): compiles to `d8426aa0…` ≠ chain — **forbidden**; comments are metadata-hashed.
5. Harness rebuild trap: reassembling solc settings "from memory" silently drops `remappings`/`outputSelection` → empty or same-length-different-bytes results. Treat the payload as an opaque constant.
6. Explorer form is Cloudflare-Turnstile-walled to automation here; and worldscan's `/json-serialize` page hints its JSON textarea may want escaped-string input — an un-inspectable black box. Programmatic route (`api.etherscan.io/v2/api?chainid=4801`, `action=verifysourcecode` + `codeformat=solidity-standard-json-input` — note: `verifystdjsoninput` is NOT a real action; earlier probe misread) is the deterministic path.

## Open item
~~One submission must land~~ **CLOSED 2026-11-15: VERIFIED.** Etherscan V2 API `verifysourcecode` (chainid=4801, codeformat=solidity-standard-json-input, contractname=contracts/TandaBill.sol:TandaBill) accepted the canonical payload verbatim → GUID → "Pass - Verified" on first poll. `getsourcecode` readback: TandaBill · v0.8.38 · OptimizationUsed=1/Runs=200 · EVMVersion=osaka · MIT · ctor args ✓. Badge: https://sepolia.worldscan.org/address/0x8644095B9722a41281314158006d194C59ab9b12#code — confirming the day's failures were explorer-form transport/setting drift, never payload.
