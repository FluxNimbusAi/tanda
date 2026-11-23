// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

import {TandaBillV2, IERC20} from "../contracts/TandaBillV2.sol";
import {TandaBillFactory} from "../contracts/TandaBillFactory.sol";
import {Test} from "forge-std/Test.sol";

/// @notice Mock ERC-20 for tests (mimics USDC 6-decimal interface).
contract MockTokenRefundOrder {
    string public name = "Mock USDC";
    string public symbol = "mUSDC";
    uint8 public decimals = 6;
    mapping(address => uint256) public balanceOf;
    mapping(address => mapping(address => uint256)) public allowance;

    function mint(address to, uint256 amount) external {
        balanceOf[to] += amount;
    }

    function transfer(address to, uint256 amount) external virtual returns (bool) {
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

/// @notice Card t_0a975d82: branch-order pins for the refund path on MAINLINE TandaBillV2.
///         The 69-test matrix pins AlreadySettled only against post-execute settlements
///         (test_confirm_revertsAfterSettle, test_refund_revertsAlreadySettled_afterExecute).
///         The refunded leg (s.refunded == 1, settledAt == 0, fullyConfirmedAt == 0) is
///         unpinned: confirm/execute must short-circuit on AlreadySettled BEFORE their
///         deeper guards (NotAwaitingConfirmations / AlreadyConfirmed / NotFullyConfirmed /
///         WindowNotElapsed). A guard reorder that lets a stale path answer first would
///         silently change revert semantics for indexers and clients that decode selectors.
contract MainlineRefundBranchOrderTest is Test {
    MockTokenRefundOrder token;
    TandaBillV2 impl;
    TandaBillFactory factory;

    address owner = address(0xA11CE);
    address alice = address(0xB0B);
    address bob   = address(0xBEEF);

    function setUp() public {
        token   = new MockTokenRefundOrder();
        impl    = new TandaBillV2();
        factory = new TandaBillFactory(address(impl));
        token.mint(owner, 1_000_000e6);
        token.mint(alice, 1_000_000e6);
        token.mint(bob,   1_000_000e6);
    }

    function _seats3() internal view returns (address[] memory s) {
        s = new address[](3);
        s[0] = owner;
        s[1] = alice;
        s[2] = bob;
    }

    /// @notice 3-seat bill, expense funded, settlement initiated (mirrors canonical helper).
    function _initiatedBill(uint256 amount) internal returns (TandaBillV2 bill) {
        vm.prank(owner);
        bill = TandaBillV2(payable(factory.createBill(IERC20(address(token)), _seats3())));
        vm.startPrank(owner);
        bill.addExpense(amount);
        token.approve(address(bill), amount);
        bill.fundEscrow(amount);
        bill.initiateSettlement();
        vm.stopPrank();
    }

    function _confirmAs(address who, TandaBillV2 bill, uint256 sid) internal {
        vm.prank(who);
        bill.confirmSettlement(sid);
    }

    /// @notice Initiate, optionally let seats confirm, then MAX_HOLD refund via owner.
    function _refundedBill(uint256 amount, bool aliceConfirmed) internal returns (TandaBillV2 bill) {
        bill = _initiatedBill(amount);
        if (aliceConfirmed) {
            _confirmAs(alice, bill, 0); // partial confirmedMask; fullyConfirmedAt stays 0
        }
        vm.warp(block.timestamp + 72 hours);
        vm.prank(owner);
        bill.refundSettlement(0);
    }

    function test_confirm_afterRefund_revertsAlreadySettled_beatsNotAwaitingConfirmations() public {
        // refunded, no confirmations yet: the ordering contract is AlreadySettled first
        // (source: 'if (s.settledAt != 0 || s.refunded) revert AlreadySettled()' precedes
        // the NotAwaitingConfirmations guard in confirmSettlement).
        TandaBillV2 bill = _refundedBill(100e6, false);
        vm.expectRevert(TandaBillV2.AlreadySettled.selector);
        _confirmAs(bob, bill, 0);
    }

    function test_confirm_afterRefund_revertsAlreadySettled_beatsAlreadyConfirmed() public {
        // alice confirmed pre-refund: her bit is set. A reorder to the AlreadyConfirmed guard
        // first would change her revert reason; pin says refunded settlements answer AlreadySettled.
        TandaBillV2 bill = _refundedBill(100e6, true);
        vm.expectRevert(TandaBillV2.AlreadySettled.selector);
        _confirmAs(alice, bill, 0);
    }

    function test_execute_afterRefund_revertsAlreadySettled_beatsNotFullyConfirmed() public {
        // never fully confirmed + refunded: NotFullyConfirmed must NOT answer first.
        TandaBillV2 bill = _refundedBill(100e6, false);
        vm.expectRevert(TandaBillV2.AlreadySettled.selector);
        bill.executeSettlement(0);
    }

    function test_execute_afterRefund_windowWarp_stillAlreadySettled() public {
        // warp past SETTLEMENT_WINDOW so the timestamp guard would also pass on a reorder;
        // AlreadySettled must still win even if fullyConfirmedAt were set. Here it is 0, so
        // this pins: refunded check precedes BOTH NotFullyConfirmed and WindowNotElapsed.
        TandaBillV2 bill = _refundedBill(100e6, false);
        vm.warp(block.timestamp + 1 hours + 1);
        vm.expectRevert(TandaBillV2.AlreadySettled.selector);
        bill.executeSettlement(0);
    }
}
