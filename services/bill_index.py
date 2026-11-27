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
# W2.5-2: RPC endpoint is env-overridable (house convention mirrors
# TANDA_NUDGE_RPC_URL) so --scan-once / tests can drive a local fake chain.
RPC_URL = os.environ.get("BILL_INDEX_RPC_URL",
                         "https://worldchain-sepolia.g.alchemy.com/public")   # 4801
USEROP_API = "https://developer.world.org/api/v2/minikit/userop/{h}"
# W10: three mint eras are decodable (prod forwarder, fast twin, pre-forwarder).
FACTORIES = [
    "0x96B6Ebc35aD760561d26a6C57d5b3F491B524332".lower(),  # canonical prod
    "0x65Ba0bB4959c2b6121d9e4Da822452aEEC6e61e6".lower(),  # fast rehearsal twin
    "0x010872d47bd7bb001037577a15d090556bfd24c3".lower(),  # V3 hardened main (SafeERC20 #32 + CEI golden #33), 4801 block 37375560
    "0x70A5dC7Ea69D19618335D89d84a32c2a605c2Ac6".lower(),  # pre-forwarder (legacy bills)
]
FACTORY = FACTORIES[-1]  # kept for self-test back-compat
WRITE_KEY_FILE = Path("~/.hermes-secrets/index_write_key.txt").expanduser()
BILLCREATED_TOPIC0 = "0xb6216d646e5d618b749776ebeba03f10245718ba2872d5b57ce0ebac8d3beae9"
# SR-KP-A1 (Flux ruling 2026-11-19, issue #18): SettlementExecuted(uint256 indexed
# settlementId, uint256 totalAmount, uint64 settledAt) — cast keccak of the ABI sig;
# emitted BY THE BILL CONTRACT, so log address == bill_address.
SETTLEMENT_EXECUTED_TOPIC0 = "0x6e15c64adb1391003365f3c4b622f5e671638baa46af47c046068a9154f37858"
# SR-003 F12 topic parity (t_m4_p01a): the FULL P0.1a settlement lifecycle, not
# just the terminal Executed leg. topic0 = cast keccak of the canonical event
# signature (contracts/TandaBillV2.sol:92-97), cross-checked 2026-11-19 against
# live 4801 logs on bill 0xbe4326dec14d41383dd195097b125905b209846c (blocks
# 37277221/37277222/37279405). All six are emitted BY THE BILL CONTRACT.
SETTLEMENT_TOPICS = {
    "0x4797782232d6165df4bc18cba44fe5bc490d99327264a9f0f500616709f2eebb": "SettlementInitiated",
    "0x867c4949e90057f87dd89cb454afd97cbb793f822e5f0be95e4321c79aa5c30a": "SeatConfirmed",
    "0xa53a3715aacdab54744ae14864b68ab5d8bdf76b6b992e926a2f665d38e40889": "SettlementFullyConfirmed",
    SETTLEMENT_EXECUTED_TOPIC0: "SettlementExecuted",
    # P0.1a pull-claim leg: claimSettlement() emits SeatPayoutClaimed per seat.
    "0x3c62290af710b13d2a5be8d22033b19a3207a05f49798c28b402d4bd484c0dea": "SeatPayoutClaimed",
    "0xf0ac96da4056bba49f666d0f71d3af8a1a294cabef05ab4ab32c17a82f0b3da7": "SettlementRefunded",
}
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
# W2.5-2 (t_0222f1e6): reorg-overlap window for the log-scan lane. op-stack
# sequencer (2s blocks) reorgs are shallow; 12 blocks (~24s) rescanned every
# pass is the safety margin. Deeper orgs are OUT of scope by design and
# documented on scan_pass().
REORG_OVERLAP = 12
SCAN_RANGE = 2000                  # ceiling for the total scan window (chunked)
# t_2a0ebac9 (2026-11-23): the keyless public RPC (worldchain-sepolia.g.alchemy.com/public)
# REJECTS eth_getLogs ranges >100 blocks (HTTP 400 / -32600; probe-verified this
# tick: ranges 2000 and 1000 -> 400, 100 and 50 -> OK). SCAN_RANGE as the sole
# chunk size was a stall-maker: any lag >100 blocks (watch off at start, or a
# --scan-once after downtime — the 114,589-block stall of 2026-11-23) failed
# EVERY pass in the watch retry loop forever. scan_pass chunks at
# min(SCAN_RANGE, RPC_LOG_CAP) now; key-bearing RPCs can raise the cap via
# BILL_INDEX_MAX_CHUNK without touching the ceiling semantics.
RPC_LOG_CAP = int(os.environ.get("BILL_INDEX_MAX_CHUNK", "100"))

HEX64 = re.compile(r"^0x[0-9a-fA-F]{64}$")
ADDR_RE = re.compile(r"^0x[a-fA-F0-9]{40}$")
# ENGINE-65: mirrors the contract MAX_HOLD (refundSettlement gate, 72h).
MAX_HOLD_SECONDS = 72 * 3600
SETTLEMENTS_PAGE_SIZE = 20  # M4-2 issue #19 SR-RV-A1: page window for GET /api/settlements
RP_ID_RE = re.compile(r"^rp_[a-z0-9]+$")

SERVER_START = time.time()  # Track A #8: uptime basis for GET /health

# ── OVERLAY-1 (kanban t_cead034d): index-vs-chain disagreement guard ─────────
# §7.4 settled law: when the indexer and the chain disagree, the chain is truth.
# Every settlement READ surface (/api/settlements, /settlements/<bill>) runs a
# cheap eth_call probe (escrowBalance + settlements[] walk) and compares against
# the ledger rows; on disagreement the response SERVES CHAIN ROWS and raises
# integrity:'DEFECT'. Probe failure -> 'UNCHECKED' (never a false DEFECT, and a
# read surface must never 500 because RPC flaked). Selectors pinned canonical,
# same hardcoded-table policy as services/nudge_engine.py:67-95 (keccak
# derived 2026-11-24 against the repo's own owner()==0x8da5cb5b ground truth —
# no keccak code in this stdlib-only service).
SEL_OVERLAY = {
    "escrow_balance": "0xe11e1b0c",  # escrowBalance()
    "settlements_at": "0x08df7dc8",  # settlements(uint256) — array index == settlementId
                                     # (TandaBillV2.sol:300 `settlementId = settlements.length`)
    "owner": "0x8da5cb5b",           # owner() — sentinel, table-sanity assert only
}
OVERLAY_ENABLED = os.environ.get("BILL_INDEX_OVERLAY", "1") == "1"
OVERLAY_RPC_TIMEOUT = float(os.environ.get("BILL_INDEX_OVERLAY_TIMEOUT", "8"))
OVERLAY_MAX_SETTLEMENTS = 64  # walk cap; v1 bills carry 1-4, cap bounds worst-case cost
OVERLAY_CACHE_TTL = 55        # seconds; absorbs UI burst on one bill
OVERLAY_CACHE = {}            # bill -> (monotonic_ts, probe_result)
OVERLAY_LOCK = threading.Lock()


def _verify_overlay_selectors():
    """Import/self-test gate mirroring nudge_engine.verify_selectors: a
    corrupted table fails loudly, never silently misprobes."""
    for k, v in SEL_OVERLAY.items():
        assert re.fullmatch(r"0x[0-9a-f]{8}", v), f"bad overlay selector {k}={v}"
    assert SEL_OVERLAY["owner"] == "0x8da5cb5b", "overlay selector table corrupted"


