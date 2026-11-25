// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

import {IERC20 as IV2ERC20} from "../contracts/TandaBillV2.sol";
import {FastTandaBillV2, IERC20 as IFastERC20} from "../contracts/FastTandaBillV2.sol";
import {TandaBill, IERC20 as IV1ERC20} from "../contracts/TandaBill.sol";
import {TandaBillFactory} from "../contracts/TandaBillFactory.sol";
import {MockToken} from "./TandaBillV2.t.sol";
import {MockToken as V1Mock} from "./TandaBill.t.sol";
import {Test} from "forge-std/Test.sol";

/// @title Engine 2026-11-25 coverage goldens (t_1086a045)
/// @dev Closes the two remaining product-coverage arcs at head 7d3dadceb:
///   [1] FastTandaBillV2.sol:349 operand-2 `!seats[seatId].active` (stmt 201/201,
///       branch 67/67). Defensively unreachable by natural routes: removeSeat is
///       the sole `active = false` write (L204) and freezes once
///       settlementInitiated (L201; the flag has exactly one write - true - at
///       L327, never reset), while expectedMask snapshots only active seats at
///       initiate (L304-310). vm.store injection proves the guard fires when the
///       invariant is violated, mirroring the mainline sibling golden
///       test_def_confirm_inactiveExpected_operand2_L394.
///   [2] TandaBill.sol:204 executeSettlement non-owner revert arc (branch 34/34).
///       Owner checks exist for addExpense/fundEscrow/initiate on V1, but no
///       stranger path was ever executed against executeSettlement.
///       Layout pinned inline (probe-before-store law): seats.length @ slot 2,
///       array data base keccak(uint256(2)), one slot per Seat
///       (wallet 20B + joinedAt uint64 + active bool pack into 29B), active bit
///       at word offset 224.
contract Engine1125FastMaskCornerTest is Test {
    address owner = address(0xA11CE);
    address alice = address(0xB0B);
    address bob   = address(0xBEEF);
    address stranger = address(0xDEAD);
    uint256 constant FUNDED = 1_000_000e6;

    MockToken token;
    TandaBillFactory factory;

    function setUp() public {
        token = new MockToken();
        FastTandaBillV2 impl = new FastTandaBillV2(); // constructor-only, never initialized
        factory = new TandaBillFactory(address(impl));
        token.mint(owner, FUNDED);
        token.mint(alice, FUNDED);
        token.mint(bob, FUNDED);
    }

    function _initiatedFastBill() internal returns (FastTandaBillV2 bill) {
        address[] memory s = new address[](3);
        s[0] = owner; s[1] = alice; s[2] = bob;
        vm.prank(owner);
        bill = FastTandaBillV2(payable(factory.createBill(IV2ERC20(address(token)), s)));
        vm.startPrank(owner);
        bill.addExpense(300e6);
        token.approve(address(bill), 300e6);
        bill.fundEscrow(300e6);
        bill.initiateSettlement();
        vm.stopPrank();
    }

    /// [1] Fast twin L349: bit stays in expectedMask, active flag cleared via
    /// storage injection - confirm must revert NotAnExpectedSeat through the
    /// short-circuit operand no natural route can reach.
    function test_fast_confirm_inactiveExpected_operand2_L349_reverts() public {
        FastTandaBillV2 bill = _initiatedFastBill();
        vm.prank(owner); bill.confirmSettlement(0);
        vm.prank(alice); bill.confirmSettlement(0);

        // ---- inline layout probe (assert BEFORE any store) ----
        assertEq(vm.load(address(bill), bytes32(uint256(2))), bytes32(uint256(3)), "seats.length @ slot 2");
        bytes32 base = keccak256(abi.encode(uint256(2)));
        bytes32 slot = bytes32(uint256(base) + 2);
        bytes32 w = vm.load(address(bill), slot);
        assertEq(uint256(uint160(address(uint160(uint256(w))))), uint256(uint160(bob)), "bob wallet @ word low 160 bits");
        assertEq(uint256(w >> 224) & 1, 1, "active bit set pre-injection");

        // ---- injection: clear active for seat 2 only ----
        w &= ~bytes32(uint256(1) << 224);
        vm.store(address(bill), slot, w);
        assertEq((uint256(vm.load(address(bill), slot)) >> 224) & 1, 0, "injection landed");

        // bob is still seatIdOf-mapped and his bit is still in expectedMask,
        // so the revert below can only come from operand 2 (!active):
        // operand 1 hits would need mask-miss, and lines 342-346 all pass.
        vm.expectRevert(FastTandaBillV2.NotAnExpectedSeat.selector);
        vm.prank(bob);
        bill.confirmSettlement(0);
    }

    /// [2] V1 mainline L204: stranger must never drive payout release.
    /// Setup carries the settlement to fully window-ready so a broken guard
    /// (missing owner check) would actually move funds on the control leg.
    function test_v1_executeSettlement_notOwner_L204_reverts() public {
        V1Mock t1 = new V1Mock();
        t1.mint(owner, FUNDED);
        vm.prank(owner);
        TandaBill v1 = new TandaBill(IV1ERC20(address(t1)));
        vm.startPrank(owner);
        v1.addSeat(alice);
        v1.addExpense(100e6);
        t1.approve(address(v1), 100e6);
        v1.fundEscrow(100e6);
        v1.initiateSettlement();
        vm.stopPrank();
        vm.warp(block.timestamp + 1 hours); // window is inclusive (L210-212)

        uint256 beforeAlice = t1.balanceOf(alice);
        vm.prank(stranger);
        vm.expectRevert(TandaBill.NotOwner.selector);
        v1.executeSettlement(0);
        assertEq(t1.balanceOf(alice), beforeAlice, "stranger attempt moved no funds");

        // Control: settlement was genuinely executable -> guard, not state,
        // produced the revert above.
        vm.prank(owner);
        v1.executeSettlement(0);
        assertGt(t1.balanceOf(alice), beforeAlice, "owner leg proves pending state was live");
    }
}
