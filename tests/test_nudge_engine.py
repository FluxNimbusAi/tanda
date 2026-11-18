#!/usr/bin/env python3
"""P1.1 cadence-nudge test suite (kanban t_7313cbab) — spec TANDA_P11_CADENCE_NUDGE_SPEC.md §6/§7.

Focused coverage of services/nudge_engine.py: trigger boundaries for all six kinds,
the eleven edge cases (§6), caps math (§4), the nudge_state lifecycle (§5), and the
DB/config fail-fast guards. ZERO network: fake RPC/HTTP callables + temp SQLite ledgers.

Stdlib unittest so the CI lane needs no pip install; runs under pytest too:
    python -m unittest discover -s tests -v
    python -m pytest tests/test_nudge_engine.py -q
"""
import copy
import os
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "services"))
import nudge_engine as ne  # noqa: E402

ENGINE = ROOT / "services" / "nudge_engine.py"

T0 = 1_763_400_000                      # fixed epoch (determinism)
MON15 = int(datetime(2026, 11, 16, 15, 0, tzinfo=timezone.utc).timestamp())  # a real Monday 15:00 UTC
BILL = "0x" + "ab" * 20
BILL2 = "0x" + "cd" * 20
OWNER = "0x" + "01" * 20
WA, WB, WC = "0x" + "1" * 40, "0x" + "2" * 40, "0x" + "3" * 40

SCHEMA = """
CREATE TABLE bill_index (user_op_hash TEXT PRIMARY KEY, tx_hash TEXT,
  bill_address TEXT UNIQUE, creator TEXT NOT NULL, token TEXT NOT NULL,
  seat_count NUMERIC, chain_id NUMERIC NOT NULL DEFAULT 4801,
  status TEXT NOT NULL DEFAULT 'pending', failed_at TEXT,
  created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now')));
CREATE TABLE seat_grants (bill_address TEXT NOT NULL, nullifier TEXT NOT NULL,
  wallet_address TEXT NOT NULL, signal TEXT NOT NULL,
  verified_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now')),
  PRIMARY KEY (bill_address, nullifier), UNIQUE (bill_address, wallet_address));
"""


def w64(x: int) -> str:
    return f"{x:064x}"


def mk_settlement(total=15_000_000, payouts=(10_000_000, 3_750_000, 1_250_000),
                  settled=0, init=T0, emask=0, cmask=0, clmask=0, fcat=0,
                  refunded=False):
    return {"totalAmount": total, "payouts": list(payouts), "settledAt": settled,
            "initiatedAt": init, "expectedMask": emask, "confirmedMask": cmask,
            "claimedMask": clmask, "fullyConfirmedAt": fcat, "refunded": refunded}


def enc_settlement(s):
    """Encode a settlement dict the way the contract ABI does (dynamic struct tail)."""
    head = [w64(s["totalAmount"]), w64(9 * 32), w64(s["settledAt"]), w64(s["initiatedAt"]),
            w64(s["expectedMask"]), w64(s["confirmedMask"]), w64(s["claimedMask"]),
            w64(s["fullyConfirmedAt"]), w64(1 if s["refunded"] else 0)]
    tail = [w64(len(s["payouts"]))] + [w64(p) for p in s["payouts"]]
    return "0x" + "".join(head + tail)


def mk_bill_state(seats, s, *, bill=BILL, window=3600, max_hold=72 * 3600,
                  expenses=(), set_count=None):
    """`seats` = [(wallet, active)]. `s` = settlement dict or None (last settlement)."""
    return {"bill": bill, "seat_count": len(seats),
            "exp_count": len(expenses),
            "set_count": set_count if set_count is not None else (1 if s else 0),
            "window": window, "max_hold": max_hold,
            "seats": [{"wallet": wl, "joinedAt": T0, "active": a} for wl, a in seats],
            "owner": OWNER,
            "expenses_tail": [{"amount": amt, "paidBy": OWNER, "addedAt": ad,
                               "settled": st} for amt, ad, st in expenses],
            "last_set": s}


GRANT_ALL = {WA, WB, WC}


class FakeRpc:
    """Per-bill contract simulator keyed by lowercase address; dead bills raise."""

    def __init__(self, sims):
        self.sims = {k.lower(): v for k, v in sims.items()}
        self.calls = 0

    def __call__(self, to, data):
        self.calls += 1
        sim = self.sims.get(to.lower())
        if sim is None or sim.dead:
            raise ne.RpcError(f"transport down for {to[:10]}")
        return sim.reply(data)


class BillSim:
    def __init__(self, seats=(), settlements=(), expenses=(), owner=OWNER,
                 window=3600, max_hold=72 * 3600, dead=False):
        self.seats = list(seats)            # [(wallet, active)]
        self.settlements = list(settlements)  # settlement dicts, index = sid
        self.expenses = list(expenses)      # [(amount, addedAt, settled)]
        self.owner = owner
        self.window = window                # None -> revert (exercise literal fallback)
        self.max_hold = max_hold
        self.dead = dead

    def reply(self, data):
        sel, arg = data[:10], (int(data[10:74], 16) if len(data) >= 74 else 0)
        if sel == ne.SEL["seats_len"]:
            return "0x" + w64(len(self.seats))
        if sel == ne.SEL["expenses_len"]:
            return "0x" + w64(len(self.expenses))
        if sel == ne.SEL["settlements_len"]:
            return "0x" + w64(len(self.settlements))
        if sel == ne.SEL["seat_at"]:
            wl, active = self.seats[arg]
            return "0x" + w64(int(wl, 16)) + w64(T0) + w64(1 if active else 0)
        if sel == ne.SEL["owner"]:
            return "0x" + w64(int(self.owner, 16))
        if sel == ne.SEL["expense_at"]:
            amt, added, settled = self.expenses[arg]
            return "0x" + w64(amt) + w64(int(self.owner, 16)) + w64(added) + w64(1 if settled else 0)
        if sel == ne.SEL["settlement_at"]:
            return enc_settlement(self.settlements[arg])
        if sel == ne.SEL["SETTLEMENT_WINDOW"]:
            if self.window is None:
                raise ne.RpcError("revert (legacy era)")
            return "0x" + w64(self.window)
        if sel == ne.SEL["MAX_HOLD"]:
            if self.max_hold is None:
                raise ne.RpcError("revert (legacy era)")
            return "0x" + w64(self.max_hold)
        raise ne.RpcError(f"unexpected selector {sel}")


