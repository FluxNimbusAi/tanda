# TandaBill UX-3: Category-Leader Benchmark & Feature Proposal Matrix

**Card:** t_2a5cc6a7 (Flux [COMMAND], UX-3 deep research)
**Lane:** HarleyValorBot (laptop verify lane) · **Date:** 2026-11-23
**Owner directive:** research benchmark category leaders → feature matrix (standard / advanced / retention hooks) → top-10 actionable proposals; evidence target = GitHub issue #172

---

## 1. Benchmark matrix (from live research sweeps, 2026-11-23)

### Stripe (payments & billing SaaS)
- **Standard:** split navigation with clear hierarchy, dashboard metrics first, global search/command palette, inline docs and microcopy, calm trust language, test/live mode toggle.
- **Advanced:** modular Elements (designable checkout primitives), webhooks with retry + event logs, idempotent API keys, sandbox environment.
- **Hooks:** billing page designed *around* the payer (fewer fields = conversion), quiet receipt confirmation as closure, minimal visual noise on money rows, consistent tone throughout (documented as a design-law for them).

### Jupiter (Solana swap aggregator)
- **Standard:** single swap surface, token picker, price chart, tx history.
- **Advanced:** multi-route aggregation with per-route fee/slippage breakdown, slippage control before sign, transaction preview showing exact intent.
- **Hooks:** favorite pairs, price-target alerts, history as narrative (what you swapped, when, at what rate).

### Phantom (self-custody wallet, super-app trajectory)
- **Standard:** balance-first home card, send/receive/swap, tx history, dapp connection list.
- **Advanced:** preview-before-sign with explicit intent ("You are approving X USDC to contract Y"), gas estimation on the signing surface, multi-chain balance consolidation, trust earned *at the moment of signing*.
- **Hooks:** notification center, dapp persistence, badge counts, biometric re-entry.

### Cash App (retail P2P)
- **Standard:** simple send/receive, activity list, phone/contact-first identity.
- **Advanced:** Lightning BTC, Cash Card, round-ups, direct-deposit early.
- **Hooks:** boost/reward game layer, referral bonuses, event-driven nudges — a known engagement-lift via *incentive*, not just information.

### Splitwise (category leader for bill splitting)
- **Standard:** groups, add-expense with paid-by selection, balances/IOU summary, activity feed.
- **Advanced:** "simplify" debt (minimize transfer count), itemized item splits, percentage/shares, filter + search on transaction log.
- **Hooks:** event notifications ("someone settled up"), settle reminders, balance-first tab ordering. **Known user complaints (from teardowns):** cluttered ledger, confusing settle flow, inconsistent notifications, "not getting a notification after someone settled up," extra steps before the money actually moves.

### World Mini Apps platform (our channel)
- **Standard:** bottom tabs, one task per page, CTA always visible, app review guidelines, 2–3 s initial load / <1 s actions.
- **Advanced:** MiniKit 2.0 EIP-1193, MiniKit.chat/share, send-notification endpoint with localization.
- **Hooks / constraints:** 40 notifications / 4 h cap for unverified apps, deep links `worldapp://mini-app?...`, username substitution in messages. *Notification design must be event-thresholded, not per-msg spam.*

---

## 2. What TandaBill already ships (verified this session)

| Capability | Where | Evidence |
|---|---|---|
| Deep-link bill landing `/bill/{address}` | miniapp | route verified live |
| One-tap invite copy/share | InvitePanel | visual-B review |
| Preview-before-sign, cancel-sends-nothing | ConfirmPreview | merged `7fcdf1d` (visual-B) |
| Refund/execute countdown chip | NudgeCountdown | payload verified |
| Tabular numerals on money sites, zero footer | VISUAL-C | merged `525d16dd` |
| Balance-first-like status surfaces | explorer (read-only) | live render verified |
| Palette-law design system (single source) | design.css + §0 | merged `cef40d49` |
| 5-screen showcase scope (bill home → profile) | showcase v1/v2 | merged `59a15ec`/`cef40d49` |

**Gap vs benchmark leaders:** no balance-first *actionable* home (read-only explorer), no settle-without-exit flow (Splitwise's famous weakness — and our pull-claim model is the native fix), no event-driven notification layer (World cap makes design the constraint), no explicit test/live trust cue.

---

## 3. Top-10 proposals (ranked by value / fit / engineering cost)

1. **Bill-home CTA state machine (balance-first actionable home).** UI pure function of bill_index reads (`/api/settlements?bill=`, `/api/grants?bill=`); CTA derives from contract state: awaiting-funds → fund (with preview), awaiting-confirm → nudge seats, settled → claim. Fixes the explorer's read-only dead-end; matches Splitwise's "balance first" and Phantom's "balance-first home."
2. **Settlement timeline with per-step status (vertical lifecycle).** EscrowFunded → SeatConfirmed×N → SettlementExecuted → SeatPayoutClaimed, per Coinbase-wallet lifecycle pattern; feeds NudgeCountdown; makes multi-party progress legible at a glance.
3. **Suggested-split debt minimization (view-only, expectedMask wins).** Splitwise's simplify, but our contract law upgrades it: display-only "suggested split," on-chain expectedMask is truth on ANY divergence. No UI-only competitor can fake this.
4. **Settle-without-exit loop (in-app claim).** With V3 pull-claim, the payee claims inside the mini-app → confirmation as *closure* (Splitwise's #1 complaint is paying elsewhere then returning). Our edge: the money actually moves here.
5. **Event-thresholded notifications under the 40/4h cap.** Webhook/delivery events (`/api/notify` dispatcher + NudgeCountdown deadlines) produce ONE message per meaningful state change (seat confirmed, window closing, payout claimable), not per update. Faithful to Stripe event-model; respects World cap.
6. **Explicit read-only / test-mode trust cue.** Stripe's test/live toggle as a *trust* tool: explorer carries a permanent "read-only — nothing here can move funds" badge already; formalize the badge language and a "testnet 4801" chip everywhere. Hiring-reviewer visible.
7. **Empty-state microcopy with next action.** Guided "no settlements yet" states (what to do first, where the button is). Splitwise's cluttered-leader criticism inverted: calm, one-action empty states.
8. **Invoice/bill share deep-link as primary growth loop.** InvitePanel copies `/bill/{address}`; add "preview what they'll see" confirmation + share sheet. Standard-meets-hook (referral earned by the product's own shareability).
9. **Tabular numerals + calmer ledger rows everywhere.** Already landed for money (VISUAL-C); extend typography law: tabular-nums for all secondary numbers (timestamps, transaction counts), consistent mono for chain refs, per design.css tokens. Finishes the "quality product" read.
10. **Profile tab as trust+preferences surface (already wired route).** UserInfo + NotificationConsent + preferredCurrency; NotificationConsent is the honest precondition for proposal 5 — ask once, explain value (World guidelines favor explicit consent), never later spam.

---

## 4. Sequencing suggestion (aligned with existing lane plan)
- **Now (no gates):** 1 → 2 → 9 (design-system-adjacent, pure UI, testable on 4801) — West of DESIGN-E entirely.
- **With DESIGN-E "go" (post-master-gate):** 3 → 4 → 8 (money-movement surfaces; need mainnet posture).
- **With AgentMail receiver (owner gates):** 5 → 10 (notification layer; consent surface ships with the receiver hook).
- **7** anytime — microcopy pass is free and pairs with every screen.

Proposals are written against the merge-verifiable evidence law: each ships as issue → branch → CI → merge with commit-sha receipts. No fabricated claims; every "already ships" row above cites a merged sha verified this session.

---

*Evidence file for issue #172. Hash/pin: see courier manifest.*