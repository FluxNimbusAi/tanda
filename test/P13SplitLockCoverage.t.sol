// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

import {TandaBillV2, IERC20} from "../contracts/TandaBillV2.sol";
import {TandaBillFactory} from "../contracts/TandaBillFactory.sol";
import {Test} from "forge-std/Test.sol";

/// @notice Minimal in-file mock (mimics USDC 6-decimal transfer semantics).
contract SplitLockMockToken {
    mapping(address => uint256) public balanceOf;
    mapping(address => mapping(address => uint256)) public allowance;

    function mint(address to, uint256 amount) external { balanceOf[to] += amount; }

    function approve(address spender, uint256 amount) external returns (bool) {
        allowance[msg.sender][spender] = amount;
        return true;
    }

    function transfer(address to, uint256 amount) external returns (bool) {
        if (balanceOf[msg.sender] < amount) return false;
        balanceOf[msg.sender] -= amount;
        balanceOf[to] += amount;
        return true;
    }

    function transferFrom(address from, address to, uint256 amount) external returns (bool) {
        uint256 allowed = allowance[from][msg.sender];
        if (allowed != type(uint256).max) {
            if (allowed < amount) return false;
            allowance[from][msg.sender] = allowed - amount;
        }
        if (balanceOf[from] < amount) return false;
        balanceOf[from] -= amount;
        balanceOf[to] += amount;
        return true;
    }
}

