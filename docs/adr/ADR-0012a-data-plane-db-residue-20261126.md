# ADR-0012a — Data-plane census: voided app_e691*/rp_a779* residue in *.db stores (2026-11-26)

Status: ACCEPTED (Nimbus executed; companion record to ADR-0011/ADR-0012, which voided
`app_e691f666…31f7` / `rp_a779c304…` and ratified canonical `app_d3f03e8b…82c2` /
`rp_4fbd4454…`). Card: t_c89c29d7 (ENG-44), spun out of the ENGINE-41 tree sweep
(t_1471a0c0), which excluded `*.db` binaries by design.

## Question asked
Does the :8096 bill_index serve or validate against any pre-migration app/rp value,
and what is the correct disposition of the byte-level residue ENGINE-41 flagged?

## Findings (ground truth, 2026-11-26)
1. **Live DB identity.** `services/bill_index.py` resolves its store as
   `BILL_INDEX_DB or <repo-root>/bill_index.db`. The live PID (:8096, PID 20204)
   runs with no env override — **the repo-root `bill_index.db` IS the live store**
   (mtime advancing during census; `/health` counters 23/20/13/4 match it exactly).
   `services/bill_index.db` is an **empty decoy** (0 rows since 2026-11-22).
2. **No serving, no validation on the voided values.** `rp_id` is
   shape-gated only (`RP_ID_RE ^rp_[a-z0-9]+$`); no app/rp value literal exists in
   the service source; no GET route echoes `rp_id` (/health COUNTs only); the
   `(rp_id, nonce)` PK means a residue row blocks only replay of its own consumed
   fixture nonce. The voided **app** id never enters this data plane at all.
3. **Residue inventory** (host-wide scan: 1,987 `*.db` files, 7 hits):
   - `tanda-sync/bill_index.db` — 3 rows in `idkit_verifications`,
     `rp_id='rp_a779c304e4f624ce'`, `verified_at` 2026-11-17, `signal_hash='0xabc'`,
     duplicated nullifier = **handcrafted /grants replay-matrix test fixtures** from
     the pre-migration era (12 byte hits = 3 rows × table leaf + PK autoindex +
     nullifier index, plus fragments on pages that absorbed the matrix's
     IntegrityError/rollback attempts).
   - `tanda-a1/bill_index.db` — dead A1 bench lane, identical fixtures, no listener,
     last write 2026-11-19.
   - `tanda-sync/scratch/t2a0ebac9_catchup.db` — catchup rehearsal copy of the same
     db from card t_2a0ebac9, static since 2026-11-23.
   - `hermes/kanban.db`, `hermes/state.db`, `profiles/nimbus/state.db`,
     `profiles/nimbus/cron/deliveries.db` — agent board/transcript/cron substrate
     quoting the voided ids **in order to void them** (this migration's own paper
     trail). Not TandaBill data plane.
   Full machine-checkable detail: `proofs/DB_CENSUS_44_20261126.json`.

## Decision — DOCUMENT-AS-HISTORICAL; purge rejected
- The 3 live-DB rows are the audit trail behind granted seats and the replay history
  itself. Rewriting `rp_id` would falsify historical proof records; deleting them
  destroys provenance **for zero security gain** — no code path consumes the value.
- Log stores are append-only memory of the swarm; editing them is out of bounds.
- No `*.db` was deleted, moved, or edited by this card. The live DB stayed
  write-free during the census (all connections `mode=ro`).

## Standing rules established
1. **R-44a:** `:8096` live store is the **repo-root** `bill_index.db`, not
   `services/bill_index.db`. Any hygiene card touching the decoy must re-derive the
   PID→path from the health-counters parity method above, never from filename.
2. **R-44b:** future tree sweeps keep `*.db` out of text scope **only when** a
   data-plane census (this card's pattern) has dispositioned them; residue without a
   note is a gap.
3. **R-44c:** if the decoy is retired (rename or explicit `BILL_INDEX_DB` pin), do it
   via the windows-daemon-restart pattern with a `/health` parity check after — the
   decoy's emptiness is currently load-bearing evidence and must not be mistaken for
   the live store at relaunch time.
4. Revival of the A1 lane (if ever) is gated by ADR-0012 sync-gate law: canonical
   anchors only.

## Consequences
- ENGINE-41's T1 line "2 excluded *.db data-plane hits" resolves to: 3 service-db
  fixture copies + 4 agent-log classes, all documented, none purged.
- `SEC_SWEEP_41_20261126.json` remains accurate; this note extends, not supersedes.
- No client, mini-app, or on-chain surface changed.
