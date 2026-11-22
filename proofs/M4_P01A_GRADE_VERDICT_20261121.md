# M4-P0.1a Receipt — Independent Grade Verdict: PASS (Nimbus, 2026-11-21)

Receipt couriered in this branch: `proofs/m4_p01a_receipt_20261119.json`
(source home: gateway bridge store `C:/Users/dbvis/AppData/Local/hermes/bridge/m4_p01a_receipt_20261119.json`, 5,211 B,
courier copy verified byte-identical, sha256(raw)=sha256(LF)= a5557bb6f8c245858b3e88c83e255c95330132f38acbc9408b3c38bdca3122f5)

## Claims re-verified live THIS TICK (23:2x ET 2026-11-21)
| Claim | Recomputed | Result |
|---|---|---|
| tanda@PR#21 state | gh pr view: MERGED, mergedAt 2026-11-19T19:24:41Z | MATCH |
| tanda@PR#21 final_head_sha | headRefOid 02a861d3343e7b7735bba46e40d0cf7e05b99b61 | MATCH |
| tanda@PR#21 squash on main | d9a59f0bd823b8133d5761987b38a948f883024d is ancestor of origin/main | MATCH |
| tanda@PR#21 receipt_sha256_LF(diff origin/main..head) | recompute `git diff 6baefbcda0f8c2d2154fe6fcc638d11e97d30aed..02a861d3343e7b7735bba46e40d0cf7e05b99b61` LF = 39ee0315c2bd5666c4856634bbeb795aae4dd5c00b59d114d45dc25eb11051b7 (43,150 NormBytes) | MATCH (64-hex exact) |
| tanda-miniapp@PR#22 state | gh pr view: MERGED, mergedAt 2026-11-19T19:24:45Z | MATCH |
| tanda-miniapp@PR#22 final_head_sha | headRefOid 39662bb8996913d3d1aacdd193a0693fe280dd1e | MATCH |
| tanda-miniapp@PR#22 squash on main | 4cbd09fb6ec4767baa60848d0b535f451835601b is ancestor of origin/main | MATCH |
| tanda-miniapp@PR#22 receipt_sha256_LF(diff origin/main..head) | recompute `git diff 5c10895471703e9dfa11cc5e50a28ad3c177d739..39662bb8996913d3d1aacdd193a0693fe280dd1e` LF = e861e53b78567d920b1f52eb99d010b57bea6b8ddf64cc447016a55e0faeae39 (6,895 NormBytes) | MATCH (64-hex exact) |

## Verdict
PASS — every machine-checkable claim in m4_p01a_receipt_20261119.json reproduces exactly under independent
sha256-LF recompute from payload and live GitHub/git reads. No drift, no fabrication. M4-1a endpoint-contract
decision (proxy-first GET /api/settlements) is ratified by evidence; consistent with the already-merged
tanda-miniapp@main 75300ed "[API] seat-grants proxy-first + repo-relative DB defaults (M4-1a, Flux GO 11-20)".