def _vault_resolve(path):
    """t_fd9ad195 (post t_flux_c3): read a ~/.hermes-secrets file; if it is a
    VAULT-MOVED stub, resolve the secret via vault_resolve.py (encrypted Hermes
    vault, handle parsed from the stub). Never prints values."""
    txt = open(os.path.expanduser(str(path)), encoding="utf-8").read()
    if not txt.startswith("VAULT-MOVED"):
        return txt
    import re as _re, subprocess as _sp, sys as _sys
    m = _re.search(r"handle:\s*(vault_[0-9a-f]+)", txt)
    if not m:
        raise RuntimeError("VAULT-MOVED stub without handle: " + str(path))
    _res = os.path.join(os.path.expanduser("~"), ".hermes-secrets", "vault_resolve.py")
    return _sp.run([_sys.executable, _res, m.group(1)],
                   capture_output=True, check=True).stdout.decode("utf-8")


def _write_key():
    """Bearer for POST /grants. Env wins; else the vaulted runtime-generated key.
    Never inline the literal: the host sanitizer rewrites secret-LOOKING strings."""
    return (os.environ.get("INDEX_WRITE_KEY")
            or _vault_resolve(WRITE_KEY_FILE).strip())


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


def decode_settlement_log(log):
    """Decode one P0.1a settlement lifecycle log. topic0 must be in
    SETTLEMENT_TOPICS (bill-contract emitter is checked by the caller).
    Indexed args live in topics, non-indexed in data — layout per
    contracts/TandaBillV2.sol:92-97. Returns dict or None (foreign topic)."""
    topics = log.get("topics") or []
    if not topics:
        return None
    name = SETTLEMENT_TOPICS.get(topics[0].lower())
    if name is None or len(topics) < 2:
        return None
    data = (log.get("data") or "0x")[2:]
    words = [data[i:i + 64] for i in range(0, len(data), 64)]

    def w(i):
        return int(words[i], 16) if len(words) > i else None

    out = {"event": name, "settlement_id": int(topics[1], 16)}
    if name == "SettlementInitiated":            # data: totalAmount, expectedSeats
        out.update(amount=w(0), expected_seats=w(1))
    elif name == "SeatConfirmed":                # topics: settlementId, seatId
        out["seat_id"] = int(topics[2], 16) if len(topics) > 2 else None
    elif name == "SettlementFullyConfirmed":     # data: uint64 at
        out["at_ts"] = w(0)
    elif name == "SettlementExecuted":           # data: totalAmount, uint64 settledAt
        out.update(amount=w(0), at_ts=w(1))
    elif name == "SeatPayoutClaimed":            # topics: sid, seatId, wallet; data: amount
        out.update(seat_id=int(topics[2], 16) if len(topics) > 2 else None,
                   wallet=("0x" + topics[3][-40:]) if len(topics) > 3 else None,
                   amount=w(0))
    elif name == "SettlementRefunded":           # data: amount
        out["amount"] = w(0)
    return out


def _ingest_settlement_logs(db, logs, known, tx_hash, block, block_hash=None):
    """SR-003 F12 parity watcher — SHARED by both ingest lanes (tx POST +
    userop resolve), so the ledger is identical regardless of entry path.
    W2.5-2: the scan lane drives this SAME function (third path, one truth)
    and passes the block_hash the log came in on, which is what makes the
    reorg sweep able to ground-truth a row's position.
    Filter: emitter must be an indexed bill (log address == bill_address) and
    topic0 must be a settlement event. Ledger UNIQUE(tx_hash, log_index) is
    the natural on-chain idempotency key; summary upkeep runs ONLY when the
    ledger insert actually wrote (rowcount==1) — replaying a POSTed tx can
    never double-count claims. Returns (n_ledger, n_created) where n_created
    counts NEWLY inserted settlement summaries."""
    n_ledger = n_created = 0
    for idx, l in enumerate(logs):
        d = decode_settlement_log(l)
        if d is None or l.get("address", "").lower() not in known:
            continue
        li = l.get("logIndex", idx)
        log_index = int(li, 16) if isinstance(li, str) else int(li)
        cur = db.execute(
            "INSERT OR IGNORE INTO settlement_events (bill_id, settlement_id,"
            " event, tx_hash, log_index, block, block_hash, seat_id, wallet, amount, at_ts)"
            " VALUES (?,?,?,?,?,?,?,?,?,?,?)",
            (l["address"].lower(), d["settlement_id"], d["event"], tx_hash,
             log_index, block, block_hash, d.get("seat_id"), d.get("wallet"),
             d.get("amount"), d.get("at_ts")))
        if cur.rowcount != 1:
            continue
        n_ledger += 1
        bill, sid = l["address"].lower(), d["settlement_id"]
        scur = db.execute("INSERT OR IGNORE INTO settlements (bill_id, settlement_id, tx_hash)"
                          " VALUES (?,?,?)", (bill, sid, tx_hash))
        n_created += scur.rowcount
        if d["event"] == "SettlementExecuted":
            db.execute("UPDATE settlements SET tx_hash=?, block=?,"
                       " total_amount=COALESCE(?, total_amount),"
                       " settled_at=COALESCE(?, settled_at)"
                       " WHERE bill_id=? AND settlement_id=?",
                       (tx_hash, block, d.get("amount"), d.get("at_ts"), bill, sid))
        elif d["event"] == "SettlementInitiated":
            db.execute("UPDATE settlements SET"
                       " total_amount=COALESCE(total_amount, ?),"
                       " initiated_block=COALESCE(initiated_block, ?)"
                       " WHERE bill_id=? AND settlement_id=?",
                       (d.get("amount"), block, bill, sid))
        elif d["event"] == "SettlementFullyConfirmed":
            db.execute("UPDATE settlements SET"
                       " fully_confirmed_at=COALESCE(fully_confirmed_at, ?)"
                       " WHERE bill_id=? AND settlement_id=?", (d.get("at_ts"), bill, sid))
        elif d["event"] == "SeatPayoutClaimed":
            db.execute("UPDATE settlements SET claimed_count=claimed_count+1,"
                       " claimed_amount=claimed_amount+COALESCE(?, 0)"
                       " WHERE bill_id=? AND settlement_id=?", (d.get("amount"), bill, sid))
            # W2.5-2 gap 3: mirror claimedMask per seat. The ledger row above
            # already gated on rowcount==1, so this insert only runs for a
            # NEWLY seen claim — replay never duplicates it. PK (bill,sid,seat)
            # means a re-claim of the same seat (contract-rejected anyway)
            # would surface as an anomaly, not a double count.
            if d.get("seat_id") is not None and d.get("wallet"):
                db.execute("INSERT OR IGNORE INTO seat_claims (bill_id, settlement_id,"
                           " seat_id, wallet, amount, tx_hash, log_index, block)"
                           " VALUES (?,?,?,?,?,?,?,?)",
                           (bill, sid, d["seat_id"], d["wallet"], d.get("amount"),
                            tx_hash, log_index, block))
        elif d["event"] == "SettlementRefunded":
            db.execute("UPDATE settlements SET refunded=1"
                       " WHERE bill_id=? AND settlement_id=?", (bill, sid))
    db.commit()
    return n_ledger, n_created


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
    # W2.5-2 reorg audit: block/block_hash are written ONLY by the scan lane
    # (and by scan re-ingests). NULL = "position not indexed by us" -> the
    # sweep NEVER prunes rows it cannot ground-truth (conservative law).
    if "block" not in cols:
        db.execute("ALTER TABLE bill_index ADD COLUMN block NUMERIC")
    if "block_hash" not in cols:
        db.execute("ALTER TABLE bill_index ADD COLUMN block_hash TEXT")
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
    # SR-003 F12 parity (t_m4_p01a): lifecycle columns on the summary table
    # (additive, ALTER-guarded for pre-parity DBs) + append-only event ledger.
    scols = [r[1] for r in db.execute("PRAGMA table_info(settlements)")]
    for col, decl in (("initiated_block", "NUMERIC"),
                      ("fully_confirmed_at", "NUMERIC"),
                      ("refunded", "INTEGER NOT NULL DEFAULT 0"),
                      ("claimed_count", "NUMERIC NOT NULL DEFAULT 0"),
                      ("claimed_amount", "NUMERIC NOT NULL DEFAULT 0")):
        if col not in scols:
            db.execute(f"ALTER TABLE settlements ADD COLUMN {col} {decl}")
    db.execute("""CREATE TABLE IF NOT EXISTS settlement_events (
        bill_id TEXT NOT NULL,
        settlement_id NUMERIC NOT NULL,
        event TEXT NOT NULL,
        tx_hash TEXT NOT NULL,
        log_index NUMERIC NOT NULL,
        block NUMERIC,
        block_hash TEXT,
        seat_id NUMERIC,
        wallet TEXT,
        amount NUMERIC,
        at_ts NUMERIC,
        recorded_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now')),
        UNIQUE (tx_hash, log_index)
    )""")
    db.execute("CREATE INDEX IF NOT EXISTS settlement_events_bill_idx"
               " ON settlement_events (bill_id, block, log_index)")
    # ENGINE-65: timeout-escalation ledger (additive-only; one row per
    # (bill, settlement), escalation is a monotonic latch -> idempotent sweeps).
    db.execute("""CREATE TABLE IF NOT EXISTS settlement_deadlines (
        bill_id TEXT NOT NULL,
        settlement_id NUMERIC NOT NULL,
        initiated_at NUMERIC NOT NULL,
        max_hold_until NUMERIC NOT NULL,
        refunded_seen INTEGER NOT NULL DEFAULT 0,
        escalated INTEGER NOT NULL DEFAULT 0,
        UNIQUE (bill_id, settlement_id)
    )""")
    # W2.5-2 gap 2: block_hash on the ledger for pre-existing DBs (additive).
    if "block_hash" not in [r[1] for r in db.execute("PRAGMA table_info(settlement_events)")]:
        db.execute("ALTER TABLE settlement_events ADD COLUMN block_hash TEXT")
    # W2.5-2 gap 1: scan-lane checkpoint. One row per key; last_indexed_block
    # is the head ATTESTED by the most recent completed scan pass. A restart
    # resumes at last_indexed_block + 1 - REORG_OVERLAP (overlap replay is
    # idempotent via the ledger's UNIQUE(tx_hash, log_index) + rowcount guard).
    db.execute("""CREATE TABLE IF NOT EXISTS indexer_state (
        key TEXT PRIMARY KEY,
        value TEXT NOT NULL,
        updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now'))
    )""")
    # W2.5-2 gap 3 (P0.1a): per-seat SeatClaimed state — the indexer mirror of
    # Settlement.claimedMask (contracts/TandaBillV2.sol:55,354-371). One row
    # per (bill, settlement, seat) that pulled its payout; written by EVERY
    # ingest lane from SeatPayoutClaimed, pruned ONLY by the reorg sweep.
    # claimed_count on the summary stays the fast-path aggregate; this table
    # is the auditable per-seat truth.
    db.execute("""CREATE TABLE IF NOT EXISTS seat_claims (
        bill_id TEXT NOT NULL,
        settlement_id NUMERIC NOT NULL,
        seat_id NUMERIC NOT NULL,
        wallet TEXT NOT NULL,
        amount NUMERIC,
        tx_hash TEXT NOT NULL,
        log_index NUMERIC NOT NULL,
        block NUMERIC,
        claimed_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now')),
        PRIMARY KEY (bill_id, settlement_id, seat_id),
        UNIQUE (tx_hash, log_index)
    )""")
    db.execute("""CREATE TABLE IF NOT EXISTS app_events (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        ts INTEGER NOT NULL,
        kind TEXT NOT NULL,
        source TEXT,
        bill_id TEXT,
        wallet TEXT
    )""")
    db.execute("CREATE INDEX IF NOT EXISTS ix_events_ts ON app_events(ts)")
    return db


