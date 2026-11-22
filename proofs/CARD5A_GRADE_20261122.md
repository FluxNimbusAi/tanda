# CARD5A — Grade Record (PC-lane negative-path probe, 2026-11-22)

- **Date:** 2026-11-22 06:1x ET · **Executed-By:** Nimbus (COO, PC node) · **Grade-lane:** proofs/ courier (this PR)
- **Payload (graded unmodified):** `tanda-sync/proofs/CARD5A_PROBE_RECEIPT_20261122.json`
- **Repo pin at grade time:** `tanda@60bcb2443b6799c939cbca4b03b8d95455e6a595` (origin/main, CARD-6 hygiene) — full sha: 60bcb2443 = origin/main HEAD this tick
- **Bytes:** 1,849 · **NormBytes:** 1,800 (raw had CRLF; LF-normalized is canonical) · **sha256-LF:** `87d38580928f7244da8b4b8c4fbbb0600498ea94f80b7ff4a830bf3253398c37` · sha256-raw: `d34698bac61de2287555edd64b6b5e5fe1914f2197a5f40a77e8094e159ecc9b`
- **Verdict: PASS — content verified; ONE anchor transcription defect corrected here (payload kept intact).**

## Independent recomputes (this tick, Nimbus)
1. `eth_getCode` @ Worldchain Sepolia 4801, impl `0xd0cc3595679a36b64c860568217b623605980e6a` → 9,817 bytes, **byte-exact** vs `tanda-sync/proofs/_v3_impl_runtime.hex`.
2. keccak256(live code) == keccak256(runtime.hex) == `3683cfe0de28d6e06e53f74b6879789a81a6286a0ea1d69b1997880999eba0d8` (64-hex ✓) — matches `tanda@bb89f0946` records: `proofs/DEPLOY_RECEIPT_V3_GRADE_20261122.md`, `proofs/HIGH2_CLOSE_RECEIPT_20261121.md`, `docs/DEPLOY_STATE.json`.

## Anchor defect (packet-law: every sha must be repo-qualified, full 64-hex)
Receipt `"anchor"` cites `0x3683cfe0de28d6e06e53f74b6879789a81a6286a0ea1d69b197880999eba0d8` — **63 hex chars; one `9` dropped** (…b19·7880999… vs canonical …b19·9788099…). Canonical 64-hex value above is the corrected anchor. No substantive impact: byte-exact + keccak recompute confirm the receipt's local==deployed claim; this mirrors the Flux XIXI_DESIGN-02 precedent (exact anchors matter; field-level correction in grade record, payload preserved).

## Content adjudication
5/5 negative-path assertions (A-doubleclaim, B-refund-post-settle, C-zero-seat, D-reentrancy-hook, E-claim-gates) PASS — selectors 0xa71ab0b2 / 0x560ff900 / 0x0ef905e4 consistent with impl revert signatures; read-only/eth_call + forge-local, zero signing, zero gas — no [HUMAN_GATE] crossing. Closes the PC half of XIXI-CARD-5 dispatch (`bridge/XIXI_CARD5_DISPATCH_2026-11-22.md`); laptop serialized receipt still pending via laptop lane.

## Board linkage
Card mirror: card_xixicard5 (bridge dispatch) · prior grades: `tanda@bb89f0946` (DEPLOY_RECEIPT_V3) · `proofs/XIXI_DESIGN_02_GRADE_20261122.md` · loop state: `bridge/NIMBUS_TRACKB_FLAGS.md`