class BaseCase(unittest.TestCase):
    """Isolates module globals + env; provides tmp ledger + fake-dispatch builders."""

    ENV_KEYS = ("NOTIFY_INTERNAL_KEY", "TANDA_NUDGE_VERIFIED", "TANDA_NUDGE_ENABLED",
                "TANDA_NUDGE_DRY_RUN", "TANDA_NUDGE_DB", "BILL_INDEX_DB")

    def setUp(self):
        self._env = {k: os.environ.get(k) for k in self.ENV_KEYS}
        for k in self.ENV_KEYS:
            os.environ.pop(k, None)
        self._globals = {g: getattr(ne, g) for g in
                         ("DB_PATH", "NOTIFY_INTERNAL_KEY_FILE", "NOTIFY_BASE_URL")}
        self.tmp = Path(tempfile.mkdtemp(prefix="nudge_test_"))
        ne.DB_PATH = self.tmp / "bill_index.db"
        ne.NOTIFY_INTERNAL_KEY_FILE = self.tmp / "no_such_keyfile.txt"  # never the real vault
        ne.NOTIFY_BASE_URL = "http://notify.test"

    def tearDown(self):
        for k, v in self._env.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
        for g, v in self._globals.items():
            setattr(ne, g, v)

    # -- fixtures -------------------------------------------------------------
    def make_ledger(self, bills=(), grants=None, *, extra_rows=True):
        """bills: iterable of addresses (status='success'); grants: {bill: [wallets]}."""
        grants = grants or {}
        db = sqlite3.connect(ne.DB_PATH)
        db.executescript(SCHEMA)
        for addr in bills:
            db.execute("INSERT INTO bill_index (user_op_hash,bill_address,creator,token,status)"
                       " VALUES (?,?,?, '0xusdc','success')", ("op_" + addr, addr, "0xown"))
        if extra_rows:  # case 5 fixtures: pending row + null-address row
            if BILL2 not in bills:
                db.execute("INSERT INTO bill_index (user_op_hash,bill_address,creator,token,status)"
                           " VALUES ('0xpend',?,'0xown','0xusdc','pending')", (BILL2,))
            db.execute("INSERT INTO bill_index (user_op_hash,bill_address,creator,token,status)"
                       " VALUES ('0xnull',NULL,'0xown','0xusdc','success')")
        for addr, wallets in grants.items():
            for i, wl in enumerate(wallets):
                db.execute("INSERT INTO seat_grants (bill_address,nullifier,wallet_address,signal)"
                           " VALUES (?,?,?,'s')", (addr, f"n{i}", wl))
        db.commit()
        db.close()

    def seed_sent(self, wallet, count=1, *, at=None, kind="N1", key_prefix="seed"):
        """Pre-load nudge_state with `count` sent rows for `wallet`."""
        at = T0 - 3600 if at is None else at
        db = ne.get_db()
        for i in range(count):
            db.execute("INSERT INTO nudge_state (dedup_key,bill_address,wallet_address,kind,"
                       "period,status,sent_at,created_at) VALUES (?,?,?,?,'p','sent',?,?)",
                       (f"{key_prefix}{i}:{wallet}", BILL, wallet, kind,
                        ne._ts_iso(at), ne._ts_iso(at)))
        db.commit()
        db.close()

    def rows(self):
        db = sqlite3.connect(ne.DB_PATH)
        db.row_factory = sqlite3.Row
        out = [dict(r) for r in db.execute("SELECT * FROM nudge_state ORDER BY dedup_key")]
        db.close()
        return out

    def armed_post(self, code=200, body=None, raises=None):
        """Fake dispatcher: records payloads; default answers ok:true."""
        posted, headers_seen = [], []
        body = {"ok": True, "sent": True} if body is None else body

        def post(url, headers, payload):
            posted.append(payload)
            headers_seen.append(headers)
            if raises:
                raise raises
            return code, body
        return posted, headers_seen, post

    def tick(self, sims, now_ts, *, send=True, key="test-key"):
        """Standard armed run: inject rpc/post, return (stats, posted)."""
        if key:
            os.environ["NOTIFY_INTERNAL_KEY"] = key
        posted, seen, post = self.armed_post()
        self.headers_seen = seen
        stats = ne.run_once(now_ts=now_ts, rpc=FakeRpc(sims), post=post, send=send,
                            quiet=True)
        return stats, posted


# ─── Pure helpers ─────────────────────────────────────────────────────────────

class TestHelpers(BaseCase):
    def test_usdc_format_exact_math(self):
        # spec §3: 6-dp USDC, trailing zeros trimmed, exact integer math
        cases = {3750000: "$3.75", 5000000: "$5", 0: "$0", 1: "$0.000001",
                 10500000: "$10.5", 1000000000000: "$1000000"}
        for raw, want in cases.items():
            self.assertEqual(ne.format_usdc(raw), want, f"amount={raw}")

    def test_payout_rank_noncontiguous_mask(self):
        # spec §7 acceptance: bits 0,3,7 -> ranks 0,1,2 (_payoutAt dense rule)
        m = 0b10001001
        self.assertEqual([ne.payout_rank(m, s) for s in (0, 3, 7)], [0, 1, 2])
        self.assertEqual(ne.payout_rank(m, 4), 2)   # rank between bits 3 and 7
        self.assertEqual(ne.payout_rank(m, 8), 3)   # past the top bit
        self.assertEqual(ne.payout_rank(0b0111, 2), 2)

    def test_calldata_pads_args(self):
        self.assertTrue(ne.calldata(ne.SEL["seat_at"], 5).startswith(ne.SEL["seat_at"]))
        self.assertEqual(len(ne.calldata("aabbccdd", 1)), 10 + 64)
        self.assertEqual(ne.calldata("0x00", 0)[-64:], "0" * 64)
        self.assertEqual(ne.calldata("0x00", 255)[-64:], "0" * 62 + "ff")

    def test_words_addr_decode(self):
        hexes = "0x" + w64(int(WA, 16)) + w64(7)
        ws = ne._words(hexes)
        self.assertEqual(ne._addr(ws[0]), WA)
        self.assertEqual(ws[1], 7)

    def test_decode_settlement_dynamic_tail(self):
        s = mk_settlement(emask=0b1011)
        self.assertEqual(ne.decode_settlement(ne._words(enc_settlement(s))), s)

    def test_selector_table_shape_and_corruption_tripwire(self):
        ne.verify_selectors()  # live table must pass
        saved = dict(ne.SEL)
        try:
            ne.SEL["owner"] = "0xdeadbeef"
            with self.assertRaises(AssertionError):
                ne.verify_selectors()
        finally:
            ne.SEL.clear()
            ne.SEL.update(saved)

    def test_selectors_unique_and_sig_consistent(self):
        self.assertEqual(len(set(ne.SEL.values())), len(ne.SEL))
        self.assertEqual(set(ne.SIGS) - set(ne.SEL), set())
        for k in ne.SIGS:
            self.assertRegex(ne.SEL[k], r"^0x[0-9a-f]{8}$")


# ─── Dedup key scheme (spec §5) ───────────────────────────────────────────────