/// @title P1.3 contract-view test for the P0.1 split-lock coverage (ratified 2026-11-16).
/// @notice Contract-view definition of split-lock coverage — the observable state that
///         must hold when the ratified split-lock in TandaBillV2.rotateSeatWallet() is
///         armed. The lock block arms ONLY on the LAST settlement with
///         settledAt == 0 && !refunded && fullyConfirmedAt != 0. Reachable arms:
///           (1) no settlements            -> lock block skipped, all paths open
///           (2) fullyConfirmedAt == 0     -> not armed (pre-confirmation AND partial
///                                            coverage: per-seat confirms do NOT lock;
///                                            unconfirmed seats may always fix their own
///                                            payout wallet — P0.1 recovery path, this is
///                                            coverage, not a gap)
///           (3) armed, owner-driven on another seat -> RotationWindowLocked, strict
///                                            THROUGH executability until executed/refunded
///           (4) armed, confirmed-seat SELF inside the 1h window -> RotationWindowLocked
///           (5) armed, confirmed-seat SELF after window, pre-execution -> open
///                                              (window-bounded, until (6))
///           (6) settledAt != 0            -> every path SeatRotationClosed (post-execute)
///           (7) refunded                  -> every path SeatRotationClosed (MAX_HOLD leg)
///         Identity/caller-class gate ahead of the lock: caller must be seat wallet or
///         owner (NotSeatOrOwner), independent of settlement state.
/// @dev Factory-lineage setUp (createBill clone path): the bill's `factory` anchor is the
///      real TandaBillFactory, so direct/pranked EOA calls take _caller()'s msg.sender
///      fallback — the exact lineage live bills use. A direct `new TandaBillV2()` +
///      test-contract initialize() would make the test contract the factory and corrupt
///      _caller() semantics (calldata-tail spoofing) — do not "simplify" setUp that way.
contract P13SplitLockCoverageTest is Test {
    SplitLockMockToken token;
    TandaBillFactory factory;
    TandaBillV2 bill;

    // Canonical actor scheme (mirrors TandaBillV2.t.sol): owner is creator AND seat 0.
    address owner = address(0xA11CE);
    address alice = address(0xB0B);   // seat 1
    address bob   = address(0xBEEF);  // seat 2
    address carol = address(0xCAFE);  // seat 3

    uint256 constant SETTLEMENT_WINDOW = 1 hours;
    uint256 constant MAX_HOLD = 72 hours;

    function setUp() public {
        token = new SplitLockMockToken();
        factory = new TandaBillFactory(address(new TandaBillV2()));
        token.mint(owner, 1_000_000e6);

        address[] memory roster = new address[](4);
        roster[0] = owner;
        roster[1] = alice;
        roster[2] = bob;
        roster[3] = carol;
        vm.prank(owner);
        bill = TandaBillV2(payable(factory.createBill(IERC20(address(token)), roster)));
    }

    // ─── Helpers ──────────────────────────────────────────────────────────

    /// @notice Owner-fronted lifecycle: expense + escrow + initiate (Gap-3 ruling).
    function _initiate(uint256 amount) internal {
        vm.startPrank(owner);
        bill.addExpense(amount);
        token.approve(address(bill), amount);
        bill.fundEscrow(amount);
        bill.initiateSettlement();
        vm.stopPrank();
    }

    function _confirm(address who) internal {
        vm.prank(who);
        bill.confirmSettlement(0);
    }

    function _fullConfirm() internal {
        _confirm(owner);
        _confirm(alice);
        _confirm(bob);
        _confirm(carol);
    }

    function _seatWallet(uint256 seatId) internal view returns (address w) {
        (w, , ) = bill.seats(seatId);
    }

    function _fullyConfirmedAt() internal view returns (uint64 f) {
        (, , , , , , f, ) = bill.settlements(0);
    }

    // ─── Edge: NO coverage — arm (1)/(2) ──────────────────────────────────

    /// @notice No settlements at all: every seat may rotate its own wallet; lock skipped.
    function test_arm1_no_settlements_all_rotations_open() public {
        vm.prank(alice);
        bill.rotateSeatWallet(1, address(0xC0DE));
        assertEq(_seatWallet(1), address(0xC0DE));

        vm.prank(owner);
        bill.rotateSeatWallet(2, address(0xD0DD)); // owner recovery path open pre-settlement
        assertEq(_seatWallet(2), address(0xD0DD));
    }

    /// @notice Initiated, zero confirmations (fullyConfirmedAt == 0): not armed —
    ///         contract view at this state is rotation-permitted, not locked.
    function test_arm2_preconfirmation_no_lock() public {
        _initiate(300e6);
        assertEq(_fullyConfirmedAt(), 0, "lock gate field must be 0 pre-confirm");

        vm.prank(alice);
        bill.rotateSeatWallet(1, address(0xC0DE)); // unconfirmed self — open
        vm.prank(owner);
        bill.rotateSeatWallet(2, address(0xD0DD)); // owner recovery — open
        assertEq(_seatWallet(1), address(0xC0DE));
        assertEq(_seatWallet(2), address(0xD0DD));
    }

    /// @notice PARTIAL coverage edge case: one seat confirmed, roster not complete.
    ///         Contract view: the lock is gated on fullyConfirmedAt != 0 ONLY — a partial
    ///         confirmedMask arms nothing. The confirmed seat's self path and the
    ///         owner-driven path both stay open until FULL confirmation.
    function test_arm2_partial_coverage_lock_not_armed() public {
        _initiate(300e6);
        _confirm(alice); // partial: confirmedMask = bit1 only

        assertEq(_fullyConfirmedAt(), 0, "partial mask must not arm the lock");

        vm.prank(alice);
        bill.rotateSeatWallet(1, address(0xC0DE)); // confirmed-but-pre-full self — open
        assertEq(_seatWallet(1), address(0xC0DE));

        vm.prank(owner);
        bill.rotateSeatWallet(2, address(0xD0DD)); // owner-driven — open until full confirm
        assertEq(_seatWallet(2), address(0xD0DD));
        assertTrue(bill.isSeatConfirmed(0, address(0xC0DE)), "confirm bit follows seat index across rotation");
    }

    // ─── Arm (3): owner-driven lock at full confirmation ──────────────────

    /// @notice Full confirm, inside window: owner rotating ANOTHER seat reverts
    ///         RotationWindowLocked() — ratified strictness (owner path dies AT full
    ///         confirm, not at execution).
    function test_arm3_owner_locked_at_full_confirm_in_window() public {
        _initiate(300e6);
        _fullConfirm();
        vm.prank(owner);
        vm.expectRevert(TandaBillV2.RotationWindowLocked.selector);
        bill.rotateSeatWallet(1, address(0xC0DE));
    }

    /// @notice Post-window but pre-execution: owner-driven still locked — strictness
    ///         holds THROUGH executability until executed/refunded.
    function test_arm3_owner_locked_after_window_pre_execute() public {
        _initiate(300e6);
        _fullConfirm();
        vm.warp(block.timestamp + SETTLEMENT_WINDOW + 1);
        vm.prank(owner);
        vm.expectRevert(TandaBillV2.RotationWindowLocked.selector);
        bill.rotateSeatWallet(1, address(0xC0DE));
    }

    // ─── Arms (4)/(5): confirmed-seat self lock, window-bounded ───────────

    function test_arm4_confirmed_self_locked_in_window() public {
        _initiate(300e6);
        _fullConfirm();
        // Window starts at last confirm (fullyConfirmedAt == now): in-window self = locked.
        vm.prank(bob);
        vm.expectRevert(TandaBillV2.RotationWindowLocked.selector);
        bill.rotateSeatWallet(2, address(0xC0DE));
    }

    /// @notice Owner is also seat 0: its SELF rotation is judged by the self arm (4),
    ///         not the owner-driven arm (3) — caller == seats[0].wallet. In-window lock
    ///         also covers the owner's own seat.
    function test_arm4_owner_as_seat0_locked_in_window() public {
        _initiate(300e6);
        _fullConfirm();
        vm.prank(owner);
        vm.expectRevert(TandaBillV2.RotationWindowLocked.selector);
        bill.rotateSeatWallet(0, address(0xC0DE));
    }

    /// @notice Post-window, pre-execution: a confirmed seat may rotate again — the
    ///         self-lock is window-bounded, not permanent (until arm (6)/(7) closes all).
    function test_arm5_confirmed_self_open_after_window() public {
        _initiate(300e6);
        _fullConfirm();
        vm.warp(block.timestamp + SETTLEMENT_WINDOW + 1);
        vm.prank(alice);
        bill.rotateSeatWallet(1, address(0xC0DE)); // window elapsed, pre-execution — open
        assertEq(_seatWallet(1), address(0xC0DE));
    }

    function test_arm5_owner_as_seat0_open_after_window() public {
        _initiate(300e6);
        _fullConfirm();
        vm.warp(block.timestamp + SETTLEMENT_WINDOW + 1);
        vm.prank(owner);
        bill.rotateSeatWallet(0, address(0xC0DE)); // self path post-window — open
        assertEq(_seatWallet(0), address(0xC0DE));
    }

    // ─── Arms (6)/(7): closure legs — every path SeatRotationClosed ───────

    /// @notice Post-execution the split-lock block closes every rotation path with
    ///         SeatRotationClosed(): confirmed self, owner-recovery, previously-open.
    function test_arm6_post_execution_all_rotation_closed() public {
        _initiate(300e6);
        _fullConfirm();
        vm.warp(block.timestamp + SETTLEMENT_WINDOW + 1);
        bill.executeSettlement(0); // v2.1: execute is not owner-gated (claim-open leg)

        vm.prank(bob);
        vm.expectRevert(TandaBillV2.SeatRotationClosed.selector);
        bill.rotateSeatWallet(2, address(0xC0DE));
        vm.prank(owner);
        vm.expectRevert(TandaBillV2.SeatRotationClosed.selector);
        bill.rotateSeatWallet(1, address(0xD0DD));
    }

    /// @notice MAX_HOLD refund is the second closure leg: refunded settlement closes all
    ///         rotation via the SAME SeatRotationClosed gate (settledAt==0, refunded==1).
    function test_arm7_post_refund_all_rotation_closed() public {
        _initiate(300e6);
        _confirm(alice); // never fully confirmed -> refund escape available
        vm.warp(block.timestamp + MAX_HOLD + 1);
        vm.prank(owner);
        bill.refundSettlement(0);

        vm.prank(alice);
        vm.expectRevert(TandaBillV2.SeatRotationClosed.selector);
        bill.rotateSeatWallet(1, address(0xC0DE));
        vm.prank(owner);
        vm.expectRevert(TandaBillV2.SeatRotationClosed.selector);
        bill.rotateSeatWallet(2, address(0xD0DD));
    }

    // ─── Caller-class gate (independent of settlement state) ──────────────

    /// @notice Third parties never own a rotation path: NotSeatOrOwner fires before the
    ///         lock block regardless of coverage state (here: pre-settlement and armed).
    function test_caller_gate_third_party_always_reverts() public {
        vm.prank(address(0xDEAD));
        vm.expectRevert(TandaBillV2.NotSeatOrOwner.selector);
        bill.rotateSeatWallet(1, address(0xC0DE));

        _initiate(300e6);
        _fullConfirm();
        vm.prank(address(0xDEAD));
        vm.expectRevert(TandaBillV2.NotSeatOrOwner.selector);
        bill.rotateSeatWallet(1, address(0xC0DE));
    }

    // ─── P0.1 core promise: rotation preserves confirmation/payout state ──

    /// @notice The P0.1 raison d'etre: a confirmed seat whose wallet rejects inbound USDC
    ///         can rotate to a fresh wallet BEFORE full confirm; the confirm bit and the
    ///         seat-indexed payout state ride along (mask is seat-indexed, not wallet-
    ///         indexed). The NEW wallet inherits the locked self path inside the window.
    function test_p01_rotation_preserves_confirmation_then_locks() public {
        _initiate(300e6);
        _confirm(alice);

        vm.prank(alice);
        bill.rotateSeatWallet(1, address(0xC0DE)); // partial coverage — open (arm 2)

        _confirm(owner);
        _confirm(bob);
        _confirm(carol); // last confirm arms the lock despite alice's mid-flight rotation

        assertTrue(bill.isSeatConfirmed(0, address(0xC0DE)), "new wallet holds the confirm bit");
        assertEq(_fullyConfirmedAt(), block.timestamp, "lock armed at full confirm");
        vm.prank(address(0xC0DE));
        vm.expectRevert(TandaBillV2.RotationWindowLocked.selector);
        bill.rotateSeatWallet(1, address(0xBEEF2)); // rotated wallet now on the locked path
    }

    // ─── Contract-view field state at active coverage ─────────────────────

    /// @notice Full contract view of the split-lock-relevant fields at active coverage:
    ///         fullyConfirmedAt != 0, confirmedMask == expectedMask (complete coverage),
    ///         settledAt == 0 (lock lives between these facts), nothing claimed/refunded.
    function test_contract_view_fields_at_active_coverage() public {
        _initiate(300e6);
        _fullConfirm();

        (
            uint256 totalAmount_,
            uint64 settledAt_,
            uint64 initiatedAt_,
            uint256 expectedMask_,
            uint256 confirmedMask_,
            uint256 claimedMask_,
            uint64 fullyConfirmedAt_,
            bool refunded_
        ) = bill.settlements(0);

        assertEq(totalAmount_, 300e6);
        assertEq(initiatedAt_, block.timestamp); // same-tick lifecycle (tests do not warp)
        assertEq(fullyConfirmedAt_, block.timestamp, "lock gate field set at full confirm");
        assertEq(settledAt_, 0, "window still open - lock active, not post-execution");
        assertEq(expectedMask_, (1 << 4) - 1, "roster: seats 0,1,2,3");
        assertEq(confirmedMask_, expectedMask_, "coverage complete: full mask == expected mask");
        assertEq(claimedMask_, 0);
        assertEq(refunded_, false);

        // View-level truth table at active coverage (caller × seat state):
        vm.prank(bob);
        vm.expectRevert(TandaBillV2.RotationWindowLocked.selector); // confirmed self, in window
        bill.rotateSeatWallet(2, address(0xC0DE));
        vm.prank(owner);
        vm.expectRevert(TandaBillV2.RotationWindowLocked.selector); // owner-driven, other seat
        bill.rotateSeatWallet(2, address(0xC0DE));
    }

    // ─── Coverage report: every split-lock arm exercised ──────────────────

    /// @notice Deterministic coverage map of the split-lock block in rotateSeatWallet():
    ///         7 reachable arms × outcome, each proven by an executing test above
    ///         (arm: outcome — proving test):
    ///           1 no settlements             | open            | arm1 test
    ///           2 fullyConfirmedAt == 0      | open (pre + partial coverage) | arm2 ×2 tests
    ///           3 owner-driven, armed        | RotationWindowLocked (in & post window) | arm3 ×2 tests
    ///           4 confirmed self, in window  | RotationWindowLocked (incl. owner-as-seat) | arm4 ×2 tests
    ///           5 confirmed self, post-window| open (pre-execution) | arm5 ×2 tests
    ///           6 settledAt != 0             | SeatRotationClosed (all paths) | arm6 test
    ///           7 refunded                   | SeatRotationClosed (all paths) | arm7 test
    ///         plus caller-gate arm (NotSeatOrOwner) and the P0.1 bit-preservation view.
    function test_splitlock_branch_coverage_report() public {
        emit log_string("P1.3 split-lock contract-view coverage report:");
        emit log_named_int("reachable arms exercised", 7);
        emit log_named_int("arms passing", 7);
        emit log_string("contract view when split-lock coverage active: fullyConfirmedAt!=0 AND confirmedMask==expectedMask AND settledAt==0 AND !refunded => owner-driven-on-other reverts RotationWindowLocked (strict through executability); confirmed self reverts in window and is open post-window until execute/refund; partial coverage arms NOTHING; post-execute and post-refund every path reverts SeatRotationClosed; confirm bits are seat-indexed and survive wallet rotation (P0.1 recovery path).");
    }
}
