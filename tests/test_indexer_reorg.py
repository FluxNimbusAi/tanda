#!/usr/bin/env python3
"""W2.5-2 indexer hardening tests (kanban t_0222f1e6) — TDD spec, zero public
network. Pins three gaps measured against d9a59f0bd:

  1. last_indexed_block checkpoint PERSISTENCE (indexer_state table) +
     restart-from-checkpoint: a fresh process (--scan-once subprocess against a
     local fake-RPC HTTP server) resumes exactly at the persisted checkpoint
     and replays only the overlap window.
  2. Reorg OVERLAP WINDOW: deterministic 2s-block reorg simulation — events
     mined, block re-mined with a different hash + foreign logs, sweep must
     prune orphaned ledger rows, empty seat_claims, recompute settlement
     aggregates, mark orphaned scan-lane bills 'reorged', and the re-mine at a
     deeper block must re-land everything (pull-claim counters climb again).
  3. Per-seat SeatClaimed state for P0.1a: seat_claims keyed
     (bill_id, settlement_id, seat_id), fed lane-agnostically from
     SeatPayoutClaimed, replay-idempotent, exposed on GET /settlements/<bill>.

Stdlib unittest so CI's `python -m unittest discover -s tests` picks it up.
"""
import json
import os
import subprocess
import sys
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

_tmp = tempfile.mkdtemp(prefix="tanda-reorg-")
os.environ["BILL_INDEX_DB"] = str(Path(_tmp) / "bill_index.db")
os.environ.pop("BILL_INDEX_RPC_URL", None)
os.environ.pop("BILL_INDEX_START_BLOCK", None)
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "services"))

import bill_index as bi  # noqa: E402

ROOT = Path(bi.__file__).resolve().parents[1]

BILL = "0x" + "11" * 20
BILL2 = "0x" + "12" * 20
CREATOR = "0x" + "22" * 20
TOKEN = "0x" + "33" * 20
SEAT0_W = "0x" + "aa" * 20
SEAT1_W = "0x" + "bb" * 20
TX_DEPLOY = "0x" + "d0" * 32
TX_LIFE = "0x" + "e1" * 32   # lifecycle tx at block 142 in canonical chain v1
TX_EXEC1 = "0x" + "e3" * 32  # executed tx at block 143 in canonical chain v1
TX_CLAIM1 = "0x" + "e4" * 32  # claim tx at block 144 in canonical chain v1
TX_EXEC2 = "0x" + "f1" * 32  # re-mined (rerolled) settle tx v2
TX_CLAIM2 = "0x" + "f2" * 32
FACT = bi.FACTORIES[0].lower()
SID = 1


def w(i):
    return hex(i)[2:].rjust(64, "0")


def bh(n):
    """Canonical block hash for height n in the fake chain."""
    return "0x" + ("%x" % (0xbeef * 100000 + n)).rjust(64, "0")


def entry(log, block, tx, idx):
    """eth_getLogs-shaped entry."""
    e = dict(log)
    e.update(blockNumber=hex(block), blockHash=bh(block),
             transactionHash=tx, logIndex=hex(idx), transactionIndex="0x0")
    return e


def billcreated(bill_addr=BILL):
    return {"address": FACT, "topics": [bi.BILLCREATED_TOPIC0,
                                        "0x" + "00" * 12 + bill_addr[2:],
                                        "0x" + "00" * 12 + CREATOR[2:],
                                        "0x" + "00" * 12 + TOKEN[2:]],
            "data": "0x" + w(2)}


def life_logs(tx=BILL):
    """Initiated, 2x SeatConfirmed, FullyConfirmed (block A) — v1."""
    t = bi.SETTLEMENT_TOPICS
    n2t = {v: k for k, v in t.items()}
    logs = [
        {"address": BILL, "topics": [n2t["SettlementInitiated"], w(SID)], "data": "0x" + w(3000) + w(2)},
        {"address": BILL, "topics": [n2t["SeatConfirmed"], w(SID), w(0)], "data": "0x"},
        {"address": BILL, "topics": [n2t["SeatConfirmed"], w(SID), w(1)], "data": "0x"},
        {"address": BILL, "topics": [n2t["SettlementFullyConfirmed"], w(SID)], "data": "0x" + w(1700)},
    ]
    return [entry(l, 142, TX_LIFE, i) for i, l in enumerate(logs)]


