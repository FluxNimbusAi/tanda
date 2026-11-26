// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

import {GateMockToken} from "./FactoryCloneGateGolden.t.sol";
import {Test} from "forge-std/Test.sol";

/// @title Engine37GateMockArmSweep [t_2812bb4a]
/// @notice ENGINE-37 (family B1) - mock-honesty arm sweep for GateMockToken, the
///         ERC20 mock that FactoryCloneGateGolden (seat-gate clone-path golden,
///         ENGINE-32) rides on. proofs/gaps_after_e32.json pinned 27 open arms:
///         mint never called (line/statement/function), both transfer require
///         paths unproven, all three transferFrom short-circuit paths unproven,
///         approve/fallbackGuard never executed. A golden whose token mock has
///         unverified revert strings is a silent false-pass risk: if the mock's
///         "insufficient"/"no" arms were wrong, every downstream fund/escrow
///         expectation calibrated on them would be fiction. This suite pins the
///         mock's real behavior by direct real-state calls - arms AND semantics.
/// @dev  ENGINE-30 sweep recipe (test/MockHarnessArms30.t.sol), audited against
///         GateMockToken source (FactoryCloneGateGolden.t.sol L27-47):
///           * combined-&& class: `require(bal && allow, "no")` in transferFrom -
///             left-FALSE probe runs BEFORE any leg that could fund the victim,
///             right-FALSE arrives via revoked allowance, so the two short-circuit
///             arms stay distinguishable (the right operand is granted TRUE on
///             the left-FALSE leg, proving which side fired);
///           * every success probe SELF-ROUTES (FUNDED -> FUNDED): ZERO, the
///             revert victim for "insufficient" and for the left-FALSE leg, never
///             holds balance (helper bug #2 class: a FUNDED -> ZERO success leg
///             poisons every downstream revert victim);
///           * no vm.mockCall anywhere; ledger deltas asserted (self-transfers
///             conserve balance, allowance decrements exactly once per unit
///             moved, reverted legs change nothing) - coverage arms + honesty.
///           * DIAGONAL LAW (sweep-discovered, pinned in
///             test_approve_writes_diagonal_not_sender_row): approve does
///             `allowance[fallbackGuard(sp)][sp] = a` and fallbackGuard is the
///             pure identity - the ROW is sp; msg.sender is never consulted.
///             Only diagonal cells allowance[X][X] are writable, so transferFrom
///             can ever only succeed with f == msg.sender (self-spend). That is
///             a deliberate deviation from real ERC20: never fund a bill escrow
///             through this mock with a third-party spender leg - the grant
///             would silently land on the spender's own diagonal cell. The E32
///             golden never transfers (seat-gate laws F1-F4 only), so existing
///             goldens stay valid; this test is the fence for the next author
///             who reaches for this token as generic test money.
contract Engine37GateMockArmSweepTest is Test {
    GateMockToken token;
    address private constant FUNDED = address(0xF00D37);
    address private constant ZERO   = address(0x2E0037); // revert victim: empty for life

    function setUp() public {
        token = new GateMockToken();
        token.mint(FUNDED, 1000); // closes mint line/statement/function gaps
        assertEq(token.balanceOf(FUNDED), 1000, "mint credited FUNDED");
    }

    /// @notice transfer(): TRUE arm via self-route first, then FALSE arm with a
    ///         victim that provably never held balance (ghost-pass guard).
    function test_transfer_arms_exact_erc20_revert() public {
        vm.prank(FUNDED);
        assertTrue(token.transfer(FUNDED, 10), "success leg returns true");
        assertEq(token.balanceOf(FUNDED), 1000, "self-transfer conserves balance");

        assertEq(token.balanceOf(ZERO), 0, "victim never funded before revert probe");
        vm.prank(ZERO);
        vm.expectRevert(bytes("insufficient"));
        token.transfer(FUNDED, 1);
        assertEq(token.balanceOf(ZERO), 0, "revert leg moved nothing");
    }

    /// @notice transferFrom(): all three paths of `require(bal && allow, "no")` in
    ///         recipe order: left-FALSE BEFORE any success leg, both-TRUE success
    ///         self-routed, right-FALSE via revoked allowance. Every leg is a
    ///         self-spend (f == caller) per the diagonal law above.
    function test_transferFrom_all_paths_in_recipe_order() public {
        // -- left-FALSE: f=ZERO with bal 0. The RIGHT operand is deliberately
        //    armed TRUE first (approve(ZERO, 500) -> diagonal [ZERO][ZERO],
        //    spent by pranking the call from ZERO), so the "no" revert is
        //    provably the left short-circuit, not an ambiguous double-false.
        vm.prank(ZERO);
        token.approve(ZERO, 500);
        assertEq(token.allowance(ZERO, ZERO), 500, "right operand armed on left-FALSE leg");
        vm.prank(ZERO);
        vm.expectRevert(bytes("no"));
        token.transferFrom(ZERO, FUNDED, 1);
        assertEq(token.balanceOf(ZERO), 0, "ZERO still never holds balance");
        assertEq(token.allowance(ZERO, ZERO), 500, "reverted tf spent no allowance");

        // -- both-TRUE success SELF-ROUTES FUNDED -> FUNDED: ZERO stays empty for
        //    every remaining probe.
        vm.prank(FUNDED);
        token.approve(FUNDED, 500);
        vm.prank(FUNDED);
        assertTrue(token.transferFrom(FUNDED, FUNDED, 3), "tf success returns true");
        assertEq(token.allowance(FUNDED, FUNDED), 497, "allowance decremented exactly");
        assertEq(token.balanceOf(FUNDED), 1000, "tf self-route conserves balance");

        // -- right-FALSE: revoked allowance with balance present => only the RIGHT
        //    operand can fail. Left TRUE, right FALSE - arms distinguishable.
        vm.prank(FUNDED);
        token.approve(FUNDED, 0);
        vm.prank(FUNDED);
        vm.expectRevert(bytes("no"));
        token.transferFrom(FUNDED, FUNDED, 1);
        assertEq(token.balanceOf(FUNDED), 1000, "reverted tf changed nothing");
        assertEq(token.allowance(FUNDED, FUNDED), 0, "revoked stays revoked");
    }

    /// @notice approve()/fallbackGuard() semantics: returns true, the guard is the
    ///         pure identity it claims to be, and the write lands on the sp
    ///         diagonal row - the msg.sender row gets NOTHING (DIAGONAL LAW).
    ///         Pinning the deviation from ERC20, not a symmetric fantasy.
    function test_approve_writes_diagonal_not_sender_row() public {
        address sp = address(0x5AFE);
        vm.prank(FUNDED);
        assertTrue(token.approve(sp, 42), "approve returns true");
        assertEq(token.allowance(sp, sp), 42, "fallbackGuard identity: row == sp diagonal");
        assertEq(token.allowance(FUNDED, sp), 0, "sender row untouched - NOT ERC20-like");
        assertEq(token.allowance(sp, FUNDED), 0, "no mirrored write either");
    }
}
