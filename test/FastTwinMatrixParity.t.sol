// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

import {IERC20} from "../contracts/TandaBillV2.sol";
import {FastTandaBillV2, IERC20 as IFastERC20} from "../contracts/FastTandaBillV2.sol";
import {TandaBillFactory} from "../contracts/TandaBillFactory.sol";
import {MockToken} from "./TandaBillV2.t.sol";
import {Test} from "forge-std/Test.sol";

/// @title FastTwinMatrixParity — card t_df262414
/// @notice Mirrors the canonical TandaBillV2 gate matrices onto FastTandaBillV2 to close the
///         twin-drift coverage gap measured at main ac0c4f339 (Fast line coverage 90/148):
///           - L174      _caller() forwarder branch (factory.callBill tail decode)
///           - L183-239  addSeat / removeSeat / rotateSeatWallet incl. RotationWindowLocked legs
///           - L381-404  executeSettlement payout loop + refundSettlement MAX_HOLD legs
///           - L421-436  totalExpenses / activeSeatCount / isSeatConfirmed / settlementPayouts
///         Every bill is created via factory.createBill lineage (lane law: NEVER raw
///         initialize from the test contract). Twin divergences honored, not papered over:
///           1. Fast settlements = 7-tuple (no claimedMask) - auto-push execute, no claims leg.
///           2. SETTLEMENT_WINDOW = 60s, MAX_HOLD = 120s (testnet pace vs canonical 1h/72h).
///           3. executeSettlement PUSHES payouts inline - balance assertions replace claim drains.
///         Contracts untouched; this file is pure test-side surface.
contract FastTwinMatrixParityTest is Test {
    MockToken token;
    FastTandaBillV2 impl;          // constructor-only, never initialized: constant reads
    TandaBillFactory factory;

    address owner   = address(0xA11CE);
    address alice   = address(0xB0B);
    address bob     = address(0xBEEF);
    address carol   = address(0xCAFE);
    address dan     = address(0xDADA);
    address eve     = address(0xE1E1);

    uint256 constant FUNDED = 1_000_000e6;

    function setUp() public {
        token = new MockToken();
        impl = new FastTandaBillV2();
        factory = new TandaBillFactory(address(impl));
        token.mint(owner, FUNDED);
        token.mint(alice, FUNDED);
        token.mint(bob, FUNDED);
        token.mint(carol, FUNDED);
        token.mint(dan, FUNDED);
        token.mint(eve, FUNDED);
    }

    // ─── Helpers (factory lineage everywhere) ────────────────────────────

    function _seats3() internal view returns (address[] memory s) {
        s = new address[](3); s[0] = owner; s[1] = alice; s[2] = bob;
    }

    /// @notice createBill pranked as `creator` - the ONLY way a bill enters this suite.
    function _createAs(address creator, address[] memory seats) internal returns (FastTandaBillV2 bill) {
        vm.prank(creator);
        bill = FastTandaBillV2(factory.createBill(IERC20(address(token)), seats));
    }

    /// @notice Standard 3-seat bill with `amount` expense + escrow + initiateSettlement.
    function _initiatedBill(uint256 amount) internal returns (FastTandaBillV2 bill) {
        bill = _createAs(owner, _seats3());
        vm.startPrank(owner);
        bill.addExpense(amount);
        token.approve(address(bill), amount);
        bill.fundEscrow(amount);
        bill.initiateSettlement();
        vm.stopPrank();
    }

    function _confirmAs(address who, FastTandaBillV2 bill, uint256 sid) internal {
        vm.prank(who);
        bill.confirmSettlement(sid);
    }

    function _fullConfirm3(FastTandaBillV2 bill) internal {
        _confirmAs(owner, bill, 0);
        _confirmAs(alice, bill, 0);
        _confirmAs(bob, bill, 0);
    }

    function _sum(uint256[] memory v) internal pure returns (uint256 acc) {
        for (uint256 i = 0; i < v.length; i++) acc += v[i];
    }

    /// @notice Fast settlements getter = 7-tuple: (totalAmount, settledAt, initiatedAt,
    ///         expectedMask, confirmedMask, fullyConfirmedAt, refunded) - payouts omitted
    ///         (dynamic array; see settlementPayouts accessor) and NO claimedMask (push twin).
    struct SView {
        uint64 settledAt;
        uint64 initiatedAt;
        uint256 expectedMask;
        uint256 confirmedMask;
        uint64 fullyConfirmedAt;
        bool refunded;
    }

    function _s(FastTandaBillV2 bill, uint256 sid) internal view returns (SView memory v) {
        (uint256 totalAmount_, uint64 settledAt_, uint64 initiatedAt_, uint256 expectedMask_,
         uint256 confirmedMask_, uint64 fullyConfirmedAt_, bool refunded_) = bill.settlements(sid);
        totalAmount_; // payouts read via settlementPayouts()
        v = SView(settledAt_, initiatedAt_, expectedMask_, confirmedMask_, fullyConfirmedAt_, refunded_);
    }

    // ─── Forwarder leg: _caller() L172-178 (tail decode at L174) ─────────

    function test_f_forwarder_callBill_fullLifecycle() public {
        address[] memory roster = new address[](2);
        roster[0] = owner;
        roster[1] = alice;
        vm.prank(owner);
        address billAddr = factory.createBill(IERC20(address(token)), roster);
        FastTandaBillV2 hub = FastTandaBillV2(billAddr);
        assertEq(address(hub.factory()), address(factory));

        bytes memory cd;
        // owner actions via forwarder: msg.sender == factory -> assembly tail decode
        vm.startPrank(owner);
        cd = abi.encodeCall(hub.addExpense, (200e6));
        factory.callBill(billAddr, cd);
        token.approve(billAddr, 200e6); // approve stays direct: spender is the CLONE
        cd = abi.encodeCall(hub.fundEscrow, (200e6));
        factory.callBill(billAddr, cd);
        cd = abi.encodeCall(hub.initiateSettlement, ());
        factory.callBill(billAddr, cd);
        vm.stopPrank();

        // confirmations via forwarder from each seat wallet (identity preserved through L174)
        vm.prank(owner);
        cd = abi.encodeCall(hub.confirmSettlement, (0));
        factory.callBill(billAddr, cd);
        vm.prank(alice);
        cd = abi.encodeCall(hub.confirmSettlement, (0));
        factory.callBill(billAddr, cd);
        assertTrue(_s(hub, 0).fullyConfirmedAt != 0);

        vm.warp(block.timestamp + 61);
        vm.prank(carol); // permissionless execute, still permissionless via forwarder
        cd = abi.encodeCall(hub.executeSettlement, (0));
        factory.callBill(billAddr, cd);

        // Fast twin PUSHES at execute - no claims leg (documented divergence)
        assertEq(token.balanceOf(alice), FUNDED + 100e6);
        assertEq(token.balanceOf(owner), FUNDED - 200e6 + 100e6);
        assertEq(token.balanceOf(billAddr), 0);
    }

    function test_f_forwarder_callBill_identityEnforced() public {
        FastTandaBillV2 bill = _createAs(owner, _seats3());
        vm.prank(carol);
        vm.expectRevert(FastTandaBillV2.NotSeatOrOwner.selector); // bubbled, selector intact
        factory.callBill(address(bill), abi.encodeCall(bill.rotateSeatWallet, (1, eve)));
    }

    function test_f_forwarder_initialize_guard() public {
        FastTandaBillV2 bill = _createAs(owner, _seats3());
        vm.prank(carol);
        vm.expectRevert(FastTandaBillV2.AlreadyInitialized.selector);
        bill.initialize(IFastERC20(address(token)), carol, _seats3());
        assertEq(address(bill.factory()), address(factory)); // trust anchor not re-pointable
    }

    // ─── addSeat / removeSeat: L183-205 ──────────────────────────────────

    function test_f_addSeat_postInitiate_receivesNothing() public {
        // mask-snapshot regression, mirrored from the canonical E2E-caught bug
        uint256 amount = 200e6;
        FastTandaBillV2 bill = _initiatedBill(amount);
        vm.prank(owner);
        bill.addSeat(dan); // after initiateSettlement: outside expectedMask
        // snapshot check BEFORE settle - post-execute confirm would revert AlreadySettled first
        vm.expectRevert(FastTandaBillV2.NotAnExpectedSeat.selector);
        _confirmAs(dan, bill, 0); // seatIdOf set, but bit not in expectedMask (L347)
        _fullConfirm3(bill);
        vm.warp(_s(bill, 0).fullyConfirmedAt + bill.SETTLEMENT_WINDOW());
        bill.executeSettlement(0);
        uint256[] memory payouts = bill.settlementPayouts(0);
        assertEq(payouts.length, 3); // snapshot: owner+alice+bob
        assertEq(_sum(payouts), amount);
        assertEq(token.balanceOf(dan), FUNDED); // received nothing
    }

    function test_f_addSeat_duplicate_reverts() public {
        FastTandaBillV2 bill = _createAs(owner, _seats3());
        vm.prank(owner);
        vm.expectRevert(abi.encodeWithSelector(FastTandaBillV2.DuplicateSeat.selector, alice));
        bill.addSeat(alice);
    }

    function test_f_removeSeat_beforeInitiate_excludedFromPayout() public {
        uint256 amount = 200e6;
        FastTandaBillV2 bill = _createAs(owner, _seats3());
        vm.prank(owner);
        bill.removeSeat(2); // bob (owner=0, alice=1, bob=2)
        vm.startPrank(owner);
        bill.addExpense(amount);
        token.approve(address(bill), amount);
        bill.fundEscrow(amount);
        bill.initiateSettlement();
        vm.stopPrank();
        _confirmAs(owner, bill, 0);
        vm.expectRevert(FastTandaBillV2.NotAnExpectedSeat.selector); // seatIdOf cleared -> L344 raw==0
        _confirmAs(bob, bill, 0); // (checked pre-full-confirm: L341 would shadow otherwise)
        _confirmAs(alice, bill, 0); // mask = seats {0,1} -> fully confirmed
        assertTrue(_s(bill, 0).fullyConfirmedAt != 0);
        vm.warp(_s(bill, 0).fullyConfirmedAt + bill.SETTLEMENT_WINDOW());
        bill.executeSettlement(0);
        uint256[] memory payouts = bill.settlementPayouts(0);
        assertEq(payouts.length, 2);
        assertEq(_sum(payouts), amount);
        assertEq(token.balanceOf(bob), FUNDED); // removed seat untouched
    }

    function test_f_removeSeat_revertsAfterInitiation() public {
        FastTandaBillV2 bill = _initiatedBill(100e6);
        vm.expectRevert(FastTandaBillV2.SettlementInitiatedAlready.selector);
        vm.prank(owner);
        bill.removeSeat(1);
    }

    function test_f_removeSeat_inactive_revertsSeatInactive() public {
        FastTandaBillV2 bill = _createAs(owner, _seats3());
        vm.startPrank(owner);
        bill.removeSeat(2); // bob active -> inactive
        vm.expectRevert(abi.encodeWithSelector(FastTandaBillV2.SeatInactive.selector, 2));
        bill.removeSeat(2); // double-remove hits L201
        vm.stopPrank();
    }

    // ─── rotateSeatWallet incl. split-lock legs: L213-239 ────────────────

    function test_f_rotate_preInitiate_seatSelf() public {
        FastTandaBillV2 bill = _createAs(owner, _seats3());
        vm.prank(alice);
        bill.rotateSeatWallet(1, eve);
        (address w0, , ) = bill.seats(0);
        (address w1, , ) = bill.seats(1);
        assertEq(w1, eve);
        assertEq(w0, owner);
        assertEq(bill.seatIdOf(eve), 2);   // seatId+1
        assertEq(bill.seatIdOf(alice), 0); // old mapping cleared
    }

    function test_f_rotate_byOwner_recovery() public {
        FastTandaBillV2 bill = _createAs(owner, _seats3());
        vm.prank(owner);
        bill.rotateSeatWallet(2, dan);
        (address w2, , ) = bill.seats(2);
        assertEq(w2, dan);
    }

    function test_f_rotate_stranger_reverts() public {
        FastTandaBillV2 bill = _createAs(owner, _seats3());
        vm.prank(carol);
        vm.expectRevert(FastTandaBillV2.NotSeatOrOwner.selector);
        bill.rotateSeatWallet(1, eve);
    }

    function test_f_rotate_duplicateTarget_reverts() public {
        FastTandaBillV2 bill = _createAs(owner, _seats3());
        vm.prank(alice);
        vm.expectRevert(abi.encodeWithSelector(FastTandaBillV2.DuplicateSeat.selector, bob));
        bill.rotateSeatWallet(1, bob);
    }

    function test_f_rotate_zeroWallet_reverts() public {
        FastTandaBillV2 bill = _createAs(owner, _seats3());
        vm.prank(alice);
        vm.expectRevert(FastTandaBillV2.ZeroWallet.selector);
        bill.rotateSeatWallet(1, address(0));
    }

    function test_f_rotate_inactive_revertsSeatInactive() public {
        FastTandaBillV2 bill = _createAs(owner, _seats3());
        vm.prank(owner);
        bill.removeSeat(1); // alice removed
        // SeatInactive gate (L215) fires before the auth gate - no prank needed
        vm.expectRevert(abi.encodeWithSelector(FastTandaBillV2.SeatInactive.selector, 1));
        bill.rotateSeatWallet(1, eve);
    }

    function test_f_rotate_unconfirmedSelf_paysNewWallet() public {
        // Ratified semantics: unconfirmed self-rotation is the rescue path (FCA==0 = no lock)
        FastTandaBillV2 bill = _initiatedBill(300e6);
        _confirmAs(owner, bill, 0);
        _confirmAs(bob, bill, 0); // alice NOT confirmed -> fullyConfirmedAt stays 0

        vm.prank(alice);
        bill.rotateSeatWallet(1, eve); // unconfirmed self, lock never armed

        _confirmAs(eve, bill, 0); // eve confirms seat 1 via the new wallet (seat-indexed bits)
        assertTrue(_s(bill, 0).fullyConfirmedAt != 0);

        vm.warp(block.timestamp + 61);
        bill.executeSettlement(0);
        assertEq(token.balanceOf(eve), FUNDED + 100e6); // push pays the rotated wallet
        assertEq(token.balanceOf(alice), FUNDED);        // old wallet got nothing
        assertEq(token.balanceOf(bob), FUNDED + 100e6);
    }

    function test_f_rotate_confirmedSelf_lockedInWindow() public {
        FastTandaBillV2 bill = _initiatedBill(300e6);
        _fullConfirm3(bill); // alice confirmed as herself -> lock armed at full confirm
        vm.prank(alice);
        vm.expectRevert(FastTandaBillV2.RotationWindowLocked.selector); // L230-231
        bill.rotateSeatWallet(1, eve);
        // after the window (executable), self-rescue of own funds opens again
        vm.warp(block.timestamp + 61);
        vm.prank(alice);
        bill.rotateSeatWallet(1, eve);
        bill.executeSettlement(0);
        assertEq(token.balanceOf(eve), FUNDED + 100e6);
    }

    function test_f_rotate_ownerLockedAtFullConfirm_inWindow() public {
        FastTandaBillV2 bill = _initiatedBill(300e6);
        _fullConfirm3(bill);
        vm.prank(owner);
        vm.expectRevert(FastTandaBillV2.RotationWindowLocked.selector); // L229: owner-driven dies at FCA
        bill.rotateSeatWallet(1, dan);
    }

    function test_f_rotate_ownerLockedAtExecutability_selfStillOk() public {
        // Audit-fix #3 mirror: at executability owner-driven stays locked, seat-self open
        FastTandaBillV2 bill = _initiatedBill(300e6);
        _fullConfirm3(bill);
        vm.warp(block.timestamp + 61);

        vm.prank(owner);
        vm.expectRevert(FastTandaBillV2.RotationWindowLocked.selector);
        bill.rotateSeatWallet(1, dan); // owner redirect attempt at the finish line

        vm.prank(alice); // seat-self unaffected
        bill.rotateSeatWallet(1, eve);

        bill.executeSettlement(0);
        assertEq(token.balanceOf(eve), FUNDED + 100e6);
        assertEq(token.balanceOf(dan), FUNDED);
    }

    function test_f_rotate_afterExecute_reverts() public {
        FastTandaBillV2 bill = _initiatedBill(300e6);
        _fullConfirm3(bill);
        vm.warp(block.timestamp + 61);
        bill.executeSettlement(0);
        vm.prank(alice);
        vm.expectRevert(FastTandaBillV2.SeatRotationClosed.selector); // L221: closed post-settle
        bill.rotateSeatWallet(1, eve);
    }

    function test_f_rotate_afterRefund_reverts() public {
        FastTandaBillV2 bill = _initiatedBill(300e6);
        _confirmAs(owner, bill, 0); // never fully confirms
        vm.warp(block.timestamp + 120); // MAX_HOLD = 120s
        vm.prank(owner);
        bill.refundSettlement(0);
        vm.prank(alice);
        vm.expectRevert(FastTandaBillV2.SeatRotationClosed.selector); // refund closes every path
        bill.rotateSeatWallet(1, eve);
    }

    // ─── executeSettlement push loop + gates: L366-388 ───────────────────

    function test_f_lifecycle_windowBoundary_pushLoop() public {
        uint256 amount = 300e6;
        FastTandaBillV2 bill = _initiatedBill(amount);
        assertEq(bill.escrowBalance(), 0); // escrow de-rated at initiate

        _confirmAs(owner, bill, 0);
        assertEq(_s(bill, 0).fullyConfirmedAt, 0);
        vm.expectRevert(FastTandaBillV2.NotFullyConfirmed.selector); // L370 leg
        bill.executeSettlement(0);

        _confirmAs(alice, bill, 0);
        _confirmAs(bob, bill, 0);
        assertTrue(_s(bill, 0).fullyConfirmedAt != 0);

        vm.expectRevert(FastTandaBillV2.WindowNotElapsed.selector); // L372 leg
        bill.executeSettlement(0);

        // At the boundary (>= fullyConfirmedAt + SETTLEMENT_WINDOW): succeeds, PUSHES
        uint64 fc = _s(bill, 0).fullyConfirmedAt;
        vm.warp(uint256(fc) + bill.SETTLEMENT_WINDOW());
        bill.executeSettlement(0);

        assertEq(token.balanceOf(owner), FUNDED - amount + amount / 3); // 300e6 splits exactly
        assertEq(token.balanceOf(alice), FUNDED + amount / 3);
        assertEq(token.balanceOf(bob), FUNDED + amount / 3);
        assertEq(token.balanceOf(address(bill)), 0); // fully drained by the push loop
        assertEq(_s(bill, 0).settledAt, uint64(block.timestamp));
    }

    function test_f_unevenSplit_remainder() public {
        uint256 amount = 100e6; // 3 seats -> 33,333,334 / 33,333,333 / 33,333,333
        FastTandaBillV2 bill = _initiatedBill(amount);
        _fullConfirm3(bill);
        vm.warp(_s(bill, 0).fullyConfirmedAt + bill.SETTLEMENT_WINDOW());
        bill.executeSettlement(0);
        uint256[] memory payouts = bill.settlementPayouts(0);
        assertEq(payouts.length, 3);
        assertEq(payouts[0], 33_333_334);
        assertEq(payouts[1], 33_333_333);
        assertEq(payouts[2], 33_333_333);
        assertEq(_sum(payouts), amount);
        assertEq(token.balanceOf(owner), FUNDED - amount + 33_333_334);
    }

    // ─── refundSettlement MAX_HOLD legs: L394-404 ────────────────────────

    function test_f_maxHold_refund_revertsBeforeMaxHold() public {
        FastTandaBillV2 bill = _initiatedBill(100e6);
        _confirmAs(owner, bill, 0); // not fully confirmed
        vm.warp(block.timestamp + 119); // MAX_HOLD = 120s (testnet pace)
        vm.expectRevert(FastTandaBillV2.RefundNotAvailable.selector);
        vm.prank(owner);
        bill.refundSettlement(0);
    }

    function test_f_maxHold_refund_succeedsAfterMaxHold() public {
        uint256 amount = 100e6;
        FastTandaBillV2 bill = _initiatedBill(amount);
        _confirmAs(owner, bill, 0); // never fully confirms
        vm.warp(block.timestamp + 120);
        assertEq(token.balanceOf(address(bill)), amount);
        uint256 ownerBefore = token.balanceOf(owner);
        vm.prank(owner);
        bill.refundSettlement(0);
        assertEq(token.balanceOf(owner), ownerBefore + amount); // Gap-3: refund returns to funder side
        assertEq(token.balanceOf(address(bill)), 0);
        assertTrue(_s(bill, 0).refunded);
        vm.expectRevert(FastTandaBillV2.AlreadySettled.selector); // refunded never executes
        bill.executeSettlement(0);
    }

    function test_f_maxHold_refund_revertsIfFullyConfirmed() public {
        FastTandaBillV2 bill = _initiatedBill(100e6);
        _fullConfirm3(bill);
        vm.warp(block.timestamp + 120);
        vm.expectRevert(FastTandaBillV2.RefundNotAvailable.selector); // fullyConfirmedAt != 0 kills refund
        vm.prank(owner);
        bill.refundSettlement(0);
    }

    function test_f_maxHold_refund_revertsIfNotOwner() public {
        FastTandaBillV2 bill = _initiatedBill(100e6);
        vm.warp(block.timestamp + 120);
        vm.expectRevert(FastTandaBillV2.NotOwner.selector); // L395 _caller gate
        vm.prank(alice);
        bill.refundSettlement(0);
    }

    // ─── Views: L421-436 ─────────────────────────────────────────────────

    function test_f_views_totalExpenses() public {
        FastTandaBillV2 bill = _createAs(owner, _seats3());
        assertEq(bill.totalExpenses(), 0); // empty ledger (L422 loop skips)
        vm.startPrank(owner);
        bill.addExpense(30e6);
        bill.addExpense(45e6);
        assertEq(bill.totalExpenses(), 75e6);
        // totalExpenses includes settled expenses (audit view) - persists post-initiate
        token.approve(address(bill), 75e6);
        bill.fundEscrow(75e6);
        bill.initiateSettlement();
        vm.stopPrank();
        assertEq(bill.totalExpenses(), 75e6);
    }

    function test_f_views_activeSeatCount() public {
        FastTandaBillV2 bill = _createAs(owner, _seats3());
        assertEq(bill.activeSeatCount(), 3);
        vm.prank(owner);
        bill.removeSeat(2);
        assertEq(bill.activeSeatCount(), 2); // L425 delegates to _activeSeatCount (L415-419)
    }

    function test_f_views_isSeatConfirmed() public {
        FastTandaBillV2 bill = _initiatedBill(100e6);
        assertFalse(bill.isSeatConfirmed(0, alice)); // L429 non-zero path pre-confirm
        _confirmAs(alice, bill, 0);
        assertTrue(bill.isSeatConfirmed(0, alice));  // L430 bit set
        assertFalse(bill.isSeatConfirmed(0, eve));   // raw == 0 short-circuit
    }

    function test_f_views_settlementPayouts() public {
        // Solidity struct getters omit dynamic arrays; settlementPayouts is the safe read
        FastTandaBillV2 bill = _initiatedBill(100e6);
        uint256[] memory p = bill.settlementPayouts(0); // L436
        assertEq(p.length, 3);
        assertEq(_sum(p), 100e6);
    }

    function test_f_constants_pace_divergence() public {
        // Pin the INTENTIONAL Fast/canonical divergence: 60s window, 120s hold, same cap
        assertEq(impl.MAX_SEATS(), 256);
        assertEq(impl.SETTLEMENT_WINDOW(), 60 seconds);
        assertEq(impl.MAX_HOLD(), 120 seconds);
    }
}