def exec_logs(tx_hash, block, idx=0):
    n2t = {v: k for k, v in bi.SETTLEMENT_TOPICS.items()}
    return [entry({"address": BILL, "topics": [n2t["SettlementExecuted"], w(SID)],
                   "data": "0x" + w(3000) + w(1800)}, block, tx_hash, idx)]


def claim_logs(tx_hash, block, base_idx=0):
    n2t = {v: k for k, v in bi.SETTLEMENT_TOPICS.items()}
    logs = [
        {"address": BILL, "topics": [n2t["SeatPayoutClaimed"], w(SID), w(0),
                                     "0x" + "00" * 12 + SEAT0_W[2:]], "data": "0x" + w(1500)},
        {"address": BILL, "topics": [n2t["SeatPayoutClaimed"], w(SID), w(1),
                                     "0x" + "00" * 12 + SEAT1_W[2:]], "data": "0x" + w(1500)},
    ]
    return [entry(l, block, tx_hash, base_idx + i) for i, l in enumerate(logs)]


def foreign_logs(block, tx="0x" + "99" * 32):
    """Reorg filler: a log that must decode to nothing we ingest."""
    return [entry({"address": "0x" + "77" * 20, "topics": ["0x" + "77" * 32], "data": "0x"},
                  block, tx, 0)]


class FakeChain:
    """Deterministic block source. Shared by the in-process _rpc stub and the
    local JSON-RPC HTTP server used for the restart-from-checkpoint test."""

    def __init__(self):
        self.blocks = {}     # number -> {"hash": str, "logs": [entry,...]}
        self.head = 0
        self.getlogs_calls = []   # (fromBlock, toBlock) seen by the client

    def mine(self, num, logs):
        self.blocks[num] = {"hash": bh(num), "logs": list(logs)}
        self.head = max(self.head, num)

    def reorg(self, num, logs):
        """Re-mine height num with a DIFFERENT hash (and different contents).
        Also re-hash every deeper block, as a real chain reorg does."""
        self.blocks[num] = {"hash": "0x" + ("re%062x" % num)[:66 - 2].rjust(64, "0"),
                            "logs": list(logs)}
        for deeper in sorted(self.blocks):
            if deeper > num:
                self.blocks[deeper]["hash"] = "0x" + ("re%062x" % deeper)[:66 - 2].rjust(64, "0")

    def rpc(self, method, params):
        if method == "eth_blockNumber":
            return hex(self.head)
        if method == "eth_getBlockByNumber":
            n = int(params[0], 16)
            b = self.blocks.get(n)
            return {"hash": b["hash"], "number": hex(n)} if b else None
        if method == "eth_getLogs":
            f = params[0]
            lo = int(f["fromBlock"], 16)
            hi = min(int(f["toBlock"], 16), self.head)
            self.getlogs_calls.append((lo, hi))
            addrs = {a.lower() for a in f.get("address", [])}
            out = []
            for n in sorted(self.blocks):
                if not (lo <= n <= hi):
                    continue
                blk = self.blocks[n]
                for l in blk["logs"]:
                    if not addrs or l["address"].lower() in addrs:
                        e = dict(l)
                        e["blockHash"] = blk["hash"]   # hash follows the CURRENT block
                        out.append(e)
            return out
        raise AssertionError(f"unexpected rpc {method}")


# ── helpers shared by the classes ─────────────────────────────────────────────

def fresh_db():
    """Isolated DB per test (module DB_PATH is monkey-patched, not env-forked)."""
    tmp = Path(tempfile.mkdtemp(prefix="tanda-reorg-t-"))
    bi.DB_PATH = tmp / "bill_index.db"
    return bi.get_db()


