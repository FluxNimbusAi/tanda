# W8 BILLCREATED RECOVERY — userOpHash → bill_address indexer design (Nimbus draft v1)

Problem: MiniKit `sendTransaction` resolves to a **userOpHash**, not a tx hash
(minikit-js@2.0.3 dist forensic; official FAQ concurs). `createBill`'s bill address is only in the
`BillCreated` event log → must resolve hash→receipt→logs server-side. No client-side guessing.

## Decode path (verified against official API reference, docs.world.org)
```
userOpHash (from client result.data.userOpHash)
  → GET https://developer.world.org/api/v2/minikit/userop/{user_op_hash}   # auth-free
      status ∈ {pending, success, failed}; success → transaction_hash, sender, nonce
  → eth_getTransactionReceipt(transaction_hash) on target chain RPC
  → filter logs: address == factory
  → decodeEventLog(BillCreated{bill indexed, creator indexed, token indexed, seatCount})
  → persist bill_index row; client polls backend by userOpHash
```
Hook alternative for the web session itself: `useUserOperationReceipt` from `@worldcoin/minikit-react`
(already used in shell for success/failure UI). The table below is the durable record.

## Storage
```sql
CREATE TABLE bill_index (
  user_op_hash  TEXT PRIMARY KEY,          -- ^0x[0-9a-fA-F]{64}$ enforced upstream
  tx_hash       TEXT UNIQUE,               -- NULL until status=success
  bill_address  TEXT UNIQUE,               -- from BillCreated
  creator       TEXT NOT NULL,             -- walletAuth-bound human (join to seat_grants/app_accounts)
  token         TEXT NOT NULL,
  seat_count    NUMERIC NOT NULL,
  chain_id      NUMERIC NOT NULL,          -- 480 vs 4801 rows coexist; era explicit, never inferred
  created_at    TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX bill_index_creator_idx ON bill_index (creator, created_at DESC);
```

## Poller contract
- On submit: `INSERT bill_index (user_op_hash, creator, token, seat_count, chain_id) VALUES (…, NULL, NULL, …)`.
- Worker (or on-demand read-through): poll userop endpoint 2s × 30 (≈60s ceiling, op-stack 2s blocks);
  success → fetch receipt (retry 3× for replica lag per W6 lesson) → decode → UPDATE.
- `failed`/timeout → mark `failed_at`; escrow never moved, client shows retry affordance.
- EOA lane (4801 forge/E2E scripts) already has real tx hashes → insert directly, skip userop hop.

## API surface for the shell
- `POST /bills` — body {user_op_hash}; 202 accepted, indexer kicks off.
- `GET  /bills/by-userop/{hash}` — {status, bill_address?} — the ONLY bill-address source the UI may use.