class TestDedupKeys(BaseCase):
    def cand(self, kind, wallet=WA, sid=3, period="3", bill=BILL):
        return ne.Candidate(kind, bill, sid, wallet, "", T0, period)

    def test_n1_wallet_week_bucket_ignores_bill(self):
        # wallet-level aggregate: same wallet+week across two bills => ONE key
        a = self.cand("N1", wallet=WA, period="2026-W47", bill=BILL)
        b = self.cand("N1", wallet=WA, period="2026-W47", bill=BILL2)
        c = self.cand("N1", wallet=WB, period="2026-W47", bill=BILL)
        self.assertEqual(a.dedup_key(), b.dedup_key())
        self.assertEqual(a.dedup_key(), f"n1:2026-W47:{WA}")
        self.assertNotEqual(a.dedup_key(), c.dedup_key())

    def test_n2_keys_per_bill_sid_wallet(self):
        for kind, letter in (("N2a", "a"), ("N2b", "b"), ("N2c", "c")):
            self.assertEqual(self.cand(kind).dedup_key(),
                             f"n2{letter}:{BILL}:3:{WA}")

    def test_n3a_bill_level_no_wallet(self):
        k1 = self.cand("N3a", wallet=WA).dedup_key()
        k2 = self.cand("N3a", wallet=WB).dedup_key()
        self.assertEqual(k1, f"n3a:{BILL}:3")
        self.assertEqual(k1, k2)  # owner-only target; key excludes wallet by design

    def test_n3b_wave_buckets_distinct(self):
        w1 = self.cand("N3b", period="3:1").dedup_key()
        w2 = self.cand("N3b", period="3:2").dedup_key()
        self.assertEqual(w1, f"n3b:{BILL}:3:{WA}:1")
        self.assertEqual(w2, f"n3b:{BILL}:3:{WA}:2")
        self.assertNotEqual(w1, w2)


# ─── Case 8: due gate + overdue suppression ───────────────────────────────────

class TestDueGate(BaseCase):
    def test_not_due_before_boundary(self):
        self.assertFalse(ne.due_ok("N2a", T0 + 2 * 3600 - 1, T0 + 2 * 3600, T0, 72 * 3600))

    def test_fires_at_and_after_boundary_within_grace(self):
        due = T0 + 2 * 3600
        self.assertTrue(ne.due_ok("N2a", due, due, T0, 72 * 3600))
        self.assertTrue(ne.due_ok("N2a", due + 6 * 3600, due, T0, 72 * 3600))

    def test_suppressed_strictly_beyond_6h(self):
        self.assertFalse(ne.due_ok("N2a", T0 + 2 * 3600 + 6 * 3600 + 1,
                                   T0 + 2 * 3600, T0, 72 * 3600))

    def test_n2c_exception_valid_until_max_hold(self):
        due = T0 + 60 * 3600
        self.assertTrue(ne.due_ok("N2c", T0 + 68 * 3600, due, T0, 72 * 3600))   # 8h late: OK
        self.assertTrue(ne.due_ok("N2c", T0 + 72 * 3600 - 1, due, T0, 72 * 3600))
        self.assertFalse(ne.due_ok("N2c", T0 + 72 * 3600, due, T0, 72 * 3600))  # escrow gone

    def test_n2c_legacy_zero_init_unbounded(self):
        self.assertTrue(ne.due_ok("N2c", T0 + 999 * 3600, T0, 0, 72 * 3600))


# ─── Trigger matrix: all six kinds at spec boundaries (§3, §6) ────────────────

