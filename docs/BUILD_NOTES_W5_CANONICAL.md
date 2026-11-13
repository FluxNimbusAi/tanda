# W5 Step-2: canonical artifact regen — 2026-11-13 (Nimbus, PC lane)

Executed per handoff Step 2 (regenerate artifacts from pushed commit) plus the production gate
(enable optimizer runs=200, verify runtime size < 24,576 B) directed on the bridge.

## Build & test provenance
| Field | Value |
|---|---|
| Source commit | `c2066c1` (W5: SETTLEMENT_WINDOW enforcement) |
| Toolchain | forge 1.9.1-nightly, solc 0.8.38 |
| Production arm | `optimizer=true, optimizer_runs=200` (now pinned in foundry.toml) |
| Test suite (this arm) | 25 passed / 0 failed / 0 skipped — executed on PC @ c2066c1 |
| Default arm (reference) | 25 passed — bus runs (laptop lanes) at same tip |

## Sizes (EIP-170 gate)
| Arm | Runtime (B) | Margin to 24,576 | Initcode (B) |
|---|---|---|---|
| default (no optimizer) | 7,696 | 16,880 | 8,058 |
| **canonical: opt runs=200** | **4,508** | **20,068** | **4,671** |

Note correcting earlier chat claims: the bus pin's runtime size (~7,801 B) and the
"24,163 B" figure were both non-canonical — actual default-arm runtime is 7,696 B.
Every arm was always well under the deploy limit; no size risk existed.

## Findings baked into this regen
1. **Pinned ABI was stale.** `artifacts/tanda_abi.json` (lane pin `5aa2d344…`) predates W5:
   the `settlements` getter still had 2 outputs, missing `initiatedAt` added by `c2066c1`.
   The canonical ABI (34 entries) now includes the 3rd output. The same stale ABI was
   embedded in `world.json.contract.abi` — also corrected. "ABI regen byte-exact vs pin" was
   therefore not achievable from the pushed commit; byte-exactness was measured against the
   pre-W5 source.
2. **Pinned bytecode was a mixed-arm artifact.** 15,602-hex-char file ≠ runtime(7,696 B)
   ≠ initcode(8,058 B) of any single PC build; per earlier bus analysis it carried a laptop
   solc-metadata CBOR tail. Superseded — convention now stated explicitly:
   `tanda_bytecode.txt` = creation/initcode hex, lowercase, no `0x`, LF-trailing.
3. **Canonical hashes (this arm, opt runs=200):**
   - initcode sha256 (hex-text): `5f1fbe5dba0aac8b…`
   - runtime sha256 (bytes): `dcde760ef2478a76…`
   - world.json: `contract.address` remains `PENDING_DEPLOY` (fills after deploy).

## Reproduce
```
FOUNDRY_OPTIMIZER=true FOUNDRY_OPTIMIZER_RUNS=200 forge build --sizes   # now the repo default
forge test   # 25/25
```
