// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

import {TandaBillV2, IERC20} from "../contracts/TandaBillV2.sol";
import {SafeERC20Minimal} from "../contracts/SafeERC20Minimal.sol";
import {TandaBillFactory} from "../contracts/TandaBillFactory.sol";
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

/// @notice P0.1a test token: per-address inbound blacklist mimicking a USDC-frozen wallet or
///         reverting receiver hook — transfer() INTO a blocked address reverts the whole call.
contract BlockableToken is MockToken {
    mapping(address => bool) public blocked;

    function blockAddress(address a) external {
        blocked[a] = true;
    }

    function transfer(address to, uint256 amount) external override returns (bool) {
        require(!blocked[to], "receiver blocked");
        require(balanceOf[msg.sender] >= amount, "insufficient");
        balanceOf[msg.sender] -= amount;
        balanceOf[to] += amount;
        return true;
    }
}

/// @title TandaBillV2 forge suite (W6) — FIRST independent forge recompilation of the
///        committed w6-contract-v2 bytes (branch tip 6e2e187; PC lane has no Foundry).
///        Covers: factory + EIP-1167 clone lifecycle, bitmap confirmation gating (Gap-2),
///        window gating, MAX_HOLD refund escape (invariant-5), the post-initiate-seat
///        regression the live E2E caught, and the gap2 witness REPOINTED AT V2 (green
///        via NotFullyConfirmed; the legacy v1-suite witness stays red against the W1
///        stub by design).
contract TandaBillV2Test is Test {
    MockToken token;
    TandaBillV2 impl;
    TandaBillFactory factory;

    address owner   = address(0xA11CE);
    address backend = address(0x8EA7E);
    address alice   = address(0xB0B);
    address bob     = address(0xBEEF);
    address carol   = address(0xCAFE);
    address dan     = address(0xDADA);
    address eve     = address(0xE1E1);

    function setUp() public {
        token = new MockToken();
        impl  = new TandaBillV2();
        factory = new TandaBillFactory(address(impl));

        token.mint(owner, 1_000_000e6);
        token.mint(alice, 1_000_000e6);
        token.mint(bob,   1_000_000e6);
        token.mint(carol, 1_000_000e6);
        token.mint(dan,   1_000_000e6);
        token.mint(eve,   1_000_000e6);
    }

    // ─── Helpers ─────────────────────────────────────────────────────────

    function _seats3() internal view returns (address[] memory s) {
        s = new address[](3);
        s[0] = owner;
        s[1] = alice;
        s[2] = bob;
    }

    function _seats4() internal view returns (address[] memory s) {
        s = new address[](4);
        s[0] = owner;
        s[1] = alice;
        s[2] = bob;
        s[3] = carol;
    }

    /// @notice createBill(seats) pranked as `creator`.
    function _createAs(address creator, address[] memory seats) internal returns (TandaBillV2 bill) {
        vm.prank(creator);
        bill = TandaBillV2(payable(factory.createBill(IERC20(address(token)), seats)));
    }

    /// @notice Standard 3-seat bill with `amount` expense + escrow + initiateSettlement.
    function _initiatedBill(uint256 amount) internal returns (TandaBillV2 bill) {
        bill = _createAs(owner, _seats3());
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

    function _fullConfirm3(TandaBillV2 bill) internal {
        _confirmAs(owner, bill, 0);
        _confirmAs(alice, bill, 0);
        _confirmAs(bob, bill, 0);
    }

    function _claimAs(address who, TandaBillV2 bill, uint256 sid) internal {
        vm.prank(who);
        bill.claimSettlement(sid);
    }

    /// @notice P0.1a: drain the standard 3-seat roster's claims (owner/alice/bob).
    function _drain3(TandaBillV2 bill) internal {
        _claimAs(owner, bill, 0);
        _claimAs(alice, bill, 0);
        _claimAs(bob, bill, 0);
    }

    function _sum(uint256[] memory v) internal pure returns (uint256 acc) {
        for (uint256 i = 0; i < v.length; i++) acc += v[i];
    }

    /// @notice Public struct getters omit the dynamic payouts array and their tuple members
    ///         can't be member-accessed — destructure into a struct once.
    struct SView {
        uint64 settledAt;
        uint64 initiatedAt;
        uint256 expectedMask;
        uint256 confirmedMask;
        uint256 claimedMask;
        uint64 fullyConfirmedAt;
        bool refunded;
    }

    function _s(TandaBillV2 bill, uint256 sid) internal view returns (SView memory v) {
        (uint256 totalAmount_, uint64 settledAt_, uint64 initiatedAt_, uint256 expectedMask_, uint256 confirmedMask_, uint256 claimedMask_, uint64 fullyConfirmedAt_, bool refunded_) = bill.settlements(sid);
        v = SView(settledAt_, initiatedAt_, expectedMask_, confirmedMask_, claimedMask_, fullyConfirmedAt_, refunded_);
    }

    // ─── Factory / clone shape ───────────────────────────────────────────

    function test_factory_createBill_ownerIsCreator_tokenBaked() public {
        TandaBillV2 bill = _createAs(owner, _seats3());
        assertEq(bill.owner(), owner);
        assertEq(address(bill.token()), address(token));
        assertTrue(factory.isBill(address(bill)));
        assertFalse(factory.isBill(address(impl)));
    }

    function test_factory_createBill_backendNeverOwner() public {
        // Structural negative: owner is whoever called createBill. The backend address
        // cannot become owner because initialize only sets the caller of createBill.
        TandaBillV2 bill = _createAs(owner, _seats3());
        assertEq(bill.owner(), owner);
        assertTrue(bill.owner() != backend);
        // initialize is clone-guarded: a second call on the same clone reverts.
        vm.expectRevert(TandaBillV2.AlreadyInitialized.selector);
        bill.initialize(IERC20(address(token)), backend, new address[](0));
    }

    function test_factory_createBill_seatsEnrolled() public {
        TandaBillV2 bill = _createAs(owner, _seats3());
        assertEq(bill.activeSeatCount(), 3);
        assertEq(bill.seatIdOf(owner), 1);
        assertEq(bill.seatIdOf(alice), 2);
        assertEq(bill.seatIdOf(bob), 3);
        (address w0,, bool a0) = bill.seats(0);
        assertEq(w0, owner);
        assertTrue(a0);
    }

    function test_factory_createBill_revertsNoSeats() public {
        address[] memory none = new address[](0);
        vm.expectRevert(TandaBillFactory.NoSeats.selector);
        factory.createBill(IERC20(address(token)), none);
    }

    function test_factory_createBill_revertsTooManySeats() public {
        address[] memory many = new address[](257);
        for (uint256 i = 0; i < 257; i++) many[i] = address(uint160(0x1000 + i));
        vm.expectRevert(TandaBillFactory.TooManySeats.selector);
        factory.createBill(IERC20(address(token)), many);
    }

    function test_factory_createBill_revertsDuplicateSeat() public {
        address[] memory dup = new address[](2);
        dup[0] = owner;
        dup[1] = owner;
        vm.expectRevert(abi.encodeWithSelector(TandaBillV2.DuplicateSeat.selector, owner));
        factory.createBill(IERC20(address(token)), dup);
    }

    function test_factory_multipleBills_distinctClones() public {
        TandaBillV2 b1 = _createAs(owner, _seats3());
        TandaBillV2 b2 = _createAs(owner, _seats3());
        assertTrue(address(b1) != address(b2));
        assertTrue(factory.isBill(address(b1)));
        assertTrue(factory.isBill(address(b2)));
        // state independence: fund b1 only, b2 stays empty
        vm.startPrank(owner);
        b1.addExpense(100e6);
        token.approve(address(b1), 100e6);
        b1.fundEscrow(100e6);
        vm.stopPrank();
        assertEq(b1.escrowBalance(), 100e6);
        assertEq(b2.escrowBalance(), 0);
    }

    function test_clone_isEip1167() public {
        TandaBillV2 bill = _createAs(owner, _seats3());
        bytes memory code = address(bill).code;
        // Canonical minimal proxy runtime = 10 B prefix + 20 B impl addr + 15 B suffix.
        bytes memory expected = abi.encodePacked(
            hex"363d3d373d3d3d363d73",
            address(impl),
            hex"5af43d82803e903d91602b57fd5bf3"
        );
        assertEq(code.length, 45);
        assertEq(code, expected);
    }

    // ─── Full lifecycle ──────────────────────────────────────────────────

    function test_lifecycle_fullConfirm_thenWindow_thenExecute() public {
        uint256 amount = 300e6;
        TandaBillV2 bill = _initiatedBill(amount);

        // Not fully confirmed until all three seats confirm; escrow moved out of balance.
        assertEq(_s(bill, 0).fullyConfirmedAt, 0);
        assertEq(bill.escrowBalance(), 0);

        _confirmAs(owner, bill, 0);
        assertEq(_s(bill, 0).fullyConfirmedAt, 0);
        _confirmAs(alice, bill, 0);
        _confirmAs(bob, bill, 0);
        assertTrue(_s(bill, 0).fullyConfirmedAt != 0);

        // Before the window elapses: revert.
        vm.expectRevert(TandaBillV2.WindowNotElapsed.selector);
        bill.executeSettlement(0);

        // At the boundary (>= fullyConfirmedAt + SETTLEMENT_WINDOW): succeeds.
        uint64 fc = _s(bill, 0).fullyConfirmedAt;
        vm.warp(fc + impl.SETTLEMENT_WINDOW());
        bill.executeSettlement(0);
        // P0.1a: execute only OPENS claims — escrow intact until each seat pulls.
        assertEq(token.balanceOf(address(bill)), amount);
        _drain3(bill);

        assertEq(token.balanceOf(owner), 1_000_000e6 - amount + amount / 3);
        assertEq(token.balanceOf(alice), 1_000_000e6 + amount / 3);
        assertEq(token.balanceOf(bob), 1_000_000e6 + amount / 3);
        assertEq(_s(bill, 0).settledAt, uint64(block.timestamp));
    }

    function test_gap2_executeRevertsNotFullyConfirmed() public {
        // THE repointed gap2 witness: green via V2 custom error (the legacy v1-suite
        // witness stays red against the W1 stub). Only part of the roster confirms.
        TandaBillV2 bill = _initiatedBill(100e6);
        _confirmAs(owner, bill, 0);
        _confirmAs(alice, bill, 0);
        // bob has NOT confirmed
        vm.expectRevert(TandaBillV2.NotFullyConfirmed.selector);
        bill.executeSettlement(0);
    }

    function test_gap2_executeRevertsBeforeWindow() public {
        TandaBillV2 bill = _initiatedBill(100e6);
        _fullConfirm3(bill);
        vm.expectRevert(TandaBillV2.WindowNotElapsed.selector);
        bill.executeSettlement(0);
    }

    function test_gap2_executeSucceedsAtBoundary() public {
        TandaBillV2 bill = _initiatedBill(100e6);
        _fullConfirm3(bill);
        uint64 fc = _s(bill, 0).fullyConfirmedAt;
        vm.warp(fc + 3600); // exactly SETTLEMENT_WINDOW
        bill.executeSettlement(0);
        assertTrue(_s(bill, 0).settledAt != 0);
    }

    function test_confirm_revertsAlreadyConfirmed() public {
        TandaBillV2 bill = _initiatedBill(100e6);
        _confirmAs(alice, bill, 0);
        vm.expectRevert(TandaBillV2.AlreadyConfirmed.selector);
        _confirmAs(alice, bill, 0);
    }

    function test_confirm_revertsNotAnExpectedSeat() public {
        TandaBillV2 bill = _initiatedBill(100e6);
        // eve is not a seat at all
        vm.expectRevert(TandaBillV2.NotAnExpectedSeat.selector);
        _confirmAs(eve, bill, 0);
        // dan is a seat but added AFTER initiation → not in the snapshot mask
        vm.prank(owner);
        bill.addSeat(dan);
        vm.expectRevert(TandaBillV2.NotAnExpectedSeat.selector);
        _confirmAs(dan, bill, 0);
    }

    function test_confirm_revertsAfterFullConfirm() public {
        TandaBillV2 bill = _initiatedBill(100e6);
        _fullConfirm3(bill);
        vm.expectRevert(TandaBillV2.NotAwaitingConfirmations.selector);
        _confirmAs(owner, bill, 0);
    }

    function test_confirm_revertsAfterSettle() public {
        TandaBillV2 bill = _initiatedBill(100e6);
        _fullConfirm3(bill);
        vm.warp(_s(bill, 0).fullyConfirmedAt + 3600);
        bill.executeSettlement(0);
        vm.expectRevert(TandaBillV2.AlreadySettled.selector);
        _confirmAs(owner, bill, 0);
    }

    function test_confirm_revertsSettlementNotFound() public {
        TandaBillV2 bill = _initiatedBill(100e6);
        vm.expectRevert(TandaBillV2.SettlementNotFound.selector);
        _confirmAs(owner, bill, 99);
    }

    // ─── MAX_HOLD refund escape (invariant-5) ────────────────────────────

    function test_maxHold_refund_revertsBeforeMaxHold() public {
        TandaBillV2 bill = _initiatedBill(100e6);
        _confirmAs(owner, bill, 0); // not fully confirmed
        vm.warp(block.timestamp + 72 hours - 1);
        vm.expectRevert(TandaBillV2.RefundNotAvailable.selector);
        vm.prank(owner);
        bill.refundSettlement(0);
    }

    function test_maxHold_refund_succeedsAfterMaxHold() public {
        uint256 amount = 100e6;
        TandaBillV2 bill = _initiatedBill(amount);
        _confirmAs(owner, bill, 0); // never fully confirms
        vm.warp(block.timestamp + 72 hours);
        uint256 escrowBefore = token.balanceOf(address(bill));
        assertEq(escrowBefore, amount);
        uint256 ownerBefore = token.balanceOf(owner);
        vm.prank(owner);
        bill.refundSettlement(0);
        assertEq(token.balanceOf(owner), ownerBefore + amount);
        assertEq(token.balanceOf(address(bill)), 0);
        assertTrue(_s(bill, 0).refunded);
        // refunded settlement can never execute
        vm.expectRevert(TandaBillV2.AlreadySettled.selector);
        bill.executeSettlement(0);
    }

    function test_maxHold_refund_revertsIfFullyConfirmed() public {
        TandaBillV2 bill = _initiatedBill(100e6);
        _fullConfirm3(bill);
        vm.warp(block.timestamp + 72 hours);
        vm.expectRevert(TandaBillV2.RefundNotAvailable.selector);
        vm.prank(owner);
        bill.refundSettlement(0);
    }

    function test_maxHold_refund_revertsIfNotOwner() public {
        TandaBillV2 bill = _initiatedBill(100e6);
        vm.warp(block.timestamp + 72 hours);
        vm.expectRevert(TandaBillV2.NotOwner.selector);
        vm.prank(alice);
        bill.refundSettlement(0);
    }

    // ─── Roster + payout math ────────────────────────────────────────────

    function test_postInitiateSeat_receivesNothing() public {
        // Regression the live E2E caught: a seat added AFTER initiate is not in the
        // expectedMask snapshot — it can't confirm, receives nothing, payouts stay 3.
        uint256 amount = 200e6;
        TandaBillV2 bill = _initiatedBill(amount);
        vm.prank(owner);
        bill.addSeat(dan); // after initiateSettlement
        _fullConfirm3(bill);
        vm.warp(_s(bill, 0).fullyConfirmedAt + 3600);
        bill.executeSettlement(0);
        _drain3(bill); // snapshot seats drain; dan (post-initiate) has no claim

        uint256[] memory payouts = bill.settlementPayouts(0);
        assertEq(payouts.length, 3); // snapshot: owner+alice+bob
        assertEq(_sum(payouts), amount);
        assertEq(token.balanceOf(dan), 1_000_000e6); // received nothing
        vm.expectRevert(TandaBillV2.NotAnExpectedSeat.selector);
        _claimAs(dan, bill, 0);
    }

    function test_removeSeat_beforeInitiate_excludedFromPayout() public {
        uint256 amount = 200e6;
        TandaBillV2 bill = _createAs(owner, _seats3());
        vm.prank(owner);
        bill.removeSeat(2); // bob (owner=0, alice=1, bob=2)
        vm.startPrank(owner);
        bill.addExpense(amount);
        token.approve(address(bill), amount);
        bill.fundEscrow(amount);
        bill.initiateSettlement();
        vm.stopPrank();
        _confirmAs(owner, bill, 0);
        _confirmAs(alice, bill, 0);
        vm.warp(_s(bill, 0).fullyConfirmedAt + 3600);
        bill.executeSettlement(0);
        _claimAs(owner, bill, 0);
        _claimAs(alice, bill, 0); // removed bob cannot claim: seatIdOf cleared
        vm.expectRevert(TandaBillV2.NotAnExpectedSeat.selector);
        _claimAs(bob, bill, 0);
        uint256[] memory payouts = bill.settlementPayouts(0);
        assertEq(payouts.length, 2);
        assertEq(token.balanceOf(bob), 1_000_000e6); // untouched
        assertEq(_sum(payouts), amount);
    }

    function test_removeSeat_revertsAfterInitiation() public {
        TandaBillV2 bill = _initiatedBill(100e6);
        vm.expectRevert(TandaBillV2.SettlementInitiatedAlready.selector);
        vm.prank(owner);
        bill.removeSeat(1);
    }

    function test_settlement_unevenSplitRemainder() public {
        uint256 amount = 100e6; // 3 seats → 33,333,333 / 33,333,333 / 33,333,334
        TandaBillV2 bill = _initiatedBill(amount);
        _fullConfirm3(bill);
        vm.warp(_s(bill, 0).fullyConfirmedAt + 3600);
        bill.executeSettlement(0);
        uint256[] memory payouts = bill.settlementPayouts(0);
        assertEq(payouts.length, 3);
        assertEq(payouts[0], 33_333_334); // owner (first active seat) gets the extra wei
        assertEq(payouts[1], 33_333_333);
        assertEq(payouts[2], 33_333_333);
        assertEq(_sum(payouts), amount);
    }

    function test_settlement_unevenSplit_fourSeats() public {
        uint256 amount = 100e6; // 4 seats → exactly 25,000,000 each
        TandaBillV2 bill = _createAs(owner, _seats4());
        vm.startPrank(owner);
        bill.addExpense(amount);
        token.approve(address(bill), amount);
        bill.fundEscrow(amount);
        bill.initiateSettlement();
        vm.stopPrank();
        _confirmAs(owner, bill, 0); _confirmAs(alice, bill, 0);
        _confirmAs(bob, bill, 0);   _confirmAs(carol, bill, 0);
        vm.warp(_s(bill, 0).fullyConfirmedAt + 3600);
        bill.executeSettlement(0);
        uint256[] memory payouts = bill.settlementPayouts(0);
        assertEq(payouts.length, 4);
        assertEq(payouts[0], 25_000_000);
        assertEq(payouts[3], 25_000_000);
        assertEq(_sum(payouts), amount);
    }

    function test_settlement_revertsIfEscrowShort() public {
        TandaBillV2 bill = _createAs(owner, _seats3());
        vm.startPrank(owner);
        bill.addExpense(100e6);
        token.approve(address(bill), 10e6);
        bill.fundEscrow(10e6); // less than expense
        vm.expectRevert(TandaBillV2.EscrowEmpty.selector);
        bill.initiateSettlement();
        vm.stopPrank();
    }

    function test_initiateSettlement_revertsIfNoActiveSeats() public {
        address[] memory one = new address[](1);
        one[0] = owner;
        TandaBillV2 bill = _createAs(owner, one);
        vm.startPrank(owner);
        bill.addExpense(100e6);
        token.approve(address(bill), 100e6);
        bill.fundEscrow(100e6);
        bill.removeSeat(0); // sole seat removed → zero active seats
        vm.expectRevert(TandaBillV2.NoActiveSeats.selector);
        bill.initiateSettlement();
        vm.stopPrank();
    }

    function test_settlementPayouts_accessorExplicit() public {
        // Solidity struct getters omit dynamic arrays; settlementPayouts is the safe read.
        TandaBillV2 bill = _initiatedBill(100e6);
        uint256[] memory p = bill.settlementPayouts(0);
        assertEq(p.length, 3);
        assertEq(_sum(p), 100e6);
    }

    function test_isSeatConfirmed_view() public {
        TandaBillV2 bill = _initiatedBill(100e6);
        assertFalse(bill.isSeatConfirmed(0, alice));
        _confirmAs(alice, bill, 0);
        assertTrue(bill.isSeatConfirmed(0, alice));
        assertFalse(bill.isSeatConfirmed(0, eve)); // non-seat
    }

    function test_fundEscrow_byAnyFunder() public {
        TandaBillV2 bill = _createAs(owner, _seats3());
        vm.prank(alice);
        token.approve(address(bill), 50e6);
        vm.prank(alice);
        bill.fundEscrow(50e6);
        assertEq(bill.escrowBalance(), 50e6); // v2 opens funding to any seat/holder
    }

    function test_addExpense_revertsIfNotOwner() public {
        TandaBillV2 bill = _createAs(owner, _seats3());
        vm.expectRevert(TandaBillV2.NotOwner.selector);
        vm.prank(alice);
        bill.addExpense(1);
    }

    function test_singleSeat_requiresExplicitConfirm() public {
        // Auto-full-confirm edge: sole seat = owner still needs explicit confirm.
        address[] memory one = new address[](1);
        one[0] = owner;
        TandaBillV2 bill = _createAs(owner, one);
        vm.startPrank(owner);
        bill.addExpense(50e6);
        token.approve(address(bill), 50e6);
        bill.fundEscrow(50e6);
        bill.initiateSettlement();
        vm.stopPrank();
        assertEq(_s(bill, 0).fullyConfirmedAt, 0); // no silent release
        vm.expectRevert(TandaBillV2.NotFullyConfirmed.selector);
        bill.executeSettlement(0);
        _confirmAs(owner, bill, 0);
        vm.warp(_s(bill, 0).fullyConfirmedAt + 3600);
        bill.executeSettlement(0);
        _claimAs(owner, bill, 0); // P0.1a: sole seat pulls its own payout
        assertEq(token.balanceOf(owner), 1_000_000e6); // own expense returned to self
    }

    // ─── Views / constants ───────────────────────────────────────────────

    function test_maxSeatsConstant() public {
        assertEq(impl.MAX_SEATS(), 256);
        assertEq(impl.SETTLEMENT_WINDOW(), 1 hours);
        assertEq(impl.MAX_HOLD(), 72 hours);
    }

    // ─── P0.1 rotateSeatWallet (W10 gate suite) ─────────────────────────

    function test_rotate_preInitiate_seatSelf() public {
        TandaBillV2 bill = _createAs(owner, _seats3());
        vm.prank(alice);
        bill.rotateSeatWallet(1, eve);
        (address w0, , ) = bill.seats(0);
        (address w1, , ) = bill.seats(1);
        assertEq(w1, eve);
        assertEq(w0, owner);
        assertEq(bill.seatIdOf(eve), 2);   // seatId+1
        assertEq(bill.seatIdOf(alice), 0); // old mapping cleared
    }

    function test_rotate_byOwner_recovery() public {
        TandaBillV2 bill = _createAs(owner, _seats3());
        vm.prank(owner);
        bill.rotateSeatWallet(2, dan);
        (address w2, , ) = bill.seats(2);
        assertEq(w2, dan);
    }

    function test_rotate_stranger_reverts() public {
        TandaBillV2 bill = _createAs(owner, _seats3());
        vm.prank(carol);
        vm.expectRevert(TandaBillV2.NotSeatOrOwner.selector);
        bill.rotateSeatWallet(1, eve);
    }

    function test_rotate_duplicateTarget_reverts() public {
        TandaBillV2 bill = _createAs(owner, _seats3());
        vm.prank(alice);
        vm.expectRevert(abi.encodeWithSelector(TandaBillV2.DuplicateSeat.selector, bob));
        bill.rotateSeatWallet(1, bob);
    }

    function test_rotate_zeroWallet_reverts() public {
        TandaBillV2 bill = _createAs(owner, _seats3());
        vm.prank(alice);
        vm.expectRevert(TandaBillV2.ZeroWallet.selector);
        bill.rotateSeatWallet(1, address(0));
    }

    /// @notice Ratified semantics: UNCONFIRMED self-rotation is the rescue path - alice
    ///         rotates before confirming; eve then confirms the seat via the new wallet
    ///         (seat-indexed confirm state follows the wallet), execute pays eve.
    function test_rotate_unconfirmedSelf_beforeConfirm_paysNewWallet() public {
        TandaBillV2 bill = _initiatedBill(300e6);
        // owner + bob confirm; alice NOT yet confirmed => not fullyConfirmed
        _confirmAs(owner, bill, 0);
        _confirmAs(bob, bill, 0);

        uint256 evePre = token.balanceOf(eve);
        uint256 alicePre = token.balanceOf(alice);
        vm.prank(alice);
        bill.rotateSeatWallet(1, eve); // unconfirmed self, FCA==0 => always allowed

        _confirmAs(eve, bill, 0); // eve confirms seat 1 via new wallet
        assertTrue(_s(bill, 0).fullyConfirmedAt != 0);

        vm.warp(block.timestamp + 1 hours + 1);
        bill.executeSettlement(0);
        _claimAs(owner, bill, 0);
        _claimAs(bob, bill, 0);
        _claimAs(eve, bill, 0); // seat 1's rotated wallet pulls the payout (P0.1a)

        assertEq(token.balanceOf(eve),   evePre + 100e6);
        assertEq(token.balanceOf(alice), alicePre);       // old wallet got nothing
        assertEq(token.balanceOf(owner), 1_000_000e6 - 300e6 + 100e6);
        assertEq(token.balanceOf(bob),   1_000_000e6 + 100e6);
    }

    /// @notice Ratified split-lock: a seat that ALREADY CONFIRMED cannot rotate inside
    ///         the settlement window (no last-second self-redirection of confirmed state).
    function test_rotate_confirmedSelf_lockedInWindow() public {
        TandaBillV2 bill = _initiatedBill(300e6);
        _fullConfirm3(bill); // alice confirmed as herself
        vm.prank(alice);
        vm.expectRevert(TandaBillV2.RotationWindowLocked.selector);
        bill.rotateSeatWallet(1, eve);
        // after the window (executable), self-rescue of own funds is allowed again
        vm.warp(block.timestamp + 1 hours + 1);
        vm.prank(alice);
        bill.rotateSeatWallet(1, eve);
        bill.executeSettlement(0);
        _claimAs(eve, bill, 0); // P0.1a: rotated wallet claims after execute
        assertEq(token.balanceOf(eve), 1_000_000e6 + 100e6);
    }

    /// @notice Owner-driven rotation of another seat dies at FULL CONFIRMATION (in-window),
    ///         strictly earlier than the window-expiry rule it replaces.
    function test_rotate_ownerLockedAtFullConfirm_inWindow() public {
        TandaBillV2 bill = _initiatedBill(300e6);
        _fullConfirm3(bill);
        vm.prank(owner);
        vm.expectRevert(TandaBillV2.RotationWindowLocked.selector);
        bill.rotateSeatWallet(1, dan); // inside window, not executable yet
    }

    // ─── Trusted forwarder (correction #1 remediation) ──────────────────

    function test_forwarder_callBill_fullLifecycle() public {
        address[] memory roster = new address[](2);
        roster[0] = owner;
        roster[1] = alice;
        vm.prank(owner);
        address billAddr = factory.createBill(IERC20(address(token)), roster);
        TandaBillV2 hub = TandaBillV2(payable(billAddr));
        assertEq(address(hub.factory()), address(factory));

        bytes memory cd;
        // owner actions via forwarder
        vm.startPrank(owner);
        cd = abi.encodeCall(hub.addExpense, (200e6));
        factory.callBill(billAddr, cd);
        token.approve(billAddr, 200e6); // approve stays direct: spender is the CLONE
        cd = abi.encodeCall(hub.fundEscrow, (200e6));
        factory.callBill(billAddr, cd);
        cd = abi.encodeCall(hub.initiateSettlement, ());
        factory.callBill(billAddr, cd);
        vm.stopPrank();

        // confirmations via forwarder from each seat wallet (identity preserved)
        vm.prank(owner);
        cd = abi.encodeCall(hub.confirmSettlement, (0));
        factory.callBill(billAddr, cd);
        vm.prank(alice);
        cd = abi.encodeCall(hub.confirmSettlement, (0));
        factory.callBill(billAddr, cd);
        assertEq(_s(hub, 0).fullyConfirmedAt != 0, true);

        vm.warp(block.timestamp + 1 hours + 1);
        vm.prank(carol); // permissionless execute, still permissionless via forwarder
        cd = abi.encodeCall(hub.executeSettlement, (0));
        factory.callBill(billAddr, cd);
        // P0.1a: claim leg flows through the forwarder too — _caller() identity survives.
        vm.prank(owner);
        cd = abi.encodeCall(hub.claimSettlement, (0));
        factory.callBill(billAddr, cd);
        vm.prank(alice);
        cd = abi.encodeCall(hub.claimSettlement, (0));
        factory.callBill(billAddr, cd);
        assertEq(token.balanceOf(alice), 1_000_000e6 + 100e6);
        assertEq(token.balanceOf(owner), 1_000_000e6 - 200e6 + 100e6);
    }

    function test_forwarder_callBill_identityEnforced() public {
        TandaBillV2 bill = _createAs(owner, _seats3());
        vm.prank(carol);
        vm.expectRevert(TandaBillV2.NotSeatOrOwner.selector); // bubbled revert, selector intact
        factory.callBill(address(bill), abi.encodeCall(bill.rotateSeatWallet, (1, eve)));
    }

    function test_forwarder_callBill_notBill_reverts() public {
        vm.expectRevert(TandaBillFactory.NotBill.selector);
        factory.callBill(address(0xBAD), hex"00");
    }

    /// @notice Freeze-receipt addendum (Flux): clone initialize is one-shot - a non-factory
    ///         direct initialize on a live clone reverts, so the _caller trust anchor cannot
    ///         be re-pointed post-create.
    function test_forwarder_initialize_guard() public {
        TandaBillV2 bill = _createAs(owner, _seats3());
        vm.prank(carol);
        vm.expectRevert(TandaBillV2.AlreadyInitialized.selector);
        bill.initialize(IERC20(address(token)), carol, _seats3());
        assertEq(address(bill.factory()), address(factory)); // anchor still canonical
    }

    function test_rotate_afterExecute_reverts() public {
        TandaBillV2 bill = _initiatedBill(300e6);
        _fullConfirm3(bill);
        vm.warp(block.timestamp + 1 hours + 1);
        bill.executeSettlement(0);
        vm.prank(alice);
        vm.expectRevert(TandaBillV2.SeatRotationClosed.selector);
        bill.rotateSeatWallet(1, eve);
    }

    /// @notice Audit-fix #3: at executability (fully-confirmed + window elapsed),
    ///         OWNER-driven rotation of another seat locks (anti-rug), while the
    ///         seat ITSELF can still rotate until executed/refunded.
    function test_rotate_ownerLockedAtExecutability_selfStillOk() public {
        TandaBillV2 bill = _initiatedBill(300e6);
        _fullConfirm3(bill);
        vm.warp(block.timestamp + 1 hours + 1);

        vm.prank(owner);
        vm.expectRevert(TandaBillV2.RotationWindowLocked.selector);
        bill.rotateSeatWallet(1, dan); // owner redirect attempt at the finish line

        vm.prank(alice); // seat-self unaffected
        bill.rotateSeatWallet(1, eve);

        bill.executeSettlement(0); // P0.1a: opens claims; eve (rotated seat wallet) pulls
        _claimAs(eve, bill, 0);
        assertEq(token.balanceOf(eve),   1_000_000e6 + 100e6);
        assertEq(token.balanceOf(dan),   1_000_000e6);
    }

    // ─── P0.1a pull-claim settlement (W10 backlog option (a)) ─────────────

    function test_pull_executeOpensClaims_nothingMoves() public {
        TandaBillV2 bill = _initiatedBill(300e6);
        _fullConfirm3(bill);
        vm.warp(block.timestamp + 1 hours + 1);
        bill.executeSettlement(0);

        assertTrue(_s(bill, 0).settledAt != 0);
        assertEq(_s(bill, 0).claimedMask, 0);
        // Escrow fully intact: pull leg, not push leg.
        assertEq(token.balanceOf(address(bill)), 300e6);
        assertEq(token.balanceOf(alice), 1_000_000e6);
        // Claims visible per seat (frontend view); non-seat sees zero.
        assertEq(bill.claimablePayout(0, owner), 100e6);
        assertEq(bill.claimablePayout(0, alice), 100e6);
        assertEq(bill.claimablePayout(0, bob),   100e6);
        assertEq(bill.claimablePayout(0, eve),   0);
    }

    function test_pull_claim_allSeats_drainsContract() public {
        TandaBillV2 bill = _initiatedBill(300e6);
        _fullConfirm3(bill);
        vm.warp(block.timestamp + 1 hours + 1);
        bill.executeSettlement(0);
        _drain3(bill);

        assertEq(token.balanceOf(address(bill)), 0);
        assertEq(token.balanceOf(owner), 1_000_000e6 - 300e6 + 100e6);
        assertEq(token.balanceOf(alice), 1_000_000e6 + 100e6);
        assertEq(token.balanceOf(bob),   1_000_000e6 + 100e6);
        assertEq(_s(bill, 0).claimedMask, _s(bill, 0).expectedMask); // fully drained
        assertEq(bill.claimablePayout(0, alice), 0);
    }

    function test_pull_claim_gatesBeforeExecuteAndAfterRefund() public {
        TandaBillV2 bill = _initiatedBill(100e6);
        // (a) settlement initiated but not executed → nothing claimable
        vm.expectRevert(TandaBillV2.NotYetClaimable.selector);
        _claimAs(alice, bill, 0);
        // (b) unknown settlement id (bounds check runs first)
        vm.expectRevert(TandaBillV2.SettlementNotFound.selector);
        _claimAs(alice, bill, 99);
        // (c) refunded settlement stays NotYetClaimable forever (settledAt never set)
        vm.warp(block.timestamp + 72 hours);
        vm.prank(owner);
        bill.refundSettlement(0);
        vm.expectRevert(TandaBillV2.NotYetClaimable.selector);
        _claimAs(alice, bill, 0);
    }

    function test_pull_claim_revertsNotAnExpectedSeat() public {
        TandaBillV2 bill = _initiatedBill(300e6);
        vm.prank(owner);
        bill.addSeat(dan); // post-initiate seat → outside the snapshot mask
        _fullConfirm3(bill);
        vm.warp(block.timestamp + 1 hours + 1);
        bill.executeSettlement(0);
        vm.expectRevert(TandaBillV2.NotAnExpectedSeat.selector);
        _claimAs(eve, bill, 0); // holds no seat at all
        vm.expectRevert(TandaBillV2.NotAnExpectedSeat.selector);
        _claimAs(dan, bill, 0); // seat, but not in expectedMask
    }

    function test_pull_claim_revertsPayoutAlreadyClaimed() public {
        TandaBillV2 bill = _initiatedBill(300e6);
        _fullConfirm3(bill);
        vm.warp(block.timestamp + 1 hours + 1);
        bill.executeSettlement(0);
        _claimAs(alice, bill, 0);
        vm.expectRevert(TandaBillV2.PayoutAlreadyClaimed.selector);
        _claimAs(alice, bill, 0);
    }

    /// @notice THE P0.1a deadlock-cure repro (backlog evidence: reverting/blacklisted seat
    ///         receiver dead-locked the push-loop escrow permanently). Act 1: with alice
    ///         inbound-blocked, executeSettlement still succeeds and every honest seat
    ///         drains; only alice's own claim reverts, state rolled back and retryable,
    ///         her share escrowed to her alone. Act 2: the operational cure — seat rotates
    ///         to a clean wallet before execute (P0.1b path), the new wallet pulls.
    function test_pull_deadlockCure_blacklistedReceiver() public {
        BlockableToken bt = new BlockableToken();
        bt.mint(owner, 1_000_000e6);
        bt.mint(alice, 1_000_000e6);
        bt.mint(bob,   1_000_000e6);

        vm.prank(owner);
        TandaBillV2 bill = TandaBillV2(payable(factory.createBill(IERC20(address(bt)), _seats3())));
        vm.startPrank(owner);
        bill.addExpense(300e6);
        bt.approve(address(bill), 300e6);
        bill.fundEscrow(300e6);
        bill.initiateSettlement();
        vm.stopPrank();
        bt.blockAddress(alice);

        _confirmAs(owner, bill, 0);
        _confirmAs(alice, bill, 0);
        _confirmAs(bob, bill, 0);
        vm.warp(block.timestamp + 1 hours + 1);

        // Push-loop world: this reverts forever on alice's transfer. Pull world: claims open.
        bill.executeSettlement(0);
        _claimAs(owner, bill, 0);
        _claimAs(bob, bill, 0);
        assertEq(bt.balanceOf(owner), 1_000_000e6 - 300e6 + 100e6);
        assertEq(bt.balanceOf(bob),   1_000_000e6 + 100e6);

        vm.expectRevert(abi.encodeWithSelector(SafeERC20Minimal.SafeERC20Failed.selector, address(bt), abi.encodeWithSignature("Error(string)", "receiver blocked"))); // HIGH-2: raw revert now typed-wrapped, behavior identical
        _claimAs(alice, bill, 0);
        // CEI: failed transfer rolls back the claim bit — retryable, not burned.
        assertEq((_s(bill, 0).claimedMask & (uint256(1) << 1)), 0);
        assertEq(bt.balanceOf(alice), 1_000_000e6);          // blocked wallet received nothing
        assertEq(bill.claimablePayout(0, alice), 100e6);      // share escrowed, pullable only by alice
        assertEq(bt.balanceOf(address(bill)), 100e6);

        // Act 2 — cure: rotate to a clean wallet before execute, claim after.
        vm.prank(owner);
        TandaBillV2 b2 = TandaBillV2(payable(factory.createBill(IERC20(address(bt)), _seats3())));
        vm.startPrank(owner);
        b2.addExpense(300e6);
        bt.approve(address(b2), 300e6);
        b2.fundEscrow(300e6);
        b2.initiateSettlement();
        vm.stopPrank();
        _confirmAs(owner, b2, 0);
        _confirmAs(bob, b2, 0);
        vm.prank(alice);
        b2.rotateSeatWallet(1, eve); // unconfirmed self-rotation (P0.1b rescue path)
        _confirmAs(eve, b2, 0);      // seat 1 confirms via the clean wallet
        vm.warp(block.timestamp + 1 hours + 1);
        b2.executeSettlement(0);
        _claimAs(owner, b2, 0);
        _claimAs(bob, b2, 0);
        _claimAs(eve, b2, 0);
        assertEq(bt.balanceOf(eve), 100e6);              // rescued payout landed on new wallet
        assertEq(bt.balanceOf(alice), 1_000_000e6);      // old (blocked) wallet still nothing
        assertEq(bt.balanceOf(address(b2)), 0);          // settlement fully drained
    }

    function test_claimablePayout_view_states() public {
        uint256 amount = 100e6; // 3 seats → 33,333,334 / 33,333,333 / 33,333,333
        TandaBillV2 bill = _initiatedBill(amount);
        assertEq(bill.claimablePayout(0, owner), 0); // pre-execute
        _fullConfirm3(bill);
        vm.warp(block.timestamp + 1 hours + 1);
        bill.executeSettlement(0);
        assertEq(bill.claimablePayout(0, owner), 33_333_334); // rank-0 seat carries the remainder wei
        assertEq(bill.claimablePayout(0, alice), 33_333_333);
        assertEq(bill.claimablePayout(0, bob),   33_333_333);
        _claimAs(alice, bill, 0);
        assertEq(bill.claimablePayout(0, alice), 0); // post-claim
        assertEq(bill.claimablePayout(0, eve),   0); // non-seat
        assertEq(bill.claimablePayout(9, alice), 0); // unknown settlement
    }
}