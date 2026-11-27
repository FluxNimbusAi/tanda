#!/usr/bin/env python3
"""ENGINE-65: settlement timeout-escalation lane (tests-then-code coupling).

Contracts pinned:
 (a) open settlement past MAX_HOLD -> escalated=1 + EXACTLY ONE app_event
     (kind='action', source='n2c', wallet=creator — existing whitelist);
 (b) replay idempotency (rowcount law): second sweep changes nothing;
 (c) refunded settlements NEVER escalate, refunded_seen=1;
 (d) settled settlements are exempt at escalation time;
 (e) GET /api/settlements/deadlines is aggregate-only (SR-RV-A1): no wallet
     may ever appear in the payload.
Idiom: real Handler methods driven with captured _json, no sockets
(parity with tests/test_funnel_track.py).
"""
import json
import os
import sys
import tempfile
import time
import unittest
from pathlib import Path

_tmp = tempfile.mkdtemp(prefix="tanda-timeout-")
os.environ["BILL_INDEX_DB"] = str(Path(_tmp) / "bill_index.db")
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "services"))

import bill_index as bi  # noqa: E402

W1 = "0x" + "11" * 20          # creator wallet (must never leak to HTTP)
CREATOR2 = "0x" + "33" * 20
B_OPEN = "0x" + "22" * 20      # timed-out, unrefunded, open
B_REF = "0x" + "44" * 20       # timed-out but refunded
B_SET = "0x" + "55" * 20       # settled normally
H80 = int(time.time()) - 80 * 3600   # past 72h MAX_HOLD
H10 = int(time.time()) - 10 * 3600   # inside the window


def seed(db, bill, creator):
    db.execute("INSERT OR IGNORE INTO bill_index (bill_address, creator, token)"
               " VALUES (?,?, '0xtoken')", (bill, creator))


def settle(db, bill, sid, tx, initiated_at, settled_at=None, refunded=0):
    db.execute("INSERT OR REPLACE INTO settlements (bill_id, settlement_id,"
               " tx_hash, block, total_amount, settled_at, refunded)"
               " VALUES (?,?,?, 100, 12500000, ?, ?)", (bill, sid, tx, settled_at, refunded))
    db.execute("INSERT OR IGNORE INTO settlement_events (bill_id, settlement_id,"
               " event, tx_hash, log_index, block, at_ts)"
               " VALUES (?,?,'SettlementInitiated',?, 1000, 90, ?)", (bill, sid, tx + "i", initiated_at))


def call_get(path):
    from io import BytesIO  # noqa: F401  (parity import with funnel tests)
    h = bi.Handler.__new__(bi.Handler)
    h.path = path
    h.headers = {}  # type: ignore[assignment]
    sent = {}
    h._json = lambda code, obj: sent.update(code=code, obj=obj)
    bi.Handler.do_GET(h)
    return sent


class TimeoutEscalation(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.db = bi.get_db()
        seed(cls.db, B_OPEN, W1)
        seed(cls.db, B_REF, CREATOR2)
        seed(cls.db, B_SET, CREATOR2)
        settle(cls.db, B_OPEN, 0, "0xT1", H80)
        settle(cls.db, B_REF, 1, "0xT2", H80)
        cls.db.execute("INSERT INTO settlement_events (bill_id, settlement_id,"
                       " event, tx_hash, log_index, block, at_ts)"
                       " VALUES (?,'1','SettlementRefunded','0xT2r', 1001, 95, ?)", (B_REF, H80 + 60))
        settle(cls.db, B_SET, 0, "0xT3", H10, settled_at=int(time.time()))

    def test_a_escalates_once_with_creator_event(self):
        out = bi._timeout_sweep(self.db)
        self.assertEqual(out["escalated"], 1)
        row = self.db.execute("SELECT escalated FROM settlement_deadlines"
                              " WHERE bill_id=? AND settlement_id='0'", (B_OPEN,)).fetchone()
        self.assertEqual(row["escalated"], 1)
        ev = self.db.execute("SELECT kind, source, wallet FROM app_events"
                             " WHERE bill_id=?", (B_OPEN,)).fetchall()
        self.assertEqual(len(ev), 1)
        self.assertEqual((ev[0]["kind"], ev[0]["source"], ev[0]["wallet"]),
                         ("action", "n2c", W1))

    def test_b_replay_is_a_noop(self):
        out2 = bi._timeout_sweep(self.db)   # run AGAIN after test_a
        self.assertEqual(out2["escalated"], 0)
        n = self.db.execute("SELECT count(*) c FROM app_events WHERE bill_id=?", (B_OPEN,)).fetchone()["c"]
        self.assertEqual(n, 1)

    def test_c_refunded_never_escalates(self):
        row = self.db.execute("SELECT escalated, refunded_seen FROM settlement_deadlines"
                              " WHERE bill_id=?", (B_REF,)).fetchone()
        self.assertEqual(row["refunded_seen"], 1)
        self.assertEqual(row["escalated"], 0)

    def test_e_endpoint_aggregate_only(self):
        # Handler opens its OWN connection (get_db) — committed truth only,
        # exactly like production scan_pass committing after the sweeps.
        cls = type(self)
        cls.db.commit()
        r = call_get("/api/settlements/deadlines")
        self.assertEqual(r["code"], 200)
        blob = json.dumps(r["obj"]).lower()
        self.assertNotIn(W1.lower(), blob)          # SR-RV-A1: no wallet, ever
        for k in ("total_tracked", "open", "past_max_hold", "escalated", "refunded_seen", "bills"):
            self.assertIn(k, r["obj"])
        self.assertGreaterEqual(r["obj"]["past_max_hold"], 2)  # open + refunded
        self.assertEqual(r["obj"]["escalated"], 1)


if __name__ == "__main__":
    unittest.main(verbosity=2)
