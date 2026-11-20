# Demo provenance — contract-loop proof frames

These frames are rendered from a **real proof run**, not a mock and not a staged screenshot.

| Fact | Value |
|---|---|
| What ran | Full bill loop on the deployed fast-twin contract: preflight (chain identity) → initiate re-decode → `settlements(0)` FAST 7-tuple decode → dust → `confirmSettlement` (owner seat) → `confirmSettlement` (seat B, external wallet) → 60 s window → `executeSettlement` → indexer POSTs + ledger read-back + counters |
| Chain | World Chain Sepolia, `chainId 4801` (testnet; no mainnet) |
| Bill | `0x2032cc313c5b115e8aaa1ae7615d60aa3a199810` |
| Result | **41/41 assertions PASS, EXIT=0** |
| Key txs | initiate `0x8662fb5c4d597fbc…` (blk 37295146) · confirm-owner `0xbbcb0c7751782190…` (blk 37314170) · confirm-seatB `0xb7b9642780f24103…` (blk 37314174) · execute `0x43903106a80039dd…` (blk 37314206) |
| Settlement final | `settledAt=1795175836`, masks 3/3, `refunded=false`, bill USDC drained (push +10000/+10000) |
| Source card | kanban `t_74cde67e` (P-A2-FASTTWIN), run 266, executed 2026-11-20 on the PC node |
| Raw capture | [`transcripts/tanda_contract_loop_2026-11-20.log`](transcripts/tanda_contract_loop_2026-11-20.log) — sha256 `e2f51de8d5641e851b00356a03db2cd2fb71684bfc49006dc64954115c3c580c` (LF-normalized; original CRLF capture sha256 `4d85156d2b92ffd0e14e5496f723818efa6991379575d31df8682725e279d573`) |
| Structured receipt | [`evidence/fasttwin_receipt.json`](evidence/fasttwin_receipt.json) — sha256 `be7a4373159f80b7af91d0b0f206294da23f72e827cfe86494774d25a135f9f9` |
| Indexer read-back | [`evidence/settlements_readback.json`](evidence/settlements_readback.json) — live `GET http://127.0.0.1:8096/api/settlements?bill=0x2032cc…` on 2026-11-20; `settled_at` / `fully_confirmed_at` match chain byte-for-byte |

## Frame integrity

`contract-loop_01..03.png` and `contract-loop.gif` are viewport slices of the raw transcript
above, rendered by [`render_frames.py`](render_frames.py) (committed) with:

```
python render_frames.py transcripts/tanda_contract_loop_2026-11-20.log docs/demo contract-loop --lines 22
```

No line is added, removed, or edited; long lines are display-wrapped only (the raw file stays
canonical). Anyone can regenerate the frames from the committed transcript and diff them.

## Scope note (honesty)

- This run exercised the **fast twin** (`FastTandaBillV2`), which predates P0.1a `claimedMask`:
  settlement value PUSHES at execute; pull-claim parity does not hold on the fast path
  (`claimed_count=0` in the ledger is the *correct* pre-P0.1a value, asserted in the transcript).
- The CI badge at the top of this README refers to `ci.yml` (forge tests + python suite), which is
  green on `main` independently of these frames; these frames are a live-testnet proof run, not CI output.
