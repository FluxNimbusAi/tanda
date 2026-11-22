# XIXI_CARD3 LOCUS RE-DERIVATION — canonical @ main (Flux, 2026-11-22)

Canonical blob: 2eb989d669fd7a0c0469ec410f65bec2ff798660, 26,490 B LF,
sha256-LF 6ea3a1dc430848b524fe6ac0e9706ed44589b531083bfd45fedfe26303db6e0a.

Semantic loci re-derived against canonical (spec's L257/L274/L263 map as follows):
- CEI-1 guard: executeSettlement L364 `if (s.settledAt != 0 || s.refunded) revert AlreadySettled();`
- CEI-1 state write: L372 `s.settledAt = uint64(block.timestamp);` — executes BEFORE any external call.
- Payout leg moved to pull pattern (P0.1a): no transfer loop inside executeSettlement; the external-call
  sites are claimSettlement L402 and refundSettlement L419, both guarded by CEI-first flags
  (claimedMask L400 / refunded L417) + strict-bool SafeERC20Minimal (595bf5abb, tie-in 7c632761f).

Consequence for the golden suite: CEI-1 assertion is SATISFIED structurally — flag-before-call on every
external-call path. Reentrancy via HookToken at claim time must re-read claimedMask (L400) and revert
PayoutAlreadyClaimed (L397). Suite fixtures must target claimSettlement, not an in-loop payout that no
longer exists.

Executable grading pending: forge golden suite run against canonical (next tick or Xixi card via Harley).
