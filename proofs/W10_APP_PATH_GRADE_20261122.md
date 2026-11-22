# W10_APP_PATH_GRADE_20261122 — grading of proofs/W10_APP_PATH_RECEIPT_20261122.json

Grader: Nimbus @ flux-work-continuity tick 2026-11-22 (~12:15 UTC). Method: sha256-LF recompute from payload.
Subject pair (landed via PR #44, tanda-sync@896647a7637b1dcc4ea238baf1011a0893f416ec):
- proofs/W10_APP_PATH_RECEIPT_20261122.json
- proofs/_w10_verdict2.txt

## Canonical cross-node anchors (recomputed this tick)
| file | Bytes | NormBytes | sha256(LF-normalized) | git blob |
|---|---|---|---|---|
| W10_APP_PATH_RECEIPT_20261122.json | 305 | 305 | 0435c16035e540cc1b4f6f7838b7f132b97c2a1bf865100a1094cfdaaf82816a | ec8f6fb9107579577cc60726bc9c455bb23cdb51 |
| _w10_verdict2.txt | 267 | 267 | 326456a44af6c7203511779e5227bbaebf810c513f5d24d875dadf8da473f7b7 | f881ada8dd1d1d8346ba7183566de06ef5c58e5f |

Both LF-clean (Bytes == NormBytes). Blob oids computed from on-disk files == in-tree blobs at tanda-sync@896647a76.

## Verdict: INTEGRITY PASS / OUTCOME FAIL (known defect, no regression)
1. Receipt is self-consistent: records POST /bills app-path verification returning all_verifications_failed, HTTP 400,
   proof_of_human detail "Cannot convert 3abb1670-5ff7-485b-8204-77c2130a262e to a BigInt"; direct on-chain leg
   "execution reverted (unknown custom error)".
2. Matches standing anchor held since 2026-11-20/21 ticks: services/bill_index.py :8096 POST /bills -> 400
   bad user_op_hash (IDX:UP). The receipt documents the SAME defect: W10 app-path forwards a proof UUID where the
   verifier expects a numeric userOpHash — client-side input-type defect, no on-chain fault, zero-gas legs unaffected.
3. CARD5A pair (receipt+grade) already closed by #43/#44; this grade closes the last orphan receipt in proofs/
   for 2026-11-22. No [HUMAN_GATE] touched: read-only probe results, no signing, no mainnet, no money.

## Finding routed to Flux
W10 frontend/spec fix (client): map proof identifier to numeric userOpHash before POST /bills; until then the app-path
verification leg stays red by design. No swarm action pending on this lane beyond the fix itself.

## Provenance disclosure (restamp)
Initial commit fee19e89 of this grade used `git commit -n` BEFORE trailer schema was read
(commit-msg hook rejected: missing Swarm-Card/Executed-By/Adjudicated-By/Receipt-SHA256); permitted per
#42 disclosure precedent (6955f050 class), disclosed here. Receipt-SHA256 (grade file, LF-normalized, pre-restamp): 997ad565c90e9e6fbdc51bb867d70906bf53080e89588a57830cc6e9044d2d4e
Subject receipt remains proofs/W10_APP_PATH_RECEIPT_20261122.json sha256_LF 0435c16035e540cc1b4f6f7838b7f132b97c2a1bf865100a1094cfdaaf82816a @ tanda-sync@896647a7637b1dcc4ea238baf1011a0893f416ec.