class IndexerReorgBase(unittest.TestCase):
    def setUp(self):
        self.db = fresh_db()
        self.chain = FakeChain()
        self._real_rpc = bi._rpc
        bi._rpc = self.chain.rpc

    def tearDown(self):
        bi._rpc = self._real_rpc


class Checkpoint(IndexerReorgBase):
    """Gap 1: last_indexed_block persistence."""

    def test_checkpoint_written_and_read(self):
        self.chain.mine(150, [])
        out = bi.scan_pass(self.db)
        self.assertEqual(out["head"], 150)
        self.assertEqual(bi._meta_get(self.db, "last_indexed_block"), 150)
        # first pass with no checkpoint starts at the window floor, NOT block 0
        self.assertEqual(out["from"], 150 - bi.REORG_OVERLAP)

    def test_overlap_floor_honors_start_block_env(self):
        os.environ["BILL_INDEX_START_BLOCK"] = "10"
        try:
            self.chain.mine(100, [])
            out = bi.scan_pass(self.db)
            self.assertEqual(out["from"], 10)
        finally:
            del os.environ["BILL_INDEX_START_BLOCK"]

    def test_second_pass_resumes_from_checkpoint(self):
        self.chain.mine(150, [])
        bi.scan_pass(self.db)
        self.chain.mine(160, [])
        self.chain.head = 160
        out = bi.scan_pass(self.db)
        self.assertEqual(out["head"], 160)
        self.assertEqual(out["from"], 150 + 1 - bi.REORG_OVERLAP)
        self.assertEqual(self.chain.getlogs_calls[-1], (out["from"], 160))

    def test_health_exposes_checkpoint(self):
        self.chain.mine(150, [])
        bi.scan_pass(self.db)
        h = bi.Handler.__new__(bi.Handler)
        sent = {}
        h._json = lambda code, obj: sent.update(code=code, obj=obj)
        h.path = "/health"
        bi.Handler.do_GET(h)
        self.assertEqual(sent["code"], 200)
        self.assertEqual(sent["obj"]["last_indexed_block"], 150)


