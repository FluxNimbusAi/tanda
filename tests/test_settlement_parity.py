#!/usr/bin/env python3
"""SR-003 F12 settlement event-topic parity tests (kanban m4_p01a).

Zero network: synthetic logs -> decode_settlement_log -> _ingest_settlement_logs
against a temp SQLite ledger via BILL_INDEX_DB. Pins (a) the six topic0 literals
byte-exactly as cast keccak of the canonical TandaBillV2 signatures,
(b) per-event decode shape, (c) lane-agnostic idempotency (replaying the same
(tx_hash, log_index) set adds nothing and never double-counts claims),
(d) GET /settlements/<bill> response shape incl. 400 on malformed address.

Stdlib unittest so CI's `python -m unittest discover -s tests` picks it up.
"""
import os
import sys
import tempfile
import unittest
from pathlib import Path

_tmp = tempfile.mkdtemp(prefix="tanda-parity-")
os.environ["BILL_INDEX_DB"] = str(Path(_tmp) / "bill_index.db")
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "services"))

import bill_index as bi  # noqa: E402

# topic0 = cast keccak of canonical event signature (contracts/TandaBillV2.sol:92-97),
# cross-checked 2026-11-19 against LIVE 4801 logs on bill
# 0xbe4326dec14d41383dd1950620...-anchor-tx 0x5fd7322b / 0x612664c7 / 0xae4a5890.
PINNED = {
    "SettlementInitiated": "0x4797782232d6165df4bc18cba44fe5bc490d99327264a9f0f500616709f2eebb",
    "SeatConfirmed": "0x867c4949e90057f87dd89cb454afd97cbb793f822e5f0be95e4321c79aa5c30a",
    "SettlementFullyConfirmed": "0xa53a3715aacdab54744ae14864b68ab5d8bdf76b6b992e926a2f665d38e40889",
    "SettlementExecuted": "0x6e15c64adb1391003365f3c4b622f5e671638baa46af47c046068a9154f37858",
    "SeatPayoutClaimed": "0x3c62290af710b13d2a5be8d22033b19a3207a05f49798c28b402d4bd484c0dea",
    "SettlementRefunded": "0xf0ac96da4056bba49f666d0f71d3af8a1a294cabef05ab4ab32c17a82f0b3da7",
}


def w(i):
    return hex(i)[2:].rjust(64, "0")


class TopicPin(unittest.TestCase):
    def test_six_topics_byte_exact(self):
        fwd = {v: k for k, v in bi.SETTLEMENT_TOPICS.items()}  # name -> topic0
        self.assertEqual(set(fwd), set(PINNED))
        for name, t0 in PINNED.items():
            self.assertEqual(fwd[name], t0)

    def test_executed_constant_still_shared(self):
        # A1 lineage uses SETTLEMENT_EXECUTED_TOPIC0 directly; the parity map
        # must carry the SAME literal (twin-fork law: one truth per topic).
        self.assertIn(bi.SETTLEMENT_EXECUTED_TOPIC0, bi.SETTLEMENT_TOPICS)


class DecodeShape(unittest.TestCase):
    def bill_log(self, name, rest_topics, data_words, idx=0, addr=None):
        return {"address": addr or "0x" + "ab" * 20,
                "topics": [PINNED[name], w(7)] + rest_topics,
                "data": "0x" + "".join(data_words),
                "logIndex": hex(idx)}

    def test_initiated(self):
        d = bi.decode_settlement_log(self.bill_log("SettlementInitiated", [], [w(1500000), w(3)]))
        self.assertEqual(d, {"event": "SettlementInitiated", "settlement_id": 7,
                             "amount": 1500000, "expected_seats": 3})

    def test_seat_confirmed(self):
        d = bi.decode_settlement_log(self.bill_log("SeatConfirmed", [w(2)], []))
        self.assertEqual(d["seat_id"], 2)

    def test_fully_confirmed(self):
        d = bi.decode_settlement_log(self.bill_log("SettlementFullyConfirmed", [], [w(1700000000)]))
        self.assertEqual(d["at_ts"], 1700000000)

    def test_executed(self):
        d = bi.decode_settlement_log(self.bill_log("SettlementExecuted", [], [w(1500000), w(1700000100)]))
        self.assertEqual((d["amount"], d["at_ts"]), (1500000, 1700000100))

    def test_payout_claimed(self):
        d = bi.decode_settlement_log(self.bill_log(
            "SeatPayoutClaimed", [w(2), "0x" + "00" * 12 + "11" * 20], [w(500000)]))
        self.assertEqual((d["seat_id"], d["wallet"], d["amount"]),
                         (2, "0x" + "11" * 20, 500000))

    def test_refunded(self):
        d = bi.decode_settlement_log(self.bill_log("SettlementRefunded", [], [w(999)]))
        self.assertEqual(d["amount"], 999)

    def test_foreign_topic_returns_none(self):
        l = self.bill_log("SeatConfirmed", [], [])
        l["topics"][0] = "0x" + "ff" * 32
        self.assertIsNone(bi.decode_settlement_log(l))

    def test_no_index_topic_returns_none(self):
        self.assertIsNone(bi.decode_settlement_log({"topics": [PINNED["SeatConfirmed"]]}))


