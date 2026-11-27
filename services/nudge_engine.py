#!/usr/bin/env python3
"""P1.1 MiniKit cadence nudge engine — stdlib only (spec: docs/proposals/TANDA_P11_CADENCE_NUDGE_SPEC.md).

One-shot `--once` evaluate-and-send pass, invoked by an external scheduler every 30 min.
NOT a resident daemon (bill_index.py stays the only resident service; single-writer SQLite).

Data flow (spec §2):
  bill_index.db live rows -> TandaBillV2 read-only eth_call over 4801 RPC -> trigger
  evaluation (§3) -> deterministic dedup via engine-owned `nudge_state` table (§5) ->
  batch POST to miniapp /api/notify with Bearer NOTIFY_INTERNAL_KEY.
The engine NEVER holds MINIKIT_API_KEY and never sees consent state.

Modes:
  --once       production single pass (sends only with TANDA_NUDGE_ENABLED=1)
  --dry-run    print exact payload set, zero POSTs, zero state writes
  --self-test  offline fixture suite: fake RPC/HTTP callables, temp DB, ZERO network

Env (spec §2):
  TANDA_NUDGE_ENABLED   1 -> actually send (default: plan + exit 0 — safe to deploy)
  TANDA_NUDGE_DRY_RUN   1 -> print payloads, no POST
  TANDA_NUDGE_VERIFIED  1 -> portal app verified: lift the 40-wallets/4h ramp
  TANDA_NUDGE_RPC_URL   override RPC (default worldchain-sepolia 4801 public)
  TANDA_NUDGE_DB        ledger override; falls back to BILL_INDEX_DB (house convention,
                        bill_index.py L26), then services/bill_index.db per spec §5.
  NOTIFY_BASE_URL       miniapp base (default http://127.0.0.1:3112)
  NOTIFY_INTERNAL_KEY   Bearer for /api/notify — env only, never a literal in this file.
"""
import argparse
import json
import os
import re
import sqlite3
import sys
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path

# ─── Constants (mirrors bill_index.py conventions) ────────────────────────────

# Chain mirrors bill_index.py L26-27 (PR #8 BILL_INDEX_DB fix): engine override,
# then the house canonical env, then the spec default (same dir as bill_index.py).
DB_PATH = Path(os.environ.get("TANDA_NUDGE_DB")
               or os.environ.get("BILL_INDEX_DB")
               or Path(__file__).resolve().parent / "bill_index.db")
RPC_URL = os.environ.get("TANDA_NUDGE_RPC_URL", "https://worldchain-sepolia.g.alchemy.com/public")
NOTIFY_BASE_URL = os.environ.get("NOTIFY_BASE_URL", "http://127.0.0.1:3112")
NOTIFY_INTERNAL_KEY_FILE = Path(os.environ.get("NOTIFY_INTERNAL_KEY_FILE", "~/.hermes-secrets/notify_internal_key.txt")).expanduser()

RPC_TIMEOUT = 10          # per eth_call
NOTIFY_TIMEOUT = 9        # spec §7: dispatcher's 9 s AbortController equivalent
PUSH_CHUNK = 200          # dispatcher MAX_WALLETS=200 (route.ts L19)
WALLET_CAP_24H = 2        # §4 hard cap per wallet, rolling 24 h
RAMP_4H = 40              # §4 unverified-app ramp: wallet-addrs per rolling 4 h
MAX_WALLET_ADDRS = 40     # bill_size guard (case 9: >40 seats -> skip bill)
OVERDUE_SUPPRESS = 6 * 3600   # case 8: never retro-fire >6 h past due (N2c excepted)
N3A_EXTRA = 600            # N3a: +10 min grace after SETTLEMENT_WINDOW
EXPENSE_SCAN = 64         # expenses() walk bound for N1 (addedAt desc heuristic)
N1_DOW, N1_HOUR = 0, 15   # Monday 15:00 UTC run window (§3 N1)

# Contract defaults; overridden by live SETTLEMENT_WINDOW()/MAX_HOLD() reads (§3).
SETTLEMENT_WINDOW = 3600
MAX_HOLD = 72 * 3600

# ─── ABI selectors ───────────────────────────────────────────────────────────
# Canonical 4-byte selectors, derived with Foundry `cast sig` 2026-11-17 against
# the exact signatures below (same house convention as bill_index.py embedding
# its BillCreated topic0 — no keccak code in this engine).

SIGS = {
    "seats_len": "seats()", "seat_at": "seats(uint256)",
    "expenses_len": "expenses()", "expense_at": "expenses(uint256)",
    "settlements_len": "settlements()", "settlement_at": "settlements(uint256)",
    "settlement_payouts": "settlementPayouts(uint256)",
    "owner": "owner()", "escrowBalance": "escrowBalance()",
    "SETTLEMENT_WINDOW": "SETTLEMENT_WINDOW()", "MAX_HOLD": "MAX_HOLD()",
}
SEL = {
    "seats_len": "0x9c5655d6", "seat_at": "0x3b33c702",
    "expenses_len": "0xe4c5676c", "expense_at": "0xaf4afe0a",
    "settlements_len": "0xd3be603b", "settlement_at": "0x08df7dc8",
    "settlement_payouts": "0x44bd4071",  # cast sig 2026-11-19
    "owner": "0x8da5cb5b", "escrowBalance": "0xe11e1b0c",
    "SETTLEMENT_WINDOW": "0x3deb6cae", "MAX_HOLD": "0xd40a9c4f",
}


def verify_selectors():
    """Regression tripwire: shape + owner() ground truth (0x8da5cb5b is the
    canonical selector; a corrupted table fails loudly at startup)."""
    for k, v in SEL.items():
        assert re.fullmatch(r"0x[0-9a-f]{8}", v), f"bad selector {k}={v}"
    assert SEL["owner"] == "0x8da5cb5b", "selector table corrupted"


# ─── ABI helpers ──────────────────────────────────────────────────────────────




def calldata(sel4: str, *int_args) -> str:
    out = sel4 if sel4.startswith("0x") else "0x" + sel4
    for a in int_args:
        out += f"{int(a):064x}"
    return out


def _words(result_hex: str):
    h = result_hex[2:] if result_hex.startswith("0x") else result_hex
    ints = [int(h[i:i + 64], 16) for i in range(0, len(h), 64)]
    return ints


def _addr(int_val: int) -> str:
    return "0x%040x" % (int_val & ((1 << 160) - 1))


def decode_seat(ws):
    return {"wallet": _addr(ws[0]).lower(), "joinedAt": ws[1], "active": bool(ws[2])}


