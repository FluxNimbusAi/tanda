# W10 Audit Corrections — Implementation Memo (2026-11-16)

## RESOLUTION 2026-11-16b (ratified by d3b0m3n after Flux review) — APPLIED
- #1 SOLVED via Trusted Factory Forwarder: factory.callBill(bill, data) appends caller
  address; clone's _caller() decodes iff msg.sender == factory (recorded in initialize);
  direct EOA/script path unchanged; legacy bills (factory slot == 0) untouched.
  MiniKit entrypoint = factory only (+ USDC for approve). NOTES: (a) d3b0m3n snippet's
  `address caller` name collides with Yul builtin (CALLER opcode) — renamed to
  `forwarded`; (b) checklist REUSE=1 against live factory 0x03012C8e is impossible —
  that factory predates callBill; fresh impl+factory deploy is MANDATORY.
- #3 RATIFIED split-lock: owner-driven rotation dies at FULL CONFIRM (kept locked through
  executability until executed/refunded — stricter than spec, delta signed off in chat);
  confirmed-self locked inside window; unconfirmed-self always free until closed.
- Unit gate: 73/73 (added: unconfirmedSelf money path, confirmedSelf window lock,
  ownerFullConfirm lock, callBill full lifecycle + identity enforcement + NotBill bubble).
- E2E (4801): harness rewritten for forwarder routing (8 cases); BLOCKED on deployer
  top-up — needs ~0.000003 ETH total (deploy 2 contracts + ~15 txs @ 0.0011 gwei).

--- original memo follows ---

Source: d3b0m3n/Flux World Chain + MiniKit v2 review, relayed 2026-11-16 (4 mandatory
corrections to be incorporated BEFORE freezing P0.1 bytecode + Slice 3 schema).
Owner of items 2-4 impl: Nimbus. Item 1 = dispatch architecture → Flux ruling REQUIRED.

## #1 Contract Entrypoint gate vs EIP-1167 clones — VERIFIED REAL, DECISION OPEN
- Evidence: `@worldcoin/minikit-js@2.0.3` build chunk AH3WTRZY L592/L608 —
  `SendTransactionErrorCodes.InvalidContract` = "The contract address is not allowed for
  your application. Please check your developer portal configurations". Static allowlist
  (Portal → Mini App → Permissions → Contract Entrypoints) vs dynamic clone addresses.
- Dispatch audit: shell currently sendTransactions ONLY to the factory (createBill) ✓
  static; probeBill path = publicClient RPC reads ✓ unaffected. confirm/execute/rotate
  are NOT yet wired — no breakage today; every future clone-targeted write would die
  with invalid_contract inside a real World App session (EOA/rpc e2e masks it).
- Options for Flux:
  A. FACTORY PASS-THROUGH ROUTER (callBill(bill,data)): plain .call sets msg.sender=factory
     → BREAKS every seat-identity check (confirm/rotate use msg.sender). Only viable if
     seat actions become signature-carried (EIP-712 inner sig + recover) — heavy V2 churn.
  B. SINGLE-CONTRACT HUB (V3): all bills in one static contract keyed by billId; msg.sender
     semantics preserved natively; ONE allowlist entry (+ USDC if approve is bundled).
     Cost: storage redesign; clone lineage becomes legacy-read-only (era-branch already
     supports reading both — W8 probe pattern).
  C. Empirical check first: verify World App behavior for factory-launched clones via a
     real-session probe once ngrok+phone leg lands (blocked). Docs publish nothing beyond
     the SDK code — portal UI is the config surface.