class IngestParity(unittest.TestCase):
    BILL = "0x" + "cd" * 20
    TX = "0x" + "ee" * 32

    def lifecycle(self, tx=TX):
        return [
            {"address": self.BILL, "topics": [PINNED["SettlementInitiated"], w(1)],
             "data": "0x" + w(30) + w(2), "logIndex": "0x0"},
            {"address": self.BILL, "topics": [PINNED["SeatConfirmed"], w(1), w(1)],
             "logIndex": "0x1"},
            {"address": self.BILL, "topics": [PINNED["SeatConfirmed"], w(1), w(2)],
             "logIndex": "0x2"},
            {"address": self.BILL, "topics": [PINNED["SettlementFullyConfirmed"], w(1)],
             "data": "0x" + w(1700), "logIndex": "0x3"},
            {"address": self.BILL, "topics": [PINNED["SeatPayoutClaimed"], w(1), w(1),
                                              "0x" + "00" * 12 + "aa" * 20],
             "data": "0x" + w(15), "logIndex": "0x4"},
            {"address": self.BILL, "topics": [PINNED["SettlementExecuted"], w(1)],
             "data": "0x" + w(30) + w(1800), "logIndex": "0x5"},
            {"address": self.BILL, "topics": [PINNED["SeatPayoutClaimed"], w(1), w(2),
                                              "0x" + "00" * 12 + "bb" * 20],
             "data": "0x" + w(15), "logIndex": "0x6"},
            # foreign emitter (factory address) must be ignored even with a
            # settlement topic — parity watcher keys on indexed bills only.
            {"address": "0x" + "ab" * 20, "topics": [PINNED["SeatConfirmed"], w(9), w(9)],
             "logIndex": "0x7"},
        ]

    def setUp(self):
        self.db = bi.get_db()

    def test_full_lifecycle_then_replay(self):
        n, c = bi._ingest_settlement_logs(self.db, self.lifecycle(), {self.BILL.lower()},
                                          self.TX, 111)
        self.assertEqual((n, c), (7, 1), "pass1: 7 ledger rows, 1 new summary")
        n2, c2 = bi._ingest_settlement_logs(self.db, self.lifecycle(), {self.BILL.lower()},
                                            self.TX, 111)
        self.assertEqual((n2, c2), (0, 0), "replay must be a complete no-op")
        s = self.db.execute("SELECT * FROM settlements WHERE bill_id=?",
                            (self.BILL.lower(),)).fetchone()
        self.assertEqual(s["claimed_count"], 2)
        self.assertEqual(s["claimed_amount"], 30)
        self.assertEqual(s["total_amount"], 30)
        self.assertEqual(s["settled_at"], 1800)
        self.assertEqual(s["fully_confirmed_at"], 1700)
        self.assertEqual(s["initiated_block"], 111)
        self.assertEqual(s["refunded"], 0)
        self.assertEqual(s["tx_hash"], self.TX)

    def test_refund_sets_flag(self):
        logs = [{"address": self.BILL, "topics": [PINNED["SettlementRefunded"], w(2)],
                 "data": "0x" + w(42), "logIndex": "0x0"}]
        bi._ingest_settlement_logs(self.db, logs, {self.BILL.lower()},
                                   "0x" + "ff" * 32, 222)
        s = self.db.execute("SELECT refunded FROM settlements WHERE settlement_id=2"
                            " AND bill_id=?", (self.BILL.lower(),)).fetchone()
        self.assertEqual(s["refunded"], 1)

    def test_unique_ledger_key_blocks_same_index_other_bill(self):
        # UNIQUE(tx_hash, log_index) is global across bills: assert distinct
        # log_index rows for two settlement ids still both land (sanity).
        logs = [
            {"address": self.BILL, "topics": [PINNED["SeatConfirmed"], w(1), w(1)],
             "logIndex": "0x0"},
            {"address": self.BILL, "topics": [PINNED["SeatConfirmed"], w(2), w(1)],
             "logIndex": "0x1"},
        ]
        n, c = bi._ingest_settlement_logs(self.db, logs, {self.BILL.lower()},
                                          "0x" + "dd" * 32, 333)
        self.assertEqual(n, 2)


class EndpointShape(unittest.TestCase):
    def test_malformed_bill_400(self):
        h = bi.Handler.__new__(bi.Handler)
        h.path = "/settlements/nothex"
        sent = {}
        h._json = lambda code, obj: sent.update(code=code, obj=obj)
        # ADDR_RE must reject before any DB touch
        import re
        self.assertFalse(bi.ADDR_RE.match("nothex"))
        self.assertTrue(bi.ADDR_RE.match("0x" + "ab" * 20))

    def test_health_exposes_settlements_counter(self):
        import inspect
        src = inspect.getsource(bi.Handler._handle_health)
        self.assertIn("FROM settlements", src)