def _meta_get(db, key, default=None):
    """Read a checkpoint value; digit-only values surface as int."""
    row = db.execute("SELECT value FROM indexer_state WHERE key=?", (key,)).fetchone()
    if row is None:
        return default
    v = row["value"] if isinstance(row, sqlite3.Row) else row[0]
    return int(v) if v.isdigit() else v


def _meta_set(db, key, value):
    db.execute("INSERT INTO indexer_state (key, value, updated_at)"
               " VALUES (?,?,strftime('%Y-%m-%dT%H:%M:%SZ','now'))"
               " ON CONFLICT(key) DO UPDATE SET value=excluded.value,"
               " updated_at=excluded.updated_at", (key, str(value)))
    db.commit()


# ── W2.5-2 scan lane: checkpoint + overlap window + reorg sweep ──────────────

# Bill rows created by block-scan have no userOpHash (EOA deploys land in a
# plain tx); user_op_hash is NULL for them — SQLite treats NULLs as distinct
# in the PK index (probe-verified), so many scan rows coexist.
SCAN_BILL_INSERT_SQL = (
    "INSERT OR IGNORE INTO bill_index (user_op_hash, tx_hash, bill_address,"
    " creator, token, seat_count, chain_id, status, synthetic, ingest_lane,"
    " block, block_hash) VALUES (NULL,?,?,?,?,?,4801,'success',0,'scan',?,?)")


def _recompute_settlement(db, bill_id, settlement_id):
    """Rebuild ONE settlement summary purely from surviving ledger rows.
    Used by the reorg sweep only; the ingest fast path keeps its incremental
    deltas. Ledger-first = deterministic: same surviving events always fold
    to the same summary, regardless of insert order or lane."""
    rows = db.execute(
        "SELECT event, tx_hash, log_index, block, amount, at_ts FROM settlement_events"
        " WHERE bill_id=? AND settlement_id=? ORDER BY block, log_index",
        (bill_id, settlement_id)).fetchall()
    if not rows:
        db.execute("DELETE FROM settlements WHERE bill_id=? AND settlement_id=?",
                   (bill_id, settlement_id))
        db.execute("DELETE FROM seat_claims WHERE bill_id=? AND settlement_id=?",
                   (bill_id, settlement_id))
        return False
    init = ex = fully = None
    refunded = 0
    claims = []
    for r in rows:  # ordered scan: last write wins per event leg
        if r["event"] == "SettlementInitiated":
            init = r
        elif r["event"] == "SettlementExecuted":
            ex = r
        elif r["event"] == "SettlementFullyConfirmed":
            fully = r
        elif r["event"] == "SettlementRefunded":
            refunded = 1
        elif r["event"] == "SeatPayoutClaimed":
            claims.append(r)
    db.execute(
        "UPDATE settlements SET tx_hash=?, block=?, initiated_block=?,"
        " total_amount=?, fully_confirmed_at=?, settled_at=?, refunded=?,"
        " claimed_count=?, claimed_amount=? WHERE bill_id=? AND settlement_id=?",
        ((ex or rows[0])["tx_hash"], (ex or rows[0])["block"],
         init["block"] if init else None,
         (ex or init)["amount"] if (ex or init) else None,
         fully["at_ts"] if fully else None,
         ex["at_ts"] if ex else None, refunded,
         len(claims), sum((c["amount"] or 0) for c in claims),
         bill_id, settlement_id))
    # Per-seat state follows the ledger: a claim row whose ledger twin was
    # pruned is an orphan by definition and must vanish with it.
    db.execute(
        "DELETE FROM seat_claims WHERE bill_id=? AND settlement_id=?"
        " AND NOT EXISTS (SELECT 1 FROM settlement_events e"
        " WHERE e.tx_hash=seat_claims.tx_hash AND e.log_index=seat_claims.log_index)",
        (bill_id, settlement_id))
    return True