- Nimbus RECOMMENDATION: B (hub) at V3/W9; meanwhile freeze nothing clone-targeting.
  P0.1 rotate logic is hub-portable (self-contained function). USDC 0x6614…eA88 listed as
  entrypoint alongside hub/factory when wiring approve (per correction #1c).

## #2 Replay-ledger PK collision + signal binding — IMPLEMENTED IN SCHEMA v2 (Slice 3)
Bug in W8 schema v1: PK (rp_id, nullifier) 409-collides on the SECOND bill join and on
P0.1 Q3 rotation re-attestation (nullifier deterministic per rp_id+action; we scope via
metadata, so (rp_id,nullifier) is reused by design).
Corrected DDL (binding for slice 3):
  CREATE TABLE idkit_verifications (
    rp_id TEXT NOT NULL, nonce TEXT NOT NULL, nullifier TEXT NOT NULL,
    wallet_address TEXT, signal_hash TEXT, bill_address TEXT,
    verified_at INTEGER NOT NULL, raw_response TEXT,
    PRIMARY KEY (rp_id, nonce)                  -- single-use rp_context nonce = true replay key
  );
  CREATE INDEX idx_verif_rp_nullifier ON idkit_verifications (rp_id, nullifier); -- NON-unique
  CREATE TABLE seat_grants (
    bill_address TEXT NOT NULL, nullifier TEXT NOT NULL, wallet_address TEXT NOT NULL,
    granted_at INTEGER NOT NULL, rotated_from TEXT,
    PRIMARY KEY (bill_address, nullifier),       -- one human per seat per bill
    UNIQUE (bill_address, wallet_address)        -- one wallet per seat per bill
  );
Signal binding (crypto-enforced, not client-metadata-trusted):
  1. Client: IDKit/MiniKit action init passes signal = "${billAddress}:${walletAddress}".
  2. Server (/api/verify-proof): after v4 verify success, assert
     proof.signal_hash == hashSignal("${billAddress}:${walletAddress}") (nullifier-hash
     computation per World ID signal semantics — use idkit-core hashSignal helper) BEFORE
     any seat_grants insert/update; mismatch → 400 + audit row.
  3. P0.1 rotation: fresh proof from newWallet with signal "${billAddress}:${newWallet}"
     → seat_grants row UPDATE wallet_address (old kept in rotated_from audit column).
     client_metadata.bill remains UX scoping ONLY, never an authn input.

## #3 Rotation window semantics — IMPLEMENTED IN CONTRACT + TESTS
- Self (msg.sender == current seat wallet): allowed until executed/refunded — broken
  receiving wallet can always be fixed by its owner mid-window. (test_rotate_postFullConfirm_paysNewWallet)
- Owner (msg.sender != seat wallet): RotationWindowLocked once
  block.timestamp >= fullyConfirmedAt + SETTLEMENT_WINDOW (executability = payout
  destinations immovable); SeatRotationClosed after executed/refunded.
  (test_rotate_ownerLockedAtExecutability_selfStillOk)
- Residual (flagged, accepted-by-design): within the window a non-self owner rotation of a
  CONFIRMED seat is still possible. Mitigation layers: seat-self can counter-rotate any
  time; event trail (SeatWalletRotated) + indexer surfaces it to participants; notification
  trigger N7 (rotation alert to seat of record) added to slice-3 trigger table.
- executeSettlement permissionless CONFIRMED from source: V2 L281-290 has no owner gate
  (W1's `require(msg.sender == owner)` was removed by Gap-2 ruling — any EOA can execute
  once full-confirmed + window). Malicious-owner stall is structurally impossible.

## #4 SQLite single-writer discipline — BINDING FOR SLICE 3
- ONE writer process: Python indexer (bill_index service) owns ALL writes
  (bill_index, idkit_verifications, seat_grants, trigger queue).
- Next.js opens the same file READ-ONLY (`?mode=ro&immutable=0` via better-sqlite3, or
  reads exclusively through the indexer's local API) — zero cross-process write skew.
- If any Node write is unavoidable later: WAL mode + busy_timeout(5000) + retry, and the
  write moves INTO the indexer service instead (preferred).
- Flux to add sqlite dependency (item 5 of his sequence) with this constraint documented.

## Freeze status
- P0.1 bytecode: NOT frozen — awaiting #1 ruling (hub/router changes dispatch surface,
  not bill logic; if B chosen, rotateSeatWallet ports verbatim).
- FAST-lane e2e of patched V2: proceeds on 4801 (EOA RPC lane, logic verification only,
  zero prod impact). Gas delta reported from live receipts.
- Repin world.json: after e2e green + Flux sign-off (per his sequencing).