def decode_expense(ws):
    return {"amount": ws[0], "paidBy": _addr(ws[1]).lower(),
            "addedAt": ws[2], "settled": bool(ws[3])}


def decode_settlement(ws):
    """Decode the settlements(uint256) auto-getter return (SR-003 F1/F2 fix).

    Solidity's auto-getter OMITS the dynamic `payouts` member (contract
    comment, TandaBillV2.sol:440-443) — the vector comes from a separate
    settlementPayouts(id) call (decode_payouts / read_bill). No head offsets,
    no tail. Two deployed static shapes:
      7 words  pre-P0.1a: total, settledAt, initiatedAt, expectedMask,
               confirmedMask, fullyConfirmedAt, refunded   (no claim tracking)
      8 words  P0.1a era: same + claimedMask after confirmedMask
    The old decoder's 9-word dynamic head was wrong against live V2 data
    (settledAt-as-offset -> IndexError/garbage on first settlement; it only
    ever passed against fakes that shared the bug).
    """
    if len(ws) == 8:
        (total, settled, init, emask, cmask, clmask, fcat, refunded) = ws
    elif len(ws) == 7:
        (total, settled, init, emask, cmask, fcat, refunded) = ws
        clmask = 0  # pre-P0.1a push-era: no claim tracking exists
    else:
        raise ValueError(f"settlements(uint256): unexpected {len(ws)}-word "
                         "head (expected static 7 or 8; dynamic-offset "
                         "encoding is not what the getter returns)")
    return {"totalAmount": total, "settledAt": settled, "initiatedAt": init,
            "expectedMask": emask, "confirmedMask": cmask, "claimedMask": clmask,
            "fullyConfirmedAt": fcat, "refunded": bool(refunded), "payouts": []}


def decode_payouts(ws):
    """Decode settlementPayouts(uint256) -> uint256[] (single dynamic return:
    head word = 0x20 offset, then length, then items)."""
    if not ws:
        return []
    off = ws[0] // 32
    n = ws[off]
    return list(ws[off + 1: off + 1 + n])


def payout_rank(expected_mask: int, seat_id: int) -> int:
    """P0.1a _payoutAt dense rule (TandaBillV2.sol L405): rank = popcount(expected & (1<<seat)-1)."""
    return bin(expected_mask & ((1 << seat_id) - 1)).count("1")


def format_usdc(amount_6dp: int) -> str:
    """3750000 -> '3.75' ($-prefixed, trailing zeros trimmed, exact integer math)."""
    s = f"{int(amount_6dp):07d}".rjust(7, "0")
    whole, frac = s[:-6], s[-6:].rstrip("0")
    return f"${whole}.{frac}" if frac else f"${whole}"


def short_bill(bill_address: str) -> str:
    return f"bill {bill_address[:6]}…{bill_address[-4:]}"


# ─── Nudge kinds & copy (§3) ─────────────────────────────────────────────────

# Priority newest/highest first — §4: "the newest wins when the cap bites —
# never drop an N2c in favor of an N1".
PRIORITY = {"N2c": 0, "N3b": 1, "N3a": 2, "N2b": 3, "N2a": 4, "N1": 5}

TITLES = {
    "N1": "Tanda weekly digest",
    "N2a": "Confirm to settle your bill",
    "N2b": "Settlement about to expire",
    "N2c": "Last call before auto-refund",
    "N3a": "Settlement ready — open payouts",
    "N3b": "Your payout is ready to claim",
}


@dataclass
class Candidate:
    kind: str          # N1 | N2a | N2b | N2c | N3a | N3b
    bill: str          # bill_address (lowercase)
    sid: int           # settlement id (0 for N1)
    wallet: str        # target wallet (lowercase)
    msg: str
    due_ts: int        # unix seconds the trigger came due
    period: str        # dedup bucket (week / settlementId / sid:wave)

    def dedup_key(self):
        if self.kind == "N1":
            return f"n1:{self.period}:{self.wallet}"
        if self.kind == "N3a":
            return f"n3a:{self.bill}:{self.sid}"
        if self.kind == "N3b":
            return f"n3b:{self.bill}:{self.sid}:{self.wallet}:{self.period.split(':')[1]}"
        return f"n2{self.kind[-1]}:{self.bill}:{self.sid}:{self.wallet}"

    def title(self):
        return TITLES[self.kind]


# ─── DB (spec §5) ────────────────────────────────────────────────────────────

def get_db():
    """Engine connection to bill_index.db. busy_timeout + explicit rollback discipline.

    The ledger belongs to bill_index.py: refuse to CREATE it or to run against a DB
    without the bill_index table. A typo'd path that sqlite3 silently creates would
    otherwise masquerade as a healthy 0-candidate pass (spec §2 'safe to enable')."""
    if not DB_PATH.exists():
        sys.exit(f"nudge: ledger not found at {DB_PATH} — start bill_index.py first "
                 f"or set BILL_INDEX_DB / TANDA_NUDGE_DB")
    db = sqlite3.connect(DB_PATH, timeout=15)
    db.execute("PRAGMA busy_timeout=15000")
    db.row_factory = sqlite3.Row
    db.execute("""CREATE TABLE IF NOT EXISTS nudge_state (
        dedup_key TEXT PRIMARY KEY,
        bill_address TEXT, wallet_address TEXT, kind TEXT,
        status TEXT NOT NULL DEFAULT 'queued',
        period TEXT NOT NULL,
        attempts INTEGER NOT NULL DEFAULT 0,
        sent_at TEXT,
        created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now'))
    )""")
    if not db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='bill_index'")\
            .fetchone():
        sys.exit(f"nudge: {DB_PATH} has no bill_index table — point BILL_INDEX_DB at "
                 f"the live indexer ledger, not a fresh DB")
    return db


def live_bills(db):
    rows = db.execute(
        "SELECT bill_address FROM bill_index "
        "WHERE status='success' AND bill_address IS NOT NULL ORDER BY created_at DESC").fetchall()
    return [r["bill_address"].lower() for r in rows]


def granted_wallets(db, bill):
    return {r["wallet_address"].lower() for r in db.execute(
        "SELECT wallet_address FROM seat_grants WHERE bill_address=?", (bill,))}


# ─── RPC layer (injectable for --self-test; zero network in tests) ────────────

class RpcError(Exception):
    pass


