// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

import {TandaBill, IERC20} from "../contracts/TandaBill.sol";
import {Test} from "forge-std/Test.sol";

/// @notice Mock ERC-20 for tests (mimics USDC 6-decimal interface).
contract MockToken {
    string public name = "Mock USDC";
    string public symbol = "mUSDC";
    uint8 public decimals = 6;
    mapping(address => uint256) public balanceOf;
    mapping(address => mapping(address => uint256)) public allowance;

    function mint(address to, uint256 amount) external {
        balanceOf[to] += amount;
    }

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

contract TandaBillTest is Test {
    MockToken token;
    TandaBill bill;

    address owner = address(0xA11CE);
    address alice = address(0xB0B);
    address bob   = address(0xBEEF);
    address carol = address(0xCAFE);

    function setUp() public {
        token = new MockToken();
        vm.prank(owner);
        bill  = new TandaBill(IERC20(address(token)));

        // Fund test wallets
        token.mint(owner, 1_000_000e6);
        token.mint(alice, 1_000_000e6);
        token.mint(bob,   1_000_000e6);
        token.mint(carol, 1_000_000e6);
    }

    // ─── Seat management ──────────────────────────────────────────────────

    function test_addSeat() public {
        vm.prank(owner);
        bill.addSeat(alice);
        (address wallet, , bool active) = bill.seats(0);
        assertEq(wallet, alice);
        assertTrue(active);
    }

    function test_addSeat_revertsIfNotOwner() public {
        vm.prank(alice);
        vm.expectRevert(TandaBill.NotOwner.selector);
        bill.addSeat(alice);
    }

    function test_removeSeat() public {
        vm.prank(owner);
        bill.addSeat(alice);
        vm.prank(owner);
        bill.removeSeat(0);
        (, , bool active) = bill.seats(0);
        assertFalse(active);
    }

    // ─── Expense logging ──────────────────────────────────────────────────

    function test_addExpense() public {
        vm.prank(owner);
        bill.addExpense(100e6);
        (uint256 amount, address paidBy, , bool settled) = bill.expenses(0);
        assertEq(amount, 100e6);
        assertEq(paidBy, owner);
        assertFalse(settled);
    }

    function test_fundEscrow() public {
        vm.prank(owner);
        token.approve(address(bill), 100e6);
        vm.prank(owner);
        bill.fundEscrow(100e6);
        assertEq(bill.escrowBalance(), 100e6);
        assertEq(token.balanceOf(address(bill)), 100e6);
    }

    // ─── Settlement ───────────────────────────────────────────────────────

    function test_settlement_equalSplit() public {
        // 3 seats, 90 USDC total → 30 each
        vm.startPrank(owner);
        bill.addSeat(alice);
        bill.addSeat(bob);
        bill.addSeat(carol);
        bill.addExpense(90e6);
        token.approve(address(bill), 90e6);
        bill.fundEscrow(90e6);
        vm.stopPrank();

        vm.prank(owner);
        bill.initiateSettlement();
        vm.prank(owner);
        bill.executeSettlement(0);

        assertEq(token.balanceOf(alice), 1_000_000e6 + 30e6);
        assertEq(token.balanceOf(bob),   1_000_000e6 + 30e6);
        assertEq(token.balanceOf(carol), 1_000_000e6 + 30e6);
        assertEq(bill.escrowBalance(), 0);
    }

    function test_settlement_unevenSplit() public {
        // 3 seats, 100 USDC → 34, 33, 33 (remainder distributed to first seats)
        vm.startPrank(owner);
        bill.addSeat(alice);
        bill.addSeat(bob);
        bill.addSeat(carol);
        bill.addExpense(100e6);
        token.approve(address(bill), 100e6);
        bill.fundEscrow(100e6);
        vm.stopPrank();

        vm.prank(owner);
        bill.initiateSettlement();
        vm.prank(owner);
        bill.executeSettlement(0);

        // alice gets the remainder (100e6 % 3 = 1 wei)
        assertEq(token.balanceOf(alice), 1_000_000e6 + 33_333_334);
        assertEq(token.balanceOf(bob),   1_000_000e6 + 33_333_333);
        assertEq(token.balanceOf(carol), 1_000_000e6 + 33_333_333);
    }

    function test_settlement_revertsIfNoExpenses() public {
        vm.startPrank(owner);
        bill.addSeat(alice);
        vm.stopPrank();
        vm.prank(owner);
        vm.expectRevert(TandaBill.EscrowEmpty.selector);
        bill.initiateSettlement();
    }

    function test_settlement_revertsIfInsufficientEscrow() public {
        vm.startPrank(owner);
        bill.addSeat(alice);
        bill.addExpense(100e6);
        // Only fund 50, not 100
        token.approve(address(bill), 50e6);
        bill.fundEscrow(50e6);
        vm.stopPrank();
        vm.prank(owner);
        vm.expectRevert(TandaBill.EscrowEmpty.selector);
        bill.initiateSettlement();
    }

    // ─── Views ────────────────────────────────────────────────────────────

    function test_totalExpenses() public {
        vm.startPrank(owner);
        bill.addExpense(50e6);
        bill.addExpense(30e6);
        vm.stopPrank();
        assertEq(bill.totalExpenses(), 80e6);
    }

    function test_activeSeatCount() public {
        vm.startPrank(owner);
        bill.addSeat(alice);
        bill.addSeat(bob);
        bill.removeSeat(1);
        vm.stopPrank();
        assertEq(bill.activeSeatCount(), 1);
    }
}
