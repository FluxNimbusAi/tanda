#!/usr/bin/env python3
"""OVERLAY-1 (kanban t_cead034d) — index-vs-chain disagreement guard.

Acceptance (Xixi): "when the indexer and chain disagree, the response serves
chain rows and a defect flag is raised." Zero public network: a fake eth_call
RPC server serves canonical Settlement-struct encodings; surfaces are driven
through bi.Handler.do_GET exactly like tests/test_indexer_reorg.py.

Stdlib unittest so CI's `python -m unittest discover -s tests` picks it up.
"""
import json
import os
import sys
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

_tmp = tempfile.mkdtemp(prefix="tanda-overlay-")
os.environ["BILL_INDEX_DB"] = str(Path(_tmp) / "overlay.db")
os.environ.pop("BILL_INDEX_RPC_URL", None)
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "services"))

import bill_index as bi  # noqa: E402

BILL = "0x" + "ab" * 20
WALLET = "0x" + "cc" * 20
TX0 = "0x" + "11" * 32

W = lambda i: hex(int(i))[2:].rjust(64, "0")


def enc_settlement(total=1500000, settled_at=1700000100, initiated_at=1700000000,
                   expected_mask=0b111, confirmed_mask=0b111, claimed_mask=0b11,
                   fully=1700000050, refunded=False, payouts=(500000, 500000, 500000)):
    head = (W(total) + W(9 * 32) + W(settled_at) + W(initiated_at) + W(expected_mask)
            + W(confirmed_mask) + W(claimed_mask) + W(fully) + W(1 if refunded else 0))
    tail = W(len(payouts)) + "".join(W(p) for p in payouts)
    return "0x" + head + tail


def escrow_word(v):
    return "0x" + W(v)


class FakeRpc:
    """Programmable eth_call responder. state keys:
      escrow:  word string | {"error": msg} (error reply)
      settlements: list of {"ret": word} | {"error": msg}; i>=len -> revert
      calls:  every (method, data) tuple observed."""

    def __init__(self, state):
        self.state = state
        self.calls = []
        outer = self

        class Rpc(BaseHTTPRequestHandler):
            def do_POST(self):
                n = int(self.headers.get("Content-Length", 0))
                req = json.loads(self.rfile.read(n).decode())
                outer.calls.append(req["params"][0]["data"])
                assert req["method"] == "eth_call", req["method"]
                data = req["params"][0]["data"]
                sel = data[2:10]
                if sel == bi.SEL_OVERLAY["escrow_balance"][2:]:
                    e = outer.state["escrow"]
                    resp = ({"error": {"message": e["error"]}}
                            if isinstance(e, dict) else {"result": e})
                elif sel == bi.SEL_OVERLAY["settlements_at"][2:]:
                    i = int(data[10:74], 16)
                    lst = outer.state["settlements"]
                    if i >= len(lst):
                        resp = {"error": {"message": "execution reverted"}}
                    elif "error" in lst[i]:
                        resp = {"error": {"message": lst[i]["error"]}}
                    else:
                        resp = {"result": lst[i]["ret"]}
                else:
                    resp = {"error": {"message": "unknown selector " + sel}}
                resp.update(jsonrpc="2.0", id=req["id"])
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

    def shutdown(self):
        self.srv.shutdown()


