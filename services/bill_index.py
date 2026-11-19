#!/usr/bin/env python3
"""W8 bill_index service — stdlib only (per W8 design doc, verified decode path).

Lane: userOpHash -> World developer API v2 (auth-free) -> tx hash -> receipt ->
BillCreated log decode -> bill_index row. The UI may only read bill addresses from
GET /bills/by-userop/{hash}; no client-side guessing.

Decode ground truth (verified live 2026-11-16 against smoke tx
0xdbd8dd14... on 4801, matched DEPLOY_RECEIPT_V2 byte-exact):
  topic0 = 0xb6216d646e5d618b749776ebeba03f10245718ba2872d5b57ce0ebac8d3beae9
  topics 1-3 = bill, creator, token (indexed); data word 0 = seatCount.
"""
import json
import os
import re
import sqlite3
import threading
import time
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

# Track A incident 2026-11-17: launching from services/ silently forked the ledger
# onto a fresh empty sibling DB while consumers (Next /api/seat-grants default
# path) kept reading the canonical one. Env override kills the whole class.
DB_PATH = Path(os.environ.get("BILL_INDEX_DB")
               or Path(__file__).resolve().parents[1] / "bill_index.db")
RPC_URL = "https://worldchain-sepolia.g.alchemy.com/public"          # 4801
USEROP_API = "https://developer.world.org/api/v2/minikit/userop/{h}"
# W10: three mint eras are decodable (prod forwarder, fast twin, pre-forwarder).
FACTORIES = [
    "0x96B6Ebc35aD760561d26a6C57d5b3F491B524332".lower(),  # canonical prod
    "0x65Ba0bB4959c2b6121d9e4Da822452aEEC6e61e6".lower(),  # fast rehearsal twin
    "0x70A5dC7Ea69D19618335D89d84a32c2a605c2Ac6".lower(),  # pre-forwarder (legacy bills)
]
FACTORY = FACTORIES[-1]  # kept for self-test back-compat
WRITE_KEY_FILE = Path("~/.hermes-secrets/index_write_key.txt").expanduser()
BILLCREATED_TOPIC0 = "0xb6216d646e5d618b749776ebeba03f10245718ba2872d5b57ce0ebac8d3beae9"
# SR-KP-A1 (Flux ruling 2026-11-19, issue #18): SettlementExecuted(uint256 indexed
# settlementId, uint256 totalAmount, uint64 settledAt) — cast keccak of the ABI sig;
# emitted BY THE BILL CONTRACT, so log address == bill_address.
SETTLEMENT_EXECUTED_TOPIC0 = "0x6e15c64adb1391003365f3c4b622f5e671638baa46af47c046068a9154f37858"
# t_0588553b: single source of truth for the tx-lane 201 INSERT (10 columns).
# The shipped blob carried VALUES (NULL,?,?,?,?,?,?,...) = 11 values for 10
# columns vs only 5 bindings -> sqlite prepare error escaped _handle_tx_lane
# (client saw RemoteDisconnected). self_test() executes THIS exact SQL so the
# merge gate can never go green without the 201 INSERT preparing cleanly.
TX_LANE_INSERT_SQL = (
    "INSERT INTO bill_index (user_op_hash, tx_hash, bill_address, creator, token,"
    " seat_count, chain_id, status, synthetic, ingest_lane)"
    " VALUES (NULL,?,?,?,?,?,4801,'success',0,'tx')")
USEROP_RE = re.compile(r"^0x[0-9a-fA-F]{64}$")
POLL_INTERVAL, POLL_MAX = 2, 30   # W8: 2s x 30 (~60s ceiling, op-stack 2s blocks)
RECEIPT_RETRIES = 3               # replica-lag lesson (W6)

HEX64 = re.compile(r"^0x[0-9a-fA-F]{64}$")
ADDR_RE = re.compile(r"^0x[a-fA-F0-9]{40}$")
RP_ID_RE = re.compile(r"^rp_[a-z0-9]+$")

SERVER_START = time.time()  # Track A #8: uptime basis for GET /health


def _write_key():
    """Bearer for POST /grants. Env wins; else the vaulted runtime-generated key.
    Never inline the literal: the host sanitizer rewrites secret-LOOKING strings."""
    return (os.environ.get("INDEX_WRITE_KEY")
            or WRITE_KEY_FILE.read_text().strip())