class TestTriggerMatrix(BaseCase):
    def test_n2a_boundary_2h_fires_only_before_not_after(self):
        seats = [(WA, True), (WB, True), (WC, True)]
        s = mk_settlement(emask=0b0111, cmask=0b0001)  # WA confirmed; WB, WC need
        b = mk_bill_state(seats, s)
        self.assertEqual(ne.evaluate_bill(b, T0 + 2 * 3600 - 1, GRANT_ALL), [])
        kinds = {c.kind for c in ne.evaluate_bill(b, T0 + 2 * 3600, GRANT_ALL)}
        self.assertEqual(kinds, {"N2a"})
        # well past grace: 21h after init -> N2a (>6h overdue) suppressed, N2b live
        kinds = {c.kind for c in ne.evaluate_bill(b, T0 + 21 * 3600, GRANT_ALL)}
        self.assertEqual(kinds, {"N2b"})

    def test_n2a_targets_unconfirmed_expected_granted_active_only(self):
        # WA confirmed; WB expected but NOT granted (case 4); WC expected+granted
        s = mk_settlement(emask=0b0110, cmask=0b0001)
        b = mk_bill_state([(WA, True), (WB, True), (WC, True)], s)
        cands = ne.evaluate_bill(b, T0 + 2 * 3600, {WA, WC})
        self.assertEqual([c.wallet for c in cands], [WC])
        self.assertIn("You're 1 of 1 holding up", cands[0].msg)

    def test_n2a_count_of_holders_up(self):
        s = mk_settlement(emask=0b0111, cmask=0)  # all three unconfirmed
        b = mk_bill_state([(WA, True), (WB, True), (WC, True)], s)
        cands = ne.evaluate_bill(b, T0 + 2 * 3600, GRANT_ALL)
        self.assertEqual(len(cands), 3)
        for c in cands:
            self.assertIn("You're 1 of 3 holding up", c.msg)
            self.assertEqual(c.kind, "N2a")
            self.assertEqual(c.sid, 0)

    def test_n2b_20h_copy_hours_left(self):
        s = mk_settlement(emask=0b0110, cmask=0b0001)
        b = mk_bill_state([(WA, True), (WB, True), (WC, True)], s)
        cands = [c for c in ne.evaluate_bill(b, T0 + 20 * 3600, GRANT_ALL)
                 if c.kind == "N2b"]
        self.assertEqual({c.wallet for c in cands}, {WB, WC})
        self.assertIn("Settlement expires in 52h", cands[0].msg)  # 72 - 20

    def test_n2c_not_before_60h_fires_at_60h(self):
        s = mk_settlement(emask=0b0110, cmask=0b0001)
        b = mk_bill_state([(WA, True), (WB, True), (WC, True)], s)
        # 59h59m: N2a/N2b beyond grace, N2c not yet due -> silence
        self.assertEqual(ne.evaluate_bill(b, T0 + 59 * 3600 + 3599, GRANT_ALL), [])
        cands = [c for c in ne.evaluate_bill(b, T0 + 60 * 3600, GRANT_ALL)
                 if c.kind == "N2c"]
        self.assertEqual({c.wallet for c in cands}, {WB, WC})
        self.assertIn("Last call: 12h left", cands[0].msg)
        self.assertIn("$15 escrow returns to the funder", cands[0].msg)

    def test_n2c_valid_at_68h_but_a_b_suppressed(self):
        s = mk_settlement(emask=0b0110, cmask=0b0001)
        b = mk_bill_state([(WA, True), (WB, True), (WC, True)], s)
        kinds = {c.kind for c in ne.evaluate_bill(b, T0 + 68 * 3600, GRANT_ALL)}
        self.assertEqual(kinds, {"N2c"})  # case 8 exception

    def test_fully_confirmed_pending_emits_no_n2(self):
        s = mk_settlement(emask=0b0111, cmask=0b0111)  # all confirmed but not executed
        b = mk_bill_state([(WA, True), (WB, True), (WC, True)], s)
        # fcat==0 keeps it out of N3a too; nothing to ask for
        self.assertEqual(ne.evaluate_bill(b, T0 + 3 * 3600, GRANT_ALL), [])

    def test_n3a_fires_window_plus_10min_owner_only(self):
        s = mk_settlement(emask=0b0111, cmask=0b0111, fcat=T0 + 3600)
        b = mk_bill_state([(WA, True), (WB, True), (WC, True)], s)
        due = T0 + 3600 + 3600 + 600  # fca + SETTLEMENT_WINDOW + N3A_EXTRA
        self.assertEqual(ne.evaluate_bill(b, due - 1, GRANT_ALL), [])
        cands = ne.evaluate_bill(b, due, GRANT_ALL)
        self.assertEqual([c.kind for c in cands], ["N3a"])
        self.assertEqual(cands[0].wallet, OWNER)  # owner only, not seats
        self.assertIn("One tap to open payouts", cands[0].msg)

    def test_n3b_wave1_at_6h_rank_priced(self):
        # settled; WA already claimed (bit0), WB rank1 $3.75, WC rank2 $1.25
        s = mk_settlement(settled=T0, emask=0b0111, cmask=0b0111, clmask=0b0001,
                          fcat=T0 - 10)
        b = mk_bill_state([(WA, True), (WB, True), (WC, True)], s)
        cands = [c for c in ne.evaluate_bill(b, T0 + 6 * 3600, GRANT_ALL)
                 if c.kind == "N3b"]
        by = {c.wallet: c for c in cands}
        self.assertEqual(set(by) , {WB, WC})  # WA claimed-out; none inactive
        self.assertIn("Your $3.75 payout is ready to claim", by[WB].msg)
        self.assertIn("Your $1.25 payout is ready to claim", by[WC].msg)
        self.assertEqual(by[WB].period, "0:1")

    def test_n3b_wave2_only_at_26h(self):
        s = mk_settlement(settled=T0, emask=0b0111, cmask=0b0111, clmask=0b0001,
                          fcat=T0 - 10)
        b = mk_bill_state([(WA, True), (WB, True), (WC, True)], s)
        cands = [c for c in ne.evaluate_bill(b, T0 + 26 * 3600, GRANT_ALL)
                 if c.kind == "N3b"]
        self.assertTrue(cands)
        self.assertEqual({c.period for c in cands}, {"0:2"})  # wave1 >6h overdue suppressed
        self.assertEqual({c.kind for c in cands}, {"N3b"})

    def test_n3b_short_payout_vector_degrades_to_zero(self):
        s = mk_settlement(settled=T0, payouts=[10_000_000], emask=0b0111,
                          cmask=0b0111, clmask=0, fcat=T0 - 10)
        b = mk_bill_state([(WA, True), (WB, True), (WC, True)], s)
        cands = [c for c in ne.evaluate_bill(b, T0 + 6 * 3600, GRANT_ALL)]
        by = {c.wallet: c for c in cands}
        self.assertIn("Your $10 payout", by[WA].msg)
        self.assertIn("Your $0 payout", by[WB].msg)  # rank 1 out of vector range

    def test_case1_fully_claimed_terminal(self):
        s = mk_settlement(settled=T0, emask=0b0111, cmask=0b0111, clmask=0b0111,
                          fcat=T0 - 10)
        b = mk_bill_state([(WA, True), (WB, True), (WC, True)], s)
        self.assertEqual(ne.evaluate_bill(b, T0 + 30 * 3600, GRANT_ALL), [])

    def test_case2_refunded_terminal(self):
        s = mk_settlement(emask=0b0111, cmask=0b0001, refunded=True)
        b = mk_bill_state([(WA, True), (WB, True), (WC, True)], s)
        cands = ne.evaluate_bill(b, T0 + 68 * 3600, GRANT_ALL)
        self.assertEqual([c for c in cands if c.kind.startswith("N2")
                          or c.kind.startswith("N3")], [])

    def test_case7_only_last_settlement_drives(self):
        # two settlements deep; second (sid 1) pending-confirm
        old = mk_settlement(settled=T0 - 100 * 3600, emask=0b0111, cmask=0b0111,
                            clmask=0b0111, fcat=T0 - 200 * 3600)
        new = mk_settlement(emask=0b0110, cmask=0b0001, init=T0)
        b = mk_bill_state([(WA, True), (WB, True), (WC, True)], new, set_count=2)
        # read path selects last_set=new (index set_count-1); sid stamped on candidates
        cands = ne.evaluate_bill(b, T0 + 2 * 3600, GRANT_ALL)
        self.assertTrue(cands)
        self.assertEqual({c.sid for c in cands}, {1})

    def test_case3_rotated_out_seat_excluded(self):
        s = mk_settlement(emask=0b0111, cmask=0b0011)  # WC (bit2) needs to confirm
        b = mk_bill_state([(WA, True), (WB, True), (WC, False)], s)
        cands = ne.evaluate_bill(b, T0 + 2 * 3600, GRANT_ALL)
        self.assertNotIn(WC, {c.wallet for c in cands})  # inactive gets nothing

    def test_case3_mask_bits_follow_contract_seat_ids(self):
        # Regression (found by this suite): mid-roster inactive seat used to shift
        # N2 mask bits positionally -> expected wallet silently missed (A) and an
        # inactive seat's bit misfired onto the next active wallet (B).
        s_gap = mk_settlement(emask=0b100, cmask=0)   # expected = seat id 2 (WC)
        b = mk_bill_state([(WA, True), (WB, False), (WC, True)], s_gap)
        cands = ne.evaluate_bill(b, T0 + 2 * 3600, GRANT_ALL)
        self.assertEqual({c.wallet for c in cands}, {WC},
                         "WC is contract seat 2; its N2a must survive the roster gap")
        s_orphan = mk_settlement(emask=0b010, cmask=0)  # expected = seat id 1 (WB, inactive)
        b = mk_bill_state([(WA, True), (WB, False), (WC, True)], s_orphan)
        cands = ne.evaluate_bill(b, T0 + 2 * 3600, GRANT_ALL)
        self.assertNotIn(WC, {c.wallet for c in cands},
                         "inactive WB's mask bit must NOT be charged to WC")

    def test_n1_requires_weekly_window_and_7d_stale(self):
        seats = [(WA, True), (WB, True)]
        expenses = [(5_000_000, MON15 - 8 * 86400, False)]
        b = mk_bill_state(seats, None, expenses=expenses)
        # Tuesday: no fire
        self.assertEqual(ne.evaluate_bill(b, MON15 + 86400, GRANT_ALL), [])
        # Monday 14:59:59: before window
        self.assertEqual(ne.evaluate_bill(b, MON15 - 1, GRANT_ALL), [])
        # Monday 15:00:01: fires (both granted seats)
        cands = ne.evaluate_bill(b, MON15 + 1, GRANT_ALL)
        self.assertEqual({c.kind for c in cands}, {"N1"})
        self.assertEqual({c.wallet for c in cands}, {WA, WB})
        # 6h grace boundary (inclusive at exactly 06:00:00 past)
        self.assertTrue(ne.evaluate_bill(b, MON15 + 6 * 3600, GRANT_ALL))
        self.assertEqual(ne.evaluate_bill(b, MON15 + 6 * 3600 + 1, GRANT_ALL), [])

    def test_n1_requires_7d_old_unsettled(self):
        seats = [(WA, True)]
        # elapsed at MON15+60 must stay UNDER 7d: backdate to 7d minus 121s
        b = mk_bill_state(seats, None,
                          expenses=[(5_000_000, MON15 - 7 * 86400 + 181, False)])
        self.assertEqual(ne.evaluate_bill(b, MON15 + 60, GRANT_ALL), [])
        b = mk_bill_state(seats, None, expenses=[(5_000_000, MON15 - 7 * 86400, False)])
        self.assertTrue(ne.evaluate_bill(b, MON15 + 60, GRANT_ALL))

    def test_n1_blocked_by_pending_settlement_and_ignores_settled_expense(self):
        s = mk_settlement(emask=0, cmask=0, init=T0)  # pending but nobody expected
        b = mk_bill_state([(WA, True)], s, expenses=[(1, MON15 - 8 * 86400, False)])
        # Monday bucket on an unrelated week: still zero because pending blocks N1
        self.assertEqual([c for c in ne.evaluate_bill(b, MON15 + 60, GRANT_ALL)
                          if c.kind == "N1"], [])
        b = mk_bill_state([(WA, True)], None, expenses=[(1, MON15 - 8 * 86400, True)])
        self.assertEqual(ne.evaluate_bill(b, MON15 + 60, GRANT_ALL), [])  # settled -> no digest

    def test_n1_grants_intersection(self):
        b = mk_bill_state([(WA, True), (WB, True)], None,
                          expenses=[(1, MON15 - 8 * 86400, False)])
        cands = ne.evaluate_bill(b, MON15 + 60, {WA})  # WB unverified -> case 4
        self.assertEqual([c.wallet for c in cands], [WA])


