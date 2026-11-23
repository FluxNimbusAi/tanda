// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

import {IERC20} from "../contracts/TandaBillV2.sol";
import {FastTandaBillV2, IERC20 as IFastERC20} from "../contracts/FastTandaBillV2.sol";
import {TandaBillFactory} from "../contracts/TandaBillFactory.sol";
import {MockToken} from "./TandaBillV2.t.sol";
import {Test} from "forge-std/Test.sol";

/// @title FastTwinConfirmLadder - card t_cd638bd6 (ENG-20261123-B1)
/// @notice Pins every reachable branch of FastTandaBillV2.confirmSettlement (L337-349), the
///         ladder FastTwinMatrixParity.t.sol never exercised (its L172 comment shows the
///         post-execute confirm leg deliberately avoided). Canonical TandaBillV2 pins the same
///         ladder in TandaBillV2.t.sol (test_confirm_revertsAfterSettle et al); this file makes
///         the twin-parity claim test-verified instead of source-verified only.
///         Cells and the precedence they pin:
///           1. L338       settlementId OOB              -> SettlementNotFound
///           2. L344       stranger (seatIdOf raw==0)    -> NotAnExpectedSeat (identity branch)
///           3. L338>L348  re-confirm AFTER full confirm -> NotAwaitingConfirmations beats
///                         AlreadyConfirmed for a seat whose bit is already set
///           4. L348       double confirm pre-full       -> AlreadyConfirmed
///           5. L340>L341  confirm after execute         -> AlreadySettled beats
///                         NotAwaitingConfirmations (settledAt!=0 AND fullyConfirmedAt!=0)
///           6. L340/refund confirm after MAX_HOLD refund -> AlreadySettled via refunded clause,
///                         sole catch (fullyConfirmedAt==0 there, so L341 can never fire)
///         Divergences honored: 7-tuple settlements (no claimedMask), WINDOW=60s / MAX_HOLD=120s
///         testnet pace, execute pushes payouts inline. All bills via factory.createBill lineage
///         (lane law: NEVER raw initialize from the test contract). Contracts untouched.
contract FastTwinConfirmLadderTest is Test {
    MockToken token;
    TandaBillFactory factory;

    address owner = address(0xA11CE);
    address alice = address(0xB0B);
    address bob   = address(0xBEEF);
    address carol = address(0xCAFE);

    uint256 constant FUNDED = 1_000_000e6;

    function setUp() public {
        token = new MockToken();
        FastTandaBillV2 impl = new FastTandaBillV2(); // constructor-only, never initialized
        factory = new TandaBillFactory(address(impl));
        token.mint(owner, FUNDED);
        token.mint(alice, FUNDED);
        token.mint(bob, FUNDED);
        token.mint(carol, FUNDED);
    }

    // ─── Helpers (factory lineage everywhere; prank INSIDE the deploy helper) ───

    function _seats3() internal view returns (address[] memory s) {
        s = new address[](3); s[0] = owner; s[1] = alice; s[2] = bob;
    }

    function _createAs(address creator, address[] memory seats) internal returns (FastTandaBillV2 bill) {
        vm.prank(creator);
        bill = FastTandaBillV2(factory.createBill(IERC20(address(token)), seats));
    }

    /// @notice 3-seat bill, one expense, escrow funded, settlement initiated.
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

    function _fullConfirm3(FastTandaBillV2 bill) internal {
        _confirmAs(owner, bill, 0);
        _confirmAs(alice, bill, 0);
        _confirmAs(bob, bill, 0);
    }

    /// @notice settlements(uint256) 7-tuple: (totalAmount, settledAt, initiatedAt,
    ///         expectedMask, confirmedMask, fullyConfirmedAt, refunded). Read what we assert.
    function _masks(FastTandaBillV2 bill) internal view returns (uint256 expectedM, uint256 confirmedM, uint64 fcAt) {
        (, , , uint256 expectedMask_, uint256 confirmedMask_, uint64 fullyConfirmedAt_, ) = bill.settlements(0);
        return (expectedMask_, confirmedMask_, fullyConfirmedAt_);
    }

    // ─── Cell 1: L338 out-of-range settlement id ───────────────────────────────

    function test_f_confirm_ladder1_sidOutOfRange_revertsSettlementNotFound() public {
        FastTandaBillV2 bill = _initiatedBill(100e6);
        vm.expectRevert(FastTandaBillV2.SettlementNotFound.selector);
        _confirmAs(alice, bill, 99);
    }

    // ─── Cell 2: L344 identity branch - caller has no seatIdOf entry at all ────

    function test_f_confirm_ladder2_stranger_revertsNotAnExpectedSeat() public {
        FastTandaBillV2 bill = _initiatedBill(100e6);
        (uint256 expectedM, uint256 confirmedM, ) = _masks(bill);
        vm.expectRevert(FastTandaBillV2.NotAnExpectedSeat.selector);
        _confirmAs(carol, bill, 0); // raw == 0 branch (L344), NOT the mask branch (L347)
        (, uint256 confirmedAfter, ) = _masks(bill);
        assertEq(confirmedAfter, confirmedM, "stranger revert must not touch confirmedMask");
        assertEq(expectedM, 7, "sanity: 3-seat expectedMask snapshot");
    }

    // ─── Cell 3: L338 precedence over L348 - re-confirm AFTER full confirm ─────

    function test_f_confirm_ladder3_afterFullConfirm_revertsNotAwaiting_beatsAlreadyConfirmed() public {
        FastTandaBillV2 bill = _initiatedBill(100e6);
        _fullConfirm3(bill);
        (, uint256 confirmedM, uint64 fcAt) = _masks(bill);
        assertTrue(fcAt != 0, "gate: fully confirmed");
        assertTrue((confirmedM & 2) != 0, "gate: alice bit already set -> L348 would also match");
        // alice (an already-confirmer) confirms again: L338 fires BEFORE L348
        vm.expectRevert(FastTandaBillV2.NotAwaitingConfirmations.selector);
        _confirmAs(alice, bill, 0);
    }

    // ─── Cell 4: L348 double confirm while still awaiting ──────────────────────

    function test_f_confirm_ladder4_doubleConfirm_preFull_revertsAlreadyConfirmed() public {
        FastTandaBillV2 bill = _initiatedBill(100e6);
        _confirmAs(bob, bill, 0);
        (, uint256 confirmedM, uint64 fcAt) = _masks(bill);
        assertEq(fcAt, 0, "gate: still awaiting (1/3 confirmed)");
        vm.expectRevert(FastTandaBillV2.AlreadyConfirmed.selector);
        _confirmAs(bob, bill, 0);
        (, uint256 confirmedAfter, uint64 fcAfter) = _masks(bill);
        assertEq(confirmedAfter, confirmedM, "AlreadyConfirmed revert must not advance mask");
        assertEq(fcAfter, 0, "re-double-confirm must not auto-full-confirm");
    }

    // ─── Cell 5: L340 precedence over L341 - confirm after execute ─────────────

    function test_f_confirm_ladder5_afterExecute_revertsAlreadySettled_beatsNotAwaiting() public {
        FastTandaBillV2 bill = _initiatedBill(100e6);
        _fullConfirm3(bill);
        (, , uint64 fcAt) = _masks(bill);
        vm.warp(fcAt + bill.SETTLEMENT_WINDOW());
        bill.executeSettlement(0); // callable by anyone post P0.1a note; fast twin pushes payouts
        (, , uint64 fcAfter) = _masks(bill);
        assertTrue(fcAfter != 0, "gate: fullyConfirmedAt survives execute -> L341 would also match");
        vm.expectRevert(FastTandaBillV2.AlreadySettled.selector);
        _confirmAs(alice, bill, 0); // L340 (settledAt != 0) fires BEFORE L341
    }

    // ─── Cell 6: L340 refunded clause - sole catch on a MAX_HOLD refund ────────

    function test_f_confirm_ladder6_afterRefund_revertsAlreadySettled_soleCatch() public {
        FastTandaBillV2 bill = _initiatedBill(100e6);
        _confirmAs(alice, bill, 0); // partial confirm only: refund stays reachable
        vm.warp(block.timestamp + bill.MAX_HOLD()); // boundary is >=, == passes
        vm.prank(owner);
        bill.refundSettlement(0);
        (, , uint64 fcAt) = _masks(bill);
        assertEq(fcAt, 0, "gate: refunded leg has fullyConfirmedAt==0 (L341 CANNOT fire there)");
        vm.expectRevert(FastTandaBillV2.AlreadySettled.selector);
        _confirmAs(alice, bill, 0); // matched by the s.refunded disjunct of L340 only
    }
}
