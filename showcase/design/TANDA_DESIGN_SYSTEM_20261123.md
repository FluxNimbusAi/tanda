# TandaBill — Design System v1 ("Neon Noir")

Owner directive (2026-11-23): dark backgrounds with neon pink and blue accents,
**done with subtlety and class**. Cherry-pick best-of-breed patterns from high-usage
apps on Solana / Base / World; do not copy any single look-and-feel.

Status: PROPOSAL — awaiting d3b0m3n sign-off before any UI implementation.
Companion artifact: `showcase/design/tandabill_showcase.html` (token-bound mockups,
real V2 lifecycle states, real API shapes).

---

## 1. What we cherry-pick (pattern, not pixels)

| Source | Pattern taken | How it lands in TandaBill |
|---|---|---|
| Phantom (Solana) | One-tap action hierarchy; balance-first home; activity feed as the default view | Bill-first home: open bill → amounts + seats + one primary CTA; settlement history below |
| Jupiter (Solana) | Dense-but-calm data tables; tabular numerals everywhere money appears | Settlement ledger: monospace tabular figures, aligned columns, no chart noise |
| Solflare (Solana) | Status chips with icon + label (never color alone) | Seat/expense/settlement chips: icon + text + color (colorblind-safe) |
| Base app (Coinbase) | Card elevation on near-black; generous 20–24px radii; confident minimal type scale | Surface scale (3 levels), 20px card radius, Inter + JetBrains Mono pairing |
| Coinbase Wallet | Transaction lifecycle as a vertical timeline with per-step status | Settlement timeline: fund → confirm (per seat) → execute → claim, each step a node |
| World mini-apps | Mobile-first: bottom tab nav, one task per page, CTA always visible, 100dvh + overscroll fix, load ≤2–3s | Non-negotiable platform compliance — this is a review gate, not a style choice |
| World UI Kit | Component primitives (buttons, inputs, toasts) already themed for the platform | We extend the kit's tokens; we do not fork components |

**Explicitly NOT copied:** Phantom's purple, Jupiter's gradient blobs, Base's blue
brand system, any app's layout skeleton. We take interaction patterns and typographic
discipline, then render them in our own token language.

## 2. Design tokens (the whole system is this file)

### Surfaces — a scale, never pure black
```
--bg-0:        #0A0B0F   app background (not #000 — avoids halation on OLED)
--bg-1:        #101218   cards / raised surfaces
--bg-2:        #171A22   modals, sheets, hover elevation
--border:      #232834   1px hairlines (elevation is borders, not shadows)
--border-hi:   #2E3546   focused / active borders
```

### Text — three tiers only
```
--text-1:      #F4F5F7   primary, amounts, active labels
--text-2:      #A0A6B4   secondary, descriptions, form labels
--text-3:      #6B7280   timestamps, placeholders, disabled
```

### Accents — the two neons, used with restraint
```
--accent-pink:   #FF3D8A   primary action (CTA), brand mark, "your" seat
--accent-pink-dim:  #B32A61  pressed/disabled CTA
--accent-blue:   #4DA6FF   information, links, verified badges, "other" seats
--accent-blue-dim: #2E6FB0
```

**The subtlety rule (class over glow):**
- Glow = `box-shadow: 0 0 16px rgba(255,61,138,0.25)` on **primary CTA only**, and
  only in the resting state. No glow on cards, no glow on text, no animated pulses.
- A number someone is about to act on is never inside a glow. Glow marks *action*,
  never *data*.
- Pink and blue never share one element. One accent per element, always.
- Accent usage budget: ≤10% of any screen's pixels. The rest is surface + text tiers.

### Status — semantic, always icon+label+color (never color alone)
```
--st-pending:   #F5B84D   (amber)   awaiting funding / awaiting confirmations
--st-active:    #4DA6FF   (blue)    in flight, escrow funded
--st-settled:   #3DDC97   (mint)    settled, claimable or claimed
--st-refunded:  #8B93A7   (slate)   refunded / closed
--st-error:     #FF5C5C   (red)     failed step — destructive context only
```

### Type
- UI prose: **Inter** (400/500/600). Scale: 13 / 15 / 18 / 24 / 32.
- Money + hashes + seat IDs: **JetBrains Mono**, `font-variant-numeric: tabular-nums`.
- Amounts are always explicit: `12.50 USDC` — symbol + code, signed where direction matters.

### Shape & space
- Radius: cards 20px, inputs/CTA 14px, chips full.
- Spacing scale: 4 / 8 / 12 / 16 / 24 / 32. Card padding 16–20px.
- Elevation: border first, shadow only for sheets/modals (`0 8px 32px rgba(0,0,0,.45)`).

## 3. The five TandaBill screens (mocked in the HTML companion)

1. **Bill home** — bill name, total, per-seat balance strip (you = pink chip, others
   = blue chips), one CTA ("Fund escrow" / "Initiate settlement" / "Claim payout" —
   exactly one, driven by contract state), verified-human badge row (World ID orb
   icon per seat — the message no Splitwise can run).