class TestFillN1(BaseCase):
    def bills(self, *specs):
        return specs

    def test_aggregate_copy_and_name_cap(self):
        mk = lambda addr, n_unsettled: {
            "bill": addr,
            "expenses_tail": [{"amount": 1, "paidBy": OWNER, "addedAt": T0,
                               "settled": False} for _ in range(n_unsettled)]}
        bills = [mk(BILL, 2), mk(BILL2, 1)]
        cands = [ne.Candidate("N1", BILL, 0, WA, "", MON15, "2026-W47"),
                 ne.Candidate("N1", BILL2, 0, WA, "", MON15, "2026-W47")]
        ne.fill_n1(cands, bills, MON15)
        msg = cands[0].msg
        self.assertIn("Still 3 unsettled across 2 bill(s)", msg)
        self.assertEqual(cands[1].msg, msg)  # wallet-level aggregate, same copy

    def test_more_than_three_bills_gets_plus_more(self):
        addrs = [f"0x{i:040x}" for i in range(1, 6)]
        bills = [{"bill": a, "expenses_tail": [{"amount": 1, "paidBy": OWNER,
                                                "addedAt": T0, "settled": False}]}
                 for a in addrs]
        cands = [ne.Candidate("N1", a, 0, WA, "", MON15, "2026-W47") for a in addrs]
        ne.fill_n1(cands, bills, MON15)
        msg = cands[0].msg
        self.assertIn("+2 more", msg)
        self.assertLessEqual(len(msg), 280)
        self.assertIn("Still 5 unsettled across 5 bill(s)", msg)


# ─── read_bill (RPC composition, guards, fallbacks) ───────────────────────────

class TestReadBill(BaseCase):
    def test_size_guard_over_40_seats_raises(self):
        seats = [(f"0x{i:040x}", True) for i in range(1, 42)]
        rpc = FakeRpc({BILL: BillSim(seats=seats)})
        with self.assertRaises(ne.RpcError):
            ne.read_bill(rpc, BILL)

    def test_window_revert_falls_back_to_literals(self):
        rpc = FakeRpc({BILL: BillSim(seats=[(WA, True)], window=None, max_hold=None)})
        b = ne.read_bill(rpc, BILL)
        self.assertEqual(b["window"], ne.SETTLEMENT_WINDOW)   # 3600
        self.assertEqual(b["max_hold"], ne.MAX_HOLD)           # 72h
        # and the fallback flows into N3a timing
        fca = T0 + 3600
        b["set_count"], b["last_set"] = 1, mk_settlement(
            emask=0b1, cmask=0b1, fcat=fca, seats=None) if False else mk_settlement(
            emask=0b1, cmask=0b1, fcat=fca)
        cands = ne.evaluate_bill(b, fca + 3600 + 600, {WA})
        self.assertEqual([c.kind for c in cands], ["N3a"])

    def test_reads_last_settlement_and_expense_tail(self):
        s1 = mk_settlement(init=T0 - 10, emask=0b01, total=1)
        s2 = mk_settlement(init=T0, emask=0b10, total=2)
        sim = BillSim(seats=[(WA, True)], settlements=[s1, s2],
                      expenses=[(10, T0, True), (20, T0, False)])
        b = ne.read_bill(FakeRpc({BILL: sim}), BILL)
        self.assertEqual(b["set_count"], 2)
        self.assertEqual(b["last_set"], s2)
        self.assertEqual(b["expenses_tail"], [
            {"amount": 10, "paidBy": OWNER, "addedAt": T0, "settled": True},
            {"amount": 20, "paidBy": OWNER, "addedAt": T0, "settled": False}])
        self.assertEqual(b["owner"], OWNER)
        self.assertEqual(b["seats"][0]["wallet"], WA)


# ─── Payload contract (§7 shape) ──────────────────────────────────────────────

class TestPayload(BaseCase):
    def test_exact_shape(self):
        p = ne.notify_payload([WA, WB], "title", "body", "idem-1")
        self.assertEqual(set(p), {"wallet_addresses", "localisations",
                                  "mini_app_path", "idempotency_key"})
        self.assertEqual(p["localisations"],
                         [{"language": "en", "title": "title", "message": "body"}])
        self.assertEqual(p["mini_app_path"], "/home")
        self.assertEqual(p["wallet_addresses"], [WA, WB])

    def test_clamps(self):
        p = ne.notify_payload([WA], "t" * 100, "m" * 400, "k")
        self.assertEqual(len(p["localisations"][0]["title"]), 72)
        self.assertEqual(len(p["localisations"][0]["message"]), 280)


# ─── group_batches (§4 batching) ──────────────────────────────────────────────

