#!/usr/bin/env python3
"""P1.3 contract-view test for the P0.1 split-lock coverage (kanban t_3ca1d4c5).

Deterministic PARSE-LEVEL repro: recovers the ratified split-lock gate structure
directly from the shipped Solidity source (contracts/TandaBillV2.sol) with
stdlib regex only, grounds a small Python decision model on the exact predicate
text, then replays the 7-arm x outcome ledger of test/P13SplitLockCoverage.t.sol
(PR #15 @ 6727aa543, kanban t_p13a/t_p13b) against that model. If the contract
text ever drifts from the ratified semantics, the grounding asserts fire before
the ledger simulation can pass.

ZERO GPU, ZERO forge/solc invocation, ZERO network, ZERO model load.
Deliberately imports NO engine: unlike tests/test_nudge_engine.py this suite
touches nothing under services/ — stdlib re/unittest/pathlib only.

Provenance (authoritative, ratified 2026-11-16):
  - docs/FLUX_RULING_P01_ROTATION_2026-11-16.md                  (Q1-Q4 + spec)
  - docs/proposals/TANDA_P01_ROTATION_PATCH_DRAFT.md             (delta table)
  - test/P13SplitLockCoverage.t.sol                              (forge ledger)
RATIFIED SPLIT-LOCK (RESOLUTION 2026-11-16b): the lock arms ONLY on the LAST
settlement with settledAt == 0 && !refunded && fullyConfirmedAt != 0;
    (1) no settlements          -> lock block skipped, all paths open
    (2) fullyConfirmedAt == 0   -> not armed (pre-confirm AND partial coverage:
                                   per-seat confirms do NOT lock; unconfirmed
                                   seats may always fix their own payout wallet)
    (3) armed, owner-driven on another seat -> RotationWindowLocked, strict
        THROUGH executability until executed/refunded
    (4) armed, confirmed-seat SELF inside the 1h window -> RotationWindowLocked
    (5) armed, confirmed-seat SELF after window, pre-execution -> open
    (6) settledAt != 0          -> every path SeatRotationClosed (post-execute)
    (7) refunded                -> every path SeatRotationClosed (MAX_HOLD leg)
Caller-identity gate (seat wallet or owner, else NotSeatOrOwner) is evaluated
BEFORE the lock and is independent of settlement state.

Run standalone:
    python -m unittest tests.test_p13_split_lock_coverage -v
Run with the suite:
    python -m unittest discover -s tests -v
"""
import re
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CONTRACT = ROOT / "contracts" / "TandaBillV2.sol"
FORGE_LEDGER = ROOT / "test" / "P13SplitLockCoverage.t.sol"

# Fixed epoch for every simulated timestamp (determinism — nothing reads a clock).
T0 = 1_763_400_000

SECONDS_PER_HOUR = 3600


# ─── Source parsing helpers (stdlib regex only) ──────────────────────────────

def _strip_comments(text: str) -> str:
    text = re.sub(r"/\*.*?\*/", "", text, flags=re.S)
    text = re.sub(r"//[^\n]*", "", text)
    return text


def _extract_function(clean_src: str, name: str) -> str:
    """Return `function name(...) ... { ... }` with brace-balanced slicing."""
    i = clean_src.index(f"function {name}(")
    j = clean_src.index("{", i)
    depth = 0
    for k in range(j, len(clean_src)):
        if clean_src[k] == "{":
            depth += 1
        elif clean_src[k] == "}":
            depth -= 1
            if depth == 0:
                return clean_src[i:k + 1]
    raise AssertionError(f"unbalanced braces extracting function {name}")


SRC = _strip_comments(CONTRACT.read_text(encoding="utf-8").replace("\r\n", "\n"))
ROTATE = _extract_function(SRC, "rotateSeatWallet")
CONFIRM = _extract_function(SRC, "confirmSettlement")
EXECUTE = _extract_function(SRC, "executeSettlement")
CLAIM = _extract_function(SRC, "claimSettlement")
REFUND = _extract_function(SRC, "refundSettlement")


def _constant_seconds(name: str) -> int:
    m = re.search(rf"uint64 public constant {name} = (\d+) hours;", SRC)
    assert m, f"{name} constant not found or not expressed in hours"
    return int(m.group(1)) * SECONDS_PER_HOUR


WINDOW = _constant_seconds("SETTLEMENT_WINDOW")   # ratified: 1 hour
MAX_HOLD = _constant_seconds("MAX_HOLD")          # ratified: 72 hours


