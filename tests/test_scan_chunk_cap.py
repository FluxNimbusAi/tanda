#!/usr/bin/env python3
"""t_2a0ebac9 (2026-11-23): scan_pass chunking must never exceed the keyless-RPC
eth_getLogs range cap (100 blocks, probe-verified: ranges 2000/1000 -> HTTP 400,
100/50 -> OK). Pins three laws with zero public network:

  1. DEFAULT: with a >100-block checkpoint lag, every eth_getLogs window issued
     by scan_pass spans at most min(SCAN_RANGE, RPC_LOG_CAP) == 100 blocks, and
     the full gap is still covered exactly once (no silent window drops).
  2. ENV: BILL_INDEX_MAX_CHUNK re-reads RPC_LOG_CAP at import (module reload).
  3. CEILING: SCAN_RANGE semantics stay intact — chunk never exceeds SCAN_RANGE.

Stdlib unittest so CI's `python -m unittest discover -s tests` picks it up.
"""
import importlib
import os
import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path

_tmp = tempfile.mkdtemp(prefix="tanda-chunkcap-")
os.environ.setdefault("BILL_INDEX_DB", str(Path(_tmp) / "bill_index.db"))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "services"))

import bill_index as bi  # noqa: E402


class ScanChunkCap(unittest.TestCase):
    """Drive scan_pass with a recorded fake _rpc — no sockets, no chain."""

    def _run_pass(self, lag_blocks, head=5000):
        recorded = []

        def fake_rpc(method, params):
            if method == "eth_blockNumber":
                return hex(head)
            if method == "eth_getLogs":
                q = params[0]
                recorded.append((int(q["fromBlock"], 16), int(q["toBlock"], 16)))
                return []
            raise AssertionError(f"unexpected rpc: {method}")

        orig_path, orig_rpc, orig_fn = bi.DB_PATH, bi._rpc, bi._reorg_sweep
        bi.DB_PATH = Path(tempfile.mkdtemp(prefix="tanda-chunk-db-")) / "bill_index.db"
        # empty DB -> sweep is a no-op; stub it to assert the scan lane only
        bi._reorg_sweep = lambda db, head: (0, 0)
        try:
            bi._rpc = fake_rpc
            db = bi.get_db()
            start = head - lag_blocks
            bi._meta_set(db, "last_indexed_block", start)
            out = bi.scan_pass(db, head=head)
            return recorded, out, db
        finally:
            bi.DB_PATH, bi._rpc, bi._reorg_sweep = orig_path, orig_rpc, orig_fn

    def test_default_cap_100_on_large_lag(self):
        """1,988-block lag (16x the stall-maker): every window <= 100 blocks."""
        recorded, out, db = self._run_pass(lag_blocks=1988)
        cap = min(bi.SCAN_RANGE, bi.RPC_LOG_CAP)
        self.assertLessEqual(cap, 100, "default effective chunk must respect "
                                       "keyless alchemy 100-block cap")
        self.assertTrue(recorded, "scan_pass issued no eth_getLogs")
        for lo, hi in recorded:
            self.assertLessEqual(hi - lo + 1, cap, f"window {lo}..{hi} exceeds cap {cap}")
            self.assertLessEqual(hi - lo + 1, bi.SCAN_RANGE)
        # exact coverage: contiguous windows from from_block to head, no gaps
        from_block = max(0, (5000 - 1988) + 1 - bi.REORG_OVERLAP)
        self.assertEqual(recorded[0][0], from_block)
        self.assertEqual(recorded[-1][1], 5000)
        for (lo1, hi1), (lo2, _hi2) in zip(recorded, recorded[1:]):
            self.assertEqual(lo2, hi1 + 1, f"window gap after {lo1}..{hi1}")
        self.assertEqual(out["head"], 5000)
        # checkpoint landed on the final chunk edge (crash-resume law intact)
        self.assertEqual(bi._meta_get(db, "last_indexed_block"), 5000)

    def test_env_override_rereads_cap(self):
        """BILL_INDEX_MAX_CHUNK is honored at import time (module reload)."""
        orig = os.environ.get("BILL_INDEX_MAX_CHUNK")
        try:
            os.environ["BILL_INDEX_MAX_CHUNK"] = "64"
            reloaded = importlib.reload(bi)
            self.assertEqual(reloaded.RPC_LOG_CAP, 64)
        finally:
            if orig is None:
                os.environ.pop("BILL_INDEX_MAX_CHUNK", None)
            else:
                os.environ["BILL_INDEX_MAX_CHUNK"] = orig
            importlib.reload(bi)
        self.assertEqual(bi.RPC_LOG_CAP, 100, "cap must return to default after env clear")


if __name__ == "__main__":
    unittest.main()