class TestBatches(BaseCase):
    def c(self, kind, wallet, msg="same", sid=0, period="0", bill=BILL):
        return ne.Candidate(kind, bill, sid, wallet, msg, T0, period)

    def test_chunking_at_200(self):
        wallets = [f"0x{i:040x}" for i in range(1, 251)]
        cands = [self.c("N2a", wl) for wl in wallets]
        batches = ne.group_batches(cands)
        self.assertEqual([len(b["wallets"]) for b in batches], [200, 50])
        self.assertTrue(batches[0]["idem"].endswith(":b0"))
        self.assertTrue(batches[1]["idem"].endswith(":b200"))

    def test_single_wallet_idem_uses_wallet(self):
        b = ne.group_batches([self.c("N2a", WA)])[0]
        self.assertEqual(b["idem"], f"n2a:{BILL}:0:{WA}")

    def test_n1_and_n3a_idem_forms(self):
        b1 = ne.group_batches([self.c("N1", WA, period="2026-W47")])[0]
        self.assertEqual(b1["idem"], f"n1:2026-W47:{WA}")
        b3 = ne.group_batches([self.c("N3a", OWNER, period="0")])[0]
        self.assertEqual(b3["idem"], f"n3a:{BILL}:0")

    def test_distinct_messages_split_batches(self):
        cands = [self.c("N2a", WA, msg="a"), self.c("N2a", WB, msg="b")]
        self.assertEqual(len(ne.group_batches(cands)), 2)

    def test_priority_ordering_of_batches(self):
        cands = [self.c("N1", WA, msg="n1"), self.c("N2c", WB, msg="last"),
                 self.c("N3b", WC, msg="claim", period="0:1")]
        kinds = [b["kind"] for b in ne.group_batches(cands)]
        self.assertEqual(kinds, ["N2c", "N3b", "N1"])


# ─── select_within_caps (§4) ──────────────────────────────────────────────────

class TestCaps(BaseCase):
    def setUp(self):
        super().setUp()
        self.make_ledger(bills=[BILL])

    def c(self, kind, wallet=WA, due=T0, bill=BILL, sid=0, period="0"):
        return ne.Candidate(kind, bill, sid, wallet, "m", due, period)

    def select(self, cands, now_ts=T0, verified=False):
        db = ne.get_db()
        try:
            return ne.select_within_caps(cands, db, now_ts, verified)
        finally:
            db.close()

    def test_wallet_cap_blocks_third_send_in_24h(self):
        self.seed_sent(WB, count=2, at=T0 - 100)
        self.assertEqual(self.select([self.c("N2a", WB)]), [])

    def test_cap_window_boundary_exclusive_at_24h_exactly(self):
        # sent_at > now-86400: a row exactly 24h old has aged out of the cap
        self.seed_sent(WB, count=2, at=T0 - 86400)
        self.assertEqual(len(self.select([self.c("N2a", WB)])), 1)

    def test_n2c_beats_n1_for_last_slot(self):
        # spec §4: "never drop an N2c in favor of an N1"
        self.seed_sent(WB, count=1, at=T0 - 100)
        picked = self.select([self.c("N1", WB, due=T0 - 500, period="2026-W47"),
                              self.c("N2c", WB, due=T0 - 100)])
        self.assertEqual([c.kind for c in picked], ["N2c"])

    def test_n3b_beats_n1_for_last_slot(self):
        self.seed_sent(WB, count=1, at=T0 - 100)
        picked = self.select([self.c("N1", WB, period="2026-W47"),
                              self.c("N3b", WB, period="0:2")])
        self.assertEqual([c.kind for c in picked], ["N3b"])

    def test_sent_and_failed_rows_never_resent(self):
        db = ne.get_db()
        db.execute("INSERT INTO nudge_state (dedup_key,period,status) "
                   "VALUES (?,?, 'sent')", (self.c("N2a").dedup_key(), "0"))
        db.execute("INSERT INTO nudge_state (dedup_key,period,status,attempts) "
                   "VALUES (?,?, 'failed', 3)",
                   (self.c("N2b", WB).dedup_key(), "0"))
        db.commit()
        db.close()
        self.assertEqual(self.select([self.c("N2a"), self.c("N2b", WB)]), [])

    def test_queued_rows_are_reselectable(self):
        db = ne.get_db()
        db.execute("INSERT INTO nudge_state (dedup_key,period,status,attempts) "
                   "VALUES (?,?, 'queued', 1)", (self.c("N2a").dedup_key(), "0"))
        db.commit()
        db.close()
        self.assertEqual(len(self.select([self.c("N2a")])), 1)

    def test_ramp_blocks_41st_new_wallet_in_4h(self):
        for i in range(40):
            self.seed_sent(f"0x{i:040x}", count=1, at=T0 - 60, key_prefix=f"r{i}")
        fresh = self.c("N2a", "0x" + "ee" * 20)
        self.assertEqual(self.select([fresh]), [])
        # already-sent wallet is NOT blocked by the ramp (only by its own cap)
        known = self.c("N2a", "0x0000000000000000000000000000000000000001")
        self.assertEqual(len(self.select([known])), 1)

    def test_ramp_admits_exactly_to_40(self):
        for i in range(39):
            self.seed_sent(f"0x{i:040x}", count=1, at=T0 - 60, key_prefix=f"r{i}")
        a = self.c("N2a", "0x" + "aa" * 20)
        b = self.c("N2a", "0x" + "bb" * 20)
        picked = self.select([a, b])
        self.assertEqual(len(picked), 1, "39 used -> exactly one new wallet admits")

    def test_verified_flag_lifts_ramp(self):
        for i in range(40):
            self.seed_sent(f"0x{i:040x}", count=1, at=T0 - 60, key_prefix=f"r{i}")
        fresh = self.c("N2a", "0x" + "ee" * 20)
        self.assertEqual(len(self.select([fresh], verified=True)), 1)

    def test_rows_older_than_4h_dont_count_toward_ramp(self):
        for i in range(40):
            self.seed_sent(f"0x{i:040x}", count=1, at=T0 - 4 * 3600 - 60,
                           key_prefix=f"r{i}")
        fresh = self.c("N2a", "0x" + "ee" * 20)
        self.assertEqual(len(self.select([fresh])), 1)


# ─── run_once: full state machine (§5) through the real code path ─────────────