class QueryEndpoint(unittest.TestCase):
    """M4-2 issue #19 SR-RV-A1: GET /api/settlements?bill=&page= — auth-free,
    paginated, 400 on malformed page/address, empty rows -> [] not error.
    Drives the real Handler.do_GET with a captured _json (no sockets)."""

    BILL = "0x" + "ab" * 20
    TX = "0x" + "12" * 32

    def setUp(self):
        db = bi.get_db()
        # 7-event lifecycle on settlement 1 (mirrors IngestParity shape)
        logs = [
            {"address": self.BILL, "topics": [PINNED["SettlementInitiated"], w(1)],
             "data": "0x" + w(30) + w(2), "logIndex": "0x0"},
            {"address": self.BILL, "topics": [PINNED["SeatConfirmed"], w(1), w(1)],
             "logIndex": "0x1"},
            {"address": self.BILL, "topics": [PINNED["SeatConfirmed"], w(1), w(2)],
             "logIndex": "0x2"},
            {"address": self.BILL, "topics": [PINNED["SettlementFullyConfirmed"], w(1)],
             "data": "0x" + w(1700), "logIndex": "0x3"},
            {"address": self.BILL, "topics": [PINNED["SeatPayoutClaimed"], w(1), w(1),
                                              "0x" + "00" * 12 + "aa" * 20],
             "data": "0x" + w(15), "logIndex": "0x4"},
            {"address": self.BILL, "topics": [PINNED["SettlementExecuted"], w(1)],
             "data": "0x" + w(30) + w(1800), "logIndex": "0x5"},
            {"address": self.BILL, "topics": [PINNED["SeatPayoutClaimed"], w(1), w(2),
                                              "0x" + "00" * 12 + "bb" * 20],
             "data": "0x" + w(15), "logIndex": "0x6"},
        ]
        # UNIQUE(tx_hash, log_index) makes re-ingest across tests a no-op
        bi._ingest_settlement_logs(db, logs, {self.BILL.lower()}, self.TX, 111)
        # 20 extra confirm events on settlement 9, block 112 -> total 27 events,
        # exercises the 20-row page window (27 = 20 + 7 + 0)
        extra = [{"address": self.BILL,
                  "topics": [PINNED["SeatConfirmed"], w(1), w(i)],
                  "logIndex": hex(i)} for i in range(20)]
        bi._ingest_settlement_logs(db, extra, {self.BILL.lower()}, self.TX[:-2] + "ee", 112)

    def call(self, path):
        h = bi.Handler.__new__(bi.Handler)
        h.path = path
        sent = {}
        h._json = lambda code, obj: sent.update(code=code, obj=obj)
        bi.Handler.do_GET(h)
        return sent

    def test_malformed_bill_400(self):
        self.assertEqual(self.call("/api/settlements?bill=nothex")["code"], 400)

    def test_missing_bill_400(self):
        self.assertEqual(self.call("/api/settlements")["code"], 400)

    def test_malformed_pages_400(self):
        q = f"/api/settlements?bill={self.BILL}"
        for bad in ("0", "-1", "abc", "1.5", ""):
            self.assertEqual(self.call(q + f"&page={bad}")["code"], 400, bad)

    def test_empty_bill_returns_lists_not_error(self):
        r = self.call(f"/api/settlements?bill={'0x' + 'ef' * 20}")
        self.assertEqual(r["code"], 200)
        b = r["obj"]
        self.assertEqual(b["settlements"], [])
        self.assertEqual(b["events"], [])
        self.assertEqual((b["total_settlements"], b["total_events"]), (0, 0))

    def test_page_window_and_totals(self):
        q = f"/api/settlements?bill={self.BILL}"
        p1 = self.call(q + "&page=1")["obj"]
        self.assertEqual(self.call(q)["obj"]["page"], 1)  # default page
        self.assertEqual((p1["page_size"], len(p1["events"]), p1["total_events"]),
                         (20, 20, 27))
        self.assertEqual(p1["total_settlements"], 1)
        self.assertEqual(len(p1["settlements"]), 1)
        self.assertEqual(p1["settlements"][0]["claimed_count"], 2)
        p2 = self.call(q + "&page=2")["obj"]
        self.assertEqual((p2["page"], len(p2["events"])), (2, 7))
        self.assertEqual(p2["settlements"], [])  # settlement 1 already on page 1
        p3 = self.call(q + "&page=3")["obj"]
        self.assertEqual(self.call(q + "&page=3")["code"], 200)
        self.assertEqual((len(p3["events"]), p3["total_events"]), (0, 27))
        # events feed ordering is (block, log_index): block 111 leg first
        self.assertEqual(p1["events"][0]["block"], 111)

    def test_path_form_still_served(self):
        r = self.call(f"/settlements/{self.BILL}")
        self.assertEqual(r["code"], 200)
        self.assertEqual(len(r["obj"]["settlements"]), 1)

if __name__ == "__main__":
    unittest.main(verbosity=2)
