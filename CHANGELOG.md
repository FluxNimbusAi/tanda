# Changelog

All notable changes to Tanda. Format favors release-notes readiness over strict Keep-a-Changelog.

## [P1.1] — 2026-11-18 — MiniKit cadence nudge engine

**Added** (`services/nudge_engine.py`, PR #11, merge `22bb324`, foundry CI green — see
`docs/MINIKIT_CADENCE_NUDGE.md` for the full guide):

- Off-chain, stdlib-only nudge engine: a one-shot `--once` pass for a 30-minute external
  scheduler. Reads the indexer ledger (`bill_index.db`), confirms on-chain truth with
  read-only `eth_call`s to TandaBillV2 (World Chain Sepolia 4801), and batch-sends World
  mini-app pushes through the mini-app `/api/notify` dispatcher. The engine never holds
  `MINIKIT_API_KEY`.
- Six triggers, all deep-linked to `/home`: **N1** weekly digest (Mon 15:00 UTC; unsettled
  expenses ≥ 7 days), **N2a/b/c** confirm countdowns at +2 h / +20 h / +60 h before escrow
  auto-refund, **N3a** owner "settlement ready" (fully confirmed + window + 10 min),
  **N3b** per-seat "claim your payout" waves at settled + 6 h and + 26 h.
- Frequency safety: hard cap 2 pushes/wallet/rolling 24 h (priority N2c > N3b > N3a > N2b >
  N2a > N1 when the cap bites), 40-wallet/4 h ramp while the app is unverified, 200-wallet
  batch chunks, title ≤ 72 / message ≤ 280 chars.
- Privacy: recipients are live contract seat wallets ∩ `seat_grants` only; zero marketing
  sends; consent state stays client-side and invisible to the engine.
- Crash/replay safety: deterministic `nudge_state` dedup table (INSERT-first, idempotency key
  on every send); 3-attempt dead-letter; dispatcher 501 keeps rows queued and retryable.
- Ops: default-disabled kill switch `TANDA_NUDGE_ENABLED` (true no-op before any DB open);
  `--dry-run` plan mode; `--self-test` offline suite (10 selector vectors + 20 scenario
  assertions, zero network); fail-fast on missing/empty ledger (no silent healthy 0-candidate
  pass); ledger path chain `TANDA_NUDGE_DB → BILL_INDEX_DB → services/bill_index.db`.

**Status:** shipped to `main`, **unarmed** — inert until portal verification, a
`NOTIFY_INTERNAL_KEY` vault file, the 30-min cron, and `TANDA_NUDGE_ENABLED=1`.