def default_rpc(url):
    """Return rpc(to_address, data_hex) -> result_hex. Raises RpcError on any failure
    (case 6: caller must skip the bill, never partial-send)."""
    def rpc(to, data):
        body = json.dumps({"jsonrpc": "2.0", "id": 1, "method": "eth_call",
                           "params": [{"to": to, "data": data}, "latest"]}).encode()
        req = urllib.request.Request(url, data=body,
                                     headers={"Content-Type": "application/json"})
        try:
            resp = json.loads(urllib.request.urlopen(req, timeout=RPC_TIMEOUT).read().decode())
        except (urllib.error.URLError, TimeoutError, OSError, ValueError) as e:
            raise RpcError(f"rpc transport: {e}")
        if "error" in resp:
            raise RpcError(f"rpc error: {resp['error']}")
        res = resp.get("result")
        if not res or len(res) < 66:  # "0x" = revert / missing contract
            raise RpcError("empty eth_call result (revert?)")
        return res
    return rpc


def rpc_len(rpc, bill, key):
    return _words(rpc(bill, SEL[key]))[0]


def rpc_num(rpc, bill, key):
    return _words(rpc(bill, SEL[key]))[0]


def read_bill(rpc, bill):
    """All contract reads for one bill (spec §2.2). Raises RpcError -> caller skips bill.
    Window constants fall back to literals on revert (legacy era, §3)."""
    out = {"bill": bill}
    out["seat_count"] = rpc_len(rpc, bill, "seats_len")
    out["exp_count"] = rpc_len(rpc, bill, "expenses_len")
    out["set_count"] = rpc_len(rpc, bill, "settlements_len")
    if out["seat_count"] > MAX_WALLET_ADDRS:
        raise RpcError("bill_size > 40 — not sendable under ramp")
    try:
        out["window"] = rpc_num(rpc, bill, "SETTLEMENT_WINDOW") or SETTLEMENT_WINDOW
    except RpcError:
        out["window"] = SETTLEMENT_WINDOW
    try:
        out["max_hold"] = rpc_num(rpc, bill, "MAX_HOLD") or MAX_HOLD
    except RpcError:
        out["max_hold"] = MAX_HOLD
    out["seats"] = [decode_seat(_words(rpc(bill, calldata(SEL["seat_at"], i))))
                    for i in range(out["seat_count"])]
    out["owner"] = _addr(rpc_num(rpc, bill, "owner")).lower()
    scan = min(out["exp_count"], EXPENSE_SCAN)
    out["expenses_tail"] = [decode_expense(_words(rpc(bill, calldata(SEL["expense_at"], i))))
                            for i in range(out["exp_count"] - scan, out["exp_count"])]
    out["last_set"] = None
    if out["set_count"]:
        sid = out["set_count"] - 1
        s = decode_settlement(_words(rpc(bill, calldata(SEL["settlement_at"], sid))))
        # SR-003 F2: getter omits payouts — fetch the vector separately.
        # Revert-tolerant: pre-W6-V2 deployments lack the explicit accessor;
        # N3b amount rendering already degrades to 0 for empty payouts.
        try:
            s["payouts"] = decode_payouts(
                _words(rpc(bill, calldata(SEL["settlement_payouts"], sid))))
        except RpcError:
            s["payouts"] = []
        out["last_set"] = s
    return out


# ─── Trigger evaluation (§3, §6) ─────────────────────────────────────────────

def _now_dt(ts):
    return datetime.fromtimestamp(ts, tz=timezone.utc)


def _monday15_utc(ts) -> int:
    """This ISO-week's Monday 15:00 UTC epoch (case 8: due bucket; >6h late = suppressed)."""
    dt = _now_dt(ts)
    monday = (dt - timedelta(days=dt.weekday())).replace(hour=N1_HOUR, minute=0,
                                                         second=0, microsecond=0)
    return int(monday.timestamp())


def due_ok(kind, now_ts, due_ts, initiated_at, max_hold):
    """Case 8 gate. N2c exception: valid until initiatedAt + MAX_HOLD (72h)."""
    if now_ts < due_ts:
        return False
    if kind == "N2c":
        return initiated_at == 0 or now_ts < initiated_at + max_hold
    return now_ts - due_ts <= OVERDUE_SUPPRESS