2. **Expense ledger** — dense table: when / who / amount / note. Tabular numerals.
   Add-expense is a bottom sheet, not a new page.
3. **Settlement timeline** — vertical, one node per lifecycle step with real event
   names from V2: `EscrowFunded → SettlementInitiated → SeatConfirmed ×N →
   SettlementFullyConfirmed → SettlementExecuted → SeatPayoutClaimed`. Each node:
   icon + label + tx hash (truncated, monospace) + timestamp. This screen *is* the
   Coinbase-Wallet-style lifecycle pattern, rendered in our tokens.
4. **Seat detail** — wallet (shortened), verified status, joined date, per-settlement
   claim state, rotate-wallet action (danger zone, blue→red on confirm).
5. **Empty / pending states** — "No expenses yet" with a single CTA; "Awaiting 2 of 3
   confirmations" with the live seat checklist. Empty states are designed, not
   forgotten — they carry the product's voice.

## 4. Technical elevation (beyond the visual pass)

The W10 contract loop is proven (41/41, V3 pull-claim hardened, explorer-verified).
**Chain posture (hard gate, docs.world.org):** mini apps do NOT support testnet —
the Sepolia deploy (4801) is a rehearsal asset only; the launch shell must point at
World Chain **mainnet (480)** with the Circle-native USDC
`0x79A02482A880bCe3F13E09da970dc34dB4cD24D1` (byte-probed in W9 recon), and the
contract + USDC must be pre-whitelisted in the Developer Portal per app. The
application layer is where "go big" pays off:

1. **Settlement state machine in the shell** — the UI must be a pure function of
   `(bill, seats, expenses, settlements, claims)` read from `bill_index` endpoints
   (`/api/settlements?bill=`, `/settlements/<bill>`, `/api/grants?bill=`,
   `/bills/by-userop/<hash>`). No client-side guessing of bill addresses (W8 law).
   The five screens above are derived views of that one state object.
2. **Debt minimization (P1-F from VALUE_ADD_RESEARCH)** — greedy min-transfer
   computation client-side, shown on the settlement screen before execution:
   "3 transfers settle this bill" with the exact pairs. Category-parity feature
   (Splitwise's headline) that our per-seat equal-share contract still supports via
   post-settlement claims.
3. **preferredCurrency-aware pay** — MiniKit state gives `preferredCurrency` for
   free; offer WLD / local stablecoin path alongside USDC where Pay supports it.
4. **Native growth loop** — `MiniKit.chat` invite + share sheet: one tap puts the
   bill invite in World chat. Distribution inside the app itself.
5. **Verified-human trust surface** — orb badge per seat from
   `verificationStatus` at init; the grants endpoint already carries nullifier +
   verified_at per wallet.
6. **Nudge engine wiring** — `services/nudge_engine.py` (six settlement triggers,
   hard caps, default-off) needs its in-app fallback UI: toast + pending-notifications
   counter, ready for the MiniKit notifications command when it ships.
7. **Performance budget** (review gate): initial load ≤2–3s, action <1s,
   100dvh + `overscroll-behavior:none`, bottom tab nav, no footers/hamburgers,
   Eruda off in production, EN/ES localization scaffold first.

## 5. What needs sign-off before build

- [ ] Token values above (esp. the two accent hexes and the "glow = CTA only" rule)
- [ ] The five-screen set as the v1 scope (anything added displaces one)
- [ ] Debt minimization as v1 feature (it's the biggest differentiator vs Splitwise)
- [ ] Whether the showcase HTML should be committed to `showcase/` on main for
      review by the whole swarm

## 6. Open platform gates (not design — tracked here so they don't get lost in the visual pass)

1. **W10 app-path defect (known, red by design):** the shell forwards an IDKit proof
   UUID where `POST /bills` expects a numeric userOpHash → 400 "Cannot convert … to a
   BigInt" (proofs/W10_APP_PATH_GRADE_20261122.md, INTEGRITY PASS / OUTCOME FAIL).
   Fix is client-side: map proof → numeric userOpHash before POST. Until then the
   app-path verification leg stays red; zero-gas legs unaffected.
2. **Pay-nonce backend verification:** `/api/generate-nonce` + `/api/confirm-payment`
   per official docs (nonce reference + transaction check via developer.world.org API
   v2) are NOT yet in the shell — payment is not "final" until this lands. The
   `idkit_verifications` ledger (nonce = replay key, single-writer via POST /grants)
   already exists in bill_index; the pay lane needs the same treatment.
3. **World App review gate:** requires a FINAL app — live MiniKit/IDKit, complete
   copy, support email, offline handling, public HTTPS URL (site ladder #1: Next.js +
   Tailwind + Vercel Hobby $0), real hosted icon asset (currently local-only).
4. **Reward channel (business, not blocker):** WLD dev-rewards are US-restricted;
   the Mini App Grants Program is the US-eligible funding path (W9 recon).
