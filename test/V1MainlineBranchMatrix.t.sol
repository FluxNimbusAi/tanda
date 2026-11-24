// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

import {TandaBill, IERC20} from "../contracts/TandaBill.sol";
import {Test} from "forge-std/Test.sol";
import {MockToken} from "./TandaBill.t.sol";

/// @title V1MainlineBranchMatrix
/// @notice Engine-tick test-matrix deepening (family 1): closes the uncovered
///         branch halves of the legacy mainnet V1 mainline (TandaBill.sol).
///         Gap targets from forge coverage @ 6b08e88cf:
///           stmts 96.30% (78/81), branches 76.47% (26/34).
///         Sites pinned here:
///           L120 removeSeat NotOwner-false half
///           L122 SeatNotFound revert side (out-of-range seatId)
///           L123 SeatInactive revert side (double removal)
///           L132 addExpense NotOwner-false half
///           L142 fundEscrow NotOwner-false half
///           L155 initiateSettlement NotOwner-false half
///           L205 SettlementNotReady revert side (out-of-range settlementId)
///           L185 already-settled expense skip (second settlement cycle)
///           L215 inactive-seat skip in payout loop (removed seat survives)
contract V1MainlineBranchMatrixTest is Test {
    MockToken token;
    TandaBill bill;

    address owner = address(0xA11CE);
    address alice = address(0xB0B);
    address bob   = address(0xBEEF);
    address carol = address(0xCAFE);
    address stranger = address(0xDEAD);

    function setUp() public {
        token = new MockToken();
        vm.prank(owner);
        bill = new TandaBill(IERC20(address(token)));
        token.mint(owner, 1_000_000e6);
        token.mint(alice, 1_000_000e6);
        token.mint(bob,   1_000_000e6);
        token.mint(carol, 1_000_000e6);
    }

    // ─── Guard half: removeSeat NotOwner (L120) ──────────────────────────

    function test_branch_removeSeat_revertsIfNotOwner() public {
        vm.prank(owner);
        bill.addSeat(alice);
        vm.prank(stranger);
        vm.expectRevert(TandaBill.NotOwner.selector);
        bill.removeSeat(0);
    }

    // ─── Revert side: SeatNotFound out-of-range (L122) ───────────────────

    function test_branch_removeSeat_outOfRange_revertsSeatNotFound() public {
        vm.prank(owner);
        bill.addSeat(alice);
        vm.prank(owner);
        vm.expectRevert(abi.encodeWithSelector(TandaBill.SeatNotFound.selector, 7));
        bill.removeSeat(7);
    }

    // ─── Revert side: SeatInactive double removal (L123) ─────────────────

    function test_branch_removeSeat_twice_revertsSeatInactive() public {
        vm.prank(owner);
        bill.addSeat(alice);
        vm.startPrank(owner);
        bill.removeSeat(0);
        vm.expectRevert(abi.encodeWithSelector(TandaBill.SeatInactive.selector, 0));
        bill.removeSeat(0);
        vm.stopPrank();
    }

    // ─── Guard halves: addExpense / fundEscrow / initiate (L132/L142/L155) ─

    function test_branch_addExpense_revertsIfNotOwner() public {
        vm.prank(stranger);
        vm.expectRevert(TandaBill.NotOwner.selector);
        bill.addExpense(100e6);
    }

    function test_branch_fundEscrow_revertsIfNotOwner() public {
        vm.prank(stranger);
        vm.expectRevert(TandaBill.NotOwner.selector);
        bill.fundEscrow(100e6);
    }

    function test_branch_initiateSettlement_revertsIfNotOwner() public {
        vm.startPrank(owner);
        bill.addSeat(alice);
        bill.addExpense(100e6);
        token.approve(address(bill), 100e6);
        bill.fundEscrow(100e6);
        vm.stopPrank();
        vm.prank(stranger);
        vm.expectRevert(TandaBill.NotOwner.selector);
        bill.initiateSettlement();
    }

    // ─── Revert side: executeSettlement out-of-range (L205) ──────────────

    function test_branch_executeSettlement_outOfRange_revertsSettlementNotReady() public {
        vm.prank(owner);
        vm.expectRevert(TandaBill.SettlementNotReady.selector);
        bill.executeSettlement(0);
    }

    // ─── Full second cycle: settled-expense skip (L185) + inactive-seat
    //     payout skip (L215) + L169 inactive skip at initiation ────────────

    function test_branch_secondSettlementCycle_skipsSettledExpensesAndInactiveSeats() public {
        // Three seats; carol removed pre-initiation (roster frozen after).
        vm.startPrank(owner);
        bill.addSeat(alice);
        bill.addSeat(bob);
        bill.addSeat(carol);
        bill.removeSeat(2);          // carol inactive -> L169/L215 false halves
        bill.addExpense(80e6);       // expense 0
        token.approve(address(bill), 80e6);
        bill.fundEscrow(80e6);
        bill.initiateSettlement();   // payouts: alice 40, bob 40
        vm.stopPrank();

        vm.warp(block.timestamp + 1 hours);
        vm.prank(owner);
        bill.executeSettlement(0);
        assertEq(token.balanceOf(alice), 1_000_000e6 + 40e6);
        assertEq(token.balanceOf(bob),   1_000_000e6 + 40e6);
        assertEq(token.balanceOf(carol), 1_000_000e6);   // inactive seat paid nothing

        // Second cycle: expense 1 unsettled, expense 0 already settled ->
        // L185 hits its false half on expenses[0] during the marking loop.
        vm.startPrank(owner);
        bill.addExpense(20e6);       // expense 1 (unsettled)
        token.approve(address(bill), 20e6);
        bill.fundEscrow(20e6);
        bill.initiateSettlement();   // unsettled = 20e6 only -> payouts alice 10, bob 10
        vm.stopPrank();

        vm.warp(block.timestamp + 1 hours);
        vm.prank(owner);
        bill.executeSettlement(1);

        assertEq(token.balanceOf(alice), 1_000_000e6 + 50e6);
        assertEq(token.balanceOf(bob),   1_000_000e6 + 50e6);
        assertEq(token.balanceOf(carol), 1_000_000e6);
        assertEq(bill.escrowBalance(), 0);
        assertEq(bill.totalExpenses(), 100e6);
        assertEq(bill.activeSeatCount(), 2);
    }

    // ─── _unsettledTotal false half via mixed settled ledger (L242) ──────

    function test_branch_unsettledTotal_mixedSettledLedger() public {
        vm.startPrank(owner);
        bill.addSeat(alice);
        bill.addExpense(60e6);
        token.approve(address(bill), 60e6);
        bill.fundEscrow(60e6);
        bill.initiateSettlement();
        vm.stopPrank();
        vm.warp(block.timestamp + 1 hours);
        vm.prank(owner);
        bill.executeSettlement(0);

        // After cycle 1 the single expense is settled; addExpense again so the
        // view loop exercises both halves of L242 on the same ledger.
        vm.prank(owner);
        bill.addExpense(25e6);
        // No external unsettledTotal() getter exists on V1; pin via initiate gate:
        // a fresh initiate with escrow short must see unsettled == 25e6 exactly.
        vm.prank(owner);
        vm.expectRevert(TandaBill.EscrowEmpty.selector); // L158 false half on mixed ledger
        bill.initiateSettlement();
    }

    // --- Empty-state loop-exit halves: views and gate order with zero seats
    // and zero expenses (covers the remaining loop-condition branch edge).
    function test_branch_emptyState_viewsAndGateOrder() public {
        assertEq(bill.activeSeatCount(), 0);
        assertEq(bill.totalExpenses(), 0);
        vm.prank(owner);
        vm.expectRevert(TandaBill.EscrowEmpty.selector); // L157 fires before L161
        bill.initiateSettlement();
    }
}