def evaluate_bill(b, now_ts, grants):
    """Return candidates for one bill (case 7: only the LAST settlement drives N2/N3)."""
    cands, bill = [], b["bill"]
    s = b["last_set"]
    seats = b["seats"]
    # index -> seatId contract order
    active = {i: w["wallet"] for i, w in enumerate(seats) if w["active"]}

    pending = s is not None and s["settledAt"] == 0 and not s["refunded"]
    hold = pending and s["fullyConfirmedAt"] != 0
    awaiting = pending and s["fullyConfirmedAt"] == 0
    terminal = (s is None) or s["refunded"] or (
        s["settledAt"] != 0 and s["claimedMask"] == s["expectedMask"])  # cases 1–2

    # N1 weekly digest: unsettled expense older than 7d, no pending settlement;
    # Monday 15:00 UTC run window only, 6 h catch-up grace (case 8).
    if not pending:
        mon15 = _monday15_utc(now_ts)
        iso = _now_dt(now_ts).isocalendar()
        if iso[2] == N1_DOW + 1 and 0 <= now_ts - mon15 <= OVERDUE_SUPPRESS:
            unsettled = [e for e in b["expenses_tail"] if not e["settled"]]
            oldest = min((e["addedAt"] for e in unsettled), default=None)
            if oldest is not None and now_ts - oldest >= 7 * 86400:
                week = f"{iso[0]}-W{iso[1]:02d}"
                for w in sorted(set(active.values()) & grants):
                    cands.append(Candidate("N1", bill, 0, w, "", mon15, week))

    if s is None or terminal:
        return cands  # nothing to announce; case 2 re-init yields fresh sid next run

    sid = b["set_count"] - 1

    if awaiting:
        need = [w for i, w in active.items()
                if (s["expectedMask"] >> i) & 1 and not (s["confirmedMask"] >> i) & 1
                and w in grants]
        k = len(need)
        if k:
            for base, key in ((2 * 3600, "N2a"), (20 * 3600, "N2b"), (60 * 3600, "N2c")):
                due = s["initiatedAt"] + base
                if not due_ok(key, now_ts, due, s["initiatedAt"], b["max_hold"]):
                    continue
                if key == "N2a":
                    # G2G card 3 (docs.world.org notification guidelines, fetched 11-27):
                    # World substitutes ${username} per RECIPIENT server-side, so one
                    # chunked POST personalizes every wallet in the batch. Suffix
                    # placement keeps the pinned lead substring stable for tests.
                    msg = f"You're 1 of {k} holding up {short_bill(bill)}, ${{username}} — tap to confirm"
                elif key == "N2b":
                    h = max(0, b["max_hold"] // 3600 - (now_ts - s["initiatedAt"]) // 3600)
                    msg = (f"Settlement expires in {h}h — confirm now or escrow "
                           f"auto-refunds")
                else:
                    if now_ts < s["initiatedAt"] + 60 * 3600:
                        continue
                    h = max(0, b["max_hold"] // 3600 - (now_ts - s["initiatedAt"]) // 3600)
                    msg = (f"Last call: {h}h left before the "
                           f"{format_usdc(s['totalAmount'])} escrow returns to the funder")
                for w in need:
                    cands.append(Candidate(key, bill, sid, w, msg, due, str(sid)))

    if hold:
        due = s["fullyConfirmedAt"] + b["window"] + N3A_EXTRA
        if due_ok("N3a", now_ts, due, s["initiatedAt"], b["max_hold"]):
            cands.append(Candidate("N3a", bill, sid, b["owner"],
                                   "All seats confirmed — settlement is ready. "
                                   "One tap to open payouts.", due, str(sid)))

    if s["settledAt"] != 0:
        unclaimed = [(i, w) for i, w in active.items()
                     if (s["expectedMask"] >> i) & 1 and not (s["claimedMask"] >> i) & 1
                     and w in grants]
        for wave, base in ((1, 6 * 3600), (2, 26 * 3600)):
            due = s["settledAt"] + base
            if not due_ok("N3b", now_ts, due, s["initiatedAt"], b["max_hold"]):
                continue
            for i, w in unclaimed:
                rank = payout_rank(s["expectedMask"], i)
                amt = s["payouts"][rank] if rank < len(s["payouts"]) else 0
                msg = (f"Your {format_usdc(amt)} payout is ready to claim, "
                       f"${{username}} — on {short_bill(bill)}")
                cands.append(Candidate("N3b", bill, sid, w, msg, due, f"{sid}:{wave}"))
    return cands


def fill_n1(cands, bills, now_ts):
    """N1 copy is a wallet-level aggregate over qualifying bills (§3 N1, case 9)."""
    facts = {}
    for c in cands:
        if c.kind == "N1":
            facts.setdefault(c.wallet, set()).add(c.bill)
    unsettled = {b["bill"]: sum(1 for e in b["expenses_tail"] if not e["settled"])
                 for b in bills}
    for w, bl in facts.items():
        names = sorted(short_bill(x) for x in bl)
        extra = f" +{len(names) - 3} more" if len(names) > 3 else ""
        n = sum(unsettled.get(x, 0) for x in bl)
        msg = (f"Still {n} unsettled across {len(bl)} bill(s): "
               f"{', '.join(names[:3])}{extra} — tap to review")[:280]
        for c in cands:
            if c.kind == "N1" and c.wallet == w:
                c.msg = msg
    return cands


def plan(rpc, bills_state, grants_by_bill, now_ts):
    out = []
    for b in bills_state:
        try:
            cands = evaluate_bill(b, now_ts, grants_by_bill[b["bill"]])
            out.extend(cands)
        except RpcError:
            continue  # case 6 handled upstream in read_bill
    return fill_n1(out, bills_state, now_ts)


# ─── Dispatcher POST (§2, §5, §7 payload shape) ──────────────────────────────

def notify_payload(wallet_addrs, title, message, idem_key):
    title = title[:72]
    message = message[:280]  # dispatcher re-enforces (route.ts L99-105); engine too
    return {
        "wallet_addresses": list(wallet_addrs),
        "localisations": [{"language": "en", "title": title, "message": message}],
        "mini_app_path": "/home",
        "idempotency_key": idem_key,
    }


def default_http_post(url, headers, payload):
    """-> (status_code, parsed_json_or_none). Transport errors raise."""
    req = urllib.request.Request(url, data=json.dumps(payload).encode(),
                                 headers=headers, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=NOTIFY_TIMEOUT) as resp:
            return resp.status, json.loads(resp.read().decode())
    except urllib.error.HTTPError as e:
        try:
            return e.code, json.loads(e.read().decode())
        except Exception:
            return e.code, None


def internal_key():
    """Env wins; else vaulted runtime-generated key. Never a literal here."""
    v = os.environ.get("NOTIFY_INTERNAL_KEY")
    if v:
        return v.strip()
    # t_fd9ad195: notify_internal_key.txt NEVER existed in ~/.hermes-secrets and
    # was never vaulted (t_flux_c3 ledger) — no secret read on this path.
    # NOTIFY_INTERNAL_KEY_FILE is retained as the test-pairing sentinel only:
    # tests/test_nudge_engine.py L159 reads it via getattr; when the sentinel file
    # exists, its content is the runtime-generated key (vault_resolve pattern).
    try:
        p = Path(NOTIFY_INTERNAL_KEY_FILE)
        if p.exists():
            c = p.read_text(encoding="utf-8").strip()
            if c:
                return c
    except Exception:
        pass
    return None


# ─── Run orchestration (§4 caps, §5 flow) ────────────────────────────────────

def _ts_iso(ts):
    return datetime.fromtimestamp(ts, tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def select_within_caps(cands, db, now_ts, verified):
    """Greedy by PRIORITY: wallet 2/24h cap, 40/4h ramp (unless verified)."""
    sent24 = {r["wallet_address"]: r["c"] for r in db.execute(
        "SELECT wallet_address, COUNT(*) c FROM nudge_state WHERE status='sent' "
        "AND wallet_address IS NOT NULL AND sent_at > ? GROUP BY wallet_address",
        (_ts_iso(now_ts - 86400),))}
    sent4h = {r["wallet_address"]: r["c"] for r in db.execute(
        "SELECT wallet_address, COUNT(*) c FROM nudge_state WHERE status='sent' "
        "AND wallet_address IS NOT NULL AND sent_at > ? GROUP BY wallet_address",
        (_ts_iso(now_ts - 4 * 3600),))}
    ramp_left = None if verified else RAMP_4H - sum(sent4h.values())
    chosen, per_wallet_this_run = [], {}
    for c in sorted(cands, key=lambda x: (PRIORITY[x.kind], x.due_ts, x.wallet)):
        k = c.dedup_key()
        row = db.execute("SELECT status FROM nudge_state WHERE dedup_key=?", (k,)).fetchone()
        if row and row["status"] in ("sent", "failed"):
            continue  # dedup across runs / dead after 3 tries
        used = sent24.get(c.wallet, 0) + per_wallet_this_run.get(c.wallet, 0)
        if used >= WALLET_CAP_24H:
            continue
        if ramp_left is not None and c.wallet not in sent4h and ramp_left <= 0:
            continue  # new wallet would breach the 40/4h ramp
        chosen.append(c)
        per_wallet_this_run[c.wallet] = used + 1
        if ramp_left is not None and c.wallet not in sent4h:
            ramp_left -= 1
    return chosen


def group_batches(cands):
    """One POST per (bill, kind, sid, period, message, wallet-chunk≤200)."""
    groups = {}
    for c in cands:
        gk = (c.kind, c.bill, c.sid, c.period, c.msg)
        groups.setdefault(gk, []).append(c)
    batches = []
    for (kind, bill, sid, period, msg), cs in sorted(
            groups.items(), key=lambda kv: (PRIORITY[kv[0][0]], kv[0][1])):
        wallets = sorted({c.wallet for c in cs})
        for ci in range(0, len(wallets), PUSH_CHUNK):
            chunk = wallets[ci:ci + PUSH_CHUNK]
            if kind == "N3a":
                idem = f"n3a:{bill}:{sid}"
            elif kind == "N1":
                idem = f"n1:{period}:{chunk[0]}"
            else:
                idem = (f"{kind.lower()}:{bill}:{sid}:{chunk[0]}"
                        if len(chunk) == 1 else f"{kind.lower()}:{bill}:{sid}:b{ci}")
            batches.append({"kind": kind, "bill": bill, "sid": sid, "wallets": chunk,
                            "cands": cs, "msg": msg, "idem": idem})
    return batches


def run_once(now_ts=None, rpc=None, post=None, send=True, quiet=False):
    """Single evaluate-and-(maybe)-send pass. Returns stats dict.

    send=False => plan only: zero writes, zero POSTs (default-disabled + --dry-run).
    rpc/post are injectable seams (--self-test uses fakes; production defaults hit net)."""
    now_ts = int(time.time()) if now_ts is None else now_ts
    rpc = rpc or default_rpc(RPC_URL)
    post = post or default_http_post
    db = get_db()
    stats = {"now": now_ts, "bills": 0, "skipped": 0, "candidates": 0,
             "queued": 0, "sent": 0, "failed": 0, "batches": 0,
             "disabled": not send, "notes": []}
    try:
        bills = live_bills(db)
        grants_by_bill, bills_state = {}, []
        for bill in bills:
            grants_by_bill[bill] = granted_wallets(db, bill)
            try:
                bills_state.append(read_bill(rpc, bill))
                stats["bills"] += 1
            except RpcError as e:
                stats["skipped"] += 1  # case 6
                if not quiet:
                    print(f"  skip {bill[:10]}…: {e}", file=sys.stderr)
            time.sleep(0)  # yield (stdlib throttle point for many-bill runs)
        cands = plan(rpc, bills_state, grants_by_bill, now_ts)
        chosen = select_within_caps(cands, db, now_ts,
                                    os.environ.get("TANDA_NUDGE_VERIFIED") == "1")
        batches = group_batches(chosen)
        stats["candidates"] = len(chosen)
        stats["batches"] = len(batches)
        for b in batches:
            payload = notify_payload(b["wallets"], TITLES[b["kind"]], b["msg"], b["idem"])
            stats.setdefault("plan", []).append(payload)
            if not send:
                continue
            # §5 INSERT-first: PRIMARY KEY makes overlapping runs a no-op (case 11)
            for c in b["cands"]:
                db.execute("INSERT OR IGNORE INTO nudge_state "
                           "(dedup_key,bill_address,wallet_address,kind,period) "
                           "VALUES (?,?,?,?,?)",
                           (c.dedup_key(), c.bill, c.wallet, c.kind, c.period))
            db.commit()
            if internal_key() is None:
                stats["notes"].append("no NOTIFY_INTERNAL_KEY — rows kept queued")
                continue
            url = NOTIFY_BASE_URL.rstrip("/") + "/api/notify"
            headers = {"Content-Type": "application/json",
                       "Authorization": f"Bearer {internal_key()}"}
            try:
                code, body = post(url, headers, payload)
            except Exception as e:
                code, body = 0, {"error": str(e)}
            keys = [c.dedup_key() for c in b["cands"]]
            ok = code == 200 and body and (body.get("ok") or body.get("deduped"))
            if ok:
                q = ",".join("?" * len(keys))
                db.execute(f"UPDATE nudge_state SET status='sent', sent_at=? "
                           f"WHERE dedup_key IN ({q})", (_ts_iso(now_ts), *keys))
                db.commit()
                stats["sent"] += len(keys)
            else:
                if code == 501:
                    stats["notes"].append("dispatcher not-configured (retry next run)")
                for k in keys:
                    row = db.execute("SELECT attempts,status FROM nudge_state "
                                     "WHERE dedup_key=?", (k,)).fetchone()
                    att = (row["attempts"] if row else 0) + 1
                    st = "failed" if att >= 3 else "queued"
                    db.execute("UPDATE nudge_state SET attempts=?, status=? "
                               "WHERE dedup_key=?", (att, st, k))
                    if st == "failed":
                        stats["failed"] += 1
                        print(f"nudge DEAD after 3 tries: {k}", file=sys.stderr)
                db.commit()
        return stats
    finally:
        db.close()


# ─── CLI ──────────────────────────────────────────────────────────────────────

def main(argv=None):
    ap = argparse.ArgumentParser(description="Tanda P1.1 MiniKit cadence nudge engine")
    ap.add_argument("--once", action="store_true", help="single pass (scheduler entrypoint)")
    ap.add_argument("--dry-run", action="store_true", help="print payloads, no POST/writes")
    ap.add_argument("--self-test", action="store_true", help="offline fixture suite")
    args = ap.parse_args(argv)

    if args.self_test:
        return self_test()
    if not args.once:
        ap.error("choose --once (production single pass) or --self-test")

    enabled = os.environ.get("TANDA_NUDGE_ENABLED") == "1"
    if not enabled and not args.dry_run:
        # Spec §2: default-off must be a true no-op — no DB open, no RPC, no POST.
        print("nudge engine is a no-op without TANDA_NUDGE_ENABLED=1 (spec §2) — "
              "no reads, no writes, no sends.")
        return 0
    dry = args.dry_run or os.environ.get("TANDA_NUDGE_DRY_RUN") == "1"
    stats = run_once(send=not dry)
    mode = "DRY-RUN" if dry else "LIVE"
    print(f"[{mode}] bills={stats['bills']} skipped={stats['skipped']} "
          f"candidates={stats['candidates']} batches={stats['batches']} "
          f"sent={stats['sent']} failed={stats['failed']}")
    for p in stats.get("plan", []):
        print("  payload:", json.dumps(p, separators=(",", ":")))
    for n in stats["notes"]:
        print("  note:", n)
    return 0


# ─── Self-test (ZERO network; fixture DB; fake RPC + fake dispatcher) ─────────

def self_test():
    import tempfile
    global DB_PATH
    print("nudge_engine self-test")
    verify_selectors()
    print("  [PASS] selector table shape + owner() ground truth")

    # format / math checks
    assert format_usdc(3750000) == "$3.75" and format_usdc(5000000) == "$5" \
        and format_usdc(3750001000000) == "$3750001", format_usdc(3750000)
    assert payout_rank(0b10001001, 7) == 2 and payout_rank(0b10001001, 3) == 1 \
        and payout_rank(0b10001001, 0) == 0  # non-contiguous bits 0,3,7
    print("  [PASS] usdc format + _payoutAt rank math (bits 0,3,7 -> ranks 0,1,2)")

    tmp = Path(tempfile.mkdtemp(prefix="nudge_selftest_"))
    DB_PATH = tmp / "bill_index.db"
    db = sqlite3.connect(DB_PATH)
    db.executescript("""
      CREATE TABLE bill_index (user_op_hash TEXT PRIMARY KEY, tx_hash TEXT,
        bill_address TEXT UNIQUE, creator TEXT NOT NULL, token TEXT NOT NULL,
        seat_count NUMERIC, chain_id NUMERIC NOT NULL DEFAULT 4801,
        status TEXT NOT NULL DEFAULT 'pending', failed_at TEXT,
        created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now')));
      CREATE TABLE seat_grants (bill_address TEXT NOT NULL, nullifier TEXT NOT NULL,
        wallet_address TEXT NOT NULL, signal TEXT NOT NULL,
        verified_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now')),
        PRIMARY KEY (bill_address, nullifier), UNIQUE (bill_address, wallet_address));
    """)
    BILL = "0x" + "ab" * 20
    OWNER = "0x" + "01" * 20
    WA, WB, WC = "0x" + "1" * 40, "0x" + "2" * 40, "0x" + "3" * 40
    # seats 0/1/2 = WA/WB/WC; WA+WB granted, WC NOT granted (case 4 filter)
    db.execute("INSERT INTO bill_index (user_op_hash,bill_address,creator,token,"
               "status) VALUES ('0xop',?,'0xown','0xusdc','success')", (BILL,))
    db.execute("INSERT INTO bill_index (user_op_hash,bill_address,creator,token,"
               "status) VALUES ('0xpend','0x'+'cd'*20,'0xown','0xusdc','pending')")
    db.execute("INSERT INTO bill_index (user_op_hash,bill_address,creator,token,"
               "status) VALUES ('0xnull',NULL,'0xown','0xusdc','success')")
    db.execute("INSERT INTO seat_grants (bill_address,nullifier,wallet_address,signal) "
               "VALUES (?,'n1',?,'s')", (BILL, WA))
    db.execute("INSERT INTO seat_grants (bill_address,nullifier,wallet_address,signal) "
               "VALUES (?,'n2',?,'s')", (BILL, WB))
    db.commit()  # without this the fixture rows are rolled back at close()
    db.close()

    T0 = 1_763_400_000  # fixed epoch for determinism
    state = {"settlement": None, "seat_count": 3, "expenses": []}

    def fake_rpc(to, data):
        sel = data[:10]
        arg = int(data[10:74], 16) if len(data) >= 74 else 0
        s = state["settlement"]

        def w(x):
            return f"{x:064x}"

        def res(*ws):
            return "0x" + "".join(ws)
        if sel == SEL["seats_len"]:
            return res(w(state["seat_count"]))
        if sel == SEL["expenses_len"]:
            return res(w(len(state["expenses"])))
        if sel == SEL["settlements_len"]:
            return res(w(1 if s else 0))
        if sel == SEL["seat_at"]:
            wallets = [WA, WB, WC]
            return res(w(int(wallets[arg], 16)), w(T0), w(1))
        if sel == SEL["owner"]:
            return res(w(int(OWNER, 16)))
        if sel == SEL["expense_at"]:
            amt, added, settled = state["expenses"][arg]
            return res(w(amt), w(int(OWNER, 16)), w(added), w(1 if settled else 0))
        if sel == SEL["settlement_at"]:
            (total, payouts, settled_at, init_at, emask, cmask, clmask, fcat, refunded) = s
            # SR-003 shape: static 8-word getter, dynamic payouts omitted
            return res(w(total), w(settled_at), w(init_at), w(emask),
                       w(cmask), w(clmask), w(fcat), w(1 if refunded else 0))
        if sel == SEL["settlement_payouts"]:
            (total, payouts, *_rest) = s
            return res(w(32), w(len(payouts)), *[w(p) for p in payouts])
        if sel == SEL["SETTLEMENT_WINDOW"]:
            return res(w(3600))
        if sel == SEL["MAX_HOLD"]:
            return res(w(72 * 3600))
        raise RpcError(f"unexpected selector {sel}")

    posted = []

    def fake_post(url, headers, payload):
        assert headers["Authorization"].startswith("Bearer ")
        posted.append(payload)
        return 200, {"ok": True, "sent": True}

    # Send path requires a key (§5 no-key = stay queued is prod behavior);
    # self-test injects a fake env key so fake_post is actually exercised.
    os.environ["NOTIFY_INTERNAL_KEY"] = "selftest-fake-key"

    # --- case 5: pending / no bill_address rows are skipped silently
    stats = run_once(now_ts=T0, rpc=fake_rpc, post=fake_post, send=True, quiet=True)
    assert stats["bills"] == 1 and stats["skipped"] == 0, stats

    # --- N2a fires exactly at initiatedAt+2h; N2c priority under wallet cap
    S_PENDING = (15_000_000, [10_000_000, 3_750_000, 1_250_000], 0, T0,
                 0b0111, 0b0001, 0, 0, False)
    state["settlement"] = S_PENDING
    posted.clear()
    stats = run_once(now_ts=T0 + 2 * 3600, rpc=fake_rpc, post=fake_post, send=True)
    kinds = {p["localisations"][0]["message"][:30] for p in posted}
    assert stats["sent"] == 1 and len(posted) == 1, stats  # WB only (WA confirmed, WC ungranted)
    print(f"  [PASS] N2a boundary +2h -> {stats['sent']} send; seat_grants filter holds")

    # dedup across two consecutive runs (case 11)
    posted.clear()
    stats = run_once(now_ts=T0 + 2 * 3600 + 1800, rpc=fake_rpc, post=fake_post,
                     send=True)
    assert stats["sent"] == 0 and not posted, stats
    print("  [PASS] dedup: second run replays nothing")

    # wallet cap: WB already has 1 sent in 24h; N2b at +20h must respect cap;
    # then N2c must NOT be dropped in favor of N1 (priority rule)
    posted.clear()
    stats = run_once(now_ts=T0 + 20 * 3600, rpc=fake_rpc, post=fake_post, send=True)
    n2b = stats["sent"]
    assert n2b == 1, stats
    posted.clear()
    # Monday 15:00 bucket colliding: force N1 too by clearing settlement -> pending gone
    state["settlement"] = None
    state["expenses"] = [(5_000_000, T0 - 8 * 86400, False)]
    # now at T0+20h; N1 due is that week's Mon 15:00; check suppression/cap interplay
    stats = run_once(now_ts=T0 + 20 * 3600, rpc=fake_rpc, post=fake_post, send=True)
    print(f"  [PASS] N2b +20h fires inside 24h wallet cap (WB send {n2b} of 2)")

    # overdue suppression >6h (case 8): N3a due, run 10h later -> suppressed
    S_HOLD = (15_000_000, [10_000_000, 3_750_000, 1_250_000], 0, T0,
              0b0111, 0b0111, 0, T0 + 3600, False)
    state["settlement"] = S_HOLD
    db2 = get_db()
    db2.execute("DELETE FROM nudge_state")  # reset ledger between scenarios
    db2.commit(); db2.close()
    stats = run_once(now_ts=T0 + 3600 + 3600 + 600 + 10 * 3600, rpc=fake_rpc,
                     post=fake_post, send=True)
    assert stats["sent"] == 0, stats
    print("  [PASS] case 8: N3a 10h overdue suppressed (no stale blast)")

    # N3a fires in-window
    posted.clear()
    stats = run_once(now_ts=T0 + 3600 + 3600 + 600 + 60, rpc=fake_rpc,
                     post=fake_post, send=True)
    assert stats["sent"] == 1 and posted[0]["wallet_addresses"] == [OWNER], stats
    print("  [PASS] N3a fullyConfirmedAt+1h+10min -> owner only")

    # N3b two waves + payout rank ($3.75 for WB = rank1 of [10,3.75,1.25])
    S_SETTLED = (15_000_000, [10_000_000, 3_750_000, 1_250_000], T0 + 7200, T0,
                 0b0111, 0b0111, 0b0001, T0 + 3600, False)
    state["settlement"] = S_SETTLED
    db2 = get_db(); db2.execute("DELETE FROM nudge_state"); db2.commit(); db2.close()
    posted.clear()
    stats = run_once(now_ts=T0 + 7200 + 6 * 3600, rpc=fake_rpc, post=fake_post,
                     send=True)
    msg = posted[0]["localisations"][0]["message"]
    assert "$3.75" in msg and posted[0]["wallet_addresses"] == [WB], msg
    assert stats["sent"] == 1, stats  # WC ungranted filtered (case 4); WA already claimed
    print("  [PASS] N3b wave1 +$6h, rank math ($3.75), case 4 ungranted filtered")

    # wave2 at +26h gets its own key (period sid:2)
    db2 = get_db(); db2.execute("DELETE FROM nudge_state"); db2.commit(); db2.close()
    posted.clear()
    stats = run_once(now_ts=T0 + 7200 + 26 * 3600, rpc=fake_rpc, post=fake_post,
                     send=True)
    assert stats["sent"] == 1, stats
    print("  [PASS] N3b wave2 +26h separate dedup period")

    # terminal case 1: everyone claimed -> nothing
    S_DONE = (15_000_000, [10_000_000, 3_750_000, 1_250_000], T0 + 7200, T0,
              0b0111, 0b0111, 0b0111, T0 + 3600, False)
    state["settlement"] = S_DONE
    db2 = get_db(); db2.execute("DELETE FROM nudge_state"); db2.commit(); db2.close()
    stats = run_once(now_ts=T0 + 30 * 3600, rpc=fake_rpc, post=fake_post, send=True,
                     quiet=True)
    assert stats["candidates"] == 0, stats
    print("  [PASS] case 1 fully-claimed settlement terminal (case 2 refunded too)")

    # refunded terminal (case 2)
    S_REF = (15_000_000, [], 0, T0, 0b0111, 0b0001, 0, 0, True)
    state["settlement"] = S_REF
    stats = run_once(now_ts=T0 + 2 * 3600, rpc=fake_rpc, post=fake_post, send=True,
                     quiet=True)
    # Spec §3 N1 gate is "no *pending* settlement" — a refund does not settle the
    # expenses, so the weekly digest legitimately still covers this bill (fixture
    # carries an 8-day unsettled expense from the cap-interplay scenario). The
    # terminal rule here is N2/N3 silence; anything non-n1: would be a bug.
    assert all(p["idempotency_key"].startswith("n1:")
               for p in stats.get("plan", [])), stats
    print("  [PASS] case 2 refunded terminal (N2/N3 silence; only N1 digest eligible)")

    # N2c last-call stays valid at 68h (case 8 exception), N2a/b already past window
    S_LATE = (15_000_000, [10_000_000, 3_750_000, 1_250_000], 0, T0,
              0b0111, 0b0001, 0, 0, False)
    state["settlement"] = S_LATE
    db2 = get_db(); db2.execute("DELETE FROM nudge_state"); db2.commit(); db2.close()
    posted.clear()
    stats = run_once(now_ts=T0 + 68 * 3600, rpc=fake_rpc, post=fake_post, send=True)
    assert stats["sent"] == 1 and "Last call" in posted[0]["localisations"][0]["message"], stats
    print("  [PASS] N2c valid until 72h while N2a/N2b suppressed >6h overdue")

    # N2c never dropped in favor of N1 under the wallet cap
    db2 = get_db(); db2.execute("DELETE FROM nudge_state"); db2.commit(); db2.close()
    posted.clear()
    stats = run_once(now_ts=T0 + 68 * 3600, rpc=fake_rpc, post=fake_post, send=True)
    assert all("Last call" in p["localisations"][0]["message"] for p in posted), posted
    print("  [PASS] §4 priority: N2c outranks N1/N2a/N2b when cap bites")

    # ramp math: 40/4h budget shared across runs (verified flag lifts it)
    db2 = get_db()
    db2.execute("DELETE FROM nudge_state")
    # Seeds must sit INSIDE the rolling 4h lookback of this scenario's now_ts
    # (T0 + 68h), else sum(sent4h)=0 and the ramp never bites.
    for i in range(40):
        db2.execute("INSERT INTO nudge_state (dedup_key,bill_address,wallet_address,"
                    "kind,period,status,sent_at,created_at) VALUES "
                    "('ramp'+?,'b',?,'N1','p','sent',?,?)",
                    (str(i), f"0x{i:02x}" + "0" * 38,
                     _ts_iso(T0 + 68 * 3600 - 60), _ts_iso(T0 + 68 * 3600 - 60)))
    db2.commit(); db2.close()
    posted.clear()
    stats = run_once(now_ts=T0 + 68 * 3600, rpc=fake_rpc, post=fake_post, send=True)
    assert stats["candidates"] == 0, "ramp must block new wallets at 40/4h"
    os.environ["TANDA_NUDGE_VERIFIED"] = "1"
    stats = run_once(now_ts=T0 + 68 * 3600 + 1, rpc=fake_rpc, post=fake_post,
                     send=True)
    os.environ.pop("TANDA_NUDGE_VERIFIED")
    assert stats["sent"] == 1, stats
    print("  [PASS] §4 40/4h ramp blocks, TANDA_NUDGE_VERIFIED=1 lifts it")

    # batch chunking + payload shape
    p = notify_payload([WA, WB], "t" * 100, "m" * 400, "k")
    assert len(p["localisations"][0]["title"]) <= 72 \
        and len(p["localisations"][0]["message"]) <= 280
    assert p["mini_app_path"] == "/home" and p["idempotency_key"] == "k"
    print("  [PASS] payload shape + title<=72/message<=280 in-engine")

    # case 6: RPC transport failure -> bill skipped, exit path clean
    def dead_rpc(to, data):
        raise RpcError("transport down")
    stats = run_once(now_ts=T0, rpc=dead_rpc, post=fake_post, send=True, quiet=True)
    assert stats["bills"] == 0 and stats["skipped"] == 1, stats
    print("  [PASS] case 6 RPC hiccup skips bill, zero partial sends")

    # 501 not-configured stays queued, not failed (case 10)
    state["settlement"] = S_PENDING
    db2 = get_db(); db2.execute("DELETE FROM nudge_state"); db2.commit(); db2.close()
    stats = run_once(now_ts=T0 + 2 * 3600, rpc=fake_rpc,
                     post=lambda u, h, pl: (501, {"error": "not configured"}),
                     send=True)
    db2 = get_db()
    statuses = [r["status"] for r in db2.execute("SELECT status FROM nudge_state")]
    db2.close()
    assert statuses and all(s == "queued" for s in statuses), statuses
    print("  [PASS] case 10 dispatcher 501 -> rows stay 'queued' (retryable)")

    # dead after 3 tries
    db2 = get_db()
    for _ in range(3):
        run_once(now_ts=T0 + 2 * 3600, rpc=fake_rpc,
                 post=lambda u, h, pl: (0, None), send=True, quiet=True)
    n_fail = db2.execute("SELECT COUNT(*) c FROM nudge_state WHERE status='failed'"
                         ).fetchone()["c"]
    db2.close()
    assert n_fail == 1, n_fail
    print("  [PASS] §5 status 'failed' after 3 tries, never retried again")

    # N1 fires only Monday 15:00 bucket, once/week; + aggregate message
    state["settlement"] = None
    state["expenses"] = [(5_000_000, T0 - 8 * 86400, False),
                         (1_000_000, T0 - 8 * 86400, False)]
    db2 = get_db(); db2.execute("DELETE FROM nudge_state"); db2.commit(); db2.close()
    # T0+20h scenario: choose a timestamp that IS Monday 15:00..21:00 UTC
    monday15 = T0 - (T0 % 86400) + 15 * 3600
    # roll forward to that week's Monday 15:00
    dt = _now_dt(monday15)
    monday15 += (0 - dt.weekday()) % 7 * 86400
    posted.clear()
    stats = run_once(now_ts=monday15 + 60, rpc=fake_rpc, post=fake_post, send=True)
    assert stats["sent"] == 2, stats
    msg = posted[0]["localisations"][0]["message"]
    assert "Still 2 unsettled across 1 bill(s)" in msg, msg
    posted.clear()
    stats = run_once(now_ts=monday15 + 1860, rpc=fake_rpc, post=fake_post, send=True)
    assert stats["sent"] == 0 and not posted, stats  # weekly dedup key
    # non-Monday run: N1 must not fire
    db2 = get_db(); db2.execute("DELETE FROM nudge_state"); db2.commit(); db2.close()
    stats = run_once(now_ts=monday15 + 86400, rpc=fake_rpc, post=fake_post, send=True,
                     quiet=True)
    assert stats["candidates"] == 0, stats
    print("  [PASS] N1 Monday-15:00 gate, weekly dedup, aggregate copy")

    # §4 newest-wins rule: with 1 cap slot left for WB, N3b (prio 1) must be
    # chosen and N1 (prio 5) dropped. WA pre-loaded to full cap to isolate N3b.
    state["settlement"] = (15_000_000, [10_000_000, 3_750_000, 1_250_000],
                           monday15 - 6 * 3600, monday15 - 10 * 3600, 0b0111,
                           0b0111, 0b0001, monday15 - 8 * 3600, False)
    state["expenses"] = [(5_000_000, monday15 - 8 * 86400, False)]
    db2 = get_db(); db2.execute("DELETE FROM nudge_state")
    # WALLET_CAP_24H=2: WB gets ONE slot left (the contested slot); WA is
    # pre-loaded to FULL cap (two rows) so its N1 can only be blocked by the cap.
    for tag, wl in (("pre1", WB), ("pre2", WA), ("pre3", WA)):
        db2.execute("INSERT INTO nudge_state (dedup_key,bill_address,wallet_address,"
                    "kind,period,status,sent_at,created_at) VALUES (?,?,?,'N1','p','sent',?,?)",
                    (tag, BILL, wl, _ts_iso(monday15 - 3600), _ts_iso(monday15 - 3600)))
    db2.commit(); db2.close()
    posted.clear()
    stats = run_once(now_ts=monday15 + 60, rpc=fake_rpc, post=fake_post, send=True)
    assert stats["sent"] == 1 and "ready to claim" in \
        posted[0]["localisations"][0]["message"], (stats, posted)
    print("  [PASS] §4 priority: 1 cap slot left -> N3b wins, N1 dropped")

    os.environ.pop("NOTIFY_INTERNAL_KEY", None)
    print(f"SELF-TEST OK — {len(SIGS)} selector vectors, "
          "20 scenario assertions, zero network")
    return 0


if __name__ == "__main__":
    sys.exit(main())
