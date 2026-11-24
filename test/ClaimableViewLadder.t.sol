// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

import {TandaBillV2, IERC20} from "../contracts/TandaBillV2.sol";
import {TandaBillFactory} from "../contracts/TandaBillFactory.sol";
import {Test} from "forge-std/Test.sol";

/// @notice Minimal ERC-20 mock (6-decimal style amounts are irrelevant here; raw units used).
contract LadderMockToken {
    mapping(address => uint256) public balanceOf;
    mapping(address => mapping(address => uint256)) public allowance;

    function mint(address to, uint256 a) external { balanceOf[to] += a; }

    function transfer(address to, uint256 a) external returns (bool) {
        require(balanceOf[msg.sender] >= a, "insufficient");
        balanceOf[msg.sender] -= a;
        balanceOf[to] += a;
        return true;
    }

    function transferFrom(address f, address t, uint256 a) external returns (bool) {
        require(balanceOf[f] >= a, "insufficient");
        require(allowance[f][msg.sender] >= a, "allowance");
        balanceOf[f] -= a;
        balanceOf[t] += a;
        allowance[f][msg.sender] -= a;
        return true;
    }

    function approve(address sp, uint256 a) external returns (bool) {
        allowance[msg.sender][sp] = a;
        return true;
    }
}

/// @title ClaimableViewLadderTest [ENG-20261123-C1]
/// @notice Pins the _payoutAt rank-remap consumer paths (claimablePayout view + claimSettlement
///         claim leg) under a HOLED expectedMask, plus two view-ladder rungs that existing
///         suites leave open: post-initiate added seat and refunded settlement.
/// @dev    Factory-lineage setUp (createBill clone path) per canonical suites: real factory
///         anchor keeps _caller() on its msg.sender fallback. Actor scheme mirrors
///         TandaBillV2.t.sol: owner = creator = seat 0 (0xA11CE).
///         Gap config recipe: removeSeat(1) + addSeat(alice) pre-initiate -> alice lands on
///         seat index 3; initiate snapshots expectedMask = {0,2,3}; payouts vector is DENSE
///         length 3: [4,3,3] for total 10 (base 3, remainder 1 at rank 0). Seat-indexing the
///         dense vector (payouts[seatId]) would OOB at index 3 - that is the regression this
///         suite dies on if _payoutAt's popcount rank ever regresses.
contract ClaimableViewLadderTest is Test {
    LadderMockToken token;
    TandaBillFactory factory;
    TandaBillV2 bill;

    address owner = address(0xA11CE);
    address alice = address(0xB0B);
    address bob   = address(0xBEEF);
    address dan   = address(0xDADA);

    function setUp() public {
        token = new LadderMockToken();
        factory = new TandaBillFactory(address(new TandaBillV2()));
        token.mint(owner, 1_000_000);

        address[] memory roster = new address[](3);
        roster[0] = owner;
        roster[1] = alice;
        roster[2] = bob;
        vm.prank(owner);
        bill = TandaBillV2(payable(factory.createBill(IERC20(address(token)), roster)));
    }

    // ─── Helpers ──────────────────────────────────────────────────────────

    function _openGappedSettlement() internal {
        vm.startPrank(owner);
        bill.removeSeat(1);        // alice off index 1; seatIdOf cleared -> re-invitable
        bill.addSeat(alice);       // alice re-enters at index 3 -> expectedMask hole at 1
        bill.addExpense(10);
        token.approve(address(bill), 10);
        bill.fundEscrow(10);
        bill.initiateSettlement(); // active set {0,2,3}; dense payouts [4,3,3]
        vm.stopPrank();
        // every expected seat confirms: owner, bob(2), alice(3)
        vm.prank(owner); bill.confirmSettlement(0);
        vm.prank(bob);   bill.confirmSettlement(0);
        vm.prank(alice); bill.confirmSettlement(0);
        vm.warp(block.timestamp + uint256(bill.SETTLEMENT_WINDOW()) + 1);
        bill.executeSettlement(0);
    }

    // ─── (a) rank remap: view side ────────────────────────────────────────

    function test_a_rankRemap_view_gappedExpectedMask() public {
        _openGappedSettlement();
        assertEq(bill.settlementPayouts(0).length, 3, "dense vector length");
        // rank, not seat index: bob (seat 2) is rank 1, alice (seat 3) is rank 2.
        assertEq(bill.claimablePayout(0, owner), 4, "rank-0 seat carries remainder wei");
        assertEq(bill.claimablePayout(0, bob),   3, "seat 2 -> payouts[1]");
        assertEq(bill.claimablePayout(0, alice), 3, "seat 3 -> payouts[2]; payouts[3] would OOB");
        assertEq(bill.claimablePayout(0, dan),   0, "non-seat");
    }

    // ─── (a') rank remap: claim leg parity + drain ────────────────────────

    function test_b_rankRemap_claimLeg_parityAndDrain() public {
        _openGappedSettlement();
        uint256 a0 = token.balanceOf(alice);
        uint256 b0 = token.balanceOf(bob);
        uint256 o0 = token.balanceOf(owner);

        vm.prank(alice); bill.claimSettlement(0);
        assertEq(token.balanceOf(alice) - a0, 3, "alice paid rank-2 share");

        vm.prank(bob);   bill.claimSettlement(0);
        assertEq(token.balanceOf(bob) - b0, 3, "bob paid rank-1 share");

        vm.prank(owner); bill.claimSettlement(0);
        assertEq(token.balanceOf(owner) - o0, 4, "owner paid rank-0 share");

        assertEq(token.balanceOf(address(bill)), 0, "escrow fully drained");

        vm.expectRevert(TandaBillV2.PayoutAlreadyClaimed.selector);
        vm.prank(alice); bill.claimSettlement(0);
    }

    // ─── (b) post-initiate added seat: view + confirm rung == rejected ────

    function test_c_postInitiateSeat_viewZeroAndConfirmReject() public {
        vm.startPrank(owner);
        bill.addExpense(30);
        token.approve(address(bill), 30);
        bill.fundEscrow(30);
        bill.initiateSettlement();
        vm.expectRevert(TandaBillV2.SettlementInitiatedAlready.selector);
        bill.addSeat(dan); // BS-3.2/#185: REJECTED at the gate (was: silent seat 3 outside snapshot {0,1,2})
        vm.stopPrank();

        // Pre-execute: dan's confirm dies on the seat rung (settledAt==0, fullyConfirmedAt==0).
        vm.prank(owner); bill.confirmSettlement(0);
        vm.expectRevert(TandaBillV2.NotAnExpectedSeat.selector);
        vm.prank(dan); bill.confirmSettlement(0);

        vm.prank(alice); bill.confirmSettlement(0);
        vm.prank(bob);   bill.confirmSettlement(0);
        vm.warp(block.timestamp + uint256(bill.SETTLEMENT_WINDOW()) + 1);
        bill.executeSettlement(0);

        assertEq(bill.claimablePayout(0, owner), 10, "expected seat paid full share");
        assertEq(bill.claimablePayout(0, dan),   0,  "post-initiate seat sees zero view");

        // Post-execute: ladder precedence pin - the AlreadySettled guard fires BEFORE the
        // seat-membership check for a non-expected wallet (settledAt rung is first).
        vm.expectRevert(TandaBillV2.AlreadySettled.selector);
        vm.prank(dan); bill.confirmSettlement(0);

        vm.expectRevert(TandaBillV2.NotAnExpectedSeat.selector);
        vm.prank(dan); bill.claimSettlement(0);
    }

    // ─── (c) refunded settlement: zero view on every rung ─────────────────

    function test_d_refundedSettlement_viewZero() public {
        vm.startPrank(owner);
        bill.addExpense(10);
        token.approve(address(bill), 10);
        bill.fundEscrow(10);
        bill.initiateSettlement();
        vm.stopPrank();

        vm.prank(owner); bill.confirmSettlement(0); // partial: fullyConfirmedAt stays 0
        vm.warp(block.timestamp + uint256(bill.MAX_HOLD()) + 1);

        uint256 pre = token.balanceOf(owner);
        vm.prank(owner); bill.refundSettlement(0);
        assertEq(token.balanceOf(owner), pre + 10, "escrow returned to owner front");

        assertEq(bill.claimablePayout(0, owner), 0, "refunded rung: owner");
        assertEq(bill.claimablePayout(0, alice), 0, "refunded rung: alice");
        assertEq(bill.claimablePayout(0, bob),   0, "refunded rung: bob");

        vm.expectRevert(TandaBillV2.AlreadySettled.selector);
        vm.prank(alice); bill.confirmSettlement(0);
    }
}