class ReorgWindow(IndexerReorgBase):
    """Gap 2: deterministic 2s-block reorg simulation."""

    def mine_canonical_v1(self):
        self.chain.mine(140, [entry(billcreated(), 140, TX_DEPLOY, 0)])
        self.chain.mine(142, life_logs())
        self.chain.mine(143, exec_logs(TX_EXEC1, 143))
        self.chain.mine(144, claim_logs(TX_CLAIM1, 144))
        self.chain.head = 146
        out = bi.scan_pass(self.db)
        self.assertEqual(out["head"], 146)
        return out

    def test_full_lifecycle_lands_per_seat_state(self):
        self.mine_canonical_v1()
        ev = self.db.execute("SELECT COUNT(*) FROM settlement_events").fetchone()[0]
        self.assertEqual(ev, 7)
        sc = self.db.execute("SELECT seat_id, wallet, amount FROM seat_claims"
                             " ORDER BY seat_id").fetchall()
        self.assertEqual(len(sc), 2)
        self.assertEqual(sc[0]["wallet"], SEAT0_W)
        self.assertEqual(sc[1]["amount"], 1500)
        s = self.db.execute("SELECT claimed_count, claimed_amount, total_amount,"
                            " settled_at, fully_confirmed_at FROM settlements").fetchone()
        self.assertEqual((s["claimed_count"], s["claimed_amount"], s["total_amount"],
                          s["settled_at"], s["fully_confirmed_at"]), (2, 3000, 3000, 1800, 1700))
        b = self.db.execute("SELECT status, ingest_lane, block, block_hash FROM bill_index"
                            " WHERE bill_address=?", (BILL.lower(),)).fetchone()
        self.assertEqual((b["status"], b["ingest_lane"]), ("success", "scan"))
        self.assertEqual(b["block"], 140)
        self.assertEqual(b["block_hash"], bh(140))

    def test_replay_pass_is_exact_noop(self):
        self.mine_canonical_v1()
        before = self.db.execute("SELECT COUNT(*) FROM settlement_events").fetchone()[0]
        out = bi.scan_pass(self.db)          # same head: pure overlap replay
        self.assertEqual(out["head"], 146)
        self.assertEqual(out["events_ingested"], 0)
        self.assertEqual(out["pruned_events"], 0)
        after = self.db.execute("SELECT COUNT(*) FROM settlement_events").fetchone()[0]
        self.assertEqual(before, after)
        s = self.db.execute("SELECT claimed_count FROM settlements").fetchone()
        self.assertEqual(s["claimed_count"], 2)

    def test_reorg_prunes_claims_and_recomputes(self):
        self.mine_canonical_v1()
        # 2s-block reorg: heights 143/144 re-mined with different hash, empty
        self.chain.reorg(143, foreign_logs(143))
        self.chain.reorg(144, [])
        self.chain.head = 146
        out = bi.scan_pass(self.db)
        self.assertEqual(out["pruned_events"], 3)   # Executed + 2 claims
        ev = self.db.execute("SELECT COUNT(*) FROM settlement_events").fetchone()[0]
        self.assertEqual(ev, 4)                     # only block-142 lifecycle survives
        self.assertEqual(self.db.execute("SELECT COUNT(*) FROM seat_claims").fetchone()[0], 0)
        s = self.db.execute("SELECT claimed_count, claimed_amount, settled_at,"
                            " total_amount, initiated_block, fully_confirmed_at,"
                            " refunded FROM settlements").fetchone()
        self.assertEqual((s["claimed_count"], s["claimed_amount"]), (0, 0))
        self.assertIsNone(s["settled_at"])          # Executed leg reorged out
        self.assertEqual(s["total_amount"], 3000)   # Initiated leg survives
        self.assertEqual(s["initiated_block"], 142)
        self.assertEqual(s["fully_confirmed_at"], 1700)
        self.assertEqual(s["refunded"], 0)

    def test_remine_after_reorg_relands_claims(self):
        self.mine_canonical_v1()
        self.chain.reorg(143, foreign_logs(143))
        self.chain.reorg(144, [])
        # re-mined: rerolled txs (new hashes) at deeper heights
        self.chain.mine(147, exec_logs(TX_EXEC2, 147))
        self.chain.mine(148, claim_logs(TX_CLAIM2, 148))
        self.chain.head = 149
        out = bi.scan_pass(self.db)
        self.assertEqual(out["pruned_events"], 3)
        self.assertEqual(out["events_ingested"], 3)  # rerolled Executed + 2 Claims re-land
        s = self.db.execute("SELECT claimed_count, claimed_amount, settled_at,"
                            " tx_hash FROM settlements").fetchone()
        self.assertEqual((s["claimed_count"], s["claimed_amount"], s["settled_at"]), (2, 3000, 1800))
        self.assertEqual(self.db.execute("SELECT COUNT(*) FROM seat_claims").fetchone()[0], 2)

    def test_bill_row_marked_reorged_then_remint(self):
        self.mine_canonical_v1()
        # deploy block itself gets reorged out (worst case, inside window)
        self.chain.reorg(140, [])
        self.chain.head = 146
        out = bi.scan_pass(self.db)
        self.assertEqual(out["bills_reorged"], 1)
        b = self.db.execute("SELECT status FROM bill_index WHERE bill_address=?",
                            (BILL.lower(),)).fetchone()
        self.assertEqual(b["status"], "reorged")
        # a rerolled deploy (different tx, different bill) re-lands inside the window
        self.chain.mine(145, [entry(billcreated(BILL2), 145, "0x" + "a5" * 32, 0)])
        self.chain.head = 147
        bi.scan_pass(self.db)
        b2 = self.db.execute("SELECT status, ingest_lane FROM bill_index WHERE bill_address=?",
                             (BILL2.lower(),)).fetchone()
        self.assertEqual((b2["status"], b2["ingest_lane"]), ("success", "scan"))

    def test_receipt_lane_rows_never_swept(self):
        # block_hash NULL (POST /bills/tx lane) => conservative: never pruned
        self.chain.mine(146, [])
        self.chain.head = 146
        self.db.execute("INSERT INTO bill_index (user_op_hash, tx_hash, bill_address,"
                        " creator, token, seat_count, chain_id, status, synthetic, ingest_lane)"
                        " VALUES (?,?,?,?,?,1,4801,'success',0,'tx')",
                        ("0x" + "cc" * 32, TX_DEPLOY, BILL.lower(), CREATOR, TOKEN))
        self.db.commit()
        self.chain.reorg(140, [])  # irrelevant height
        bi.scan_pass(self.db)
        b = self.db.execute("SELECT status FROM bill_index WHERE bill_address=?",
                            (BILL.lower(),)).fetchone()
        self.assertEqual(b["status"], "success")