def _rpc(method, params):
    body = json.dumps({"jsonrpc": "2.0", "id": 1, "method": method, "params": params}).encode()
    req = urllib.request.Request(RPC_URL, data=body, headers={"Content-Type": "application/json"})
    resp = json.loads(urllib.request.urlopen(req, timeout=25).read().decode())
    if "error" in resp:
        raise RuntimeError(f"rpc error: {resp['error']}")
    return resp["result"]


def decode_billcreated(log):
    """Return {bill, creator, token, seatCount} from a factory BillCreated log entry."""
    topics, data = log["topics"], log["data"][2:]
    words = [data[i:i + 64] for i in range(0, len(data), 64)]
    return {
        "bill": "0x" + topics[1][-40:],
        "creator": "0x" + topics[2][-40:],
        "token": "0x" + topics[3][-40:],
        "seatCount": int(words[0], 16),
    }


def get_db():
    db = sqlite3.connect(DB_PATH, timeout=15)
    db.execute("PRAGMA busy_timeout=15000")
    db.row_factory = sqlite3.Row
    db.execute("""CREATE TABLE IF NOT EXISTS bill_index (
        user_op_hash TEXT PRIMARY KEY,
        tx_hash TEXT,
        bill_address TEXT UNIQUE,
        creator TEXT NOT NULL,
        token TEXT NOT NULL,
        seat_count NUMERIC,
        chain_id NUMERIC NOT NULL DEFAULT 4801,
        status TEXT NOT NULL DEFAULT 'pending',
        failed_at TEXT,
        created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now'))
    )""")
    db.execute("CREATE INDEX IF NOT EXISTS bill_index_creator_idx ON bill_index (creator, created_at DESC)")
    # W10 hygiene: synthetic flag (self-test/smoke residue=1, service-genuine=0)
    # + ingest lane ('userop' = MiniKit lane, 'tx' = EOA direct per W8 design L40).
    cols = [r[1] for r in db.execute("PRAGMA table_info(bill_index)")]
    if "synthetic" not in cols:
        db.execute("ALTER TABLE bill_index ADD COLUMN synthetic INTEGER NOT NULL DEFAULT 1")
    if "ingest_lane" not in cols:
        db.execute("ALTER TABLE bill_index ADD COLUMN ingest_lane TEXT NOT NULL DEFAULT 'userop'")
    # W10 P1.1 ledger — audit correction #2 shape. nonce (single-use RP-signature
    # request nonce) is the true replay key; (rp_id, nullifier) gets a NON-unique
    # index: one human re-joins many bills with the same nullifier per action.
    db.execute("""CREATE TABLE IF NOT EXISTS idkit_verifications (
        rp_id TEXT NOT NULL,
        nonce TEXT NOT NULL,
        nullifier TEXT NOT NULL,
        signal_hash TEXT,
        action TEXT,
        protocol_version TEXT,
        bill_address TEXT,
        verified_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now')),
        PRIMARY KEY (rp_id, nonce)
    )""")
    db.execute("CREATE INDEX IF NOT EXISTS idkit_nullifier_idx ON idkit_verifications (rp_id, nullifier)")
    db.execute("""CREATE TABLE IF NOT EXISTS seat_grants (
        bill_address TEXT NOT NULL,
        nullifier TEXT NOT NULL,
        wallet_address TEXT NOT NULL,
        signal TEXT NOT NULL,
        verified_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now')),
        PRIMARY KEY (bill_address, nullifier),
        UNIQUE (bill_address, wallet_address)
    )""")
    # SR-KP-A1 (Flux ruling 2026-11-19, issue #18): settlement index written
    # in the same tx-lane as bill_index rows — indexer stays the single
    # audited source for the M3 settlement-vector render (NOT client RPC).
    db.execute("""CREATE TABLE IF NOT EXISTS settlements (
        bill_id TEXT NOT NULL,
        settlement_id NUMERIC NOT NULL,
        user_op_hash TEXT,
        tx_hash TEXT NOT NULL,
        block NUMERIC,
        total_amount NUMERIC,
        settled_at NUMERIC,
        confirmed_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now')),
        PRIMARY KEY (bill_id, settlement_id)
    )""")
    return db


