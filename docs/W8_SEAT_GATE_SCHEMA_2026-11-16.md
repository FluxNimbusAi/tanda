# W8 SEAT-GATE SCHEMA — IDKit verification backend contract (Nimbus draft v1, for Flux approval)

Status: PROPOSED. Blocking item = Flux sign-off on the wallet-rotation ruling (below).
Scope: off-chain seat membership gate for Tanda bills. On-chain roster mutation stays `addSeat` /
`initialize(token, owner, seats[])` — the gate decides WHO the backend/creator adds, with
one-human-per-seat enforced by World ID nullifiers.

## Action spec (Developer Portal)
| field | value | note |
|---|---|---|
| app_id | `<World ID app>` | separate from Mini App app_id (official docs: dual-app split allowed) |
| action | `tanda_seat_join` | non-dynamic |
| bill scoping | `client_metadata.bill` (JSON), NOT per-bill dynamic actions | avoids action-registration explosion; nullifier is identical across bills for non-dynamic actions → scoping MUST live in our DB |
| min_sig_count | 1 | default |

## Tables (canonical DDL)
```sql
CREATE TABLE seat_grants (
  bill_address   TEXT NOT NULL,           -- lowercase 0x…
  nullifier      TEXT NOT NULL,           -- World ID nullifier_hash
  wallet_address TEXT NOT NULL,           -- walletAuth SIWE address bound at grant
  created_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
  PRIMARY KEY (bill_address, nullifier),  -- one seat per bill per human
  UNIQUE (bill_address, wallet_address)   -- one seat per bill per wallet
);

CREATE TABLE app_accounts (                -- global nullifier→wallet binding
  nullifier      TEXT PRIMARY KEY,
  current_wallet TEXT NOT NULL UNIQUE,
  last_seen_at   TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE idkit_verifications (         -- replay ledger
  nullifier      TEXT NOT NULL,
  action         TEXT NOT NULL,
  bill_address   TEXT NOT NULL,
  proof_hash     TEXT NOT NULL,
  verified_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
  PRIMARY KEY (nullifier, action, bill_address)
);
```

## Verify flow
1. Client: IDKit (`@worldcoin/idkit` 4.x, native World App transport) → proof for `tanda_seat_join`, `client_metadata={bill}`.
2. Backend: `POST https://developer.worldcoin.org/api/v2/verify/{app_id}` `{proof, action, nullifier_hash}` → reject unless `success && nullifier_hash != ''`.
3. Backend: `MiniKit.walletAuth` SIWE address already in session (message embeds `chain_id: 480`) → PoP of the wallet.
4. `UPSERT app_accounts` (nullifier → current wallet).
5. `INSERT seat_grants ON CONFLICT DO NOTHING` → 0 rows = HTTP 409 `SeatAlreadyBound`.
6. Creator-executed on-chain step: `bill.addSeat(wallet)` (or roster passed at `createBill` — factory sets atomically; child `onlyOwner` trap documented in W6).

## RULING REQUIRED (Flux)
Seat identity = **nullifier**, not wallet. Wallet rotation → `UPDATE seat_grants.wallet_address`
(history table optional). Rationale: one-human-one-seat is the product invariant; the wallet is the
weaker claim and World App users can rotate wallets. Approve / reject.

## Edge cases
- Duplicate join attempts: idempotent via PK + 409.
- Human joins two bills: allowed (PK is per-bill).
- Wallet spoof across humans: blocked by walletAuth PoP + `UNIQUE(bill, wallet)`.
- Proof replay: `idkit_verifications` PK + World backend's own nonce tracking.
