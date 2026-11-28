// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

import {TandaBillV2, IERC20} from "../contracts/TandaBillV2.sol";
import {FastTandaBillV2} from "../contracts/FastTandaBillV2.sol";
import {TandaBillFactory} from "../contracts/TandaBillFactory.sol";
import {MockToken} from "./TandaBillV2.t.sol";
import {Test} from "forge-std/Test.sol";

/// @title Engine68TwinFuzzConservation - card t_9e2dfe2b (family B1, new axis)
/// @notice Fuzzes the payout-conservation axis the golden ladders never randomized:
///           P1  cross-twin parity - identical expense legs must yield element-wise
///               IDENTICAL settlementPayouts vectors on mainline V2 and Fast twin
///               (mask/rank split arithmetic drift would be invisible to per-twin
///               selector ladders; only shared-input fuzz catches it).
///           P2  fast push conservation - executeSettlement drains the clone to zero
///               and every seat's balance delta equals its vector slot exactly.
///           P3  mainline claim conservation - per-seat claimablePayout pre-claim ==
///               post-claim delta == vector slot, contract fully drained.
///         Sum invariant on both sides: sum(payouts) == sum(legs), always.
/// @dev  Factory lineage only (lane law): new TandaBillFactory(address(impl)) then
///       vm.prank(creator); factory.createBill(token, roster). The constructor-only
///       impl instances here are for VIEW constant reads (SETTLEMENT_WINDOW), never
///       for bill lifecycle. Roster = 3 active seats (owner/alice/bob) so confirm
///       count always equals expectedMask popcount (fullyConfirmedAt arms honestly).
///       Legs bounded 1..100e6, count 1..5, FUNDED=1e12 so funding never overflows
///       minted balances. block.timestamp warps only past each bill's own window.
contract Engine68TwinFuzzConservationTest is Test {
    MockToken token;
    TandaBillV2 implM;            // constructor-only: constant reads, never initialized
    FastTandaBillV2 implF;        // constructor-only: constant reads, never initialized
    TandaBillFactory mFactory;
    TandaBillFactory fFactory;

    address owner = address(0xA11CE);
    address alice = address(0xB0B);
    address bob   = address(0xBEEF);
    address carol = address(0xCAFE);

    uint256 constant FUNDED = 1_000_000e6;

    struct MView {
        uint64 settledAt;
        uint256 fullyConfirmedAt;
    }

    struct FView {
        uint64 settledAt;
        uint64 fullyConfirmedAt;
    }

    function setUp() public {
        token = new MockToken();
        implM = new TandaBillV2();
        implF = new FastTandaBillV2();
        mFactory = new TandaBillFactory(address(implM));
        fFactory = new TandaBillFactory(address(implF));
        token.mint(owner, FUNDED);
        token.mint(alice, FUNDED);
        token.mint(bob, FUNDED);
        token.mint(carol, FUNDED);
    }

    // ─── Helpers ──────────────────────────────────────────────────────────

    function _seats3() internal view returns (address[] memory s) {
        s = new address[](3);
        s[0] = owner; s[1] = alice; s[2] = bob;
    }

    /// @notice Deterministic leg vector from fuzz args: count in 1..5, each leg in 1..100e6.
    function _legs(uint256 a1, uint256 a2, uint256 a3, uint256 a4, uint256 a5, uint8 nRaw)
        internal pure returns (uint256[] memory ls, uint256 total)
    {
        uint256[5] memory raws = [a1, a2, a3, a4, a5];
        uint256 n = bound(nRaw, 1, 5);
        ls = new uint256[](n);
        for (uint256 i = 0; i < n; i++) {
            ls[i] = uint256(bound(raws[i], 1, 100e6));
            total += ls[i];
        }
    }

    function _sum(uint256[] memory v) internal pure returns (uint256 acc) {
        for (uint256 i = 0; i < v.length; i++) acc += v[i];
    }

    /// @notice Mainline 8-tuple getter order: (total, settledAt, initiatedAt, expectedMask,
    ///         confirmedMask, claimedMask, fullyConfirmedAt, refunded).
    function _ms(TandaBillV2 bill, uint256 sid) internal view returns (MView memory v) {
        (
            uint256 totalAmount_, uint64 settledAt_, uint64 initiatedAt_, uint256 expectedMask_,
            uint256 confirmedMask_, uint256 claimedMask_, uint64 fullyConfirmedAt_, bool refunded_
        ) = bill.settlements(sid);
        totalAmount_; initiatedAt_; expectedMask_; confirmedMask_; claimedMask_; refunded_;
        v = MView(settledAt_, fullyConfirmedAt_);
    }

    /// @notice Fast 7-tuple getter order: (total, settledAt, initiatedAt, expectedMask,
    ///         confirmedMask, fullyConfirmedAt, refunded) - no claimedMask (push twin).
    function _fs(FastTandaBillV2 bill, uint256 sid) internal view returns (FView memory v) {
        (
            uint256 totalAmount_, uint64 settledAt_, uint64 initiatedAt_, uint256 expectedMask_,
            uint256 confirmedMask_, uint64 fullyConfirmedAt_, bool refunded_
        ) = bill.settlements(sid);
        totalAmount_; initiatedAt_; expectedMask_; confirmedMask_; refunded_;
        v = FView(settledAt_, fullyConfirmedAt_);
    }

    /// @notice Settle a mainline bill through full confirm (NO execute - caller warps).
    function _settleMainline(uint256[] memory ls) internal returns (TandaBillV2 bill, uint256 total) {
        vm.prank(owner);
        bill = TandaBillV2(mFactory.createBill(IERC20(address(token)), _seats3()));
        vm.startPrank(owner);
        for (uint256 i = 0; i < ls.length; i++) {
            bill.addExpense(ls[i]);
            total += ls[i];
        }
        token.approve(address(bill), total);
        bill.fundEscrow(total);
        bill.initiateSettlement();
        vm.stopPrank();
        _confirmAsM(owner, bill); _confirmAsM(alice, bill); _confirmAsM(bob, bill);
    }

    /// @notice Settle a fast bill through full confirm (NO execute - caller warps).
    function _settleFast(uint256[] memory ls) internal returns (FastTandaBillV2 bill, uint256 total) {
        vm.prank(owner);
        bill = FastTandaBillV2(fFactory.createBill(IERC20(address(token)), _seats3()));
        vm.startPrank(owner);
        for (uint256 i = 0; i < ls.length; i++) {
            bill.addExpense(ls[i]);
            total += ls[i];
        }
        token.approve(address(bill), total);
        bill.fundEscrow(total);
        bill.initiateSettlement();
        vm.stopPrank();
        _confirmAsF(owner, bill); _confirmAsF(alice, bill); _confirmAsF(bob, bill);
    }

    function _confirmAsM(address who, TandaBillV2 bill) internal {
        vm.prank(who);
        bill.confirmSettlement(0);
    }

    function _confirmAsF(address who, FastTandaBillV2 bill) internal {
        vm.prank(who);
        bill.confirmSettlement(0);
    }

    function _executeM(TandaBillV2 bill) internal {
        vm.warp(_ms(bill, 0).fullyConfirmedAt + implM.SETTLEMENT_WINDOW());
        vm.prank(owner);
        bill.executeSettlement(0);
    }

    function _executeF(FastTandaBillV2 bill) internal {
        vm.warp(_fs(bill, 0).fullyConfirmedAt + implF.SETTLEMENT_WINDOW());
        vm.prank(carol); // fast execute is permissionless on both twins
        bill.executeSettlement(0);
    }

    // ─── P1: cross-twin payout parity under shared random legs ───────────

    function testFuzz_e68_twin_payout_parity(
        uint256 a1, uint256 a2, uint256 a3, uint256 a4, uint256 a5, uint8 nRaw
    ) public {
        (uint256[] memory ls, uint256 totalM) = _legs(a1, a2, a3, a4, a5, nRaw);

        (TandaBillV2 billM, uint256 totalM2) = _settleMainline(ls);
        _executeM(billM);
        uint256[] memory pm = billM.settlementPayouts(0);

        // recompute legs for the fast run (same vector, pure helper is idempotent)
        (uint256[] memory ls2, uint256 totalF) = _legs(a1, a2, a3, a4, a5, nRaw);
        (FastTandaBillV2 billF, uint256 totalF2) = _settleFast(ls2);
        _executeF(billF);
        uint256[] memory pf = billF.settlementPayouts(0);

        assertEq(totalM, totalM2, "mainline total drift");
        assertEq(totalF, totalF2, "fast total drift");
        assertEq(pm.length, 3, "mainline vector arity");
        assertEq(pf.length, 3, "fast vector arity");
        for (uint256 i = 0; i < 3; i++) {
            assertEq(pm[i], pf[i], "twin payout drift");
        }
        assertEq(_sum(pm), totalM, "mainline sum conservation");
        assertEq(_sum(pf), totalF, "fast sum conservation");
        assertTrue(_ms(billM, 0).settledAt != 0, "mainline settled");
        assertTrue(_fs(billF, 0).settledAt != 0, "fast settled");
    }

    // ─── P2: fast push conservation (execute drains clone, deltas == slots) ─

    function testFuzz_e68_fast_push_conservation(
        uint256 a1, uint256 a2, uint256 a3, uint256 a4, uint256 a5, uint8 nRaw
    ) public {
        (uint256[] memory ls, uint256 total) = _legs(a1, a2, a3, a4, a5, nRaw);
        (FastTandaBillV2 bill, uint256 total2) = _settleFast(ls);
        assertEq(total, total2, "fast settle total");

        uint256 balO = token.balanceOf(owner);
        uint256 balA = token.balanceOf(alice);
        uint256 balB = token.balanceOf(bob);

        _executeF(bill);
        uint256[] memory pf = bill.settlementPayouts(0);

        assertEq(token.balanceOf(address(bill)), 0, "fast clone drained");
        assertEq(token.balanceOf(owner) - balO, pf[0], "owner push slot");
        assertEq(token.balanceOf(alice) - balA, pf[1], "alice push slot");
        assertEq(token.balanceOf(bob) - balB, pf[2], "bob push slot");
        assertEq(_sum(pf), total, "fast push conservation");
    }

    // ─── P3: mainline claim conservation (claimable == delta == slot) ─────

    function testFuzz_e68_mainline_claim_conservation(
        uint256 a1, uint256 a2, uint256 a3, uint256 a4, uint256 a5, uint8 nRaw
    ) public {
        (uint256[] memory ls, uint256 total) = _legs(a1, a2, a3, a4, a5, nRaw);
        (TandaBillV2 bill, uint256 total2) = _settleMainline(ls);
        assertEq(total, total2, "mainline settle total");

        _executeM(bill);
        uint256[] memory pm = bill.settlementPayouts(0);

        uint256 claimableO = bill.claimablePayout(0, owner);
        uint256 claimableA = bill.claimablePayout(0, alice);
        uint256 claimableB = bill.claimablePayout(0, bob);
        assertEq(claimableO, pm[0], "owner claimable slot");
        assertEq(claimableA, pm[1], "alice claimable slot");
        assertEq(claimableB, pm[2], "bob claimable slot");

        uint256 balO = token.balanceOf(owner);
        uint256 balA = token.balanceOf(alice);
        uint256 balB = token.balanceOf(bob);

        vm.prank(owner); bill.claimSettlement(0);
        vm.prank(alice); bill.claimSettlement(0);
        vm.prank(bob);   bill.claimSettlement(0);

        assertEq(token.balanceOf(owner) - balO, pm[0], "owner claim delta");
        assertEq(token.balanceOf(alice) - balA, pm[1], "alice claim delta");
        assertEq(token.balanceOf(bob) - balB, pm[2], "bob claim delta");
        assertEq(token.balanceOf(address(bill)), 0, "mainline drained");
        assertEq(_sum(pm), total, "mainline claim conservation");

        // double-claim must revert typed (ledger honesty, not just arithmetic)
        uint256 balAfter = token.balanceOf(owner);
        vm.prank(owner);
        vm.expectRevert(TandaBillV2.PayoutAlreadyClaimed.selector);
        bill.claimSettlement(0);
        assertEq(token.balanceOf(owner), balAfter, "reclaim left balance untouched");
    }
}
