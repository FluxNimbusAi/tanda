// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

import {TandaBillV2, IERC20} from "../contracts/TandaBillV2.sol";
import {TandaBillFactory} from "../contracts/TandaBillFactory.sol";
import {Test} from "forge-std/Test.sol";

/// @notice Minimal 6-decimal mock (same semantics as the main suite's MockToken).
contract BoundaryMockToken {
    mapping(address => uint256) public balanceOf;
    mapping(address => mapping(address => uint256)) public allowance;

    function mint(address to, uint256 amount) external { balanceOf[to] += amount; }

    function transfer(address to, uint256 amount) external returns (bool) {
        require(balanceOf[msg.sender] >= amount, "insufficient");
        balanceOf[msg.sender] -= amount;
        balanceOf[to] += amount;
        return true;
    }

    function transferFrom(address from, address to, uint256 amount) external returns (bool) {
        require(balanceOf[from] >= amount, "insufficient");
        require(allowance[from][msg.sender] >= amount, "allowance");
        balanceOf[from] -= amount;
        balanceOf[to] += amount;
        allowance[from][msg.sender] -= amount;
        return true;
    }

    function approve(address spender, uint256 amount) external returns (bool) {
        allowance[msg.sender][spender] = amount;
        return true;
    }
}

/// @title V2BoundaryLedgerMatrix
/// @notice ENGINE family-(1) test-matrix deepening: pins four boundary behaviors of
///         TandaBillV2's ledger/escrow arithmetic that had no explicit coverage:
///         (1) addExpense(0) is ACCEPTED by design (ledger-neutral, still reverts non-owner);
///         (2) fundEscrow(0) succeeds as a no-op and must not move escrowBalance;
///         (3) over-funded escrow: initiateSettlement charges ONLY unsettled, the residual
///             stays claimable-neutral inside the bill after full drain (never auto-paid);
///         (4) remainder wei after seat removal goes to the FIRST ACTIVE seat in enrollment
///             order (idx-based assignment, not seat-id based).
contract V2BoundaryLedgerMatrix is Test {
    BoundaryMockToken token;
    TandaBillV2 impl;
    TandaBillFactory factory;

    address owner = address(0xA11CE);
    address alice = address(0xB0B);
    address bob   = address(0xBEEF);

    function setUp() public {
        token   = new BoundaryMockToken();
        impl    = new TandaBillV2();
        factory = new TandaBillFactory(address(impl));
        token.mint(owner, 1_000_000e6);
        token.mint(alice, 1_000_000e6);
        token.mint(bob,   1_000_000e6);
    }

    function _seats3() internal view returns (address[] memory s) {
        s = new address[](3);
        s[0] = owner; s[1] = alice; s[2] = bob;
    }

    function _createAs(address creator, address[] memory s) internal returns (TandaBillV2 bill) {
        vm.prank(creator);
        bill = TandaBillV2(payable(factory.createBill(IERC20(address(token)), s)));
    }

    function _confirmAs(address who, TandaBillV2 bill, uint256 sid) internal {
        vm.prank(who);
        bill.confirmSettlement(sid);
    }

    function _claimAs(address who, TandaBillV2 bill, uint256 sid) internal {
        vm.prank(who);
        bill.claimSettlement(sid);
    }

    // ---- (1) zero-value expense is accepted, ledger-neutral, non-owner still blocked ----
    function test_boundary_addExpense_zero_accepted_ledgerNeutral() public {
        TandaBillV2 bill = _createAs(owner, _seats3());
        vm.prank(owner);
        bill.addExpense(0);
        assertEq(bill.totalExpenses(), 0);          // zero expense adds nothing
        vm.prank(owner);
        bill.addExpense(0);
        assertEq(bill.totalExpenses(), 0);

        // zero-only ledger still reverts settlement: unsettled == 0 -> EscrowEmpty
        vm.startPrank(owner);
        token.approve(address(bill), 10e6);
        bill.fundEscrow(10e6);
        vm.expectRevert(TandaBillV2.EscrowEmpty.selector);
        bill.initiateSettlement();
        vm.stopPrank();

        // non-owner boundary unchanged even for zero
        vm.expectRevert(TandaBillV2.NotOwner.selector);
        vm.prank(alice);
        bill.addExpense(0);
    }

    // ---- (2) zero-amount funding is a clean no-op ----
    function test_boundary_fundEscrow_zero_noBalanceChange() public {
        TandaBillV2 bill = _createAs(owner, _seats3());
        vm.startPrank(owner);
        token.approve(address(bill), 1);
        bill.fundEscrow(0);
        assertEq(bill.escrowBalance(), 0);
        assertEq(token.balanceOf(address(bill)), 0);
        bill.fundEscrow(0);
        assertEq(bill.escrowBalance(), 0);
        vm.stopPrank();
    }

    // ---- (3) over-funded escrow: settlement charges ONLY unsettled; residual stays in bill ----
    function test_boundary_overEscrow_residualStaysInBill() public {
        TandaBillV2 bill = _createAs(owner, _seats3());
        uint256 expense = 300e6;                    // settlement will cost exactly 300e6
        uint256 funded  = 450e6;                    // deliberate over-funding
        vm.startPrank(owner);
        bill.addExpense(expense);
        token.approve(address(bill), funded);
        bill.fundEscrow(funded);
        bill.initiateSettlement();
        vm.stopPrank();

        assertEq(bill.escrowBalance(), funded - expense); // residual 150e6 kept aside
        uint256[] memory payouts = bill.settlementPayouts(0);
        uint256 sum;
        for (uint256 i = 0; i < payouts.length; i++) sum += payouts[i];
        assertEq(sum, expense);                     // payouts cover unsettled, not funding

        _confirmAs(owner, bill, 0);
        _confirmAs(alice, bill, 0);
        _confirmAs(bob,   bill, 0);
        vm.warp(block.timestamp + 1 hours + 1);
        vm.prank(owner);
        bill.executeSettlement(0);

        _claimAs(owner, bill, 0);
        _claimAs(alice, bill, 0);
        _claimAs(bob,   bill, 0);

        // residual is NEVER auto-paid: after full drain, exactly 150e6 still sits in the bill
        assertEq(token.balanceOf(address(bill)), 150e6);
        assertEq(bill.escrowBalance(), 150e6);
        // seats received exactly their equal-split payouts (300e6 total)
        assertEq(token.balanceOf(alice), 1_000_000e6 + 100e6);
        assertEq(token.balanceOf(bob),   1_000_000e6 + 100e6);
        assertEq(token.balanceOf(owner), 1_000_000e6 - funded + 100e6);
    }

    // ---- (4) remainder wei lands on first ACTIVE seat in enrollment order after removal ----
    function test_boundary_remainder_afterRemoval_toFirstActiveSeat() public {
        TandaBillV2 bill = _createAs(owner, _seats3());
        vm.startPrank(owner);
        bill.removeSeat(1);                         // alice out; owner + bob remain active
        bill.addExpense(101e6 + 1);                 // odd amount -> base 50,500,000 rem 1
        token.approve(address(bill), 101e6 + 1);
        bill.fundEscrow(101e6 + 1);
        bill.initiateSettlement();
        vm.stopPrank();

        assertEq(bill.activeSeatCount(), 2);
        uint256[] memory payouts = bill.settlementPayouts(0);
        assertEq(payouts.length, 2);
        assertEq(payouts[0], 50_500_001);           // idx-0 = first active (owner), NOT seat-id parity
        assertEq(payouts[1], 50_500_000);           // idx-1 = bob
        assertEq(bill.claimablePayout(0, alice), 0); // removed seat claims nothing

        _confirmAs(owner, bill, 0);
        _confirmAs(bob,   bill, 0);
        vm.warp(block.timestamp + 1 hours + 1);
        vm.prank(owner);
        bill.executeSettlement(0);
        _claimAs(owner, bill, 0);
        _claimAs(bob,   bill, 0);

        assertEq(token.balanceOf(address(bill)), 0);            // escrow fully drained
        assertEq(token.balanceOf(alice), 1_000_000e6);          // removed seat unchanged
        assertEq(token.balanceOf(bob),   1_000_000e6 + 50_500_000);
    }
}
