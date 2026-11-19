#!/usr/bin/env python3
"""SR-KP-A2 deterministic tx-lane race test (issue #17). No sleep-based flake:
exercises (1) DB-layer IntegrityError contract, (2) handler-level 201/200/503
outcomes via fake-self, (3) the T13 invariant — handler never raises outward."""
import io
import json
import os
import sqlite3
import sys
import tempfile

TMP = tempfile.mkdtemp(prefix="a2race")
os.environ["BILL_INDEX_DB"] = os.path.join(TMP, "race.db")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import bill_index as bi  # noqa: E402

TX = "0x" + "ab" * 32
TX2 = "0x" + "cd" * 32
BILL = "0x" + "11" * 20


def fake_body(tx):
    return json.dumps({"tx_hash": tx}).encode()


class FakeHandler:
    """Drives the real _handle_tx_lane with stubbed transport + RPC."""

    def __init__(self, tx):
        self.headers = {"Content-Length": str(len(fake_body(tx)))}
        self.rfile = io.BytesIO(fake_body(tx))
        self.code = None
        self.obj = None

    def _json(self, code, obj):
        self.code, self.obj = code, obj
        return code

    def _authed(self):
        return True

    _handle_tx_lane = bi.Handler._handle_tx_lane


def drive(tx):
    bi._rpc = lambda *a: {"status": "0x1", "logs": [
        {"address": next(iter(bi.FACTORIES)), "topics": [bi.BILLCREATED_TOPIC0]}]}
    bi.decode_billcreated = lambda l: {"bill": BILL, "creator": "0x" + "22" * 20,
                                      "token": "0x" + "33" * 20, "seatCount": 3}
    h = FakeHandler(tx)
    raised = None
    try:
        h._handle_tx_lane()
    except BaseException as e:  # T13 invariant: must never happen
        raised = e
    assert raised is None, f"handler escaped outward: {raised!r} (T13 regression)"
    return h.code, h.obj


def main():
    # 1) first writer: 201 + exactly one row
    code, obj = drive(TX)
    assert code == 201 and obj.get("bill_address") == BILL, (code, obj)
    db = bi.get_db()
    assert db.execute("SELECT COUNT(*) FROM bill_index WHERE bill_address=?",
                      (BILL,)).fetchone()[0] == 1

    # 2) second writer, different tx, same bill: precheck path -> 200, still 1 row
    code, obj = drive(TX2)
    assert code == 200, code
    assert db.execute("SELECT COUNT(*) FROM bill_index WHERE bill_address=?",
                      (BILL,)).fetchone()[0] == 1

    # 3) DB-layer race contract: bypass precheck, raw double insert ->
    #    IntegrityError caught+rollback+reconcile == winner row, no raise.
    try:
        db.execute(bi.TX_LANE_INSERT_SQL,
                   (TX2, BILL, "0x" + "22" * 20, "0x" + "33" * 20, 3))
        raise AssertionError("expected IntegrityError on duplicate bill")
    except sqlite3.IntegrityError:
        db.rollback()
    row = db.execute("SELECT * FROM bill_index WHERE bill_address=?", (BILL,)).fetchone()
    assert row is not None, "lost-writer reconcile must find winner row"

    # 4) 503 path — exact T13 repro: post-insert read returns None
    #    (dict(None) TypeError class). Fake the db boundary deterministically.
    class FakeRow0:
        def fetchone(self):
            return None  # precheck miss
    class FakeDB:
        def __init__(self): self.inserted = False

        def execute(self, sql, params=()):
            if sql is bi.TX_LANE_INSERT_SQL:
                self.inserted = True
                return FakeRow0()
            if "bill_address IS NOT NULL" in sql:
                return []  # A1 known-bills scan finds nothing (fake boundary)
            return FakeRow0()  # winner vanished -> lost write

        def commit(self):
            pass

        def rollback(self):
            pass
    real_get_db = bi.get_db
    bi.get_db = lambda: FakeDB()
    try:
        code, obj = drive(TX)
        assert code == 503 and "lost" in str(obj), (code, obj)  # no TypeError
    finally:
        bi.get_db = real_get_db
    print("A2 RACE TEST: PASS (201/200/reconcile/503 — zero outward raises)")


if __name__ == "__main__":
    main()
