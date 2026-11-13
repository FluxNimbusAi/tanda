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
        // W5: warp past the settlement window before executing.
        vm.warp(block.timestamp + 1 hours);
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
        // W5: warp past the settlement window.
        vm.warp(block.timestamp + 1 hours);
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
        // W5: warp past the settlement window.
        vm.warp(block.timestamp + 1 hours);
        bill.executeSettlement(0); // first: succeeds
        vm.stopPrank();

        // Second execution of the same settlement id must revert.
        vm.prank(owner);
        vm.expectRevert(TandaBill.AlreadySettled.selector);
        bill.executeSettlement(0);
    }

    /// Gap 2: settle-after-seat-removal — FIXED by Option 1 (bus ruling).
    /// BEFORE the fix this was a real fund-stranding bug: initiateSettlement
    /// zeroed escrowBalance and froze payouts[] for N active seats, then
    /// executeSettlement skipped a seat removed in between — so the removed
    /// seat's share was never transferred and never accounted for (stranded in
    /// the contract, no recovery path, invariant #1).
    /// OPTION 1 (ratified): removeSeat now reverts once settlementInitiated is
    /// true, so the stranding state is unreachable by construction. This test
    /// pins the guard: removing a seat after initiation must revert with
    /// SettlementInitiatedAlready(), and the roster stays frozen.
    /// See docs/test-audit-20261113.md gap 2 + W2_FINDINGS.md.
    function test_removeSeat_revertsAfterSettlementInitiated() public {
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
        assertTrue(bill.settlementInitiated());
        // Remove bob AFTER initiation, BEFORE execution → must now revert.
        vm.expectRevert(TandaBill.SettlementInitiatedAlready.selector);
        bill.removeSeat(1);
        vm.stopPrank();

        // Roster is frozen: bob is still active, so settlement pays both seats.
        vm.prank(owner);
        // W5: warp past the settlement window.
        vm.warp(block.timestamp + 1 hours);
        bill.executeSettlement(0);
        assertEq(token.balanceOf(alice), 1_000_000e6 + 50e6);
        assertEq(token.balanceOf(bob),   1_000_000e6 + 50e6); // NOT stranded — guard held
        // Nothing left in the contract: no stranding possible.
        assertEq(bill.escrowBalance(), 0);
        assertEq(token.balanceOf(address(bill)), 0);
    }

    /// Gap 2 (positive control): removeSeat still works BEFORE initiation.
    /// The Option-1 guard must not over-restrict — pre-settlement removal is
    /// the normal flow and must keep working.
    function test_removeSeat_allowedBeforeSettlementInitiated() public {
        vm.startPrank(owner);
        bill.addSeat(alice);
        bill.addSeat(bob);
        assertFalse(bill.settlementInitiated());
        bill.removeSeat(1); // pre-initiation: allowed
        (, , bool active) = bill.seats(1);
        assertFalse(active);
        vm.stopPrank();
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
        // W5: warp past the settlement window.
        vm.warp(block.timestamp + 1 hours);
        bill.executeSettlement(0);
        vm.stopPrank();

        assertEq(token.balanceOf(alice), 1_000_000e6 + 25e6);
        assertEq(token.balanceOf(bob),   1_000_000e6 + 25e6);
        assertEq(token.balanceOf(carol), 1_000_000e6 + 25e6);
        assertEq(token.balanceOf(dave),  1_000_000e6 + 25e6);
        assertEq(bill.escrowBalance(), 0);
    }

    // ─── W5: SETTLEMENT_WINDOW enforcement ───────────────────────────────

    /// W5-1: executeSettlement must revert if called before the settlement
    /// window has elapsed. The window is anchored to initiatedAt (the block
    /// timestamp at which initiateSettlement was called). This test warps
    /// time to just before the window closes and expects a revert with
    /// SettlementNotReady().
    function test_W5_executeSettlement_revertsBeforeWindow() public {
        vm.startPrank(owner);
        bill.addSeat(alice);
        bill.addSeat(bob);
        bill.addExpense(100e6);
        token.approve(address(bill), 100e6);
        bill.fundEscrow(100e6);

        uint256 tInit = block.timestamp;
        bill.initiateSettlement();

        // Warp to just before the window closes (1 hour - 1 second).
        vm.warp(tInit + 1 hours - 1);
        vm.expectRevert(TandaBill.SettlementNotReady.selector);
        bill.executeSettlement(0);
        vm.stopPrank();

        // No funds should have moved.
        assertEq(token.balanceOf(alice), 1_000_000e6);
        assertEq(token.balanceOf(bob),   1_000_000e6);
        assertEq(token.balanceOf(address(bill)), 100e6);
    }

    /// W5-2: executeSettlement succeeds exactly at the window boundary
    /// (block.timestamp == initiatedAt + SETTLEMENT_WINDOW). This pins the
    /// boundary condition: the window is inclusive, not exclusive.
    function test_W5_executeSettlement_succeedsAtWindowBoundary() public {
        vm.startPrank(owner);
        bill.addSeat(alice);
        bill.addSeat(bob);
        bill.addExpense(100e6);
        token.approve(address(bill), 100e6);
        bill.fundEscrow(100e6);

        uint256 tInit = block.timestamp;
        bill.initiateSettlement();

        // Warp to exactly the window boundary.
        vm.warp(tInit + 1 hours);
        bill.executeSettlement(0);
        vm.stopPrank();

        assertEq(token.balanceOf(alice), 1_000_000e6 + 50e6);
        assertEq(token.balanceOf(bob),   1_000_000e6 + 50e6);
        assertEq(bill.escrowBalance(), 0);
    }

    /// W5-3: executeSettlement succeeds after the window has fully elapsed.
    /// Warps well past the boundary to confirm the happy path is intact.
    function test_W5_executeSettlement_succeedsAfterWindow() public {
        vm.startPrank(owner);
        bill.addSeat(alice);
        bill.addSeat(bob);
        bill.addExpense(100e6);
        token.approve(address(bill), 100e6);
        bill.fundEscrow(100e6);

        uint256 tInit = block.timestamp;
        bill.initiateSettlement();

        // Warp well past the window (2 hours).
        vm.warp(tInit + 2 hours);
        bill.executeSettlement(0);
        vm.stopPrank();

        assertEq(token.balanceOf(alice), 1_000_000e6 + 50e6);
        assertEq(token.balanceOf(bob),   1_000_000e6 + 50e6);
        assertEq(bill.escrowBalance(), 0);
    }

    /// W5-4: The window is anchored to initiatedAt, not to the current block
    /// timestamp at call time. This test warps time BEFORE initiation, then
    /// initiates, then checks that the window is measured from the initiation
    /// timestamp (not the pre-warped time).
    function test_W5_windowAnchoredToInitiatedAt() public {
        vm.startPrank(owner);
        bill.addSeat(alice);
        bill.addSeat(bob);
        bill.addExpense(100e6);
        token.approve(address(bill), 100e6);
        bill.fundEscrow(100e6);

        // Warp to a future time BEFORE initiation.
        uint256 tFuture = vm.getBlockTimestamp() + 1 days;
        vm.warp(tFuture);
        bill.initiateSettlement();
        // initiatedAt should be tFuture, not the original timestamp.

        // Now warp to tFuture + 30 minutes (halfway through the window).
        vm.warp(tFuture + 30 minutes);
        vm.expectRevert(TandaBill.SettlementNotReady.selector);
        bill.executeSettlement(0);
        vm.stopPrank();

        // Warp to tFuture + 1 hour (window boundary) → should succeed.
        vm.prank(owner);
        vm.warp(tFuture + 1 hours);
        bill.executeSettlement(0);
        assertEq(token.balanceOf(alice), 1_000_000e6 + 50e6);
        assertEq(token.balanceOf(bob),   1_000_000e6 + 50e6);
    }

    /// W5-5: Existing tests that call executeSettlement immediately after
    /// initiateSettlement (without warping) will now fail because the window
    /// hasn't elapsed. This test documents that the existing test suite
    /// requires vm.warp adjustments. We verify the revert fires.
    function test_W5_immediateExecuteReverts() public {
        vm.startPrank(owner);
        bill.addSeat(alice);
        bill.addSeat(bob);
        bill.addExpense(100e6);
        token.approve(address(bill), 100e6);
        bill.fundEscrow(100e6);
        bill.initiateSettlement();
        // No warp — execute immediately → must revert.
        vm.expectRevert(TandaBill.SettlementNotReady.selector);
        bill.executeSettlement(0);
        vm.stopPrank();
    }

    // ─── W3: Settlement execution hardening ──────────────────────────────

    /// W3-1: Idempotent payout re-entry guard.
    /// executeSettlement must be strictly single-shot per settlement id.
    /// The guard `require(s.settledAt == 0, AlreadySettled())` ensures that a
    /// second call on the same id reverts BEFORE any token transfer, so no
    /// seat can be paid twice. This test pins the guard: after a successful
    /// execution, a re-entry (even from a different caller context) must
    /// revert with AlreadySettled() and leave all balances unchanged.
    function test_W3_executeSettlement_revertsOnReentry() public {
        vm.startPrank(owner);
        bill.addSeat(alice);
        bill.addSeat(bob);
        bill.addExpense(100e6);
        token.approve(address(bill), 100e6);
        bill.fundEscrow(100e6);
        bill.initiateSettlement();
        // W5: warp past the settlement window.
        vm.warp(block.timestamp + 1 hours);
        bill.executeSettlement(0); // first: succeeds, pays 50/50
        vm.stopPrank();

        // Capture post-execution balances.
        uint256 aliceAfter = token.balanceOf(alice);
        uint256 bobAfter   = token.balanceOf(bob);
        uint256 contractAfter = token.balanceOf(address(bill));

        // Re-entry: same settlement id, must revert with AlreadySettled().
        vm.prank(owner);
        vm.expectRevert(TandaBill.AlreadySettled.selector);
        bill.executeSettlement(0);

        // Balances must be unchanged — no double-payout.
        assertEq(token.balanceOf(alice), aliceAfter);
        assertEq(token.balanceOf(bob),   bobAfter);
        assertEq(token.balanceOf(address(bill)), contractAfter);
    }

    /// W3-2: Zero-split edge case — settlement with zero unsettled expenses.
    /// initiateSettlement requires `unsettled > 0`, so a bill with no expenses
    /// (or all expenses already settled) must revert with EscrowEmpty() before
    /// any payout array is constructed. This pins the guard against a
    /// degenerate zero-split that would produce an empty payouts[] and a
    /// settlement that pays nothing.
    function test_W3_initiateSettlement_revertsIfNoUnsettledExpenses() public {
        vm.startPrank(owner);
        bill.addSeat(alice);
        bill.addSeat(bob);
        // No expenses added — unsettled total is 0.
        token.approve(address(bill), 100e6);
        bill.fundEscrow(100e6); // escrow has funds, but nothing to settle
        vm.expectRevert(TandaBill.EscrowEmpty.selector);
        bill.initiateSettlement();
        vm.stopPrank();
    }

    /// W3-2b: Zero-split edge case — all seats removed before initiation.
    /// If the owner removes every seat, activeCount is 0 and
    /// initiateSettlement must revert with SeatNotFound(0) (the existing
    /// guard for "no active seats"). This prevents a settlement with an
    /// empty payouts[] that would strand the full escrow balance.
    function test_W3_initiateSettlement_revertsIfNoActiveSeats() public {
        vm.startPrank(owner);
        bill.addSeat(alice);
        bill.addSeat(bob);
        bill.addExpense(100e6);
        token.approve(address(bill), 100e6);
        bill.fundEscrow(100e6);
        // Remove ALL seats before initiation.
        bill.removeSeat(0);
        bill.removeSeat(1);
        vm.expectRevert(abi.encodeWithSelector(TandaBill.SeatNotFound.selector, 0));
        bill.initiateSettlement();
        vm.stopPrank();
    }

    /// W3-3: Event-emission audit — full lifecycle emits the correct event
    /// sequence with correct parameters. This is a regression guard: if a
    /// future change alters the event signature, drops an emission, or
    /// reorders the sequence, this test catches it.
    function test_W3_eventEmissionAudit_fullLifecycle() public {
        vm.startPrank(owner);

        // 1. addSeat(alice) → SeatAdded(0, alice, ts)
        vm.expectEmit(true, false, false, true);
        emit TandaBill.SeatAdded(0, alice, uint64(block.timestamp));
        bill.addSeat(alice);

        // 2. addSeat(bob) → SeatAdded(1, bob, ts)
        vm.expectEmit(true, false, false, true);
        emit TandaBill.SeatAdded(1, bob, uint64(block.timestamp));
        bill.addSeat(bob);

        // 3. addExpense(100e6) → ExpenseAdded(0, owner, 100e6)
        vm.expectEmit(true, false, false, true);
        emit TandaBill.ExpenseAdded(0, owner, 100e6);
        bill.addExpense(100e6);

        // 4. fundEscrow — no event (by design: transferFrom is the observable)

        // 5. initiateSettlement → SettlementInitiated(0, 100e6, 2)
        token.approve(address(bill), 100e6);
        bill.fundEscrow(100e6);
        vm.expectEmit(true, false, false, true);
        emit TandaBill.SettlementInitiated(0, 100e6, 2);
        bill.initiateSettlement();

        // 6. executeSettlement(0) → SettlementExecuted(0, 100e6, ts)
        // W5: warp past the settlement window.
        uint256 tExec = vm.getBlockTimestamp() + 1 hours;
        vm.warp(tExec);
        vm.expectEmit(true, false, false, true);
        emit TandaBill.SettlementExecuted(0, 100e6, uint64(tExec));
        bill.executeSettlement(0);

        vm.stopPrank();

        // Post-conditions: settlement recorded, escrow drained.
        (uint256 totalAmount, , uint64 settledAt) = bill.settlements(0);
        assertEq(totalAmount, 100e6);
        assertTrue(settledAt > 0);
        assertEq(bill.escrowBalance(), 0);
    }
}

/// @notice Token that always fails transferFrom — for the failure-path test.
contract FailingToken {
    function transfer(address, uint256) external pure returns (bool) { return false; }
    function transferFrom(address, address, uint256) external pure returns (bool) { return false; }
    function balanceOf(address) external pure returns (uint256) { return 0; }
}
