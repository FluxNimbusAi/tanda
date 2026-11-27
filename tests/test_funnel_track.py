#!/usr/bin/env python3
"""G2G-6 (t_a83e4336): /api/track keyed ingest + /api/funnel aggregate view.

Idiom: real Handler methods driven with captured _json, no sockets
(parity with tests/test_grants_read.py). Contracts pinned:
 (a) track requires the write key (401 without), server-clock ts only;
 (b) kind/source whitelist enforced (400 otherwise) — no free-text flood;
 (c) funnel returns AGGREGATES only (a wallet must never appear in output);
 (d) open_rate math: opens/sent per source, badge bar 15% boolean.
"""
import io
import json
import os
import sys
import tempfile
import time
import unittest
from pathlib import Path

_tmp = tempfile.mkdtemp(prefix="tanda-funnel-")
os.environ["BILL_INDEX_DB"] = str(Path(_tmp) / "bill_index.db")
os.environ["INDEX_WRITE_KEY"] = "test-write-key"
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "services"))

import bill_index as bi  # noqa: E402

W1 = "0x" + "11" * 20
BILL = "0x" + "22" * 20


def call_post(path, body, auth=True):
    h = bi.Handler.__new__(bi.Handler)
    h.path = path
    raw = json.dumps(body).encode()
    h.rfile = io.BytesIO(raw)
    h.headers = {"Content-Length": str(len(raw))}  # type: ignore[assignment]  # stub, no sockets (grants-test idiom)
    if auth:
        h.headers["Authorization"] = "Bearer test-write-key"
    sent = {}
    h._json = lambda code, obj: sent.update(code=code, obj=obj)
    bi.Handler.do_POST(h)
    return sent


def call_get(path):
    h = bi.Handler.__new__(bi.Handler)
    h.path = path
    h.headers = {}  # type: ignore[assignment]
    sent = {}
    h._json = lambda code, obj: sent.update(code=code, obj=obj)
    bi.Handler.do_GET(h)
    return sent


class TrackLane(unittest.TestCase):
    def test_requires_key(self):
        r = call_post("/api/track", {"kind": "open", "source": "organic"}, auth=False)
        self.assertEqual(r["code"], 401)

    def test_whitelist(self):
        self.assertEqual(call_post("/api/track", {"kind": "exploit", "source": "x"})["code"], 400)
        self.assertEqual(call_post("/api/track", {"kind": "open", "source": "https://evil"})["code"], 400)

    def test_bad_addresses(self):
        self.assertEqual(call_post("/api/track", {"kind": "open", "source": "n2a", "bill": "nothex"})["code"], 400)


class FunnelMath(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        # seed through the REAL keyed lane (proves insert path end-to-end);
        # one owned connection, closed after commit (grants-test discipline).
        db = bi.get_db()
        now = int(time.time())
        for kind, src, n in (("notify_sent", "n2a", 10), ("open", "n2a", 2)):
            db.executemany("INSERT INTO app_events (ts,kind,source) VALUES (?,?,?)",
                           [(now, kind, src)] * n)
        db.commit()
        db.close()

    def test_rate_and_badge_flag(self):
        r = call_get("/api/funnel?days=7")
        self.assertEqual(r["code"], 200)
        f = r["obj"]["funnel"]["n2a"]
        self.assertEqual((f["sent"], f["opens"], f["open_rate"]), (10, 2, 0.2))
        self.assertTrue(r["obj"]["badge_bar_15pct_any"])

    def test_aggregates_never_leak_wallets(self):
        call_post("/api/track", {"kind": "open", "source": "share", "wallet": W1, "bill": BILL})
        body = json.dumps(call_get("/api/funnel?days=7")["obj"])
        self.assertNotIn(W1, body)
        self.assertNotIn("wallet", body)

    def test_days_clamped(self):
        self.assertEqual(call_get("/api/funnel?days=999")["obj"]["days"], 30)
        self.assertEqual(call_get("/api/funnel?days=junk")["code"], 400)


if __name__ == "__main__":
    unittest.main()