def resolve_userop(db, user_op_hash):
    """Poll userop endpoint -> tx hash -> receipt -> decode. Idempotent; returns row."""
    row = db.execute("SELECT * FROM bill_index WHERE user_op_hash=?", (user_op_hash,)).fetchone()
    if row and row["bill_address"]:
        return dict(row)
    for attempt in range(POLL_MAX):
        try:
            req = urllib.request.Request(USEROP_API.format(h=user_op_hash))
            data = json.loads(urllib.request.urlopen(req, timeout=25).read().decode())
        except Exception:
            # non-JSON / transient — guard per verified assumption; keep polling
            time.sleep(POLL_INTERVAL)
            continue
        status = (data.get("status") or "").lower()
        if status == "success":
            tx_hash = data.get("transaction_hash")
            rec = None
            for _ in range(RECEIPT_RETRIES):
                rec = _rpc("eth_getTransactionReceipt", [tx_hash])
                if rec:
                    break
                time.sleep(2)
            if not rec:
                continue
            logs = [l for l in rec["logs"]
                    if l["address"].lower() in FACTORIES and l["topics"][0].lower() == BILLCREATED_TOPIC0]
            if not logs:
                db.execute("UPDATE bill_index SET status='no_event' WHERE user_op_hash=?", (user_op_hash,))
                db.commit()
                return None
            d = decode_billcreated(logs[0])
            db.execute("""UPDATE bill_index SET tx_hash=?, bill_address=?, creator=COALESCE(creator,?),
                token=?, seat_count=?, status='success' WHERE user_op_hash=?""",
                (tx_hash, d["bill"], d["creator"], d["token"], d["seatCount"], user_op_hash))
            db.commit()
            return db.execute("SELECT * FROM bill_index WHERE user_op_hash=?", (user_op_hash,)).fetchone()
        if status == "failed":
            db.execute("UPDATE bill_index SET status='failed', failed_at=strftime('%Y-%m-%dT%H:%M:%SZ','now') WHERE user_op_hash=?",
                       (user_op_hash,))
            db.commit()
            return db.execute("SELECT * FROM bill_index WHERE user_op_hash=?", (user_op_hash,)).fetchone()
        time.sleep(POLL_INTERVAL)
    db.execute("UPDATE bill_index SET status='timeout' WHERE user_op_hash=?", (user_op_hash,))
    db.commit()
    return db.execute("SELECT * FROM bill_index WHERE user_op_hash=?", (user_op_hash,)).fetchone()


