#!/usr/bin/env python3
"""SR-KP-A1 settlement-watcher unit test (issue #18). Deterministic, no sleeps,
no live RPC: fakes _rpc + decode, drives the real _handle_tx_lane via FakeHandler."""
import io
import json
import os
import sqlite3
import sys
import tempfile

TMP = tempfile.mkdtemp(prefix="a1watch")
os.environ["BILL_INDEX_DB"] = os.path.join(TMP, "watch.db")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import bill_index as bi  # noqa: E402

BILL = "0x" + "11" * 20
TX1 = "0x" + "ab" * 32
TX2 = "0x" + "cd" * 32
TX3 = "0x" + "ef" * 32
FACT = next(iter(bi.FACTORIES))
SETTLED_AT = 1763500000
TOPIC_SID = "0x" + "00" * 31 + "02"  # settlementId = 2
DATA = "0x" + (5000).to_bytes(32, "big").hex() + SETTLED_AT.to_bytes(32, "big").hex()


class FakeHandler:
    def __init__(self, tx):
        body = json.dumps({"tx_hash": tx}).encode()
        self.headers = {"Content-Length": str(len(body))}
        self.rfile = io.BytesIO(body)
        self.code = None
        self.obj = None

    def _json(self, code, obj):
        self.code, self.obj = code, obj
        return code

    _handle_tx_lane = bi.Handler._handle_tx_lane


def drive(tx, logs):
    bi._rpc = lambda *a: {"status": "0x1", "blockNumber": "0x1d4c0", "logs": logs}
    bi.decode_billcreated = lambda l: {"bill": BILL, "creator": "0x" + "22" * 20,
                                       "token": "0x" + "33" * 20, "seatCount": 3}
    h = FakeHandler(tx)
    try:
        h._handle_tx_lane()
    except BaseException as e:
        raise AssertionError(f"T13-class outward raise: {e!r}")
    return h.code, h.obj


def bill_created():
    return [{"address": FACT, "topics": [bi.BILLCREATED_TOPIC0, BILL,
                                         "0x" + "00" * 12 + "22" * 20,
                                         "0x" + "00" * 12 + "33" * 20],
             "data": "0x" + (3).to_bytes(32, "big").hex()}]


def settlement_log(addr=BILL):
    return [{"address": addr, "topics": [bi.SETTLEMENT_EXECUTED_TOPIC0, TOPIC_SID],
             "data": DATA}]


def main():
    db = bi.get_db()
    # 1) bill lands first (201)
    code, _ = drive(TX1, bill_created())
    assert code == 201, code

    # 2) settlement tx for indexed bill -> 200 + row with chain facts
    code, obj = drive(TX2, settlement_log())
    assert code == 200 and obj["settlements_recorded"] == 1, (code, obj)
    row = db.execute("SELECT * FROM settlements WHERE bill_id=?", (BILL,)).fetchone()
    assert row["settlement_id"] == 2 and row["block"] == 0x1d4c0
    assert row["total_amount"] == 5000 and row["settled_at"] == SETTLED_AT
    assert row["tx_hash"] == TX2 and row["confirmed_at"]

    # 3) duplicate POST -> idempotent, still one row, recorded=0
    code, obj = drive(TX2, settlement_log())
    assert code == 200 and obj["settlements_recorded"] == 0, (code, obj)
    assert db.execute("SELECT COUNT(*) FROM settlements").fetchone()[0] == 1

    # 4) settlement from UNKNOWN bill -> ignored (no FK pollution) -> 422
    code, obj = drive(TX3, settlement_log("0x" + "99" * 20))
    assert code == 422, (code, obj)
    assert db.execute("SELECT COUNT(*) FROM settlements").fetchone()[0] == 1

    # 5) combined tx: same tx creates bill AND settles (slog seen via known∪d)
    NEWB = "0x" + "77" * 20
    bi.decode_billcreated = lambda l: {"bill": NEWB, "creator": "0x" + "22" * 20,
                                       "token": "0x" + "33" * 20, "seatCount": 3}
    bi._rpc = lambda *a: {"status": "0x1", "blockNumber": "0x1d4c1",
                          "logs": bill_created() + settlement_log(NEWB)}
    h = FakeHandler(TX3)
    h._handle_tx_lane()
    assert h.code == 201, (h.code, h.obj)
    assert db.execute("SELECT COUNT(*) FROM settlements WHERE bill_id=?",
                      (NEWB,)).fetchone()[0] == 1

    # 6) settlements count feeds /health (shape asserted by direct SQL)
    n = db.execute("SELECT COUNT(*) FROM settlements").fetchone()[0]
    assert n == 2, n
    print("A1 WATCHER TEST: PASS (ingest/idempotency/unknown-bill-skip/combined/health-count)")


if __name__ == "__main__":
    main()
