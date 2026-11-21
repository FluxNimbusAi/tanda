#!/usr/bin/env python3
"""M4-1a (t_3aed711f, Flux GO 2026-11-20): GET /api/grants auth-free read view.

Pins three contracts:
 (a) shape parity with the keyed /grants read (wallet -> {nullifier, verified_at}),
 (b) 400 on missing/malformed bill (same ADDR_RE posture as /api/settlements),
 (c) NO Authorization header is consulted on the /api/... lane: a request that
     would 401 on the keyed route must 200 here (this is what lets a hosted
     mini-app read grants without ever touching the write key).

Stdlib unittest, drives the real Handler.do_GET with captured _json -
same idiom as tests/test_settlement_parity.py (no sockets).
"""
import os
import sys
import tempfile
import unittest
from pathlib import Path

_tmp = tempfile.mkdtemp(prefix="tanda-grants-")
os.environ["BILL_INDEX_DB"] = str(Path(_tmp) / "bill_index.db")
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "services"))

import bill_index as bi  # noqa: E402

BILL = "0x2032cc313c5b115e8aaa1ae7615d60aa3a199810"
W1 = "0x1111111111111111111111111111111111111111"
N1 = "0x" + "ab" * 32


class GrantsReadView(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        db = bi.get_db()
        db.execute(
            "INSERT OR IGNORE INTO seat_grants (bill_address, nullifier, wallet_address, signal)"
            " VALUES (?,?,?,?)",
            (BILL, N1, W1, "sig-test"),
        )
        db.commit()

    def call(self, path, headers=None):
        h = bi.Handler.__new__(bi.Handler)
        h.path = path
        sent = {}
        h._json = lambda code, obj: sent.update(code=code, obj=obj)
        # headers consulted only by the keyed lane; /api/ lane must never reach them
        h.headers = headers or {}  # type: ignore[assignment]  # stub, no sockets (parity-test idiom)
        bi.Handler.do_GET(h)
        return sent

    def test_shape_parity_with_keyed_lane(self):
        r = self.call(f"/api/grants?bill={BILL}")
        self.assertEqual(r["code"], 200)
        g = r["obj"]["grants"]
        self.assertIn(W1, g)
        self.assertEqual(g[W1]["nullifier"], N1)
        self.assertIn("verified_at", g[W1])

    def test_empty_bill_returns_empty_map(self):
        r = self.call("/api/grants?bill=0x" + "00" * 20)
        self.assertEqual(r["code"], 200)
        self.assertEqual(r["obj"]["grants"], {})

    def test_malformed_bill_400(self):
        self.assertEqual(self.call("/api/grants?bill=nothex")["code"], 400)

    def test_missing_bill_400(self):
        self.assertEqual(self.call("/api/grants")["code"], 400)

    def test_no_auth_required_on_api_lane(self):
        # same request without ANY Authorization header must 200 here...
        ok = self.call(f"/api/grants?bill={BILL}")
        self.assertEqual(ok["code"], 200)
        # ...while the keyed lane still refuses it (proves we did not loosen writes)
        keyed = self.call(f"/grants?bill={BILL}", headers={})
        self.assertEqual(keyed["code"], 401)


if __name__ == "__main__":
    unittest.main()