class TestRunOnce(BaseCase):
    def pending_setup(self, s=None, seats=((WA, True), (WB, True), (WC, False))):
        s = s or mk_settlement(emask=0b0011, cmask=0, init=T0)  # WA+WB expected
        self.make_ledger(bills=[BILL], grants={BILL: [WA, WB]})
        return {BILL: BillSim(seats=list(seats), settlements=[s])}

    def test_send_disabled_is_plan_only_zero_writes(self):
        sims = self.pending_setup()
        stats, posted = self.tick(sims, T0 + 2 * 3600, send=False, key=None)
        self.assertTrue(stats["disabled"])
        self.assertGreater(stats["candidates"], 0)
        self.assertEqual(posted, [])
        self.assertEqual(self.rows(), [])  # nudge_state untouched

    def test_successful_send_writes_sent_state(self):
        sims = self.pending_setup()
        stats, posted = self.tick(sims, T0 + 2 * 3600)
        self.assertEqual(stats["sent"], 2)          # WA + WB (WC ungranted+inactive)
        self.assertEqual(len(posted), 1)            # same copy -> one batch, both wallets
        self.assertEqual(sorted(posted[0]["wallet_addresses"]), sorted([WA, WB]))
        for p in posted:
            self.assertEqual(set(p), {"wallet_addresses", "localisations",
                                      "mini_app_path", "idempotency_key"})
            self.assertTrue(p["idempotency_key"].startswith("n2a:"))
        rows = self.rows()
        self.assertEqual({r["status"] for r in rows}, {"sent"})
        self.assertEqual({r["wallet_address"] for r in rows}, {WA, WB})
        for r in rows:
            self.assertEqual(r["sent_at"], ne._ts_iso(T0 + 2 * 3600))
            self.assertEqual(r["attempts"], 0)

    def test_case11_dedup_across_two_consecutive_runs(self):
        sims = self.pending_setup()
        stats1, posted1 = self.tick(sims, T0 + 2 * 3600)
        self.assertEqual(stats1["sent"], 2)
        stats2, posted2 = self.tick(sims, T0 + 2 * 3600 + 1800)  # next 30-min tick
        self.assertEqual(stats2["sent"], 0)
        self.assertEqual(posted2, [])
        self.assertEqual(len(self.rows()), 2)  # replay adds nothing

    def test_insert_first_ordering_visible_to_dispatcher(self):
        # §5 crash-safety: rows must be durable as 'queued' BEFORE the POST happens
        sims = self.pending_setup()
        os.environ["NOTIFY_INTERNAL_KEY"] = "test-key"
        observed = {}

        def post(url, headers, payload):
            db = sqlite3.connect(ne.DB_PATH)
            rows = db.execute("SELECT status, COUNT(*) c FROM nudge_state "
                              "GROUP BY status").fetchall()
            observed["during_post"] = dict(rows)
            db.close()
            return 200, {"ok": True}

        ne.run_once(now_ts=T0 + 2 * 3600, rpc=FakeRpc(sims), post=post, send=True,
                    quiet=True)
        self.assertEqual(observed["during_post"].get("queued"), 2)
        self.assertEqual({r["status"] for r in self.rows()}, {"sent"})

    def test_deduped_true_counts_as_sent(self):
        # §5 at-least-once backstop: dispatcher {deduped:true} on a retry payload
        # must close the rows as 'sent', not leave them queued forever
        sims = self.pending_setup()
        os.environ["NOTIFY_INTERNAL_KEY"] = "test-key"
        posted, _, post = self.armed_post(code=200, body={"deduped": True})
        stats = ne.run_once(now_ts=T0 + 2 * 3600, rpc=FakeRpc(sims), post=post,
                            send=True, quiet=True)
        self.assertEqual(stats["sent"], 2)
        self.assertEqual(len(posted), 1)
        for r in self.rows():
            self.assertEqual(r["status"], "sent")

    def test_transport_exception_bumps_attempts_keeps_queued(self):
        sims = self.pending_setup()
        os.environ["NOTIFY_INTERNAL_KEY"] = "test-key"
        boom = ConnectionResetError("dispatcher died mid-flight")

        def post(url, headers, payload):
            raise boom

        stats = ne.run_once(now_ts=T0 + 2 * 3600, rpc=FakeRpc(sims), post=post,
                            send=True, quiet=True)
        rows = self.rows()
        self.assertTrue(rows)
        for r in rows:
            self.assertEqual(r["status"], "queued")
            self.assertEqual(r["attempts"], 1)
        self.assertEqual(stats["sent"], 0)

    def test_dead_letter_after_three_attempts_then_never_retried(self):
        sims = self.pending_setup()
        os.environ["NOTIFY_INTERNAL_KEY"] = "test-key"
        for i in range(3):
            ne.run_once(now_ts=T0 + 2 * 3600 + i * 1800,
                        rpc=FakeRpc(sims),
                        post=lambda u, h, p: (500, {"error": "boom"}),
                        send=True, quiet=True)
        rows = self.rows()
        self.assertTrue(rows)
        for r in rows:
            self.assertEqual(r["status"], "failed")
            self.assertEqual(r["attempts"], 3)
        # a WORKING dispatcher must not resurrect failed rows
        stats, posted = self.tick(sims, T0 + 2 * 3600 + 5400)
        self.assertEqual(posted, [])
        self.assertEqual(stats["sent"], 0)

    def test_case10_501_stays_queued_retryable(self):
        sims = self.pending_setup()
        os.environ["NOTIFY_INTERNAL_KEY"] = "test-key"
        stats = ne.run_once(now_ts=T0 + 2 * 3600, rpc=FakeRpc(sims),
                            post=lambda u, h, p: (501, {"error": "not configured"}),
                            send=True, quiet=True)
        rows = self.rows()
        self.assertTrue(rows)
        for r in rows:
            self.assertEqual(r["status"], "queued")   # never sent, never dead yet
            self.assertEqual(r["attempts"], 1)
        self.assertTrue(any("retry" in n for n in stats["notes"]))

    def test_missing_key_keeps_queued_zero_posts(self):
        sims = self.pending_setup()
        stats, posted = self.tick(sims, T0 + 2 * 3600, key=None)
        self.assertEqual(posted, [])
        self.assertTrue(any("NOTIFY_INTERNAL_KEY" in n for n in stats["notes"]))
        for r in self.rows():
            self.assertEqual(r["status"], "queued")
            self.assertEqual(r["attempts"], 0)

    def test_key_file_fallback_used_as_bearer(self):
        sims = self.pending_setup()
        keyfile = self.tmp / "runtime_key.txt"
        keyfile.write_text("file-issued-key\n")
        ne.NOTIFY_INTERNAL_KEY_FILE = keyfile
        posted, seen, post = self.armed_post()
        stats = ne.run_once(now_ts=T0 + 2 * 3600, rpc=FakeRpc(sims), post=post,
                            send=True, quiet=True)
        self.assertEqual(stats["sent"], 2)
        self.assertTrue(seen, "expected at least one POST")
        for h in seen:
            self.assertEqual(h["Authorization"], "Bearer file-issued-key")

    def test_case6_dead_bill_skipped_others_still_send(self):
        sA = mk_settlement(emask=0b0011, cmask=0, init=T0)
        self.make_ledger(bills=[BILL, BILL2], grants={BILL: [WA, WB], BILL2: [WA]})
        sims = {BILL: BillSim(seats=[(WA, True), (WB, True), (WC, False)],
                              settlements=[sA]),
                BILL2: BillSim(dead=True)}
        stats, posted = self.tick(sims, T0 + 2 * 3600)
        self.assertEqual(stats["skipped"], 1)
        self.assertEqual(stats["bills"], 1)
        self.assertTrue(all(BILL in p["idempotency_key"] for p in posted))

    def test_case5_pending_and_null_rows_never_read(self):
        sims = self.pending_setup()
        stats, _ = self.tick(sims, T0 + 2 * 3600)
        self.assertEqual(stats["bills"], 1)  # ledger also holds 'pending' + NULL addr rows

    def test_case4_no_state_rows_for_ungranted_wallets(self):
        # WC is an active seat but ungranted here; must appear nowhere
        sims = self.pending_setup(s=mk_settlement(emask=0b0111, cmask=0, init=T0),
                                  seats=((WA, True), (WB, True), (WC, True)))
        stats, posted = self.tick(sims, T0 + 2 * 3600)
        self.assertNotIn(WC, {r["wallet_address"] for r in self.rows()})
        for p in posted:
            self.assertNotIn(WC, p["wallet_addresses"])

    def test_wallet_cap_enforced_through_run_path(self):
        # one prior send/24h each; wave1 (+6h) admits (used->2); wave2 (+26h, still
        # inside the rolling 24h of both prior rows) is blocked by the hard cap
        s = mk_settlement(settled=T0, emask=0b0011, cmask=0b0011, clmask=0,
                          fcat=T0 - 10)
        self.make_ledger(bills=[BILL], grants={BILL: [WA, WB]})
        self.seed_sent(WA, count=1, at=T0 + 5 * 3600, kind="N2a")
        self.seed_sent(WB, count=1, at=T0 + 5 * 3600, kind="N2a")
        sims = {BILL: BillSim(seats=[(WA, True), (WB, True)], settlements=[s])}
        stats1, _ = self.tick(sims, T0 + 6 * 3600)           # wave1: 2 sent (used=2)
        self.assertEqual(stats1["sent"], 2)
        stats2, posted2 = self.tick(sims, T0 + 26 * 3600)    # wave2: capped out
        self.assertEqual(stats2["sent"], 0)
        self.assertEqual(posted2, [])

    def test_ramp_enforced_through_run_path_and_verified_lifts(self):
        s = mk_settlement(emask=0b0011, cmask=0, init=T0)
        self.make_ledger(bills=[BILL], grants={BILL: [WA, WB]})
        for i in range(40):
            self.seed_sent(f"0x{i:040x}", count=1, at=T0 + 2 * 3600 - 60,
                           key_prefix=f"rp{i}")
        sims = {BILL: BillSim(seats=[(WA, True), (WB, True), (WC, False)],
                              settlements=[s])}
        stats, posted = self.tick(sims, T0 + 2 * 3600)
        self.assertEqual(stats["candidates"], 0)
        self.assertEqual(posted, [])
        os.environ["TANDA_NUDGE_VERIFIED"] = "1"
        stats2, posted2 = self.tick(sims, T0 + 2 * 3600 + 1)
        self.assertEqual(stats2["sent"], 2)  # ramp lifted; caps still fine (fresh wallets)

    def test_n1_full_cycle_weekly_dedup(self):
        self.make_ledger(bills=[BILL], grants={BILL: [WA, WB]})
        sims = {BILL: BillSim(seats=[(WA, True), (WB, True)],
                              expenses=[(5_000_000, MON15 - 8 * 86400, False),
                                        (1_000_000, MON15 - 8 * 86400, False)])}
        stats, posted = self.tick(sims, MON15 + 60)
        self.assertEqual(stats["sent"], 2)
        self.assertIn("Still 2 unsettled across 1 bill(s)",
                      posted[0]["localisations"][0]["message"])
        # second tick same week: dedup
        stats2, posted2 = self.tick(sims, MON15 + 60 + 1800)
        self.assertEqual((stats2["sent"], posted2), (0, []))
        # next Monday: new key fires again
        stats3, _ = self.tick(sims, MON15 + 7 * 86400 + 60)
        self.assertEqual(stats3["sent"], 2)

    def test_nudge_state_table_created_idempotently(self):
        self.make_ledger(bills=[BILL])
        db1 = ne.get_db()
        db2 = ne.get_db()  # CREATE IF NOT EXISTS twice = no error
        db1.close()
        n = db2.execute("SELECT COUNT(*) FROM nudge_state").fetchone()[0]
        db2.close()
        self.assertEqual(n, 0)