def _reorg_sweep(db, head):
    """Prune ledger rows whose recorded block is no longer canonical within
    the overlap window [head - REORG_OVERLAP + 1, head]. Ground truth per
    row: its stored block_hash vs eth_getBlockByNumber. Rows with NULL
    block_hash were never positioned by the scan lane -> NEVER swept
    (conservative law; they are receipt-backed). Bill rows orphaned the same
    way flip to status='reorged' (never deleted: bill_address UNIQUE preserves
    the audit trail even if a rerolled deploy re-lands beside it).
    Returns (n_events_pruned, n_bills_reorged)."""
    lo = max(0, head - REORG_OVERLAP + 1)
    canon = {}

    def canonical_hash(n):
        if n not in canon:
            blk = _rpc("eth_getBlockByNumber", [hex(n), False])
            canon[n] = (blk or {}).get("hash")
        return canon[n]

    n_pruned = 0
    pairs = set()
    for r in db.execute(
            "SELECT rowid AS rid, bill_id, settlement_id, block, block_hash"
            " FROM settlement_events WHERE block>=? AND block<=?"
            " AND block_hash IS NOT NULL", (lo, head)):
        if canonical_hash(r["block"]) != r["block_hash"]:
            db.execute("DELETE FROM settlement_events WHERE rowid=?", (r["rid"],))
            pairs.add((r["bill_id"], r["settlement_id"]))
            n_pruned += 1
    for bill_id, sid in pairs:
        _recompute_settlement(db, bill_id, sid)
    n_bills = 0
    for r in db.execute(
            "SELECT rowid AS rid, block, block_hash FROM bill_index"
            " WHERE block>=? AND block<=? AND block_hash IS NOT NULL"
            " AND status <> 'reorged'", (lo, head)):
        if canonical_hash(r["block"]) != r["block_hash"]:
            db.execute("UPDATE bill_index SET status='reorged' WHERE rowid=?", (r["rid"],))
            n_bills += 1
    db.commit()
    return n_pruned, n_bills


def _timeout_sweep(db, now_ts=None):
    """ENGINE-65 settlement-timeout escalation (clock + DB only, NO RPC —
    stricter than _reorg_sweep which needs canonical-block reads). Mirrors
    the rowcount/idempotency law: UNIQUE(bill_id, settlement_id) + the
    monotonic escalated latch guarantee ONE app_event per timed-out
    settlement, forever. Initiation truth is read from the LEDGER event
    (at_ts), never from the summary, per the contract-state-is-authority
    law. Refunded or settled rows can never escalate (checked at
    escalation time, not just at track time)."""
    now = int(now_ts if now_ts is not None else time.time())
    for r in db.execute(
            "SELECT s.bill_id, s.settlement_id, e.at_ts"
            " FROM settlements s"
            " JOIN settlement_events e ON e.bill_id = s.bill_id"
            "   AND e.settlement_id = s.settlement_id"
            "   AND e.event = 'SettlementInitiated'"
            " WHERE s.settled_at IS NULL AND e.at_ts IS NOT NULL"):
        db.execute(
            "INSERT INTO settlement_deadlines"
            " (bill_id, settlement_id, initiated_at, max_hold_until)"
            " VALUES (?,?,?,?)"
            " ON CONFLICT(bill_id, settlement_id) DO NOTHING",
            (r["bill_id"], r["settlement_id"], r["at_ts"], r["at_ts"] + MAX_HOLD_SECONDS))
    db.execute(
        "UPDATE settlement_deadlines SET refunded_seen=1 WHERE EXISTS ("
        " SELECT 1 FROM settlement_events e WHERE e.bill_id=settlement_deadlines.bill_id"
        "  AND e.settlement_id=settlement_deadlines.settlement_id"
        "  AND e.event='SettlementRefunded')")
    n_esc = 0
    for d in db.execute(
            "SELECT bill_id, settlement_id FROM settlement_deadlines"
            " WHERE escalated=0 AND refunded_seen=0 AND max_hold_until < ?",
            (now,)).fetchall():
        row = db.execute(
            "SELECT settled_at, refunded FROM settlements"
            " WHERE bill_id=? AND settlement_id=?",
            (d["bill_id"], d["settlement_id"])).fetchone()
        if row is None or row["settled_at"] is not None or row["refunded"]:
            continue
        creator = db.execute(
            "SELECT creator FROM bill_index WHERE bill_address=?",
            (d["bill_id"],)).fetchone()
        db.execute("UPDATE settlement_deadlines SET escalated=1"
                   " WHERE bill_id=? AND settlement_id=?",
                   (d["bill_id"], d["settlement_id"]))
        if creator:
            # whitelist-legal event: ('action','n2c') already permitted by
            # KINDS/SOURCES — ops attribution to the bill creator, local lane.
            db.execute(
                "INSERT INTO app_events (ts, kind, source, bill_id, wallet)"
                " VALUES (?,?,?,?,?)",
                (now, "action", "n2c", d["bill_id"], creator["creator"]))
        n_esc += 1
    tracked = db.execute("SELECT count(*) c FROM settlement_deadlines").fetchone()["c"]
    return {"tracked": tracked, "escalated": n_esc}


def scan_pass(db, head=None):
    """One hardened indexer pass: sweep orphans -> ingest
    [last_indexed_block + 1 - REORG_OVERLAP .. head] through the shared
    lane-agnostic ingest -> persist checkpoint. Overlap replay is a no-op by
    construction (UNIQUE(tx_hash, log_index) + rowcount guard), which is what
    makes reorg recovery safe: after a sweep the canonical re-mine re-lands
    the rerolled rows inside the same window. Reorgs DEEPER than
    REORG_OVERLAP blocks are out of scope by design (op-stack 2s sequencer
    keeps orgs shallow); surface one via reindex from a chosen START_BLOCK.
    First-ever pass (no checkpoint): floor at head - REORG_OVERLAP — history
    stays owned by the request-driven lanes unless BILL_INDEX_START_BLOCK is
    set for an explicit backfill.
    Returns a machine-checkable summary dict (printed by --scan-once)."""
    if head is None:
        head = int(_rpc("eth_blockNumber", []), 16)
    last = _meta_get(db, "last_indexed_block")
    env_start = os.environ.get("BILL_INDEX_START_BLOCK")
    if last is None:
        from_block = int(env_start) if env_start else max(0, head - REORG_OVERLAP)
    else:
        from_block = max(0, last + 1 - REORG_OVERLAP)
    pruned, bills_reorged = _reorg_sweep(db, head)
    deadlines = _timeout_sweep(db)
    known = {r[0].lower() for r in db.execute(
        "SELECT bill_address FROM bill_index WHERE bill_address IS NOT NULL")}
    n_events = n_bills = 0
    factory_set = {f.lower() for f in FACTORIES}
    lo = from_block
    chunk = min(SCAN_RANGE, RPC_LOG_CAP)  # t_2a0ebac9: never exceed the RPC range cap
    while lo <= head:
        hi = min(lo + chunk - 1, head)
        logs = _rpc("eth_getLogs", [{"fromBlock": hex(lo), "toBlock": hex(hi),
                                     "address": sorted(factory_set | known)}])
        new_bills = False
        for l in logs:
            if l["address"].lower() not in factory_set:
                continue
            if not l.get("topics") or l["topics"][0].lower() != BILLCREATED_TOPIC0:
                continue
            d = decode_billcreated(l)
            blk = int(l["blockNumber"], 16)
            cur = db.execute(SCAN_BILL_INSERT_SQL,
                             (l["transactionHash"], d["bill"].lower(), d["creator"].lower(),
                              d["token"].lower(), d["seatCount"], blk, l.get("blockHash")))
            if cur.rowcount == 1:
                n_bills += 1
                known.add(d["bill"].lower())
                new_bills = True
        # A bill minted in THIS chunk may already settle in this chunk; the
        # address filter we just queried with could not have known it. Re-query
        # once with the widened set (bounded: only when a new bill landed).
        if new_bills:
            logs = _rpc("eth_getLogs", [{"fromBlock": hex(lo), "toBlock": hex(hi),
                                         "address": sorted(factory_set | known)}])
        by_tx = {}
        for l in logs:
            if not l.get("topics") or l["topics"][0].lower() not in SETTLEMENT_TOPICS:
                continue
            key = (l["transactionHash"], int(l["blockNumber"], 16), l.get("blockHash"))
            by_tx.setdefault(key, []).append(l)
        for (tx, blk, bhash) in sorted(by_tx, key=lambda k: (k[1], k[0])):
            n, _c = _ingest_settlement_logs(db, by_tx[(tx, blk, bhash)], known, tx, blk, bhash)
            n_events += n
        _meta_set(db, "last_indexed_block", hi)  # per-chunk: crash resumes at chunk edge
        db.commit()
        lo = hi + 1
    return {"head": head, "from": from_block, "pruned_events": pruned,
            "bills_reorged": bills_reorged, "events_ingested": n_events,
            "bills_ingested": n_bills}


