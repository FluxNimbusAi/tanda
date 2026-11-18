# MiniKit Cadence Nudge (P1.1)

Off-chain notification engine (`services/nudge_engine.py`) that nudges Tanda seats through the
World mini-app push channel (MiniKit) so bills actually reach settlement. Stdlib-only, one-shot
per run — designed for a 30-minute external scheduler, not a resident daemon
(`bill_index.py` stays the only always-on service; single-writer SQLite).

Spec: `docs/proposals/TANDA_P11_CADENCE_NUDGE_SPEC.md` §2–§7. Shipped via PR #11
(merge `22bb324`, foundry CI green).

## What it does

Each run: reads live bills from the indexer ledger (`bill_index.db`) → pulls on-chain truth via
read-only `eth_call`s to TandaBillV2 on World Chain Sepolia (4801) → evaluates six triggers →
dedups against an engine-owned `nudge_state` table → batch-POSTs to the mini-app
`/api/notify` dispatcher with a Bearer key.

The engine **never holds `MINIKIT_API_KEY`** (that lives only in the mini-app server) and never
sees user consent state — non-consenting wallets are silently skipped platform-side.

## The six nudges — when they appear

All times UTC; contract values (`SETTLEMENT_WINDOW` = 1 h, `MAX_HOLD` = 72 h) are read live,
with 1 h/72 h fallback for legacy-era bills. Every tap lands on `/home` in the mini-app.

| Kind | Push title | Fires when | Who gets it |
|---|---|---|---|
| N1 weekly digest | Tanda weekly digest | Monday 15:00 UTC run (6 h catch-up grace): bill has ≥1 unsettled expense older than 7 days and no pending settlement. One aggregate message per wallet (up to 3 bills named) | Every active, World-ID-verified seat wallet (∩ `seat_grants`) |
| N2a confirm-early | Confirm to settle your bill | Settlement initiated + 2 h, still awaiting full confirmation | Seats in `expectedMask` that have **not** confirmed |
| N2b confirm-late | Settlement about to expire | Initiated + 20 h; copy counts down remaining hours to auto-refund | Same unconfirmed seats |
| N2c expiry-final | Last call before auto-refund | Initiated + 60 h (once); names the escrow amount returning to the funder | Same unconfirmed seats |
| N3a execute-ready | Settlement ready — open payouts | Fully confirmed + settlement window + 10 min grace | Bill owner only |
| N3b claim-me | Your payout is ready to claim | Settled + 6 h, repeated once at settled + 26 h | Seats owed a payout that have **not** claimed (per-seat USDC amount) |

Guards: only the **last** settlement of a bill drives N2/N3; nothing fires for refunded/fully-
claimed or terminal bills; overdue triggers never retro-fire more than 6 h late (N2c excepted);
bills larger than 40 seats are skipped (matches the platform ramp).

## Frequency & privacy (hard rules)

- **Max 2 notifications per wallet per rolling 24 h.** When the cap bites, priority order is
  N2c > N3b > N3a > N2b > N2a > N1 — a last-call is never dropped in favor of a digest.
- **Unverified-app ramp:** ≤ 40 distinct wallets per rolling 4 h until the World portal
  verifies the app (`TANDA_NUDGE_VERIFIED=1` lifts it).
- Batch POSTs respect the dispatcher's 200-wallet-per-call cap; payload guards keep
  title ≤ 72 chars and message ≤ 280 chars.
- Recipients are always *live contract seat wallets ∩ `seat_grants`*: a wallet that left the
  roster or was never verified gets nothing. Zero marketing sends — only the six kinds above.
- Every send carries an `idempotency_key` = the dedup key, so a crash or replay mid-run can
  never double-send.

## Configuration

| Env var | Default | Meaning |
|---|---|---|
| `TANDA_NUDGE_ENABLED` | **unset = OFF** | Kill switch. Unset: true no-op before the DB is even opened (exit 0). Must be `1` to send anything. |
| `TANDA_NUDGE_DRY_RUN` | unset | `1` = print the exact payload plan, zero POSTs, zero writes (same as `--dry-run`). |
| `TANDA_NUDGE_VERIFIED` | unset | `1` = portal app verified; lifts the 40-wallet/4 h ramp. |
| `TANDA_NUDGE_DB` | fallthrough | Ledger path; unset falls back to `BILL_INDEX_DB` (house convention), then `services/bill_index.db`. |
| `TANDA_NUDGE_RPC_URL` | `https://worldchain-sepolia.g.alchemy.com/public` | Read-only RPC endpoint. |
| `NOTIFY_BASE_URL` | `http://127.0.0.1:3112` | Mini-app dispatcher base. |
| `NOTIFY_INTERNAL_KEY` | vault file | Bearer for `/api/notify`; env wins, else read from `~/.hermes-secrets/notify_internal_key.txt`. Never a literal in code. |

Fail-fast: a missing or table-less ledger exits 1 with a clear message rather than masquerading
as a healthy zero-candidate pass.

## Running it

```
python services/nudge_engine.py --self-test   # offline: 10 selector vectors + 20 scenario assertions, zero network
python services/nudge_engine.py --dry-run     # print today's exact plan; no sends, no writes
python services/nudge_engine.py --once        # one production pass (sends only if TANDA_NUDGE_ENABLED=1)
```

Deployment (currently **unarmed — inert until armed**): wire a 30-min cron to `--once`, place
`NOTIFY_INTERNAL_KEY` in the vault file, complete World portal verification, then set
`TANDA_NUDGE_ENABLED=1`. Queue state is observable at any time via the `nudge_state` table in
the ledger (`queued` → `sent` / `failed`; 3 failed attempts = dead-letter, never retried;
dispatcher 501 "not configured" leaves rows queued and retryable).

## User-visible behavior summary

A verified seat may receive up to two World-app pushes per day, each with one of the six titles
above and a bill-specific message (counts, countdown hours, or their exact USDC share). Tapping
opens the Tanda mini-app home to act. Opting out / consent prompts stay client-side (localStorage)
— the engine never re-prompts and never learns the answer.