# ─── Gate-model grounding: every model branch must match shipped source text ──
# (model is DERIVED from the contract, not a copy of it: if a predicate changes
#  shape, the corresponding regex stops matching and the suite fails loudly.)

GROUNDED = {
    "not_found":      r"if \(seatId >= seats\.length\) revert SeatNotFound\(seatId\);",
    "inactive":       r"if \(!seats\[seatId\]\.active\) revert SeatInactive\(seatId\);",
    "zero_wallet":    r"if \(newWallet == address\(0\)\) revert ZeroWallet\(\);",
    "caller_resolve": r"address caller = _caller\(\);",
    "identity_gate":  r"if \(caller != seats\[seatId\]\.wallet && caller != owner\) "
                      r"revert NotSeatOrOwner\(\);",
    "any_settlement": r"if \(settlements\.length > 0\) \{",
    "last_only":      r"Settlement storage last = settlements\[settlements\.length - 1\];",
    "closed_gate":    r"if \(last\.settledAt != 0 \|\| last\.refunded\) revert SeatRotationClosed\(\);",
    "arm_gate":       r"if \(last\.fullyConfirmedAt != 0\) \{",
    "window_pred":    r"bool inWindow = block\.timestamp < uint256\(last\.fullyConfirmedAt\) "
                      r"\+ SETTLEMENT_WINDOW;",
    "owner_locked":   r"if \(caller != seats\[seatId\]\.wallet && caller == owner\) "
                      r"revert RotationWindowLocked\(\);",
    "self_locked":    r"if \(caller == seats\[seatId\]\.wallet && inWindow\s*&& "
                      r"\(last\.confirmedMask & \(uint256\(1\) << seatId\)\) != 0\) "
                      r"revert RotationWindowLocked\(\);",
    "dup_gate":       r"if \(seatIdOf\[newWallet\] != 0\) revert DuplicateSeat\(newWallet\);",
    "cei_clear_old":  r"seatIdOf\[old\] = 0;",
    "cei_set_wallet": r"seats\[seatId\]\.wallet = newWallet;",
    "cei_map_new":    r"seatIdOf\[newWallet\] = seatId \+ 1;",
    "emit_rotation":  r"emit SeatWalletRotated\(seatId, old, newWallet\);",
}


def _positions(body: str) -> dict:
    """Locate every grounding regex inside a function body; fail on any miss."""
    pos = {}
    for key, pat in GROUNDED.items():
        m = re.search(pat, body)
        if not m:
            raise AssertionError(
                f"grounding regex for {key!r} no longer matches the shipped "
                f"rotateSeatWallet source — split-lock semantics drifted: {pat}")
        pos[key] = m.start()
    return pos


POS = _positions(ROTATE)


def rotate_decide(*, n_settlements: int, settled_at: int, refunded: bool,
                  fully_confirmed_at: int, confirmed_mask: int, seat_id: int,
                  now: int, window: int, caller_is_seat: bool,
                  caller_is_owner: bool, duplicate_target: bool) -> str:
    """Faithful decision model of the shipped split-lock arm of rotateSeatWallet.

    Returns the first error selector the contract would revert with, or "OK".
    Every branch below is pinned 1:1 to a GROUNDED regex matched in POS, and the
    evaluation order equals the source-text order asserted in TestGateOrdering.
    """
    if not (caller_is_seat or caller_is_owner):        # identity_gate (before lock)
        return "NotSeatOrOwner"
    if n_settlements > 0:                              # any_settlement
        if settled_at != 0 or refunded:                # closed_gate
            return "SeatRotationClosed"
        if fully_confirmed_at != 0:                    # arm_gate
            in_window = now < fully_confirmed_at + window  # window_pred
            if (not caller_is_seat) and caller_is_owner:   # owner_locked
                return "RotationWindowLocked"
            if caller_is_seat and in_window \
                    and (confirmed_mask >> seat_id) & 1:   # self_locked
                return "RotationWindowLocked"
    if duplicate_target:                               # dup_gate
        return "DuplicateSeat"
    return "OK"                                        # emit_rotation path


# ─── Ledger states (mirrors P13SplitLockCoverage.t.sol actor scheme:           ─
#     owner is creator AND seat 0; 4 seats; expectedMask = 0b1111 unless the    ─
#     seat was inactive at initiation).                                         ─