def watch_loop(stop=None, interval=None, max_passes=None):
    """Resident scan lane, OFF unless BILL_INDEX_WATCH=1 at service start.
    One DB pass at a time (get_db per iteration re-reads the checkpoint). A
    failed pass logs and retries — the sweep/ingest pair is idempotent, so a
    retry after a half-written chunk cannot double-count."""
    if interval is None:
        interval = float(os.environ.get("BILL_INDEX_WATCH_INTERVAL", "5"))
    passes = 0
    while True:
        try:
            out = scan_pass(get_db())
            print(f"[watch] {json.dumps(out)}", flush=True)
        except Exception as e:
            print(f"[watch] pass failed: {e!r} (retrying)", flush=True)
        passes += 1
        if max_passes is not None and passes >= max_passes:
            return passes
        if stop is not None:
            if stop.wait(interval):
                return passes
        else:
            time.sleep(interval)


WATCH_STOP = threading.Event()


# ── OVERLAY-1 machinery (t_cead034d) ─────────────────────────────────────────

def _eth_call_overlay(to, data):
    """Overlay-lane eth_call with its OWN short timeout — a UI read must not
    inherit the 25s ingest timeout."""
    body = json.dumps({"jsonrpc": "2.0", "id": 1, "method": "eth_call",
                       "params": [{"to": to, "data": data}, "latest"]}).encode()
    req = urllib.request.Request(RPC_URL, data=body,
                                 headers={"Content-Type": "application/json"})
    resp = json.loads(urllib.request.urlopen(req, timeout=OVERLAY_RPC_TIMEOUT).read().decode())
    if "error" in resp:
        raise RuntimeError(f"rpc error: {resp['error']}")
    return resp.get("result") or "0x"


def _decode_settlement_ret(ret):
    """Decode the abi.encode of struct Settlement (TandaBillV2.sol:56-67) as
    returned by settlements(i). 9 static head words + payouts[] tail:
    [total, payoutsOffset, settledAt, initiatedAt, expectedMask, confirmedMask,
     claimedMask, fullyConfirmedAt, refunded]. None if shorter than head."""
    data = (ret or "0x")[2:]
    if len(data) < 9 * 64:
        return None
    w = [data[i:i + 64] for i in range(0, len(data), 64)]
    poff = int(w[1], 16) // 32
    n = int(w[poff], 16) if poff < len(w) else 0
    payouts = [int(x, 16) for x in w[poff + 1:poff + 1 + n]]
    return {"total_amount": int(w[0], 16), "settled_at": int(w[2], 16),
            "initiated_at": int(w[3], 16), "expected_mask": int(w[4], 16),
            "confirmed_mask": int(w[5], 16), "claimed_mask": int(w[6], 16),
            "fully_confirmed_at": int(w[7], 16), "refunded": int(w[8], 16) != 0,
            "payouts": payouts}


def _chain_overlay_probe(bill):
    """escrowBalance() + settlements[0..] walk via eth_call. Array end is a
    revert / short-return on index i>0 (expected); a revert or empty answer at
    i==0 alongside a non-decodable escrow getter means no bill contract there —
    raise so the caller serves 'UNCHECKED'. Transport errors always raise —
    never silent-truncate a walk count (that would fabricate a count DEFECT)."""
    esc = _eth_call_overlay(bill, SEL_OVERLAY["escrow_balance"])
    if len(esc[2:]) < 64:
        raise RuntimeError("bill has no on-chain contract data (escrowBalance() empty)")
    settlements = []
    truncated = False
    for i in range(OVERLAY_MAX_SETTLEMENTS):
        try:
            ret = _eth_call_overlay(bill, SEL_OVERLAY["settlements_at"] + W64(i))
        except Exception as e:
            if "revert" in str(e).lower() and i > 0:
                break  # out-of-range array read = end of settlements[]
            raise
        d = _decode_settlement_ret(ret)
        if d is None:
            if i == 0:
                raise RuntimeError("settlements(0) unreadable on a contract that answered escrow")
            break
        d["settlement_id"] = i
        d["claimed_count"] = d["claimed_mask"].bit_count()
        d["claimed_seats"] = [b for b in range(min(d["expected_mask"].bit_length(), 256))
                              if (d["claimed_mask"] >> b) & 1]
        settlements.append(d)
    else:
        truncated = True  # walked to the cap without seeing the array end
    return {"escrow_balance": int(esc[2:66], 16), "settlements": settlements,
            "truncated": truncated}


def W64(i):
    return hex(int(i))[2:].rjust(64, "0")


def _overlay_probe_cached(bill):
    now = time.monotonic()
    with OVERLAY_LOCK:
        hit = OVERLAY_CACHE.get(bill)
        if hit and now - hit[0] < OVERLAY_CACHE_TTL:
            return hit[1]
    probe = _chain_overlay_probe(bill)
    with OVERLAY_LOCK:
        OVERLAY_CACHE[bill] = (now, probe)
        if len(OVERLAY_CACHE) > 512:  # bound the cache; evict expired first
            for k in [k for k, (ts, _) in OVERLAY_CACHE.items()
                      if now - ts >= OVERLAY_CACHE_TTL]:
                OVERLAY_CACHE.pop(k, None)
    return probe


def _chain_rows(bill, probe):
    """Chain-derived settlement rows mirroring the `settlements` summary
    columns, plus source:'chain' provenance. tx_hash/block are ledger-only
    fields — NULL on chain rows (never forge index values from chain data)."""
    out = []
    for cs in probe["settlements"]:
        out.append({
            "bill_id": bill, "settlement_id": cs["settlement_id"],
            "user_op_hash": None, "tx_hash": None, "block": None,
            "total_amount": cs["total_amount"],
            "settled_at": cs["settled_at"] or None,
            "confirmed_at": None, "initiated_block": None,
            "fully_confirmed_at": cs["fully_confirmed_at"] or None,
            "refunded": 1 if cs["refunded"] else 0,
            "claimed_count": cs["claimed_count"],
            "claimed_amount": sum(cs["payouts"][b] for b in cs["claimed_seats"]
                                  if b < len(cs["payouts"])),
            "source": "chain",
        })
    return out