# ─── get_db / DB_PATH hardening (parent-run guards) ───────────────────────────

class TestLedgerGuards(BaseCase):
    def test_missing_db_exits_without_creating_file(self):
        missing = self.tmp / "sub" / "typo_ledger.db"
        ne.DB_PATH = missing
        with self.assertRaises(SystemExit):
            ne.get_db()
        self.assertFalse(missing.exists())  # fail-fast must not touch the FS

    def test_db_without_bill_index_table_rejected(self):
        other = self.tmp / "empty.db"
        sqlite3.connect(other).close()  # valid sqlite file, no bill_index
        ne.DB_PATH = other
        with self.assertRaises(SystemExit):
            ne.get_db()

    def test_db_path_env_chain(self):
        import importlib
        saved = dict(ne.__dict__["DB_PATH"]) if False else ne.DB_PATH
        try:
            os.environ["BILL_INDEX_DB"] = str(self.tmp / "house.db")
            importlib.reload(ne)
            self.assertEqual(str(ne.DB_PATH), str(self.tmp / "house.db"))
            os.environ["TANDA_NUDGE_DB"] = str(self.tmp / "override.db")
            importlib.reload(ne)
            self.assertEqual(str(ne.DB_PATH), str(self.tmp / "override.db"))
        finally:
            os.environ.pop("TANDA_NUDGE_DB", None)
            os.environ.pop("BILL_INDEX_DB", None)
            importlib.reload(ne)
            ne.DB_PATH = saved  # restore per-test isolation


# ─── CLI / subprocess: kill-switch truth (spec §2) ────────────────────────────

class TestCli(unittest.TestCase):
    def _env(self, **over):
        env = os.environ.copy()
        for k in ("TANDA_NUDGE_ENABLED", "TANDA_NUDGE_DRY_RUN", "TANDA_NUDGE_DB",
                  "BILL_INDEX_DB", "TANDA_NUDGE_VERIFIED", "NOTIFY_INTERNAL_KEY"):
            env.pop(k, None)
        env.update({k: v for k, v in over.items() if v is not None})
        return env

    def test_default_off_touches_nothing(self):
        tmp = Path(tempfile.mkdtemp(prefix="nudge_cli_"))
        missing = tmp / "does_not_exist.db"
        r = subprocess.run([sys.executable, str(ENGINE), "--once"],
                           env=self._env(TANDA_NUDGE_DB=str(missing)),
                           capture_output=True, timeout=60)
        self.assertEqual(r.returncode, 0)
        self.assertIn(b"no-op", r.stdout)
        self.assertFalse(missing.exists())  # proves: no DB open before the flag check

    def test_shipped_self_test_still_green(self):
        # the engine's own offline suite is a regression gate for this PR's fix
        r = subprocess.run([sys.executable, str(ENGINE), "--self-test"],
                           env=self._env(), capture_output=True, timeout=120)
        self.assertEqual(r.returncode, 0, r.stdout.decode() + r.stderr.decode())
        self.assertIn(b"SELF-TEST OK", r.stdout)


if __name__ == "__main__":
    unittest.main(verbosity=2)
