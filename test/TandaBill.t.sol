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

    // ─── W2 gap tests (from Flux test-audit-20261113.md) ──────────────────

    /// Gap 1: double-settlement of the same expense must revert.
    /// executeSettlement guards with `require(s.settledAt == 0, AlreadySettled())`.
    function test_settlement_revertsIfDoubleSettled() public {
        vm.startPrank(owner);
        bill.addSeat(alice);
        bill.addSeat(bob);
        bill.addExpense(60e6);
        token.approve(address(bill), 60e6);
        bill.fundEscrow(60e6);
        bill.initiateSettlement();
        bill.executeSettlement(0); // first: succeeds
        vm.stopPrank();

        // Second execution of the same settlement id must revert.
        vm.prank(owner);
        vm.expectRevert(TandaBill.AlreadySettled.selector);
        bill.executeSettlement(0);
    }

    /// Gap 2: settle-after-seat-removal semantics — PINNED, not assumed.
    /// DESIGN FINDING (confirmed by execution, not assumption):
    ///   - initiateSettlement subtracts the FULL unsettled total from escrowBalance
    ///     at initiation (escrowBalance → 0) and builds payouts[] for N active seats.
    ///   - executeSettlement re-iterates seats and pays payouts[idx] only to seats
    ///     active AT EXECUTION. A seat removed between the two calls is skipped.
    ///   - NET EFFECT: the removed seat's share is NEVER transferred and NEVER
    ///     accounted for. escrowBalance reads 0, but the contract's token balance
    ///     still holds the removed seat's share — permanently stranded, with no
    ///     recovery path (invariant #1: no key custody / no recovery).
    /// This is a real fund-stranding bug. The test pins current behavior so it
    /// can't regress unnoticed; the FIX (re-derive payouts at execute, or forbid
    /// seat removal after initiate) is a design decision for the bus.
    /// See docs/test-audit-20261113.md gap 2.
    function test_settlement_seatRemovedBetweenInitiateAndExecute() public {
        // 2 active seats at initiation: alice + bob, 100 USDC → 50 each
        vm.startPrank(owner);
        bill.addSeat(alice);
        bill.addSeat(bob);
        bill.addExpense(100e6);
        token.approve(address(bill), 100e6);
        bill.fundEscrow(100e6);
        bill.initiateSettlement();
        // escrowBalance is zeroed at initiation (full total subtracted).
        assertEq(bill.escrowBalance(), 0);
        // Remove bob AFTER initiation, BEFORE execution.
        bill.removeSeat(1);
        vm.stopPrank();

        vm.prank(owner);
        bill.executeSettlement(0);

        // alice gets payouts[0] = 50e6. bob is skipped (inactive at execute).
        assertEq(token.balanceOf(alice), 1_000_000e6 + 50e6);
        assertEq(token.balanceOf(bob),   1_000_000e6); // unchanged — his 50e6 was dropped
        // escrowBalance still reads 0, but the contract HOLDS bob's stranded 50e6.
        assertEq(bill.escrowBalance(), 0);
        assertEq(token.balanceOf(address(bill)), 50e6); // ← FUND STRANDING (the bug)
    }

    /// Gap 3: transferFrom failure path must revert cleanly with TokenTransferFailed().
    /// Mock token always succeeds; this uses a failing mock to prove fundEscrow's
    /// require(token.transferFrom(...)) guard fires on a real-world USDC failure.
    function test_fundEscrow_revertsIfTransferFromFails() public {
        FailingToken bad = new FailingToken();
        vm.prank(owner);
        TandaBill b2 = new TandaBill(IERC20(address(bad)));
        // No mint, no approve → transferFrom must fail.
        vm.prank(owner);
        vm.expectRevert(TandaBill.TokenTransferFailed.selector);
        b2.fundEscrow(100e6);
    }

    /// Gap 4 (confirmation): uneven-split remainder test uses N>1.
    /// Already covered by test_settlement_unevenSplit (3 seats). This is a
    /// documentation-only assertion that the remainder logic engages for N>1:
    /// with 4 seats and 100 USDC, base=25e6, remainder=0 → all get exactly 25e6.
    /// The N>1 remainder path (100e6 % 3 = 1 wei) is the unevenSplit test above.
    function test_settlement_unevenSplit_fourSeats() public {
        // 4 seats, 100 USDC → 25 each (no remainder); pins N=4 distribution.
        address dave = address(0xDA7E);
        token.mint(dave, 1_000_000e6); // dave not minted in setUp
        vm.startPrank(owner);
        bill.addSeat(alice);
        bill.addSeat(bob);
        bill.addSeat(carol);
        bill.addSeat(dave);
        bill.addExpense(100e6);
        token.approve(address(bill), 100e6);
        bill.fundEscrow(100e6);
        bill.initiateSettlement();
        bill.executeSettlement(0);
        vm.stopPrank();

        assertEq(token.balanceOf(alice), 1_000_000e6 + 25e6);
        assertEq(token.balanceOf(bob),   1_000_000e6 + 25e6);
        assertEq(token.balanceOf(carol), 1_000_000e6 + 25e6);
        assertEq(token.balanceOf(dave),  1_000_000e6 + 25e6);
        assertEq(bill.escrowBalance(), 0);
    }
}

/// @notice Token that always fails transferFrom — for the failure-path test.
contract FailingToken {
    function transfer(address, uint256) external pure returns (bool) { return false; }
    function transferFrom(address, address, uint256) external pure returns (bool) { return false; }
    function balanceOf(address) external pure returns (uint256) { return 0; }
}
