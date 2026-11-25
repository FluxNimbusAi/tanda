// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

import {TandaBillV2, IERC20} from "../contracts/TandaBillV2.sol";
import {TandaBillFactory} from "../contracts/TandaBillFactory.sol";
import {Test} from "forge-std/Test.sol";

/// @notice Minimal USDC-shaped mock (identical semantics to TandaBillV2.t.sol MockToken).
contract CornerMockToken {
    mapping(address => uint256) public balanceOf;
    mapping(address => mapping(address => uint256)) public allowance;

    function mint(address to, uint256 amount) external { balanceOf[to] += amount; }

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

/// @title V2 defensive mask-corner goldens (engine card t_66303ab9)
/// @notice closes the four invariant-blocked coverage corners of contracts/TandaBillV2.sol
///         (gaps_full.json 2026-11-24 22:29): the `expectedMask/active` compound checks at
///         L394 (confirmSettlement), L453 (claimSettlement), L537 (claimablePayout) — whose
///         revert / return-0 bodies can never fire through honest calldata because the W5
///         roster freeze keeps expectedMask a superset-consistent snapshot — and the
///         `return false` at L498 (_allSettlementsDrained) which needs a non-terminal
///         sibling settlement at the drain check. Each corner is pinned BOTH operand
///         directions where applicable, via storage-injection (vm.store), proving the
///         guards behave to typed-error spec even if seatIdOf/seats[] were ever made
///         inconsistent by migration/upgrade surgery — a defensive-legality test, not a
///         reachability claim: natural paths are asserted impossible by the freeze goldens
///         in TandaBillV2.t.sol (test_pull_claim_revertsNotAnExpectedSeat et al.).
/// @dev storage layout (PROBE-CONFIRMED 2026-11-24, SeatsSlotProbe run on this tree):
///      token 0 | owner+!_initialized packed 1 | seats[] 2 | seatIdOf 3 | expenses[] 4 |
///      settlements[] 5 | escrowBalance 6 | settlementInitiated+factory PACKED 7 (bool byte0,
///      address bytes1-20 — 1+20<=32) | seatNullifierOf 8 | seatNullifierSignalHash 9.
///      Seat word packing: wallet bits [0,160) | joinedAt [160,224) | active bit 224.
contract V2DefensiveMaskCornersTest is Test {
    CornerMockToken token;
    TandaBillV2 impl;
    TandaBillFactory factory;

    address owner = address(0xA11CE);
    address alice = address(0xB0B);
    address bob   = address(0xBEEF);
    address carol = address(0xCAFE); // NOT in the standard roster -> ghost raw candidate

    function setUp() public {
        token = new CornerMockToken();
        impl  = new TandaBillV2();
        factory = new TandaBillFactory(address(impl));
        token.mint(owner, 1_000_000e6);
        token.mint(alice, 1_000_000e6);
        token.mint(bob,   1_000_000e6);
        token.mint(carol, 1_000_000e6);
    }

    // ─── helpers ──────────────────────────────────────────────────────────

    function _seats3() internal view returns (address[] memory s) {
        s = new address[](3);
        s[0] = owner;
        s[1] = alice;
        s[2] = bob;
    }

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

    function _claimAs(address who, TandaBillV2 bill, uint256 sid) internal {
        vm.prank(who);
        bill.claimSettlement(sid);
    }

    /// @notice inject seatIdOf[ghost] = id+1 (mapping at slot 3 — probe-confirmed).
    function _injectSeatIdOf(TandaBillV2 bill, address ghost, uint256 raw) internal {
        bytes32 slot = keccak256(abi.encode(uint256(uint160(ghost)), uint256(3)));
        vm.store(address(bill), slot, bytes32(raw));
    }

    /// @notice clear seats[i].active (array at slot 2 — probe-confirmed; single packed word).
    function _injectSeatInactive(TandaBillV2 bill, uint256 i) internal {
        bytes32 base = keccak256(abi.encode(uint256(2)));
        bytes32 slot = bytes32(uint256(base) + i);
        bytes32 w = vm.load(address(bill), slot);
        w &= ~bytes32(uint256(1) << 224);
        vm.store(address(bill), slot, w);
    }

    function _toExecuted(TandaBillV2 bill) internal {
        _confirmAs(owner, bill, 0);
        _confirmAs(alice, bill, 0);
        _confirmAs(bob,   bill, 0);
        vm.warp(block.timestamp + 1 hours + 1);
        bill.executeSettlement(0);
    }

    // ─── operand 1: (expectedMask & bit) == 0 with raw != 0 ───────────────

    function test_def_confirm_ghostSeatId_operand1_L394() public {
        TandaBillV2 bill = _initiatedBill(300e6);
        _injectSeatIdOf(bill, carol, 4); // seatId 3 -> bit 8, outside expectedMask 0b111
        vm.expectRevert(TandaBillV2.NotAnExpectedSeat.selector);
        _confirmAs(carol, bill, 0);
    }

    function test_def_claim_ghostSeatId_operand1_L453() public {
        TandaBillV2 bill = _initiatedBill(300e6);
        _toExecuted(bill);
        _injectSeatIdOf(bill, carol, 4);
        vm.expectRevert(TandaBillV2.NotAnExpectedSeat.selector);
        _claimAs(carol, bill, 0);
    }

    function test_def_view_ghostSeatId_operand1_L537() public {
        TandaBillV2 bill = _initiatedBill(300e6);
        _toExecuted(bill);
        _injectSeatIdOf(bill, carol, 4);
        assertEq(bill.claimablePayout(0, carol), 0, "ghost raw must return 0 at L537");
    }

    // ─── operand 2: !seats[seatId].active with bit inside expectedMask ────

    function test_def_confirm_inactiveExpected_operand2_L394() public {
        TandaBillV2 bill = _initiatedBill(300e6);
        _confirmAs(owner, bill, 0);
        _confirmAs(alice, bill, 0);
        _injectSeatInactive(bill, 2); // bob: bit 4 IS in expectedMask, active cleared
        vm.expectRevert(TandaBillV2.NotAnExpectedSeat.selector);
        _confirmAs(bob, bill, 0);
    }

    function test_def_claim_inactiveExpected_operand2_L453() public {
        TandaBillV2 bill = _initiatedBill(300e6);
        _toExecuted(bill);
        _injectSeatInactive(bill, 2); // bob confirmed pre-injection; share still unclaimed
        vm.expectRevert(TandaBillV2.NotAnExpectedSeat.selector);
        _claimAs(bob, bill, 0);
        // and bob's unclaimed share keeps everyone else's freeze honest:
        assertTrue(bill.settlementInitiated(), "round stays initiated while a share is live");
    }

    function test_def_view_inactiveExpected_operand2_L537() public {
        TandaBillV2 bill = _initiatedBill(300e6);
        _toExecuted(bill);
        _injectSeatInactive(bill, 2);
        assertEq(bill.claimablePayout(0, bob), 0, "inactive expected seat must view 0 at L537");
    }

    // ─── L498: _allSettlementsDrained sees a non-terminal sibling ─────────

    function test_def_drain_pendingSibling_L498() public {
        // S0 initiated and left PENDING (never fully confirmed -> settledAt == 0).
        TandaBillV2 bill = _initiatedBill(300e6);
        // NO slot surgery needed (prior draft's store(slot 8) cleared the
        // seatNullifierOf mapping base — a no-op on the latch): initiateSettlement
        // does NOT gate on settlementInitiated, so a second live round is the
        // NATURAL route to L498's return-false while S0 stays non-terminal.
        vm.startPrank(owner);
        bill.addExpense(300e6);
        token.approve(address(bill), 300e6);
        bill.fundEscrow(300e6);
        bill.initiateSettlement(); // S1 (latch was already true since S0)
        vm.stopPrank();

        _confirmAs(owner, bill, 1);
        _confirmAs(alice, bill, 1);
        _confirmAs(bob,   bill, 1);
        vm.warp(block.timestamp + 1 hours + 1);
        bill.executeSettlement(1);

        _claimAs(owner, bill, 1);
        assertTrue(bill.settlementInitiated(), "claim must not release freeze while S0 pending (L498)");
        _claimAs(alice, bill, 1);
        _claimAs(bob,   bill, 1);
        // S1 fully drained, yet the L498 return-false keeps the round lock engaged:
        assertTrue(bill.settlementInitiated(), "S1 drained but S0 non-terminal -> freeze persists (L498)");

        // payouts honored on the executed round (S0 escrow untouched):
        assertEq(token.balanceOf(alice), 1_000_000e6 + 100e6);
        assertEq(token.balanceOf(bob),   1_000_000e6 + 100e6);
        assertEq(token.balanceOf(address(bill)), 300e6, "S0 escrow stays held");
    }
}
