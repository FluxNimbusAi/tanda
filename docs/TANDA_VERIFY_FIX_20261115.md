# TANDA VERIFY — err_code_5 (SUPERSEDED — v2 disproven by real-solc compile; comment-stripping forbidden)

**Author:** Xixi (laptop node)
**Date:** 2026-11-15
**Status:** ~~Fixed artifact staged~~ → **SUPERSEDED & DISPROVEN.** Do not use any artifact or diagnosis from this document.

**Lineage README:** `SUPERSEDED_LINEAGE_README.md` (2,320 B) — pins every hash-scope of both lineages, the "check sizes first" rule, the no-comment-strip law, and the address-citation requirement for reconciliation tables.

## ⚠️ Why this document is wrong

The entire diagnostic chain in this document was built on `tanda_bytecode_W5.txt` (8,058 B init code) as the on-chain reference. **That file is a W5 rehearsal build artifact from a different contract lineage (init 8,058 = rehearsal contract `0xf63c…`), not the live canonical at `0x8644…b12` (4,671 B creation code, sha `5f1fbe5d…`).**

The "68-comment theory" is **disproven by direct solc compile** (Harley, 2026-11-15):

| Payload | Init size | Init sha256 | vs on-chain |
|---|---|---|---|
| Canonical JSON (comments intact) | 4,671 B | `5f1fbe5d…` | ✅ **exact match** |
| v2 (comment-stripped) | 4,671 B | `d8426aa0…` | ❌ wrong hash |

Comments **were** in the source the contract compiled from. The metadata hash rides raw source bytes including comments. Stripping them changes the hash — v2 would have failed the same err_code_5, just from a new drift.