class PerSeatClaims(IndexerReorgBase):
    """Gap 3: per-seat SeatClaimed state (P0.1a pull-claim mirror)."""

    def test_ingest_lane_agnostic_seat_state(self):
        # receipt-lane ingest (FakeHandler-style direct call) must ALSO fill
        # seat_claims — per-seat state is ledger-wide, not scan-only.
        self.db.execute("INSERT INTO bill_index (user_op_hash, tx_hash, bill_address,"
                        " creator, token, seat_count, chain_id, status, synthetic, ingest_lane)"
                        " VALUES (?,?,?,?,?,1,4801,'success',0,'tx')",
                        ("0x" + "cc" * 32, TX_LIFE, BILL.lower(), CREATOR, TOKEN))
        self.db.commit()
        raw = [ {k: v for k, v in l.items() if k in ("address", "topics", "data", "logIndex")}
                for l in (life_logs() + exec_logs(TX_LIFE, 143, idx=4)
                          + claim_logs(TX_LIFE, 143, base_idx=5)) ]
        n, _ = bi._ingest_settlement_logs(self.db, raw, {BILL.lower()}, TX_LIFE, 142, "0x" + "11" * 32)
        self.assertEqual(n, 7)
        sc = self.db.execute("SELECT settlement_id, seat_id, wallet, amount, tx_hash"
                             " FROM seat_claims ORDER BY seat_id").fetchall()
        self.assertEqual([(r["settlement_id"], r["seat_id"], r["wallet"], r["amount"]) for r in sc],
                         [(SID, 0, SEAT0_W, 1500), (SID, 1, SEAT1_W, 1500)])
        # replay via the same lane: zero growth anywhere
        n2, _ = bi._ingest_settlement_logs(self.db, raw, {BILL.lower()}, TX_LIFE, 142, "0x" + "11" * 32)
        self.assertEqual(n2, 0)
        self.assertEqual(self.db.execute("SELECT COUNT(*) FROM seat_claims").fetchone()[0], 2)
        self.assertEqual(self.db.execute("SELECT claimed_count FROM settlements").fetchone()[0], 2)

    def test_endpoint_exposes_claims(self):
        self.chain.mine(140, [entry(billcreated(), 140, TX_DEPLOY, 0)])
        self.chain.mine(142, life_logs())
        self.chain.mine(143, exec_logs(TX_EXEC1, 143))
        self.chain.mine(144, claim_logs(TX_CLAIM1, 144))
        self.chain.head = 146
        bi.scan_pass(self.db)
        h = bi.Handler.__new__(bi.Handler)
        sent = {}
        h._json = lambda code, obj: sent.update(code=code, obj=obj)
        h.path = "/settlements/" + BILL
        bi.Handler.do_GET(h)
        self.assertEqual(sent["code"], 200)
        claims = sent["obj"]["claims"]
        self.assertEqual([c["seat_id"] for c in claims], [0, 1])
        self.assertEqual(claims[0]["wallet"], SEAT0_W)


