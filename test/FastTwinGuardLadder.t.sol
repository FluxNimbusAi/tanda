// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

import {IERC20} from "../contracts/TandaBillV2.sol";
import {FastTandaBillV2, IERC20 as IFastERC20} from "../contracts/FastTandaBillV2.sol";
import {TandaBillFactory} from "../contracts/TandaBillFactory.sol";
import {MockToken} from "./TandaBillV2.t.sol";
import {Test} from "forge-std/Test.sol";

/// @title FastTwinGuardLadder - card t_4f624db2 (engine tick 2026-11-23)
/// @notice Pair-level (fn, error) audit over FastTandaBillV2.sol at main c45b38aa4 found
///         14 guard arms NEVER exercised by any fast-twin test. Mirrors the V2 precedent
///         (t_555edba1 9-arm matrix, t_cd638bd6 confirm ladder, t_c82d4e00 L146/L280 pins).
///         Cells pinned here (line refs = FastTandaBillV2.sol):
///           1. L245  addExpense    stranger              -> NotOwner
///           2. L184  addSeat       stranger              -> NotOwner
///           3. L186  addSeat       257th at cap          -> TooManySeats
///           4. L198  removeSeat    stranger              -> NotOwner
///           5. L200  removeSeat    OOB id                -> SeatNotFound(seatId)
///           6. L214  rotateSeatWallet OOB id             -> SeatNotFound(seatId) (runs BEFORE L218 identity gate)
///           7. L289  initiate      stranger              -> NotOwner
///           8. L291  initiate      no unsettled expense  -> EscrowEmpty (first arm)
///           9. L292  initiate      expense but no escrow -> EscrowEmpty (second arm, same selector)
///          10. L296  initiate      all seats removed     -> NoActiveSeats (escrow fully funded)
///          11. L367  execute       OOB id                -> SettlementNotFound (first fast arm; beats L369 AlreadySettled)
///          12. L396  refund        OOB id                -> SettlementNotFound
///          13. L398  refund        post-execute          -> AlreadySettled (beats L400 RefundNotAvailable)
///          14. L155  initialize    dup roster via factory bubbling -> DuplicateSeat(wallet)
///          15. L156  initialize    257-seat direct call  -> TooManySeats (factory pre-caps at 256, L34)
///         Lane law honored: bills enter only via factory.createBill lineage, except the
///         deliberate direct initialize() call in cell 15 (only way to reach L156; same
///         exception documented for V2 L146 in t_c82d4e00). Contracts untouched.
contract FastTwinGuardLadderTest is Test {
    MockToken token;
    FastTandaBillV2 impl;
    TandaBillFactory factory;

    address owner = address(0xA11CE);
    address alice = address(0xB0B);
    address bob   = address(0xBEEF);
    address eve   = address(0xE1E1);

    uint256 constant FUNDED = 1_000_000e6;

    function setUp() public {
        token = new MockToken();
        impl = new FastTandaBillV2();
        factory = new TandaBillFactory(address(impl));
        token.mint(owner, FUNDED);
        token.mint(alice, FUNDED);
        token.mint(bob, FUNDED);
        token.mint(eve, FUNDED);
    }

    // ─── Helpers (factory lineage, mirrors FastTwinMatrixParity) ──────────

    function _seats3() internal view returns (address[] memory s) {
        s = new address[](3); s[0] = owner; s[1] = alice; s[2] = bob;
    }

    function _createAs(address creator, address[] memory seats) internal returns (FastTandaBillV2 bill) {
        vm.prank(creator);
        bill = FastTandaBillV2(factory.createBill(IERC20(address(token)), seats));
    }

    function _initiatedBill(uint256 amount) internal returns (FastTandaBillV2 bill) {
        bill = _createAs(owner, _seats3());
        vm.startPrank(owner);
        bill.addExpense(amount);
        token.approve(address(bill), amount);
        bill.fundEscrow(amount);
        bill.initiateSettlement();
        vm.stopPrank();
    }

    function _confirmAs(address who, FastTandaBillV2 bill, uint256 sid) internal {
        vm.prank(who);
        bill.confirmSettlement(sid);
    }

    // ─── Seat/expense owner gates ─────────────────────────────────────────

    function test_f_addExpense_revertsNotOwner_L245() public {
        FastTandaBillV2 bill = _createAs(owner, _seats3());
        vm.expectRevert(FastTandaBillV2.NotOwner.selector);
        vm.prank(eve);
        bill.addExpense(10e6);
    }

    function test_f_addSeat_revertsNotOwner_L184() public {
        FastTandaBillV2 bill = _createAs(owner, _seats3());
        vm.expectRevert(FastTandaBillV2.NotOwner.selector);
        vm.prank(eve);
        bill.addSeat(eve);
    }

    function test_f_addSeat_revertsTooManySeats_L186() public {
        FastTandaBillV2 bill = _createAs(owner, _seats3()); // roster 3/256
        vm.startPrank(owner);
        for (uint256 i = 1; i <= 253; i++) {
            bill.addSeat(address(uint160(0x10000 + i))); // distinct, none in roster
        }
        assertEq(bill.activeSeatCount(), 256); // seats.length == MAX_SEATS
        vm.expectRevert(FastTandaBillV2.TooManySeats.selector);
        bill.addSeat(address(uint160(0x20000)));
        vm.stopPrank();
    }

    function test_f_removeSeat_revertsNotOwner_L198() public {
        FastTandaBillV2 bill = _createAs(owner, _seats3());
        vm.expectRevert(FastTandaBillV2.NotOwner.selector);
        vm.prank(eve);
        bill.removeSeat(1);
    }

    function test_f_removeSeat_revertsSeatNotFound_L200() public {
        FastTandaBillV2 bill = _createAs(owner, _seats3());
        vm.startPrank(owner);
        vm.expectRevert(abi.encodeWithSelector(FastTandaBillV2.SeatNotFound.selector, 99));
        bill.removeSeat(99);
        vm.stopPrank();
    }

    /// @notice L214 bounds check runs BEFORE the L218 identity gate: a stranger can
    ///         still learn seat-count bounds via this arm (pinned behavior, not a vuln).
    function test_f_rotate_revertsSeatNotFound_L214() public {
        FastTandaBillV2 bill = _createAs(owner, _seats3());
        vm.expectRevert(abi.encodeWithSelector(FastTandaBillV2.SeatNotFound.selector, 99));
        vm.prank(eve);
        bill.rotateSeatWallet(99, address(uint160(0xD0D0)));
    }

    // ─── initiateSettlement guard ladder ──────────────────────────────────

    function test_f_initiate_revertsNotOwner_L289() public {
        FastTandaBillV2 bill = _createAs(owner, _seats3());
        vm.expectRevert(FastTandaBillV2.NotOwner.selector);
        vm.prank(eve);
        bill.initiateSettlement();
    }

    function test_f_initiate_revertsEscrowEmpty_L291_noExpenses() public {
        FastTandaBillV2 bill = _createAs(owner, _seats3()); // unsettled == 0
        vm.startPrank(owner);
        vm.expectRevert(FastTandaBillV2.EscrowEmpty.selector);
        bill.initiateSettlement();
        vm.stopPrank();
    }

    function test_f_initiate_revertsEscrowEmpty_L292_unfunded() public {
        FastTandaBillV2 bill = _createAs(owner, _seats3());
        vm.startPrank(owner);
        bill.addExpense(50e6); // unsettled > 0, escrow still 0 -> second arm, same selector
        vm.expectRevert(FastTandaBillV2.EscrowEmpty.selector);
        bill.initiateSettlement();
        vm.stopPrank();
    }

    function test_f_initiate_revertsNoActiveSeats_L296() public {
        uint256 amount = 90e6;
        FastTandaBillV2 bill = _createAs(owner, _seats3());
        vm.startPrank(owner);
        bill.addExpense(amount);
        token.approve(address(bill), amount);
        bill.fundEscrow(amount); // escrow covers unsettled -> L291/L292 pass
        bill.removeSeat(0);
        bill.removeSeat(1);
        bill.removeSeat(2); // activeCount == 0
        vm.expectRevert(FastTandaBillV2.NoActiveSeats.selector);
        bill.initiateSettlement();
        vm.stopPrank();
    }

    // ─── execute/refund bounds + short-circuit order ──────────────────────

    function test_f_execute_revertsSettlementNotFound_L367() public {
        FastTandaBillV2 bill = _initiatedBill(100e6); // settlement 0 exists, 99 does not
        vm.expectRevert(FastTandaBillV2.SettlementNotFound.selector);
        vm.prank(eve);
        bill.executeSettlement(99);
    }

    function test_f_refund_revertsSettlementNotFound_L396() public {
        FastTandaBillV2 bill = _initiatedBill(100e6);
        vm.startPrank(owner);
        vm.expectRevert(FastTandaBillV2.SettlementNotFound.selector);
        bill.refundSettlement(99);
        vm.stopPrank();
    }

    /// @notice Post-execute refund must answer AlreadySettled (L398) BEFORE the
    ///         RefundNotAvailable hold-window check (L400) would fire: settledAt != 0.
    function test_f_refund_revertsAlreadySettled_L398_postExecute() public {
        FastTandaBillV2 bill = _initiatedBill(100e6);
        _confirmAs(owner, bill, 0);
        _confirmAs(alice, bill, 0);
        _confirmAs(bob, bill, 0); // full confirm opens window
        (, , , , , uint64 fc, ) = bill.settlements(0);
        vm.warp(uint256(fc) + bill.SETTLEMENT_WINDOW());
        vm.startPrank(owner);
        bill.executeSettlement(0);
        vm.expectRevert(FastTandaBillV2.AlreadySettled.selector);
        bill.refundSettlement(0);
        vm.stopPrank();
    }

    // ─── initialize() arms only reachable pre-clone ───────────────────────

    /// @notice Factory pre-checks (L33/L34) cannot reject duplicates, so the roster loop
    ///         arm L155 executes inside the clone and bubbles FastTandaBillV2.DuplicateSeat.
    function test_f_createBill_duplicateRoster_bubblesDuplicateSeat_L155() public {
        address[] memory dup = new address[](2);
        dup[0] = alice;
        dup[1] = alice;
        vm.expectRevert(abi.encodeWithSelector(FastTandaBillV2.DuplicateSeat.selector, alice));
        vm.prank(owner);
        factory.createBill(IERC20(address(token)), dup);
    }

    /// @notice Direct initialize bypasses the factory cap pre-check (L34 rejects >256 before
    ///         forwarding), so ONLY this path exercises the in-loop L156 arm. Same exception
    ///         documented for the V2 twin in t_c82d4e00 (L146).
    function test_f_initialize_direct_revertsTooManySeats_L156() public {
        FastTandaBillV2 orphan = new FastTandaBillV2(); // factory impl untouched
        address[] memory many = new address[](257);
        for (uint256 i = 0; i < 257; i++) {
            many[i] = address(uint160(i + 1)); // distinct, iteration 256 trips L156
        }
        vm.expectRevert(FastTandaBillV2.TooManySeats.selector);
        orphan.initialize(IFastERC20(address(token)), owner, many);
    }
}