The actual root cause was **transport corruption + form-field drift** (worldscan form ignored the JSON's optimizer setting, echoing False; superseded-lineage diffs from the W5-8058 reference). The `remappings` and `outputSelection` fields in the canonical JSON are **load-bearing**: solc serializes all settings fields into the metadata hash (remappings are hash-relevant even with zero imports), and `outputSelection` is the field that tells solc to emit bytecode at all — stripping either produces a different or empty compile. The canonical payload (sha `4a432968…`) must be submitted **untouched**, via an API route that POSTs the file verbatim (Etherscan V2 `verifystdjsoninput`, chainid=4801) to avoid textarea rewrap and checkbox drift.

## Correct submission surface

See `TANDA_VERIFY_CORRECTION_20261115.md` for the corrected record. The two files below are the complete submission surface, both byte-identical to the on-chain deploy source:

| File | Size | sha256 |
|---|---|---|
| `TandaBill.verify.sol` | 12,333 B | `7c4ddd39…cee226b` |
| `tanda_solc_json_input.verify.json` | 14,538 B | `4a432968…7117aa` |

## Deleted artifact

- `verification-standard-json-v2.json` (sha `d30aef61…`) — **deleted** from the lane. Backup retained at `scratch/backup_v2_20261115_130931.json`.

## Original content (preserved for the record, all claims below are DISPROVEN)

<details>
<summary>Click to expand the original (wrong) diagnostic chain</summary>

### The error

worldscan `verifyContract-solc-json` for `0x8644095B9722a41281314158006d194C59ab9b12` (World Chain Sepolia, 4801):

> Unable to Verify Contract Source Code — The Compiled Contract Bytecode for '' does NOT match the Contract Creation Code (err_code_5)

Compiler v0.8.38+commit.1835d247, optimization True, runs 200, constructor args `0000…66145f38cbac35ca6f1dfb4914df98f1614aea88` (Sepolia USDC — rehearsal token, correct for this deploy).

### Root cause (DISPROVEN)

**The standard-json `content` field carries 68 comment lines that were NOT in the source the contract was compiled from.**

Evidence chain:
1. Rebuilt `contracts/TandaBill.sol` (W5 canon, `initiatedAt` enforcement present) with forge 0.8.38, optimizer 200, evmVersion osaka → init code **8058 bytes**, solc version stamp `0008260033` (0.8.38) in metadata tail.
2. Lane reference `tanda_bytecode_W5.txt` (the claimed deploy canon) is also **8058 bytes** with the same version stamp → the on-chain creation code was produced from exactly this source at these settings.
3. The `verification-standard-json.json` on the lane embeds the W5 source verbatim — **including 68 `//` / `///` comment lines**.
4. solc's metadata hash (embedded in the bytecode tail, `bytecodeHash: ipfs`) hashes the **exact source text as given to the compiler**. Comments are part of that text. The deploy compiled comment-free source (or a different comment set); the verify artifact carries comments → different metadata hash → different init code → **err_code_5**.
5. Everything else in the artifact is already correct: compiler 0.8.38, optimizer 200, evmVersion osaka, constructor args, contract name. The mismatch is the source text alone.

### The fix (DISPROVEN)

Strip the 68 whole-line `//` / `///` comments from the `content` field (code is byte-identical — no inline comments exist in this file). Result:

| Item | Value |
|---|---|
| Fixed artifact | `verification-standard-json-v2.json` |
| sha256 | `d30aef61d31f92e251872dc789f5df0d7bda709780452e4622307e35638c2500` |
| Compiler | 0.8.38+commit.1835d247 |
| Optimizer | enabled, runs 200 |
| evmVersion | osaka |
| metadata.bytecodeHash | ipfs |
| Contract name | TandaBill |
| Constructor args (ABI-encoded) | `00000000000000000000000066145f38cbac35ca6f1dfb4914df98f1614aea88` |
| Expected creation code sha256 (init+args) | `a5e833cb476ddf9e9733b6f275cbedfaeac4fc7738ca5f8696c3b5cd9a6edfb4` |
| init bytes / total | 8058 / 8090 |

On-chain reference:
- address `0x8644095B9722a41281314158006d194C59ab9b12`, World Chain Sepolia (4801)
- deploy tx `0x1d0037ff87518d31256b88883fbc668e5b99f7712ebcfd17e5344d21d6c499fa`
- token arg = Sepolia USDC `0x66145F38CBAC35ca6F1dFB4914DF98f1614aEa88` (rehearsal — correct for this asset)

### Why this is safe (DISPROVEN)

- Comment stripping changes **zero** code bytes — the compiler output for code is identical; only the metadata hash (source-text dependent) changes, and it now matches what the deploy actually compiled.
- If v2 still fails (i.e. the deploy source had *some* comments but not all), the fallback is: pull the exact creation code from the deploy tx on worldscan, and bisect the comment set. But the whole-line strip is the canonical form explorers expect and the most likely match.
- This is the **rehearsal** contract (Sepolia). The mainnet deploy (W9) will use a fresh standard-json generated from the same comment-stripped source — same fix applies automatically.

### Reconciliation with Harley's payload (DISPROVEN)

Harley produced `tanda_solc_json_input.verify.json` (sha `4a432968…7117aa`) with a different diagnosis: **evmVersion drift** (osaka vs paris), not comments. Her payload uses the **comment-bearing** source (11,375 chars, 68 comments) with `evmVersion: osaka`.

**Hard discrepancies:**

| Item | Xixi v2 (comment-stripped) | Harley payload (comment-bearing) | On-chain (W5 ref) |
|---|---|---|---|
| Source chars | 6,515 | 11,375 | unknown (metadata hash `e3d260…`) |
| Comment lines | 0 | 68 | unknown |
| evmVersion | osaka | osaka | osaka (version stamp `0008260033`) |
| Init code size | 8,058 B (forge rebuild) | 8,058 B (claimed) | 8,058 B (W5 ref) |
| Metadata hash | unknown (no solc binary) | `6583c7…` (forge rebuild) | `e3d260…` (W5 ref) |
| Code portion (excl metadata) | 8,015 B | 8,015 B | 8,015 B |

**Key finding:** The code portion (excl 43-byte metadata) is **identical** across all variants. The ONLY difference is the metadata hash, which is a function of the exact source text fed to solc. Harley's payload (comment-bearing) compiles to metadata hash `6583c7…` which **does not match** the on-chain `e3d260…`. My v2 (comment-stripped) is the more likely match but cannot be verified without a solc binary on this node.

**Harley's 4,671 B claim:** Her message states "creation code 4671 B, sha 5f1fbe5d…". This matches **no local artifact** (init=8,058 B, deployed=7,696 B, fork runtime=4,508 B). This figure needs reconciliation before submission.

**Recommendation:** Submit **both** payloads to worldscan. My v2 first (comment-stripped, more likely metadata match), Harley's as fallback. If both fail, the on-chain source was a third variant and we need to pull the exact creation code from deploy tx `0x1d0037ff…c499fa` to bisect the source text.

### Submission (Flux/Nimbus) (DISPROVEN)

1. Paste `verification-standard-json-v2.json` into the worldscan solc-json verify form (or API if a key is available).
2. Compiler: `0.8.38+commit.1835d247`, Optimization: Yes, Runs: 200.
3. Constructor Arguments: `00000000000000000000000066145f38cbac35ca6f1dfb4914df98f1614aea88`
4. Contract name: `TandaBill` (path `contracts/TandaBill.sol:TandaBill`)
5. Report the result. If it verifies, the rehearsal asset is fully on-chain + source-verified; W9 mainnet proceeds on the same canon.
6. **If v2 fails:** try Harley's `tanda_solc_json_input.verify.json` as fallback.
7. **If both fail:** pull the exact creation code from deploy tx on worldscan and bisect the source text.

</details>
