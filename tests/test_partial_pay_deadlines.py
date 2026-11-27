#!/usr/bin/env python3
"""#67 KAIZEN-5: partial-payment invariants on the deadline lane (Flux 58090 pins).

These encode ENGINE-65's shipped guarantees against regression:
 (1) a PARTIAL settlement (claimed_* legs written, settled_at NULL) that ages
     past MAX_HOLD still escalates — partial pay never clears or bypasses the
     deadline row (rowcount law: exactly one app_event);
 (2) partial-then-refund sequence: refunded_seen wins, NEVER escalates;
 (3) /api/settlements/deadlines leaks no wallet: every 0x40-hex value in the
     payload must belong to the KNOWN-PUBLIC bill set (shape assertion, not
     key-name absence — a wallet under a renamed key still fails here);
 (4) replay idempotency: second sweep mutates nothing (full-table checksum).
Clock+DB-only law: no RPC monkeypatch — any accidental network call hangs the
test and CI shows it.
"""
import json
import os
import re
import sys
import tempfile
import time
import unittest
from pathlib import Path

_tmp = tempfile.mkdtemp(prefix="tanda-p67-")
os.environ["BILL_INDEX_DB"] = str(Path(_tmp) / "bill_index.db")
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "services"))

import bill_index as bi  # noqa: E402

CREATOR = "0x" + "aa" * 20
SEATER = "0x" + "bb" * 20
B_PART = "0x" + "cc" * 20   # partial, timed-out, must escalate
B_PR = "0x" + "dd" * 20     # partial then refunded, must never escalate
H80 = int(time.time()) - 80 * 3600
HEX40 = re.compile(r"0x[0-9a-fA-F]{40}")


def seed(db, bill, sid, tx, initiated_at, claimed_amount, refunded=0):
    db.execute("INSERT OR IGNORE INTO bill_index (bill_address, creator, token)"
               " VALUES (?,?, '0xtok')", (bill, CREATOR))
    db.execute("INSERT OR REPLACE INTO settlements (bill_id, settlement_id,"
               " tx_hash, block, total_amount, settled_at, refunded,"
               " claimed_count, claimed_amount)"
               " VALUES (?,?,'0x' || ?, 100, 12500000, NULL, ?, 1, ?)",
               (bill, sid, tx, refunded, claimed_amount))
    db.execute("INSERT OR IGNORE INTO settlement_events (bill_id, settlement_id,"
               " event, tx_hash, log_index, block, at_ts)"
               " VALUES (?,?,'SettlementInitiated','0xe' || ? || 'i', 1000, 90, ?)",
               (bill, sid, tx, initiated_at))


def call_get(path):
    h = bi.Handler.__new__(bi.Handler)
    h.path = path
    h.headers = {}  # type: ignore[assignment]
    sent = {}
    h._json = lambda code, obj: sent.update(code=code, obj=obj)
    bi.Handler.do_GET(h)
    return sent


def snapshot(db):
    rows = []
    for t in ("settlement_deadlines", "app_events"):
        rows += [tuple(r) for r in db.execute(f"SELECT * FROM {t} ORDER BY rowid")]
    return rows


class PartialPayDeadlineInvariants(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.db = bi.get_db()
        seed(cls.db, B_PART, 0, "T1", H80, 5000000)      # half-claimed, open
        seed(cls.db, B_PR, 1, "T2", H80, 3000000)        # partial, then refund
        cls.db.execute("INSERT INTO settlement_events (bill_id, settlement_id,"
                       " event, tx_hash, log_index, block, at_ts)"
                       " VALUES (?, '1', 'SettlementRefunded','0xT2r', 1001, 95, ?)",
                       (B_PR, H80 + 60))
        cls.db.commit()

    def test_1_partial_pay_still_escalates_once(self):
        out = bi._timeout_sweep(self.db)
        self.db.commit()
        self.assertEqual(out["escalated"], 1)             # B_PART only, B_PR exempt
        d = self.db.execute("SELECT escalated FROM settlement_deadlines"
                            " WHERE bill_id=?", (B_PART,)).fetchone()
        self.assertEqual(d["escalated"], 1)               # latch survived partial
        n = self.db.execute("SELECT count(*) c FROM app_events WHERE bill_id=?",
                            (B_PART,)).fetchone()["c"]
        self.assertEqual(n, 1)

    def test_2_partial_then_refund_never_escalates(self):
        d = self.db.execute("SELECT escalated, refunded_seen FROM settlement_deadlines"
                            " WHERE bill_id=?", (B_PR,)).fetchone()
        self.assertEqual(d["refunded_seen"], 1)
        self.assertEqual(d["escalated"], 0)

    def test_3_endpoint_shape_no_wallet_leak(self):
        r = call_get("/api/settlements/deadlines")
        self.assertEqual(r["code"], 200)
        blob = json.dumps(r["obj"])
        # EVERY hex40 in the payload must be a known-public bill address:
        for addr in HEX40.findall(blob):
            self.assertIn(addr.lower(), (B_PART.lower(), B_PR.lower()))
        for entry in r["obj"]["bills"]:
            self.assertEqual(set(entry), {"bill", "settlement", "past_due",
                                          "escalated", "refunded"})
        self.assertNotIn(CREATOR.lower(), blob.lower())
        self.assertNotIn(SEATER.lower(), blob.lower())

    def test_4_replay_changes_nothing(self):
        before = snapshot(self.db)
        out2 = bi._timeout_sweep(self.db)
        self.db.commit()
        self.assertEqual(out2["escalated"], 0)
        self.assertEqual(snapshot(self.db), before)


if __name__ == "__main__":
    unittest.main(verbosity=2)