class OverlayBase(unittest.TestCase):
    def seed(self, settlements, claims):
        """settlements: list of dicts -> summary rows; claims: (sid, seat_id)."""
        db = bi.get_db()
        db.execute("INSERT OR IGNORE INTO bill_index (user_op_hash, bill_address,"
                   " creator, token, status, synthetic) VALUES (?,?,?,?, 'success', 0)",
                   ("0x" + "ee" * 32, BILL, WALLET, WALLET))
        for s in settlements:
            db.execute("INSERT INTO settlements (bill_id, settlement_id, tx_hash,"
                       " total_amount, settled_at, refunded, claimed_count,"
                       " claimed_amount, initiated_block, fully_confirmed_at)"
                       " VALUES (?,?,?,?,?,?,?,?,?,?)",
                       (BILL, s["settlement_id"], TX0, s.get("total_amount"),
                        s.get("settled_at"), s.get("refunded", 0),
                        s.get("claimed_count", 0), s.get("claimed_amount", 0),
                        s.get("initiated_block"), s.get("fully_confirmed_at")))
        for sid, seat in claims:
            db.execute("INSERT INTO seat_claims (bill_id, settlement_id, seat_id,"
                       " wallet, amount, tx_hash, log_index, block)"
                       " VALUES (?,?,?,?,?,?,?,?)",
                       (BILL, sid, seat, WALLET, 500000, TX0, seat, 100))
        db.commit()
        db.close()

    def start_rpc(self, state):
        self.rpc = FakeRpc(state)
        self._saved_url = bi.RPC_URL
        bi.RPC_URL = f"http://127.0.0.1:{self.rpc.port}"

    def get_json(self, path):
        h = bi.Handler.__new__(bi.Handler)
        sent = {}
        h._json = lambda code, obj: sent.update(code=code, obj=obj)
        h.path = path
        bi.Handler.do_GET(h)
        self.assertEqual(sent.get("code"), 200, path)
        return sent["obj"]

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="tanda-overlay-case-")
        self._saved_db = bi.DB_PATH
        bi.DB_PATH = str(Path(self.tmp) / "case.db")
        for k in list(bi.OVERLAY_CACHE):
            bi.OVERLAY_CACHE.pop(k)
        self._saved = (bi.OVERLAY_ENABLED, bi.OVERLAY_MAX_SETTLEMENTS)
        bi.OVERLAY_ENABLED = True
        self.rpc = None

    def tearDown(self):
        bi.DB_PATH = self._saved_db
        bi.OVERLAY_ENABLED, bi.OVERLAY_MAX_SETTLEMENTS = self._saved
        if self.rpc:
            self.rpc.shutdown()
        bi.RPC_URL = getattr(self, "_saved_url", bi.RPC_URL)


