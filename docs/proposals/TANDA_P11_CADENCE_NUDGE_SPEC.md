# TANDA P1.1 — MiniKit Cadence Nudge: Implementation Spec

Status: RATIFIED SPEC (task t_f709b13d). Worker tasks: implement t_0d4fb7c5, tests t_7313cbab, docs t_05a30a74.
Date: 2026-11-17. Author: nimbus. No contract changes — P1.1 is purely off-chain (indexer + notification lane).

## 1. Problem & origin
Backlog P1.1 (`docs/research/TANDA_W10_BACKLOG_20261116.md`): Splitwise Pro's #1 retention driver is
calendar-cadence reminders (research lane 1 #5: monthly summary email, per-bill advance reminders).
Tanda's equivalent: **weekly digest for open bills with unsettled expenses + settlement-window countdown
push**, delivered via World App MiniKit notifications. The consent banner (`NotificationConsent`) and the
server-side dispatcher (`tanda-miniapp/src/app/api/notify/route.ts`) already shipped in W10 — this spec
defines and scopes the MISSING leg: the **trigger engine** that decides who gets what nudge, when, once.

## 2. Architecture decision (binding for all three child tasks)
New stdlib-only Python service in tanda-sync: **`services/nudge_engine.py`** — one-shot `--once`
evaluate-and-send run, invoked by an external scheduler every 30 min (Hermes cron / Task Scheduler).
NOT a resident daemon (bill_index.py stays the only resident service; single-writer SQLite discipline).
Data flow:
1. Read `bill_index.db` (same dir as bill_index.py): live bills = rows with `status='success'` AND
   `bill_address` non-null; verified seat wallets from `seat_grants` (bill_address, wallet_address).
2. Poll each live bill's contract state over RPC `https://worldchain-sepolia.g.alchemy.com/public`
   (4801) via public getters: `seats(i)`, `expenses(i)` (walk while < count; swap-pop keeps dense),
   `settlements(i)` last index, `settlements.length`, `escrowBalance`, `settlementInitiated`, `owner()`.
   All factory-era bills answer the TandaBillV2 read ABI (fast-twin + pre-forwarder + prod; V1 legacy
   direct-deploy bills are NOT in bill_index → out of scope).
3. Evaluate triggers (§3), dedupe against engine-owned table (§5), batch POST to the miniapp
   `/api/notify` with `Authorization: Bearer $NOTIFY_INTERNAL_KEY`.
The engine NEVER holds `MINIKIT_API_KEY` (lives only in the miniapp server) and never learns consent
state — non-consenting wallets are silently skipped platform-side.
Env: `TANDA_NUDGE_ENABLED=1` (default: engine prints plan and exits 0 without sending — safe to deploy),
`TANDA_NUDGE_DRY_RUN=1` (print payloads, no POST), `NOTIFY_BASE_URL` (default `http://127.0.0.1:3112`),
`NOTIFY_INTERNAL_KEY` (must match miniapp env; generate at runtime, never inline literals).

## 3. Trigger library (the "cadence nudge" proper)
Constants read from contract (`SETTLEMENT_WINDOW = 1h`, `MAX_HOLD = 72h`) — engine fetches via the two
public getters, with fallback literals 1h/72h if the read reverts (legacy era). All times UTC.
Every send carries `mini_app_path` deep-link and an `idempotency_key` = the dedup key (§5).

| Kind | Condition (evaluated per bill per run) | Target | Timing / cadence | Copy (en) | Link |
|---|---|---|---|---|---|
| N1 weekly-digest | ≥1 expense with `settled==false` AND last `addedAt` older than 7d AND no pending settlement | each verified seat wallet | Monday 15:00 UTC run only; one message per wallet aggregating up to 3 bills | "Still ${n} unsettled across ${c} bill(s) — tap to review" | /home |
| N2a confirm-early | settlement pending (`settledAt==0, refunded==0, fullyConfirmedAt==0`) | expectedMask seats NOT in confirmedMask (∩ seat_grants) | `initiatedAt + 2h` (±30 min poll tolerance) | "You're 1 of ${k} holding up ${billName} — tap to confirm" | /home |
| N2b confirm-late | same | same | `initiatedAt + 20h` | "Settlement expires in ${h}h — confirm now or escrow auto-refunds" (${h} = 72−hours-since-init) | /home |
| N2c expiry-final | same AND `now ≥ initiatedAt + 60h` | same | once, `initiatedAt + 60h` | "Last call: ${h}h left before the ${usdc} escrow returns to the funder" | /home |
| N3a execute-ready | `fullyConfirmedAt != 0 && settledAt == 0` | owner wallet only | `fullyConfirmedAt + SETTLEMENT_WINDOW + 10 min` | "All seats confirmed — settlement is ready. One tap to open payouts." | /home |
| N3b claim-me | `settledAt != 0` (P0.1a pull-claims open) | expectedMask seats NOT in claimedMask (∩ seat_grants) | `settledAt + 6h`, repeat once at `settledAt + 26h` | "Your ${usdc} payout is ready to claim on ${billName}" | /home |

Amount math for `${usdc}`: USDC 6 decimals; seat share = `settlements[last].payouts[rank]` where
`rank = popcount(expectedMask & ((1<<seatId)-1))` — the dense-vector rule from P0.1a `_payoutAt`
(TandaBillV2.sol L405). Format: trim trailing zeros, e.g. 3750000 → "3.75".
DEFERRED (explicitly not P1.1): N4 settled-receipt, N5 refund-fired notice, N6 monthly recap —
event-driven extras, next pass. Do not implement.

## 4. Frequency & platform-safety rules (hard)
- **Per-wallet cap**: max 2 sends rolling 24h (N2a/N2b/N2c count together for the same settlement;
  the newest wins when the cap bites — never drop an N2c in favor of an N1).
- **Unverified-app ramp**: while the portal app is unverified, World caps 40 notifications / 4h window
  (SDK-verified; miniapp route comment). Engine batches each run so cumulative wallet-addresses sent in
  any 4h window ≤ 40 (`TANDA_NUDGE_VERIFIED=1` env removes the ramp for production).
- Batches respect the dispatcher's `MAX_WALLETS=200` cap; all wallets in one POST share the bill's copy.
- **Privacy guardrail (from W10 spec §3)**: recipients = live contract seat wallet ∧ `seat_grants` row
  for that bill. A wallet that left the roster (`active==false`) or was never World-ID-verified gets
  nothing. Zero marketing sends; only the six kinds above.
- `already_requested`/`user_rejected` consent state is client-side (localStorage) — engine must NOT
  infer or re-prompt; no client changes in this slice.

## 5. Dedup & state (crash-safe, restart-safe)
Engine-owned table in the SAME `bill_index.db` (create-if-missing; writer side must use
`PRAGMA busy_timeout=15000` + rollback on every error branch — single-writer lesson from /grants):
```sql
CREATE TABLE IF NOT EXISTS nudge_state (
  dedup_key TEXT PRIMARY KEY,          -- deterministic, recomputable
  bill_address TEXT, wallet_address TEXT, kind TEXT,
  status TEXT NOT NULL DEFAULT 'queued',   -- queued -> sent | failed
  period TEXT NOT NULL,                -- trigger bucket (see keys below)
  created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now'))
);
```
Key scheme (deterministic ⇒ engine restart replays nothing new):
- N1: `n1:{isoYearWeek}:{wallet}` (wallet-level aggregate, not per-bill)
- N2a/b/c: `n2{a|b|c}:{bill}:{settlementId}:{wallet}`
- N3a: `n3a:{bill}:{settlementId}`  ·  N3b: `n3b:{bill}:{settlementId}:{wallet}:{1|2}`
Flow per run: compute candidate set → INSERT OR IGNORE queued rows for new keys → POST batches →
on dispatcher `ok:true` (or `deduped:true`) UPDATE status='sent'; failure leaves 'queued' →
one retry next run; 'failed' after 3 tries, logged to stderr. A send that half-failed upstream is
at-w-most-once: the dispatcher's own idempotency map (24 h TTL) is the backstop for retry payloads
carrying the same `idempotency_key` = dedup_key.

## 6. Edge cases (each gets a test in t_7313cbab)
1. **Bill fully settled** (`settledAt!=0` and `claimedMask==expectedMask`) → terminal, skip forever.
2. **Refunded** (`refunded==1`) → terminal, skip. Post-72h never-confirmed bills may still be
   re-initiated by the creator — new settlementId → fresh keys, nudges resume legally.
3. **Wallet rotation mid-nudge** (`SeatWalletRotated`): live contract read is the source of truth at
   send time; rotated-out wallet gets nothing further; rotated-in wallet nudges only after its own
   verify-proof lands it in seat_grants (P0.1b flow).
4. **Seat not in seat_grants** (created bills before grant indexing, or unverified seat) → silently
   skipped; NO retries or error rows.
5. **bill_index row pending / no bill_address** → skip row (indexer lag is normal).
6. **RPC hiccup / revert on a getter** → skip that bill for this run, no partial sends, exit 0.
7. **Two settlements deep history** → only the LAST settlement drives N2/N3; older ones terminal.
8. **Clock drift** (±30 min poll cadence): trigger fires on the first run at-or-after the due time;
   never retro-fires more than 6 h past due (a run that resumes after a long outage must not blast
   stale nudges — skip kinds whose due time is > 6 h overdue, EXCEPT N2c which is the last-call
   message and stays valid until initiatedAt+72h).
9. **User in many bills** → N1 aggregates per wallet (≤3 bill names listed, "+N more"); N2/N3 remain
   per-bill but the 24 h wallet cap in §4 throttles bursts.
10. **Dispatcher unconfigured** (501 from /api/notify: missing MINIKIT_API_KEY/APP_ID on the miniapp)
    → treat as retryable 'queued', never mark sent; log once per run.
11. **Duplicate runs** (scheduler overlap): INSERT-then-send ordering + PRIMARY KEY make the second
    run a no-op; safe to run `--once` concurrently.

## 7. Acceptance criteria (definition of done for the P1.1 lane)
Implement (t_0d4fb7c5):
- [ ] `services/nudge_engine.py`, stdlib only (json/sqlite3/urllib/argparse), mirrors bill_index.py
      conventions (runtime-generated secrets, no literals; 9 s AbortController equivalent via
      urlopen timeout).
- [ ] Modes: `--once` (production single pass), `--dry-run`, `--self-test` (fixture DB + injected
      fake RPC/HTTP callables — ZERO network in self-test).
- [ ] Sends ONLY through miniapp /api/notify with Bearer NOTIFY_INTERNAL_KEY; payload shape
      `{wallet_addresses, localisations:[{language:"en",title,message}], mini_app_path,
      idempotency_key}`; title ≤ 72, message ≤ 280 enforced in-engine before dispatch.
- [ ] Default disabled: without `TANDA_NUDGE_ENABLED=1` the engine plans and exits, sends nothing.
- [ ] `nudge_state` table creation is idempotent and safe alongside bill_index.py's writer
      (busy_timeout + rollback discipline).
- [ ] No contract changes; `forge test` untouched and still green (regression guard only).
Tests (t_7313cbab):
- [ ] `--self-test` passes offline and covers: each of the six kinds firing at boundary times,
      terminal-state skip (case 1–2), seat_grants filtering (4), dedup across two consecutive runs
      (11), 24 h wallet cap incl. N2c priority rule, 40/4h ramp batching math, >6 h overdue
      suppression with N2c exception (8), payout rank math vs `_payoutAt` incl. non-contiguous
      expectedMask fixture (e.g. bits 0,3,7 → ranks 0,1,2).
- [ ] Live rehearsal (testnet, existing 4801 bills): one dry-run sweep printing the exact payload set;
      if MINIKIT creds are configured on the dev-lane miniapp, at least one REAL end-to-end N2a to a
      consenting test wallet with the World App notification observed — else record the missing-cred
      gate in the receipt, do not fake it.
Docs (t_05a30a74):
- [ ] `docs/P11_NUDGE.md`: trigger table (copy verbatim from §3), env flags, scheduler registration
      snippet (30-min cadence), release-notes paragraph; miniapp `.env.sample` note that
      NOTIFY_INTERNAL_KEY is consumed by the engine too.
- [ ] Backlog line P1.1 annotated SHIPPED with commit ref; W10_FRONTEND_SPEC §3 slice 3/4 status
      updated (N1–N3 shipped, N4–N6 deferred).
Guardrail: guidelines-compliant cadence (opt-in, low frequency, meaningful triggers) is the whole point
— any change that increases send volume beyond §4 caps needs a spec amendment, not an implementation
"improvement".