class RestartFromCheckpoint(unittest.TestCase):
    """Acceptance: a FRESH PROCESS resumes from the persisted checkpoint.

    Runs the shipped `--scan-once` entrypoint as a subprocess against a local
    fake-RPC HTTP server (no public net). Phase A seeds the temp DB in-process;
    phase B lets a second interpreter pick up exactly where it stopped.
    """

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="tanda-restart-"))
        self.db_path = self.tmp / "restart.db"
        self.chain = FakeChain()
        self.requests = []

        chain = self.chain
        requests = self.requests

        class Rpc(BaseHTTPRequestHandler):
            def do_POST(self):
                n = int(self.headers.get("Content-Length", 0))
                req = json.loads(self.rfile.read(n).decode())
                requests.append(req)
                try:
                    result = chain.rpc(req["method"], req["params"])
                    resp = {"jsonrpc": "2.0", "id": req["id"], "result": result}
                except Exception as e:  # mirror rpc-error shape
                    resp = {"jsonrpc": "2.0", "id": req["id"], "error": {"message": str(e)}}
                body = json.dumps(resp).encode()
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def log_message(self, *a):
                pass

        self.srv = ThreadingHTTPServer(("127.0.0.1", 0), Rpc)
        self.port = self.srv.server_address[1]
        threading.Thread(target=self.srv.serve_forever, daemon=True).start()

    def tearDown(self):
        self.srv.shutdown()

    def _scan_once(self):
        env = dict(os.environ)
        env["BILL_INDEX_DB"] = str(self.db_path)
        env["BILL_INDEX_RPC_URL"] = f"http://127.0.0.1:{self.port}"
        r = subprocess.run([sys.executable, str(ROOT / "services" / "bill_index.py"),
                            "--scan-once"], env=env, capture_output=True, text=True, timeout=120)
        self.assertEqual(r.returncode, 0, r.stderr[-2000:])
        return json.loads(r.stdout.strip().splitlines()[-1])

    def test_second_process_resumes_checkpoint(self):
        self.chain.mine(140, [entry(billcreated(), 140, TX_DEPLOY, 0)])
        self.chain.mine(142, life_logs())
        self.chain.mine(143, exec_logs(TX_EXEC1, 143))
        self.chain.mine(144, claim_logs(TX_CLAIM1, 144))
        self.chain.head = 146

        a = self._scan_once()
        self.assertEqual(a["head"], 146)
        db = sqlite_conn(self.db_path)
        self.assertEqual(bi._meta_get(db, "last_indexed_block"), 146)
        self.assertEqual(db.execute("SELECT COUNT(*) FROM settlement_events").fetchone()[0], 7)

        # ── process #2 (fresh interpreter): overlap replay must NOT grow the
        # ledger nor double-count; then advance head and re-scan.
        b = self._scan_once()
        self.assertEqual(b["head"], 146)
        self.assertEqual(b["events_ingested"], 0)
        self.assertEqual(db.execute("SELECT COUNT(*) FROM settlement_events").fetchone()[0], 7)
        self.assertEqual(db.execute("SELECT claimed_count FROM settlements").fetchone()[0], 2)

        # deep reorg past the window floor: 143/144 orphaned, rerolled deeper
        self.chain.reorg(143, foreign_logs(143))
        self.chain.reorg(144, [])
        self.chain.mine(148, exec_logs(TX_EXEC2, 148))
        self.chain.mine(149, claim_logs(TX_CLAIM2, 149))
        self.chain.head = 150
        c = self._scan_once()
        self.assertEqual(c["pruned_events"], 3)
        self.assertEqual(c["head"], 150)
        s = db.execute("SELECT claimed_count, settled_at FROM settlements").fetchone()
        self.assertEqual((s["claimed_count"], s["settled_at"]), (2, 1800))
        self.assertEqual(db.execute("SELECT COUNT(*) FROM seat_claims").fetchone()[0], 2)
        self.assertEqual(bi._meta_get(db, "last_indexed_block"), 150)

        # and a FINAL replay pass lands nothing new (restart-stable fixpoint)
        d = self._scan_once()
        self.assertEqual(d["events_ingested"], 0)
        self.assertEqual(d["pruned_events"], 0)


def sqlite_conn(path):
    import sqlite3
    db = sqlite3.connect(path, timeout=15)
    db.row_factory = sqlite3.Row
    return db


if __name__ == "__main__":
    unittest.main(verbosity=2)