FULL_MASK = 0b1111
ARMED_IN_WINDOW = dict(n_settlements=1, settled_at=0, refunded=False,
                       fully_confirmed_at=T0, confirmed_mask=FULL_MASK,
                       now=T0 + WINDOW // 2)           # mid-window
ARMED_PAST_WINDOW = dict(ARMED_IN_WINDOW, now=T0 + WINDOW + 1)
PRE_CONFIRM = dict(n_settlements=1, settled_at=0, refunded=False,
                   fully_confirmed_at=0, confirmed_mask=0, now=T0)
PARTIAL = dict(PRE_CONFIRM, confirmed_mask=0b0011)     # seats 0,1 confirmed only
EXECUTED = dict(ARMED_PAST_WINDOW, settled_at=T0 + 2 * WINDOW)
REFUNDED = dict(n_settlements=1, settled_at=0, refunded=True,
                fully_confirmed_at=0, confirmed_mask=0, now=T0 + MAX_HOLD)
NO_SETTLEMENTS = dict(n_settlements=0, settled_at=0, refunded=False,
                      fully_confirmed_at=0, confirmed_mask=0, now=T0)

CALLERS = {
    "self":           dict(caller_is_seat=True,  caller_is_owner=False),
    "owner_as_seat0": dict(caller_is_seat=True,  caller_is_owner=True),
    "owner_other":    dict(caller_is_seat=False, caller_is_owner=True),
    "stranger":       dict(caller_is_seat=False, caller_is_owner=False),
}


def decide(state: dict, *, seat_id: int, caller: str, duplicate: bool = False) -> str:
    kw = dict(state)
    kw.update(seat_id=seat_id, window=WINDOW, duplicate_target=duplicate,
              **CALLERS[caller])
    return rotate_decide(**kw)


class TestModelGrounding(unittest.TestCase):
    """The Python model is a derived artifact of the shipped source text."""

    def test_all_predicates_ground_in_contract(self):
        # _positions() raises on any miss; reaching here proves 17/17 grounded.
        self.assertEqual(len(POS), len(GROUNDED))

    def test_rationale_constants_are_ratted_values(self):
        self.assertEqual(WINDOW, 3600)     # 1 hour hold after full confirmation
        self.assertEqual(MAX_HOLD, 72 * 3600)  # refund escape leg (arm 7 context)

    def test_single_active_settlement_deviation(self):
        # Recorded delta: ruling spec looped ALL settlements; shipped inspects
        # only settlements[last]. If a loop ever reappears inside rotate, fail.
        self.assertNotIn("for (uint256 i", ROTATE)
        self.assertIn("settlements[settlements.length - 1]", ROTATE)


class TestGateOrdering(unittest.TestCase):
    """Guard sequence in rotateSeatWallet must equal the ratified evaluation order."""

    ORDER = ["not_found", "inactive", "zero_wallet", "caller_resolve",
             "identity_gate", "any_settlement", "last_only", "closed_gate",
             "arm_gate", "window_pred", "owner_locked", "self_locked",
             "dup_gate", "cei_clear_old", "cei_set_wallet", "cei_map_new",
             "emit_rotation"]

    def test_guards_fire_in_declared_sequence(self):
        seq = [POS[k] for k in self.ORDER]
        self.assertEqual(seq, sorted(seq),
                         "rotateSeatWallet guard order drifted from ratified "
                         "identity -> closed -> window-lock -> duplicate -> CEI -> emit")

    def test_identity_gate_precedes_settlement_state(self):
        self.assertLess(POS["identity_gate"], POS["any_settlement"])

    def test_close_gate_precedes_window_lock(self):
        # Arms 6/7 answer SeatRotationClosed even where the window rule would lock.
        self.assertLess(POS["closed_gate"], POS["arm_gate"])

    def test_window_lock_precedes_duplicate_check(self):
        self.assertLess(POS["self_locked"], POS["dup_gate"])

    def test_cei_effect_before_emit(self):
        self.assertLess(POS["cei_clear_old"], POS["cei_set_wallet"])
        self.assertLess(POS["cei_set_wallet"], POS["cei_map_new"])
        self.assertLess(POS["cei_map_new"], POS["emit_rotation"])

    def test_rotation_never_touches_confirm_state(self):
        # Immutable trail (ruling Q2.2): rotateSeatWallet reads confirmedMask for
        # the lock but must never write any mask.
        self.assertNotIn("confirmedMask =", ROTATE)
        self.assertNotIn("claimedMask", ROTATE)


class TestContractViewSurface(unittest.TestCase):
    """Declared surface the P0.1 split-lock contract view is expressed through."""

    def test_errors_declared_bare_as_shipped(self):
        for decl in ("error SeatNotFound(uint256 seatId);",
                     "error SeatInactive(uint256 seatId);",
                     "error DuplicateSeat(address wallet);",
                     "error ZeroWallet();",
                     "error NotSeatOrOwner();",
                     "error SeatRotationClosed();",
                     "error RotationWindowLocked();"):
            self.assertIn(decl, SRC, f"missing error declaration: {decl}")
        # Ratified deviation: bare RotationWindowLocked(), NOT the ruling spec's
        # (uint256 settlementId) shape.
        self.assertIn("error RotationWindowLocked();", SRC)
        self.assertNotIn("error RotationWindowLocked(uint256", SRC)

    def test_event_shipped_as_three_arg(self):
        # Documented deviation: ruling proposed a 4th `uint64 at` param — not shipped.
        self.assertIn("event SeatWalletRotated(uint256 indexed seatId, "
                      "address indexed from, address indexed to);", SRC)
        self.assertNotIn("SeatWalletRotated(uint256 indexed seatId, address indexed from, "
                         "address indexed to, uint64", SRC)

    def test_settlement_struct_fields(self):
        m = re.search(r"struct Settlement \{([^}]*)\}", SRC)
        if m is None:
            self.fail("struct Settlement not found in contract source")
        for field in ("totalAmount", "payouts", "settledAt", "initiatedAt",
                      "expectedMask", "confirmedMask", "claimedMask",
                      "fullyConfirmedAt", "refunded"):
            self.assertIn(field, m.group(1), f"Settlement.{field} missing")

    def test_public_view_getters_for_coverage_reads(self):
        # The state a P1.3 consumer reads to observe split-lock coverage:
        for sig in ("Seat[] public seats;",
                    "Settlement[] public settlements;",
                    "mapping(address => uint256) public seatIdOf;",
                    "function isSeatConfirmed(uint256 settlementId, address wallet) "
                    "external view returns (bool)",
                    "function claimablePayout(uint256 settlementId, address wallet) "
                    "external view returns (uint256)",
                    "function settlementPayouts(uint256 settlementId) "
                    "external view returns (uint256[] memory)"):
            self.assertIn(sig, SRC, f"contract view surface missing: {sig}")


class TestSplitLockLedger(unittest.TestCase):
    """7-arm x caller-class outcome grid (parses to forge PR #15 semantics)."""

    # (arm, state, seat_id, caller, duplicate, expected)
    GRID = [
        # (1) no settlements — lock block skipped entirely
        ("1.no_settlement.self",         NO_SETTLEMENTS, 1, "self", False, "OK"),
        ("1.no_settlement.owner_other",  NO_SETTLEMENTS, 1, "owner_other", False, "OK"),
        ("1.no_settlement.owner_seat0",  NO_SETTLEMENTS, 0, "owner_as_seat0", False, "OK"),
        # (2) initiated, pre-confirm — not armed
        ("2.pre_confirm.self",           PRE_CONFIRM, 1, "self", False, "OK"),
        ("2.pre_confirm.owner_other",    PRE_CONFIRM, 1, "owner_other", False, "OK"),
        ("2.pre_confirm.owner_seat0",    PRE_CONFIRM, 0, "owner_as_seat0", False, "OK"),
        # (2') partial coverage — per-seat confirms do NOT lock (coverage, not gap)
        ("2p.partial.confirmed_self",    PARTIAL, 1, "self", False, "OK"),
        ("2p.partial.unconfirmed_self",  PARTIAL, 3, "self", False, "OK"),
        ("2p.partial.owner_other",       PARTIAL, 1, "owner_other", False, "OK"),
        # (3) armed, owner-driven on another seat — strict THROUGH executability
        ("3.armed_mid.owner_other",      ARMED_IN_WINDOW, 1, "owner_other", False,
         "RotationWindowLocked"),
        ("3.armed_past.owner_other",     ARMED_PAST_WINDOW, 1, "owner_other", False,
         "RotationWindowLocked"),
        # (4) armed, confirmed-seat SELF mid-window — locked (also owner-as-seat0)
        ("4.armed_mid.confirmed_self",   ARMED_IN_WINDOW, 1, "self", False,
         "RotationWindowLocked"),
        ("4.armed_mid.owner_as_seat0",   ARMED_IN_WINDOW, 0, "owner_as_seat0", False,
         "RotationWindowLocked"),
        # (4') armed but seat NOT in confirmedMask (bit clear — e.g. inactive at
        #      initiation): unconfirmed seats may always fix their own payout wallet
        ("4u.armed_mid.unexpected_self",
         dict(ARMED_IN_WINDOW, confirmed_mask=0b1011), 2, "self", False, "OK"),
        ("4u.armed_mid.confirmed_control",
         dict(ARMED_IN_WINDOW, confirmed_mask=0b1011), 1, "self", False,
         "RotationWindowLocked"),
        # (5) armed, confirmed-seat SELF after window, pre-execution — reopens
        ("5.armed_past.confirmed_self",  ARMED_PAST_WINDOW, 1, "self", False, "OK"),
        ("5.armed_past.owner_as_seat0",  ARMED_PAST_WINDOW, 0, "owner_as_seat0", False,
         "OK"),
        # (6) executed — every identity path closed
        ("6.executed.self",              EXECUTED, 1, "self", False, "SeatRotationClosed"),
        ("6.executed.owner_other",       EXECUTED, 1, "owner_other", False,
         "SeatRotationClosed"),
        ("6.executed.owner_seat0",       EXECUTED, 0, "owner_as_seat0", False,
         "SeatRotationClosed"),
        # (7) refunded (MAX_HOLD leg) — every identity path closed
        ("7.refunded.self",              REFUNDED, 1, "self", False, "SeatRotationClosed"),
        ("7.refunded.owner_other",       REFUNDED, 1, "owner_other", False,
         "SeatRotationClosed"),
        # identity gate is state-independent: stranger ALWAYS NotSeatOrOwner,
        # including on arms 6/7 (it precedes the settlement-state checks)
        ("1.no_settlement.stranger",     NO_SETTLEMENTS, 1, "stranger", False,
         "NotSeatOrOwner"),
        ("2.pre_confirm.stranger",       PRE_CONFIRM, 1, "stranger", False,
         "NotSeatOrOwner"),
        ("3.armed_mid.stranger",         ARMED_IN_WINDOW, 1, "stranger", False,
         "NotSeatOrOwner"),
        ("6.executed.stranger",          EXECUTED, 1, "stranger", False,
         "NotSeatOrOwner"),
        ("7.refunded.stranger",          REFUNDED, 1, "stranger", False,
         "NotSeatOrOwner"),
        # gate precedence: window-lock answers before the duplicate check
        ("3.dup_but_armed.owner_other",  ARMED_IN_WINDOW, 1, "owner_other", True,
         "RotationWindowLocked"),
        ("4.dup_but_armed.confirmed_self", ARMED_IN_WINDOW, 1, "self", True,
         "RotationWindowLocked"),
        # duplicate guard bites only when every lock is off
        ("1.dup_open_path.self",         NO_SETTLEMENTS, 1, "self", True, "DuplicateSeat"),
        ("2.dup_open_path.self",         PRE_CONFIRM, 1, "self", True, "DuplicateSeat"),
        ("5.armed_past.dup.self",        ARMED_PAST_WINDOW, 1, "self", True,
         "DuplicateSeat"),
    ]

    def test_ledger_grid(self):
        ids = [row[0] for row in self.GRID]
        self.assertEqual(len(ids), len(set(ids)), "duplicate grid arm id")
        for name, state, seat_id, caller, dup, expected in self.GRID:
            with self.subTest(arm=name):
                got = decide(state, seat_id=seat_id, caller=caller, duplicate=dup)
                self.assertEqual(got, expected)

    def test_stranger_class_universal(self):
        # Quantified form of the identity-gate rows above.
        for state in (NO_SETTLEMENTS, PRE_CONFIRM, PARTIAL, ARMED_IN_WINDOW,
                      ARMED_PAST_WINDOW, EXECUTED, REFUNDED):
            self.assertEqual(decide(state, seat_id=1, caller="stranger"),
                             "NotSeatOrOwner")

    def test_all_identity_paths_close_on_executed_and_refunded(self):
        for state in (EXECUTED, REFUNDED):
            for caller in ("self", "owner_as_seat0", "owner_other"):
                self.assertEqual(decide(state, seat_id=0 if caller != "self" else 1,
                                        caller=caller), "SeatRotationClosed")


class TestEconomicRationale(unittest.TestCase):
    """Grounding of WHY the lock arms mid-window (ruling Q2.1 verdict basis)."""

    def test_full_confirm_is_the_only_lock_armer(self):
        # fullyConfirmedAt has exactly one setter: the all-expected-seats guard.
        self.assertEqual(
            len(re.findall(r"s\.fullyConfirmedAt = ", CONFIRM)), 1)
        self.assertIn("if ((s.confirmedMask & s.expectedMask) == s.expectedMask)",
                      CONFIRM)
        # Per-seat confirm appends only — it can arm the lock but never pre-arm it.
        self.assertIn("s.confirmedMask |= bit;", CONFIRM)
        self.assertNotIn("confirmedMask =", CONFIRM)

    def test_execute_requires_window_elapse(self):
        # Lock arm (3) stays strict THROUGH this boundary: executability does not
        # lift the owner-driven lock until settledAt/refunded flip.
        self.assertIn("require(block.timestamp >= uint256(s.fullyConfirmedAt) "
                      "+ SETTLEMENT_WINDOW, WindowNotElapsed());", EXECUTE)

    def test_claim_pays_current_seat_wallet(self):
        # Payout destination is read at claim time from Seat.wallet — the exact
        # channel a mid-window rotation would redirect. This is the money-redirect
        # hazard the 1h window lock defends (ruling Q2.1).
        # Post-PR#32 shape (t_33f03aaf wrapper ruling): destination semantics
        # unchanged — still read from Seat.wallet at claim time — but the leg
        # moved to the vendored SafeERC20 wrapper (retargeted 2026-11-22,
        # stale assertion caught by t_w10fix CI run; test intent preserved).
        self.assertIn("SafeERC20Minimal.safeTransfer(address(token), "
                      "seats[seatId].wallet, amount);", CLAIM)

    def test_refund_leg_closes_only_via_max_hold_pre_confirm(self):
        # Arm (7) companion: refund available ONLY while fullyConfirmedAt == 0 and
        # MAX_HOLD elapsed — once a bill fully confirms, refund exits via execute.
        self.assertIn("require(s.fullyConfirmedAt == 0 && block.timestamp >= "
                      "uint256(s.initiatedAt) + MAX_HOLD, RefundNotAvailable());",
                      REFUND)
        self.assertIn("s.refunded = true;", REFUND)

    def test_confirm_identity_resolves_via_seatidof(self):
        # Immutable trail (Q2.2/Q2.3): confirms resolve through seatIdOf; after a
        # rotation seatIdOf[old] == 0 so the old wallet cannot re-confirm, while
        # the recorded mask bit stays bound to the original wallet forever.
        self.assertIn("uint256 raw = seatIdOf[_caller()];", CONFIRM)
        self.assertIn("if (raw == 0) revert NotAnExpectedSeat();", CONFIRM)


@unittest.skipUnless(FORGE_LEDGER.exists(),
                     "forge ledger test/P13SplitLockCoverage.t.sol not in this "
                     "checkout (landed origin/main @6727aa543); cross-check skipped")
class TestForgeLedgerConsistency(unittest.TestCase):
    """This Python grid must not contradict the merged forge suite's header."""

    # arm number -> (tokens that must appear in that arm's clause,
    #                tokens that must NOT appear)
    ARMS = {
        1: (["no settlements", "open"], []),
        2: (["fullyConfirmedAt == 0", "not armed"], []),
        3: (["owner-driven on another seat", "RotationWindowLocked"], ["open"]),
        4: (["confirmed-seat SELF inside the 1h window", "RotationWindowLocked"], []),
        5: (["confirmed-seat SELF after window", "open"], ["RotationWindowLocked"]),
        6: (["settledAt != 0", "SeatRotationClosed"], ["open"]),
        7: (["refunded", "SeatRotationClosed"], ["open"]),
    }

    def _arm_clause(self, n: int) -> str:
        text = FORGE_LEDGER.read_text(encoding="utf-8")
        start = text.index(f"({n}) ")
        nxt = [m.start() for m in re.finditer(r"\(\d+\) ", text) if m.start() > start]
        end = min(nxt) if nxt else len(text)
        return re.sub(r"\s+", " ", text[start:end])

    def test_arm_clauses_agree_with_grid(self):
        for n, (must, must_not) in self.ARMS.items():
            clause = self._arm_clause(n)
            for token in must:
                self.assertIn(token, clause, f"forge arm ({n}) lost token {token!r}")
            for token in must_not:
                self.assertNotIn(token, clause,
                                 f"forge arm ({n}) contradicts {token!r}")

    def test_contract_under_test_reference(self):
        text = FORGE_LEDGER.read_text(encoding="utf-8")
        self.assertIn('import {TandaBillV2, IERC20} from "../contracts/TandaBillV2.sol";',
                      text)
        self.assertIn("contract P13SplitLockCoverageTest is Test", text)


if __name__ == "__main__":
    unittest.main(verbosity=2)