class TestOverlaySurfaces(OverlayBase):
    def test_agreement_ok_serves_index_rows(self):
        self.seed([{"settlement_id": 0, "total_amount": 1500000,
                    "settled_at": 1700000100, "claimed_count": 2}],
                  [(0, 0), (0, 1)])
        self.start_rpc({"escrow": escrow_word(250000),
                        "settlements": [{"ret": enc_settlement()}]})
        out = self.get_json(f"/settlements/{BILL}")
        self.assertEqual(out["integrity"], "OK")
        self.assertEqual(out["chain"], {"escrow_balance": 250000, "n_settlements": 1})
        self.assertNotIn("defects", out)
        self.assertEqual(out["settlements"][0]["tx_hash"], TX0)  # index rows stand
        self.assertEqual(len(out["claims"]), 2)

    def test_count_disagreement_defects_and_chain_rows(self):
        self.seed([{"settlement_id": 0, "total_amount": 1500000,
                    "settled_at": 1700000100, "claimed_count": 2}],
                  [(0, 0), (0, 1)])
        self.start_rpc({"escrow": escrow_word(0),
                        "settlements": [{"ret": enc_settlement()},
                                        {"ret": enc_settlement(total=300, settled_at=0,
                                                               expected_mask=0b11,
                                                               confirmed_mask=0,
                                                               claimed_mask=0,
                                                               fully=0,
                                                               payouts=(150, 150))}]})
        out = self.get_json(f"/settlements/{BILL}")
        self.assertEqual(out["integrity"], "DEFECT")
        self.assertTrue(any(d.startswith("settlement_count: chain=2 index=1")
                            for d in out["defects"]), out["defects"])
        self.assertEqual(len(out["settlements"]), 2)
        self.assertTrue(all(r["source"] == "chain" for r in out["settlements"]))
        self.assertIsNone(out["settlements"][0]["tx_hash"])  # never forge from chain
        self.assertEqual(out["settlements"][1]["total_amount"], 300)

    def test_claimed_mask_disagreement(self):
        # index knows 1 claim; chain mask shows 2 (seat 0,1)
        self.seed([{"settlement_id": 0, "total_amount": 1500000,
                    "settled_at": 1700000100, "claimed_count": 1}], [(0, 0)])
        self.start_rpc({"escrow": escrow_word(0),
                        "settlements": [{"ret": enc_settlement(claimed_mask=0b11)}]})
        out = self.get_json(f"/settlements/{BILL}")
        self.assertEqual(out["integrity"], "DEFECT")
        self.assertTrue(any("claimedMask chain=[0, 1] index=[0]" in d
                            for d in out["defects"]), out["defects"])
        self.assertEqual([c["seat_id"] for c in out["claims"]], [0, 1])
        self.assertTrue(all(c["source"] == "chain" for c in out["claims"]))

    def test_settled_state_disagreement(self):
        self.seed([{"settlement_id": 0, "total_amount": 1500000,
                    "settled_at": None, "claimed_count": 2}], [(0, 0), (0, 1)])
        self.start_rpc({"escrow": escrow_word(0),
                        "settlements": [{"ret": enc_settlement(settled_at=1700000100)}]})
        out = self.get_json(f"/settlements/{BILL}")
        self.assertEqual(out["integrity"], "DEFECT")
        self.assertTrue(any(d.startswith("settlement_0: settled_at chain=1700000100 index=None")
                            for d in out["defects"]), out["defects"])

    def test_amount_and_refunded_disagreement(self):
        self.seed([{"settlement_id": 0, "total_amount": 999,
                    "settled_at": 1700000100, "refunded": 1, "claimed_count": 2}],
                  [(0, 0), (0, 1)])
        self.start_rpc({"escrow": escrow_word(0),
                        "settlements": [{"ret": enc_settlement(total=1500000)}]})
        out = self.get_json(f"/settlements/{BILL}")
        self.assertEqual(out["integrity"], "DEFECT")
        self.assertTrue(any("total_amount chain=1500000 index=999" in d for d in out["defects"]))
        self.assertTrue(any("refunded flag chain=False index=True" in d for d in out["defects"]))

    def test_rpc_down_unchecked_never_false_defect(self):
        self.seed([{"settlement_id": 0, "total_amount": 1500000,
                    "settled_at": 1700000100, "claimed_count": 2}], [(0, 0), (0, 1)])
        self.start_rpc({"escrow": {"error": "upstream unavailable"}, "settlements": []})
        out = self.get_json(f"/settlements/{BILL}")
        self.assertEqual(out["integrity"], "UNCHECKED")
        self.assertIn("upstream unavailable", out["chain"]["reason"])
        self.assertEqual(out["settlements"][0]["tx_hash"], TX0)  # index rows stand

    def test_mid_walk_transport_error_never_truncates(self):
        # index has 0; a RESET (not revert) at i=1 must NOT read as "chain has 1"
        self.seed([], [])
        self.start_rpc({"escrow": escrow_word(0),
                        "settlements": [{"ret": enc_settlement()},
                                        {"error": "connection was reset"}]})
        out = self.get_json(f"/settlements/{BILL}")
        self.assertEqual(out["integrity"], "UNCHECKED")
        self.assertIn("reset", out["chain"]["reason"])

    def test_no_contract_unchecked(self):
        self.seed([{"settlement_id": 0, "total_amount": 1, "settled_at": None}], [])
        self.start_rpc({"escrow": "0x", "settlements": []})
        out = self.get_json(f"/settlements/{BILL}")
        self.assertEqual(out["integrity"], "UNCHECKED")
        self.assertIn("no on-chain contract", out["chain"]["reason"])

    def test_overlay_disabled_legacy_shape(self):
        self.seed([{"settlement_id": 0, "total_amount": 1500000,
                    "settled_at": 1700000100, "claimed_count": 2}], [(0, 0), (0, 1)])
        self.start_rpc({"escrow": escrow_word(0), "settlements": []})
        bi.OVERLAY_ENABLED = False
        out = self.get_json(f"/settlements/{BILL}")
        self.assertNotIn("integrity", out)
        self.assertNotIn("chain", out)
        self.assertEqual(self.rpc.calls, [])  # zero RPC when disabled

    def test_probe_cache_absorbs_bursts(self):
        self.seed([{"settlement_id": 0, "total_amount": 1500000,
                    "settled_at": 1700000100, "claimed_count": 2}], [(0, 0), (0, 1)])
        self.start_rpc({"escrow": escrow_word(0),
                        "settlements": [{"ret": enc_settlement()}]})
        a = self.get_json(f"/settlements/{BILL}")
        b = self.get_json(f"/api/settlements?bill={BILL}")
        self.assertEqual(a["integrity"], "OK")
        self.assertEqual(b["integrity"], "OK")
        # escrow(1) + settlements(0..1 stop) = 3 calls for the FIRST read, zero more
        self.assertEqual(len(self.rpc.calls), 3)

    def test_truncated_walk_unchecked(self):
        self.seed([], [])
        self.start_rpc({"escrow": escrow_word(0),
                        "settlements": [{"ret": enc_settlement()},
                                        {"ret": enc_settlement()},
                                        {"ret": enc_settlement()}]})
        bi.OVERLAY_MAX_SETTLEMENTS = 2
        out = self.get_json(f"/settlements/{BILL}")
        self.assertEqual(out["integrity"], "UNCHECKED")
        self.assertIn("OVERLAY_MAX_SETTLEMENTS", out["chain"]["reason"])

    def test_api_settlements_pagination_plus_integrity(self):
        self.seed([{"settlement_id": 0, "total_amount": 1500000,
                    "settled_at": 1700000100, "claimed_count": 2},
                   {"settlement_id": 1, "total_amount": 5, "settled_at": None}],
                  [(0, 0), (0, 1)])
        chain1 = enc_settlement(total=5, settled_at=0, expected_mask=0b1,
                                confirmed_mask=0, claimed_mask=0, fully=0, payouts=(5,))
        self.start_rpc({"escrow": escrow_word(0),
                        "settlements": [{"ret": enc_settlement()}, {"ret": chain1}]})
        out = self.get_json(f"/api/settlements?bill={BILL}&page=1")
        self.assertEqual(out["integrity"], "OK")
        self.assertEqual(out["total_settlements"], 2)
        self.assertEqual([r["settlement_id"] for r in out["settlements"]], [0, 1])
        # page=x -> 400 (SR-RV-A1 validation order preserved): the 400 must
        # return BEFORE any chain probe, so the RPC call count stays as the
        # page=1 read left it. Harness get_json asserts 200, so drive the
        # handler directly for the negative case.
        rpc = self.rpc
        assert rpc is not None  # start_rpc() always runs first in this test
        calls_before = len(rpc.calls)
        h = bi.Handler.__new__(bi.Handler)
        sent = {}
        h._json = lambda code, obj: sent.update(code=code, obj=obj)
        h.path = f"/api/settlements?bill={BILL}&page=x"
        bi.Handler.do_GET(h)
        self.assertEqual(sent.get("code"), 400, sent)
        self.assertEqual(sent.get("obj", {}).get("error"), "bad page")
        self.assertEqual(len(rpc.calls), calls_before)  # 400 never probes

    def test_defect_serves_all_chain_rows_regardless_of_page(self):
        self.seed([{"settlement_id": 0, "total_amount": 1, "settled_at": None}], [])
        chain1 = enc_settlement(total=7, settled_at=0, expected_mask=0b1,
                                confirmed_mask=0, claimed_mask=0, fully=0, payouts=(7,))
        self.start_rpc({"escrow": escrow_word(0),
                        "settlements": [{"ret": enc_settlement()}, {"ret": chain1}]})
        out = self.get_json(f"/api/settlements?bill={BILL}&page=2")
        self.assertEqual(out["integrity"], "DEFECT")
        self.assertEqual(len(out["settlements"]), 2)  # full chain truth, not page-2 slice


class TestOverlayUnits(OverlayBase):
    def test_selector_table_verified(self):
        bi._verify_overlay_selectors()
        saved = dict(bi.SEL_OVERLAY)
        try:
            bi.SEL_OVERLAY["owner"] = "0xdeadbeef"
            with self.assertRaises(AssertionError):
                bi._verify_overlay_selectors()
        finally:
            bi.SEL_OVERLAY.clear()
            bi.SEL_OVERLAY.update(saved)

    def test_settlement_decode_vector(self):
        d = bi._decode_settlement_ret(enc_settlement(total=42, claimed_mask=0b101,
                                                     payouts=(1, 2, 3, 4), refunded=True))
        self.assertIsNotNone(d)
        self.assertEqual(d["total_amount"], 42)
        self.assertEqual(d["claimed_mask"], 0b101)
        self.assertEqual(d["payouts"], [1, 2, 3, 4])
        self.assertTrue(d["refunded"])
        self.assertIsNone(bi._decode_settlement_ret("0x"))


if __name__ == "__main__":
    unittest.main(verbosity=2)