class Handler(BaseHTTPRequestHandler):
    def _json(self, code, obj):
        body = json.dumps(obj).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_POST(self):
        if self.path == "/grants":
            return self._handle_grant()
        if self.path == "/bills/tx":
            return self._handle_tx_lane()
        if self.path != "/bills":
            return self._json(404, {"error": "not found"})
        n = int(self.headers.get("Content-Length", 0))
        try:
            body = json.loads(self.rfile.read(n).decode())
        except Exception:
            return self._json(400, {"error": "invalid json"})
        h = body.get("user_op_hash", "")
        if not HEX64.match(h):
            return self._json(400, {"error": "bad user_op_hash"})
        db = get_db()
        # insert pending row; resolve in background thread (202 semantics per W8)
        db.execute("""INSERT OR IGNORE INTO bill_index (user_op_hash, creator, token, chain_id,
                       synthetic, ingest_lane) VALUES (?,?,?,?,0,'userop')""",
                   (h.lower(), body.get("creator", ""), body.get("token", ""), int(body.get("chain_id", 4801))))
        db.commit()
        def _poll(h):
            try:
                resolve_userop(get_db(), h)
            except Exception as e:
                db2 = get_db()
                db2.execute("UPDATE bill_index SET status='error' WHERE user_op_hash=?", (h,))
                db2.commit()
        threading.Thread(target=_poll, args=(h.lower(),), daemon=True).start()
        return self._json(202, {"status": "accepted", "user_op_hash": h.lower()})

    def _handle_tx_lane(self):
        n = int(self.headers.get("Content-Length", 0))
        try:
            body = json.loads(self.rfile.read(n).decode())
        except Exception:
            return self._json(400, {"error": "invalid json"})
        th = body.get("tx_hash", "")
        if not HEX64.match(th):
            return self._json(400, {"error": "bad tx_hash"})
        try:
            rec = _rpc("eth_getTransactionReceipt", [th])
        except Exception as e:
            return self._json(502, {"error": f"rpc: {e}"})
        if not rec or rec.get("status") not in ("0x1", "0x01"):
            return self._json(422, {"error": "no receipt or failed tx"})
        logs = [l for l in rec["logs"]
                if l["address"].lower() in FACTORIES
                and l["topics"][0].lower() == BILLCREATED_TOPIC0]
        db = get_db()
        d = decode_billcreated(logs[0]) if logs else None
        # SR-KP-A1 watcher: SettlementExecuted logs (emitted by indexed bills)
        # land in `settlements` in this same handler — INSERT OR IGNORE keyed
        # by (bill_id, settlement_id) so repeat POSTs are idempotent.
        known = {r[0].lower() for r in
                 db.execute("SELECT bill_address FROM bill_index WHERE bill_address IS NOT NULL")}
        if d:
            known.add(d["bill"].lower())
        slogs = [l for l in rec["logs"]
                 if l.get("topics") and len(l["topics"]) > 1
                 and l["topics"][0].lower() == SETTLEMENT_EXECUTED_TOPIC0
                 and l["address"].lower() in known]
        n_settle = 0
        blk = rec.get("blockNumber")
        block = int(blk, 16) if blk else None
        for l in slogs:
            data = (l.get("data") or "0x")[2:]
            words = [data[i:i + 64] for i in range(0, len(data), 64)]
            try:
                cur = db.execute(
                    "INSERT OR IGNORE INTO settlements (bill_id, settlement_id,"
                    " user_op_hash, tx_hash, block, total_amount, settled_at)"
                    " VALUES (?,?,?,?,?,?,?)",
                    (l["address"], int(l["topics"][1], 16), None, th, block,
                     int(words[0], 16) if words else None,
                     int(words[1], 16) if len(words) > 1 else None))
                n_settle += cur.rowcount
                db.commit()
            except sqlite3.Error as e:
                db.rollback()
                return self._json(503, {"error": f"settlement write failed: {e}"})
        if not logs and not slogs:
            return self._json(422, {"error": "no BillCreated/SettlementExecuted in receipt"})
        if not d:
            return self._json(200, {"settlements_recorded": n_settle, "tx_hash": th})
        existing = db.execute("SELECT * FROM bill_index WHERE bill_address=?", (d["bill"],)).fetchone()
        if existing:
            return self._json(200, dict(existing))
        # SR-KP-A2 (Flux ruling 2026-11-19, issue #17): a concurrent writer on
        # the same bill must never escape as IntegrityError/TypeError — that
        # killed the handler thread mid-response and the client saw
        # RemoteDisconnected (T13 class). Wrap, roll back, reconcile by read.
        try:
            db.execute(TX_LANE_INSERT_SQL,
                       (th, d["bill"], d["creator"], d["token"], d["seatCount"]))
            db.commit()
        except sqlite3.IntegrityError:
            db.rollback()  # lost the race; winner's row is authoritative
        except sqlite3.Error as e:  # never die silently on the socket
            db.rollback()
            return self._json(503, {"error": f"tx-lane write failed: {e}"})
        row = db.execute("SELECT * FROM bill_index WHERE bill_address=?",
                         (d["bill"],)).fetchone()
        if not row:
            return self._json(503, {"error": "tx-lane write lost; retry"})
        return self._json(201, dict(row))

    def _authed(self):
        got = (self.headers.get("Authorization") or "").removeprefix("Bearer ").strip()
        return bool(got) and got == _write_key()

    def _handle_grant(self):
        """W10 P1.1 ingest: verified-proof rows land ONLY through this writer
        (single-writer invariant, correction #4). Cryptographic gate (keccak
        signal_hash assert) already passed upstream in /api/verify-proof; this
        re-checks structure + format binding and enforces ledger keys."""
        if not self._authed():
            return self._json(401, {"error": "bad write key"})
        n = int(self.headers.get("Content-Length", 0))
        try:
            b = json.loads(self.rfile.read(n).decode())
        except Exception:
            return self._json(400, {"error": "invalid json"})
        rp, nonce = b.get("rp_id", ""), b.get("nonce", "")
        nul, sig = b.get("nullifier", ""), (b.get("signal") or "")
        wallet, bill = b.get("wallet_address", "").lower(), b.get("bill_address", "").lower()
        if not RP_ID_RE.match(rp):
            return self._json(400, {"error": "bad rp_id"})
        if not HEX64.match(nonce):
            return self._json(400, {"error": "bad nonce"})
        if not HEX64.match(nul):
            return self._json(400, {"error": "bad nullifier"})
        if not (ADDR_RE.match(wallet) and ADDR_RE.match(bill)):
            return self._json(400, {"error": "bad wallet/bill address"})
        parts = sig.split(":")
        if len(parts) != 2 or parts[0].lower() != bill or parts[1].lower() != wallet:
            return self._json(400, {"error": "signal must be bill:wallet (exact)"})
        db = get_db()
        try:
            db.execute("INSERT INTO idkit_verifications (rp_id, nonce, nullifier, signal_hash, action, protocol_version, bill_address) VALUES (?,?,?,?,?,?,?)",
                       (rp, nonce.lower(), nul.lower(), (b.get("signal_hash") or "").lower(),
                        b.get("action", ""), b.get("protocol_version", ""), bill))
        except sqlite3.IntegrityError:
            # CRITICAL: the failed INSERT left an implicit transaction open;
            # without rollback this connection holds a write lock and the next
            # request dies with 'database is locked' (correction #4, live-caught
            # in the 2026-11-16 /grants matrix — case 4 poisoned case 5).
            db.rollback()
            return self._json(409, {"error": "nonce already used (replay)"})
        # Explicit pre-check — an identical re-grant violates BOTH PK and
        # wallet-UNIQUE and sqlite picks either message; never classify by
        # error text (live-caught in matrix case A).
        dup = db.execute("SELECT nullifier, wallet_address FROM seat_grants WHERE bill_address=? AND (nullifier=? OR wallet_address=?)",
                         (bill, nul.lower(), wallet)).fetchone()
        if dup:
            if dup["nullifier"].lower() == nul.lower() and dup["wallet_address"].lower() == wallet:
                db.commit()  # keep the ledger row: this human really did re-verify
                return self._json(200, {"status": "already_granted", "bill": bill, "wallet": wallet})
            db.rollback()
            return self._json(409, {"error": "wallet already seated by a different human"})
        try:
            db.execute("INSERT INTO seat_grants (bill_address, nullifier, wallet_address, signal) VALUES (?,?,?,?)",
                       (bill, nul.lower(), wallet, f"{bill}:{wallet}"))
        except sqlite3.IntegrityError:
            db.rollback()
            return self._json(409, {"error": "wallet already seated by a different human"})
        db.commit()
        return self._json(200, {"status": "granted", "bill": bill, "wallet": wallet, "nullifier": nul.lower()})

    def _handle_health(self):
        """Track A #8: liveness/readiness probe. Local-only by design — never
        touches RPC or the userop API, so upstream flakiness can't poison
        health. Auth-free: exposes counters and uptime only, no secrets."""
        db = get_db()
        return self._json(200, {
            "status": "ok",
            "service": "bill_index",
            "chain_id": 4801,
            "uptime_s": round(time.time() - SERVER_START, 1),
            "db": "ok",
            "bills_indexed": db.execute("SELECT COUNT(*) FROM bill_index").fetchone()[0],
            "bills_resolved": db.execute(
                "SELECT COUNT(*) FROM bill_index WHERE status='success'").fetchone()[0],
            "seat_grants": db.execute("SELECT COUNT(*) FROM seat_grants").fetchone()[0],
            "verifications": db.execute("SELECT COUNT(*) FROM idkit_verifications").fetchone()[0],
            "settlements": db.execute("SELECT COUNT(*) FROM settlements").fetchone()[0],
        })

    def do_GET(self):
        if self.path == "/health":
            return self._handle_health()
        if self.path.startswith("/grants"):
            if not self._authed():
                return self._json(401, {"error": "bad write key"})
            qs = self.path.split("?", 1)[1] if "?" in self.path else ""
            bill = dict(p.split("=", 1) for p in qs.split("&") if "=" in p).get("bill", "").lower()
            if not ADDR_RE.match(bill):
                return self._json(400, {"error": "bad bill"})
            db = get_db()
            rows = db.execute("SELECT wallet_address, nullifier, verified_at FROM seat_grants WHERE bill_address=?", (bill,)).fetchall()
            return self._json(200, {"grants": {r["wallet_address"]: {"nullifier": r["nullifier"], "verified_at": r["verified_at"]} for r in rows}})
        if not self.path.startswith("/bills/by-userop/"):
            return self._json(404, {"error": "not found"})
        h = self.path.split("/")[-1].lower()
        if not HEX64.match(h):
            return self._json(400, {"error": "bad user_op_hash"})
        db = get_db()
        row = db.execute("SELECT * FROM bill_index WHERE user_op_hash=?", (h,)).fetchone()
        if not row:
            # lazy-resolve on GET (W8: UI reads by hash; poller must run regardless of entry path)
            db.execute("INSERT OR IGNORE INTO bill_index (user_op_hash, synthetic, ingest_lane) VALUES (?,0,'userop')", (h,))
            db.commit()
            row = resolve_userop(db, h)
            if not row:
                return self._json(200, {"user_op_hash": h, "status": "no_event"})
        out = dict(row)
        out["bill_address"] = out["bill_address"]  # only source the UI may use
        return self._json(200, out)

    def log_message(self, fmt, *args):
        pass