def _chain_claims(bill, probe):
    """Per-seat claim mirror derived from claimedMask x payouts (wallets are
    ledger-only — chain claims carry seat_id + amount)."""
    out = []
    for cs in probe["settlements"]:
        for b in cs["claimed_seats"]:
            out.append({"bill_id": bill, "settlement_id": cs["settlement_id"],
                        "seat_id": b,
                        "amount": cs["payouts"][b] if b < len(cs["payouts"]) else None,
                        "source": "chain"})
    return out


def _overlay_check(db, bill, index_rows):
    """Returns (integrity, payload, defects). None when disabled by env —
    surfaces then keep their exact pre-OVERLAY shape. NEVER raises: probe
    failure downgrades to 'UNCHECKED' with the index rows served as-is."""
    if not OVERLAY_ENABLED:
        return None, None, None
    try:
        probe = _overlay_probe_cached(bill)
    except Exception as e:
        return "UNCHECKED", {"reason": str(e)[:180]}, []
    if probe["truncated"]:  # cap reached: count is a floor, no disagreement claim
        return "UNCHECKED", {"reason": "settlements walk hit OVERLAY_MAX_SETTLEMENTS"}, []
    chain = probe["settlements"]
    defects = []
    if len(chain) != len(index_rows):
        defects.append(f"settlement_count: chain={len(chain)} index={len(index_rows)}")
    by_sid = {int(r["settlement_id"]): r for r in index_rows}
    for cs in chain:
        sid = cs["settlement_id"]
        ir = by_sid.get(sid)
        if ir is None:
            defects.append(f"settlement_{sid}: on chain, absent from index")
            continue
        ia = ir.get("total_amount")
        if ia is not None and int(ia) != cs["total_amount"]:
            defects.append(f"settlement_{sid}: total_amount chain={cs['total_amount']} index={int(ia)}")
        ies = ir.get("settled_at")
        if (ies is None and cs["settled_at"]) or (ies is not None and int(ies) != cs["settled_at"]):
            defects.append(f"settlement_{sid}: settled_at chain={cs['settled_at']} index={ies}")
        if bool(ir.get("refunded") or 0) != cs["refunded"]:
            defects.append(f"settlement_{sid}: refunded flag chain={cs['refunded']} index={bool(ir.get('refunded') or 0)}")
        db_seats = {int(r[0]) for r in db.execute(
            "SELECT seat_id FROM seat_claims WHERE bill_id=? AND settlement_id=?", (bill, sid))}
        if db_seats != set(cs["claimed_seats"]):
            defects.append(f"settlement_{sid}: claimedMask chain={sorted(cs['claimed_seats'])} index={sorted(db_seats)}")
    payload = {"escrow_balance": probe["escrow_balance"], "n_settlements": len(chain),
               "settlements": _chain_rows(bill, probe), "claims": _chain_claims(bill, probe)}
    return ("DEFECT" if defects else "OK"), payload, defects


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
            # SR-003 F12 parity (t_m4_p01a): the SAME lifecycle watcher runs on
            # the userop lane, so ledger contents never depend on entry path.
            known = {r[0].lower() for r in db.execute(
                "SELECT bill_address FROM bill_index WHERE bill_address IS NOT NULL")}
            blk = rec.get("blockNumber")
            try:
                _ingest_settlement_logs(db, rec["logs"], known, tx_hash,
                                        int(blk, 16) if blk else None)
            except sqlite3.Error:
                db.rollback()  # bill row committed; parity retried via POST /bills/tx
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
        if self.path == "/api/track":
            # G2G-6 (analytics funnel): keyed event ingest. The BROWSER NEVER
            # HOLDS THE KEY - the Next /api/track route proxies server-side
            # (notify-route posture). ts is server-clock; client clocks lie.
            if not self._authed():
                return self._json(401, {"error": "bad write key"})
            n = int(self.headers.get("Content-Length", 0))
            if n > 4096:
                return self._json(413, {"error": "body too large"})
            try:
                body = json.loads(self.rfile.read(n).decode())
            except Exception:
                return self._json(400, {"error": "invalid json"})
            return self._track_insert(body)
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
        # SR-KP-A1 watcher, SR-003 F12 widened (t_m4_p01a): the FULL lifecycle
        # (all six P0.1a topics) ingests through the shared lane-agnostic
        # _ingest_settlement_logs; ledger UNIQUE(tx_hash, log_index) makes
        # repeat POSTs idempotent and the rowcount-guard forbids double count.
        known = {r[0].lower() for r in
                 db.execute("SELECT bill_address FROM bill_index WHERE bill_address IS NOT NULL")}
        if d:
            known.add(d["bill"].lower())
        slogs = [l for l in rec["logs"]
                 if l.get("topics") and len(l["topics"]) > 1
                 and l["topics"][0].lower() in SETTLEMENT_TOPICS
                 and l["address"].lower() in known]
        blk = rec.get("blockNumber")
        block = int(blk, 16) if blk else None
        try:
            _, n_settle = _ingest_settlement_logs(db, rec["logs"], known, th, block)
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

    def _apply_overlay(self, db, bill, index_rows, out):
        """OVERLAY-1 (§7.4): annotate a settlement response with the chain
        probe result. DEFECT -> chain rows replace the served summary rows
        (and claims where the surface has them); OK/UNCHECKED -> index rows
        stand. Env-disabled: response shape is byte-identical to pre-OVERLAY."""
        integrity, payload, defects = _overlay_check(db, bill, index_rows)
        if integrity is None or payload is None:  # env-disabled: pre-OVERLAY shape
            return out
        out["integrity"] = integrity
        if integrity == "UNCHECKED":
            out["chain"] = payload
            return out
        out["chain"] = {"escrow_balance": payload["escrow_balance"],
                        "n_settlements": payload["n_settlements"]}
        if integrity == "DEFECT":
            out["defects"] = defects
            out["settlements"] = payload["settlements"]
            if "claims" in out:
                out["claims"] = payload["claims"]
        return out

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
            # W2.5-2: scan-lane checkpoint (None until the first watch pass).
            "last_indexed_block": _meta_get(db, "last_indexed_block"),
            # OVERLAY-1 config token (no RPC touched — health stays local-only).
            "overlay": "on" if OVERLAY_ENABLED else "off",
        })

    SOURCES = ("n1", "n2a", "n2b", "n2c", "n3a", "n3b",
               "organic", "share", "notify_sent")
    KINDS = ("open", "action", "notify_sent")

    def _track_insert(self, body):
        if not isinstance(body, dict):
            return self._json(400, {"error": "object required"})
        kind = body.get("kind", "")
        source = body.get("source", "")
        if kind not in self.KINDS or source not in self.SOURCES:
            return self._json(400, {"error": "kind/source not whitelisted"})
        bill = (body.get("bill") or "").lower()
        wallet = (body.get("wallet") or "").lower()
        if bill and not ADDR_RE.match(bill):
            return self._json(400, {"error": "bad bill"})
        if wallet and not ADDR_RE.match(wallet):
            return self._json(400, {"error": "bad wallet"})
        db = get_db()
        db.execute("INSERT INTO app_events (ts, kind, source, bill_id, wallet) VALUES (?,?,?,?,?)",
                   (int(time.time()), kind, source, bill or None, wallet or None))
        # 90-day retention, cheap prune every insert (dev-scale volumes)
        db.execute("DELETE FROM app_events WHERE ts < ? - 90*86400", (int(time.time()),))
        db.commit()
        return self._json(201, {"ok": True})

    def _handle_funnel(self):
        """GET /api/funnel?days=7 -> aggregate-only open-rate view (auth-free
        like /api/grants: numbers, never raw rows; no wallet ever returned)."""
        qs = self.path.split("?", 1)[1] if "?" in self.path else ""
        params = dict(p.split("=", 1) for p in qs.split("&") if "=" in p)
        try:
            days = max(1, min(30, int(params.get("days", "7"))))
        except ValueError:
            return self._json(400, {"error": "bad days"})
        since = int(time.time()) - days * 86400
        db = get_db()
        def grp(kind):
            rows = db.execute(
                "SELECT source, count(*) c FROM app_events WHERE kind=? AND ts>=? GROUP BY source",
                (kind, since)).fetchall()
            return {r["source"]: r["c"] for r in rows}
        opens = grp("open")
        sent = grp("notify_sent")
        funnel = {}
        for src in ("n1", "n2a", "n2b", "n2c", "n3a", "n3b"):
            s_n = sent.get(src, 0)
            o_n = opens.get(src, 0)
            funnel[src] = {"sent": s_n, "opens": o_n,
                           "open_rate": round(o_n / s_n, 4) if s_n else None}
        badge_eligible = any(v["open_rate"] is not None and v["open_rate"] >= 0.15
                             for v in funnel.values())
        return self._json(200, {"days": days, "funnel": funnel,
                                "organic_opens": opens.get("organic", 0),
                                "share_opens": opens.get("share", 0),
                                "badge_bar_15pct_any": badge_eligible})

    def _handle_deadlines(self):
        """ENGINE-65 GET /api/settlements/deadlines — aggregate-only
        (SR-RV-A1, same posture as /api/funnel): counts + per-bill timeout
        masks; wallet addresses NEVER appear in the payload."""
        now = int(time.time())
        db = get_db()
        one = lambda q, *a: db.execute(q, a).fetchone()["c"] if a else db.execute(q).fetchone()["c"]  # noqa: E731
        bills = [{"bill": r["bill_id"], "settlement": int(r["settlement_id"]),
                  "past_due": 1 if r["max_hold_until"] < now else 0,
                  "escalated": r["escalated"], "refunded": r["refunded_seen"]}
                 for r in db.execute(
                     "SELECT bill_id, settlement_id, max_hold_until, escalated,"
                     " refunded_seen FROM settlement_deadlines"
                     " ORDER BY max_hold_until LIMIT 50")]
        return self._json(200, {
            "total_tracked": one("SELECT count(*) c FROM settlement_deadlines"),
            "open": one("SELECT count(*) c FROM settlement_deadlines d WHERE"
                        " d.refunded_seen=0 AND EXISTS (SELECT 1 FROM settlements s"
                        " WHERE s.bill_id=d.bill_id AND s.settlement_id=d.settlement_id"
                        " AND s.settled_at IS NULL)"),
            "past_max_hold": one("SELECT count(*) c FROM settlement_deadlines"
                                 " WHERE max_hold_until < ?", now),
            "escalated": one("SELECT count(*) c FROM settlement_deadlines"
                             " WHERE escalated=1"),
            "refunded_seen": one("SELECT count(*) c FROM settlement_deadlines"
                                 " WHERE refunded_seen=1"),
            "bills": bills})

    def do_GET(self):
        if self.path.startswith("/api/funnel"):
            return self._handle_funnel()
        if self.path == "/health":
            return self._handle_health()
        if self.path.startswith("/api/grants"):
            # M4-1a (t_3aed711f, Flux GO 2026-11-20): auth-free bill-scoped
            # grants READ view - same SR-RV-A1 posture as /api/settlements.
            # The keyed /grants lane (write + authenticated read) is untouched.
            qs = self.path.split("?", 1)[1] if "?" in self.path else ""
            bill = dict(p.split("=", 1) for p in qs.split("&") if "=" in p).get("bill", "").lower()
            if not ADDR_RE.match(bill):
                return self._json(400, {"error": "bad bill"})
            db = get_db()
            rows = db.execute("SELECT wallet_address, nullifier, verified_at FROM seat_grants WHERE bill_address=?", (bill,)).fetchall()
            return self._json(200, {"grants": {r["wallet_address"]: {"nullifier": r["nullifier"], "verified_at": r["verified_at"]} for r in rows}})
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
        if self.path.startswith("/api/settlements/deadlines"):
            return self._handle_deadlines()
        if self.path.startswith("/api/settlements"):
            # M4-2 / issue #19 SR-RV-A1 (t_m4_p01a): canonical query-form read
            # GET /api/settlements?bill=0x<addr>&page=<n> — auth-free local
            # read (same posture as /health), paginated (page_size=20).
            # Malformed page/address -> 400; bill with no rows -> [] (200).
            qs = self.path.split("?", 1)[1] if "?" in self.path else ""
            qp = dict(p.split("=", 1) for p in qs.split("&") if "=" in p)
            bill = qp.get("bill", "").lower()
            if not ADDR_RE.match(bill):
                return self._json(400, {"error": "bad bill"})
            page = qp.get("page", "1")
            if not re.fullmatch(r"[1-9][0-9]*", page):
                return self._json(400, {"error": "bad page"})
            pno = int(page)
            off = (pno - 1) * SETTLEMENTS_PAGE_SIZE
            db = get_db()
            # OVERLAY-1: compare against the FULL bill summary set (not the
            # page window) — chain truth is window-independent; page slice is
            # derived in Python from the same read (kills the COUNT(*) leg).
            full = [dict(r) for r in db.execute(
                "SELECT * FROM settlements WHERE lower(bill_id)=? ORDER BY settlement_id",
                (bill,))]
            srows = full[off:off + SETTLEMENTS_PAGE_SIZE]
            erows = [dict(r) for r in db.execute(
                "SELECT settlement_id, event, tx_hash, log_index, block, seat_id,"
                " wallet, amount, at_ts, recorded_at FROM settlement_events"
                " WHERE lower(bill_id)=? ORDER BY block, log_index LIMIT ? OFFSET ?",
                (bill, SETTLEMENTS_PAGE_SIZE, off))]
            out = self._apply_overlay(db, bill, full, {
                "bill": bill, "page": pno, "page_size": SETTLEMENTS_PAGE_SIZE,
                "total_settlements": len(full),
                "total_events": db.execute(
                    "SELECT COUNT(*) FROM settlement_events WHERE lower(bill_id)=?", (bill,)).fetchone()[0],
                "settlements": srows, "events": erows,
            })
            return self._json(200, out)
        if self.path.startswith("/settlements/"):
            # SR-003 F12 (t_m4_p01a): per-bill lifecycle readout — summary rows
            # (additive parity cols) + append-only event ledger. W2.5-2: plus
            # per-seat SeatClaimed state (P0.1a pull-claim mirror). Auth-free
            # and local-only, same posture as /health.
            bill = self.path.split("?", 1)[0].split("/")[-1].lower()
            if not ADDR_RE.match(bill):
                return self._json(400, {"error": "bad bill"})
            db = get_db()
            rows = [dict(r) for r in db.execute(
                "SELECT * FROM settlements WHERE lower(bill_id)=? ORDER BY settlement_id",
                (bill,))]
            events = [dict(e) for e in db.execute(
                "SELECT settlement_id, event, tx_hash, log_index, block, block_hash,"
                " seat_id, wallet, amount, at_ts, recorded_at FROM settlement_events"
                " WHERE bill_id=? ORDER BY block, log_index", (bill,))]
            claims = [dict(c) for c in db.execute(
                "SELECT settlement_id, seat_id, wallet, amount, tx_hash, log_index,"
                " block, claimed_at FROM seat_claims WHERE bill_id=?"
                " ORDER BY settlement_id, seat_id", (bill,))]
            out = self._apply_overlay(db, bill, rows, {"bill": bill, "settlements": rows,
                                                       "events": events, "claims": claims})
            return self._json(200, out)
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
    # SR-003 F12 parity probe (t_m4_p01a): synthetic full lifecycle (Initiated,
    # 2x SeatConfirmed, FullyConfirmed, Executed, 2x SeatPayoutClaimed) on a
    # fresh probe bill, ingested TWICE through the shared watcher to pin the
    # rowcount-guard: replay must add zero ledger rows and zero summary deltas.
    pbill, ptx = "0x" + os.urandom(20).hex(), "0x" + os.urandom(32).hex()
    db.execute("INSERT OR IGNORE INTO bill_index (user_op_hash, bill_address, creator)"
               " VALUES (?,?,?)", ("0x" + os.urandom(32).hex(), pbill, "selftest"))
    _w = lambda i: hex(i)[2:].rjust(64, "0")
    n2t = {v: k for k, v in SETTLEMENT_TOPICS.items()}
    logs = [
        {"address": pbill, "topics": [n2t["SettlementInitiated"], "0x7"],
         "data": "0x" + _w(1500000) + _w(3), "logIndex": "0x0"},
        {"address": pbill, "topics": [n2t["SeatConfirmed"], "0x7", "0x1"], "logIndex": "0x1"},
        {"address": pbill, "topics": [n2t["SeatConfirmed"], "0x7", "0x2"], "logIndex": "0x2"},
        {"address": pbill, "topics": [n2t["SettlementFullyConfirmed"], "0x7"],
         "data": "0x" + _w(1700000000), "logIndex": "0x3"},
        {"address": pbill, "topics": [n2t["SeatPayoutClaimed"], "0x7", "0x1", "0x" + "11" * 20],
         "data": "0x" + _w(500000), "logIndex": "0x4"},
        {"address": pbill, "topics": [n2t["SettlementExecuted"], "0x7"],
         "data": "0x" + _w(1500000) + _w(1700000100), "logIndex": "0x5"},
        {"address": pbill, "topics": [n2t["SeatPayoutClaimed"], "0x7", "0x2", "0x" + "22" * 20],
         "data": "0x" + _w(500000), "logIndex": "0x6"},
    ]
    known_p = {pbill.lower()}
    got = _ingest_settlement_logs(db, logs, known_p, ptx, 999)
    assert got == (7, 1), f"parity pass1 expected (7,1), got {got}"
    got2 = _ingest_settlement_logs(db, logs, known_p, ptx, 999)
    assert got2 == (0, 0), f"parity replay expected (0,0), got {got2}"
    s = db.execute("SELECT claimed_count, claimed_amount, refunded, total_amount,"
                   " fully_confirmed_at, settled_at, initiated_block"
                   " FROM settlements WHERE bill_id=?", (pbill,)).fetchone()
    assert s["claimed_count"] == 2 and s["claimed_amount"] == 1000000 \
        and s["total_amount"] == 1500000 and s["settled_at"] == 1700000100 \
        and s["fully_confirmed_at"] == 1700000000 and s["initiated_block"] == 999, dict(s)
    e = db.execute("SELECT amount, wallet FROM settlement_events WHERE event="
                   "'SeatPayoutClaimed' AND seat_id=2").fetchone()
    assert e["amount"] == 500000 and e["wallet"] == "0x" + "22" * 20, dict(e)
    # W2.5-2 probes (offline): per-seat SeatClaimed mirror + checkpoint KV.
    sc = db.execute("SELECT seat_id, wallet FROM seat_claims WHERE bill_id=?"
                    " ORDER BY seat_id", (pbill,)).fetchall()
    assert [dict(r) for r in sc] == [{"seat_id": 1, "wallet": "0x" + "11" * 20},
                                     {"seat_id": 2, "wallet": "0x" + "22" * 20}], [dict(r) for r in sc]
    assert db.execute("SELECT COUNT(*) FROM seat_claims WHERE bill_id=?",
                      (pbill,)).fetchone()[0] == 2, "claim replay must not duplicate seats"
    _meta_set(db, "selftest_probe", "x")
    assert _meta_get(db, "selftest_probe") == "x"
    db.execute("DELETE FROM indexer_state WHERE key='selftest_probe'")
    db.commit()
    db.execute("DELETE FROM settlement_events WHERE bill_id=?", (pbill,))
    db.execute("DELETE FROM settlements WHERE bill_id=?", (pbill,))
    db.execute("DELETE FROM seat_claims WHERE bill_id=?", (pbill,))
    db.execute("DELETE FROM bill_index WHERE bill_address=?", (pbill,))
    db.commit()
    assert db.execute("SELECT COUNT(*) FROM settlement_events WHERE bill_id=?",
                      (pbill,)).fetchone()[0] == 0
    assert db.execute("SELECT COUNT(*) FROM seat_claims WHERE bill_id=?",
                      (pbill,)).fetchone()[0] == 0
    # OVERLAY-1 offline probes (t_cead034d): selector table sanity + Settlement
    # struct decode vector built against the exact TandaBillV2.sol:56-67 layout
    # (9 head words, payouts tail at offset 9*32, mask 0b101 -> popcount 2).
    _verify_overlay_selectors()
    _vec = (_w(1500000) + _w(9 * 32) + _w(1700000100) + _w(1700000000)
            + _w(0b111) + _w(0b111) + _w(0b101) + _w(1700000050) + _w(0)
            + _w(3) + _w(500000) + _w(600000) + _w(900000))
    _d0 = _decode_settlement_ret("0x" + _vec)
    assert _d0 is not None, "vector head must decode"
    assert _d0["total_amount"] == 1500000 and _d0["settled_at"] == 1700000100 \
        and _d0["initiated_at"] == 1700000000 and _d0["expected_mask"] == 0b111 \
        and _d0["claimed_mask"] == 0b101 and _d0["claimed_mask"].bit_count() == 2 \
        and _d0["fully_confirmed_at"] == 1700000050 and _d0["refunded"] is False \
        and _d0["payouts"] == [500000, 600000, 900000], _d0
    assert _decode_settlement_ret("0x" + _vec[:8 * 64]) is None, "short head must reject"
    print("SELF_TEST PASS: decode matches DEPLOY_RECEIPT_V2 smoke bill byte-exact; "
          "storage OK; tx-lane 201 INSERT prepares with 5/5 bindings; "
          "SR-003 F12 lifecycle parity + replay idempotency OK; "
          "W2.5-2 seat_claims mirror + indexer_state checkpoint OK (probe rows cleaned); "
          "OVERLAY-1 selector table + Settlement struct decode vector OK")
    return d


if __name__ == "__main__":
    import sys
    if "--self-test" in sys.argv:
        self_test()
    elif "--scan-once" in sys.argv:
        # W2.5-2: single hardened pass (restart-from-checkpoint entrypoint).
        # Stdout = exactly one JSON summary line (machine-checked by tests/ops).
        print(json.dumps(scan_pass(get_db())))
    else:
        get_db()
        PORT = int(__import__("os").environ.get("BILL_INDEX_PORT", "8096"))  # W10: match miniapp BILL_INDEX_URL default; 8091 was drift-bait
        srv = ThreadingHTTPServer(("127.0.0.1", PORT), Handler)
        if os.environ.get("BILL_INDEX_WATCH") == "1":
            threading.Thread(target=watch_loop, kwargs={"stop": WATCH_STOP},
                             daemon=True, name="bill-index-watch").start()
        print(f"bill_index service on http://127.0.0.1:{PORT} "
              f"(GET /health, POST /bills, GET /bills/by-userop/{'{hash}'}, "
              f"watch={'on' if os.environ.get('BILL_INDEX_WATCH') == '1' else 'off'})")
        srv.serve_forever()