def self_test():
    """Decode-path test against live smoke tx (no userOpHash available in artifacts)."""
    tx = "0xdbd8dd14884d97231a9e8e89da99ec9ca26746a02a9d6dcdc911fb3cfd7d14cd"
    expected_bill = "0x" + "db8e84c552954862bda7e0e8cc5571356b0eddc5"
    rec = _rpc("eth_getTransactionReceipt", [tx])
    logs = [l for l in rec["logs"] if l["address"].lower() == FACTORY and l["topics"][0].lower() == BILLCREATED_TOPIC0]
    assert len(logs) == 1, f"expected 1 factory log, got {len(logs)}"
    d = decode_billcreated(logs[0])
    assert d["bill"].lower() == expected_bill.lower(), f"bill mismatch: {d['bill']}"
    assert d["seatCount"] == 1, f"seatCount mismatch: {d['seatCount']}"
    # storage + endpoint-shape test (no network)
    db = get_db()
    db.execute("INSERT OR IGNORE INTO bill_index (user_op_hash, creator, token) VALUES (?,?,?)",
               ("0x" + "ab" * 32, "test_creator", "test_token"))
    db.commit()
    row = db.execute("SELECT status FROM bill_index WHERE user_op_hash=?", ("0x" + "ab" * 32,)).fetchone()
    assert row["status"] == "pending"
    # t_0588553b regression: exercise the tx-lane 201 INSERT with the handler's
    # exact 5 bindings (bill_address is UNIQUE -> fresh random probe bill; the
    # probe row is deleted so the canonical ledger keeps zero residue).
    probe_tx, probe_bill = "0x" + os.urandom(32).hex(), "0x" + os.urandom(20).hex()
    db.execute(TX_LANE_INSERT_SQL, (probe_tx, probe_bill, "selftest", "selftest", 1))
    p = db.execute("SELECT status, ingest_lane, chain_id, seat_count, synthetic"
                   " FROM bill_index WHERE tx_hash=?", (probe_tx,)).fetchone()
    assert p["status"] == "success" and p["ingest_lane"] == "tx" and p["chain_id"] == 4801 \
        and p["seat_count"] == 1 and p["synthetic"] == 0, dict(p)
    db.execute("DELETE FROM bill_index WHERE tx_hash=?", (probe_tx,))
    db.commit()
    assert db.execute("SELECT COUNT(*) FROM bill_index WHERE tx_hash=?", (probe_tx,)).fetchone()[0] == 0
    print("SELF_TEST PASS: decode matches DEPLOY_RECEIPT_V2 smoke bill byte-exact; "
          "storage OK; tx-lane 201 INSERT prepares with 5/5 bindings (probe row cleaned)")
    return d


if __name__ == "__main__":
    import sys
    if "--self-test" in sys.argv:
        self_test()
    else:
        get_db()
        PORT = int(__import__("os").environ.get("BILL_INDEX_PORT", "8096"))  # W10: match miniapp BILL_INDEX_URL default; 8091 was drift-bait
        srv = ThreadingHTTPServer(("127.0.0.1", PORT), Handler)
        print(f"bill_index service on http://127.0.0.1:{PORT} "
              f"(GET /health, POST /bills, GET /bills/by-userop/{'{hash}'})")
        srv.serve_forever()
