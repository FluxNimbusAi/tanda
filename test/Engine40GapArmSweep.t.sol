// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

import {OobMockToken} from "./ViewOobGolden34.t.sol";
import {Test} from "forge-std/Test.sol";

/// @title Engine40GapArmSweep [t_afe7dcc1]
/// @notice ENGINE-40 (family B1) - mock-honesty arm sweep for OobMockToken, the ERC20
///         mock ViewOobGolden34 (ENGINE-34/35 bounds-guard golden) rides on. The fresh
///         gaps census at main tip a279adebc (proofs/ENGINE40_GAPS_CENSUS_a279adebc.json,
///         byte-shape identical to proofs/gaps_after_e37.json - independent-run equality)
///         pinned 13 open paths; 10 of them are THIS mock: transfer never called at all
///         (function/line + BOTH require arms) and transferFrom missing both require
///         FAIL arms (L24 balance, L25 allowance). A golden whose token mock has
///         unverified revert arms is a silent false-pass risk: ViewOobGolden34's
///         fund/execute legs calibrate escrow expectations on this mock's behavior -
///         if its "insufficient"/"allowance" arms were wrong, those goldens would be
///         fiction. This suite pins the mock's real semantics by direct real-state
///         calls: arms AND ledger deltas AND return values.
/// @dev  ENGINE-37 GateMockToken sweep recipe (test/Engine37GateMockArmSweep.t.sol),
///         audited against OobMockToken source (ViewOobGolden34.t.sol L12-36):
///           * separate-requires class: transferFrom L24 (balance) and L25 (allowance)
///             are distinct require statements with distinct revert strings, so the two
///             FAIL arms are distinguishable by reason string alone - no combined-&&
///             ordering constraint, but the law still holds:
///           * revert victims NEVER hold balance: victim (0xDEAD) is never minted to;
///             success legs self-route FUNDED -> FUNDED-aware counterpart (recipient is
///             pre-funded so it never doubles as a victim);
///           * every test gets a fresh setUp (contract re-deployed per function), so
///             cross-function poisoning is structurally impossible;
///           * no vm.mockCall anywhere; exact ledger deltas asserted; allowance decrements
///             exactly once per unit transferred;
///           * no branches (if/require/&&) in THIS contract: the sweep file must itself
///             stay gap-free in the after-census (forge coverage keys gaps per file,
///             test files included - precedent: 295-test suite zero test-file gaps).
///         The 3 remaining census items (script/TandaDeploy L45 FAIL, L47 FAIL;
///         script/TandaDeployV2 L28 FAIL) are DEAD DEFENSES, unreachable by
///         construction - re-verified against source this tick: TandaBill.token is
///         `IERC20 public immutable` (contracts/TandaBill.sol L47) set from the ctor arg
///         the require compares against (L96); activeSeatCount() is 0 by definition on a
///         bill that run() just deployed without adding seats; factory.implementation is
///         `address public immutable` (contracts/TandaBillFactory.sol L13) set from the
///         impl deployed on the line above. Pinned as adjudicated-residual in
///         proofs/ENGINE40_GAPS_AFTER_e40.json - NOT closed by test, closed by proof-of-
///         unreachability. Do not card these.
contract Engine40GapArmSweepTest is Test {
    OobMockToken token;

    address funded = address(0xF0DED);   // transfer/transferFrom source, minted 100
    address recipient = address(0x2E79); // pre-funded counterpart: success legs stay FUNDED->FUNDED
    address victim = address(0xDEAD);    // revert victim: NEVER holds balance

    function setUp() public {
        token = new OobMockToken();
        token.mint(funded, 100 ether);
        token.mint(recipient, 1 ether);
    }

    // ─── transfer: FAIL arm of L17 require (never called before this sweep) ───
    function test_e1_transfer_insufficient_reverts() public {
        vm.prank(victim); // balance 0 < 1
        vm.expectRevert(bytes("insufficient"));
        token.transfer(funded, 1);
        assertEq(token.balanceOf(victim), 0);
        assertEq(token.balanceOf(funded), 100 ether);
    }

    // ─── transfer: TRUE arm + full body L16-L21 + return value + ledger ───
    function test_e2_transfer_success_ledger_exact() public {
        uint f0 = token.balanceOf(funded);
        uint r0 = token.balanceOf(recipient);
        vm.prank(funded);
        assertTrue(token.transfer(recipient, 40 ether));
        assertEq(token.balanceOf(funded), f0 - 40 ether);
        assertEq(token.balanceOf(recipient), r0 + 40 ether);
        assertEq(token.balanceOf(victim), 0);
    }

    // ─── transferFrom: L24 FAIL arm (balance) ───
    function test_e3_transferFrom_insufficient_balance_reverts() public {
        vm.prank(recipient); // spender holds funds; FROM is the zero-holder
        vm.expectRevert(bytes("insufficient"));
        token.transferFrom(victim, recipient, 1);
        assertEq(token.balanceOf(victim), 0);
        assertEq(token.balanceOf(recipient), 1 ether);
    }

    // ─── transferFrom: L25 FAIL arm (allowance) - balance OK, zero grant ───
    function test_e4_transferFrom_allowance_reverts() public {
        vm.prank(funded);
        assertTrue(token.approve(recipient, 0)); // explicit zero grant
        vm.prank(recipient);
        vm.expectRevert(bytes("allowance"));
        token.transferFrom(funded, victim, 5 ether);
        assertEq(token.balanceOf(funded), 100 ether); // victim-call revert left no scar
        assertEq(token.balanceOf(victim), 0);
    }

    // ─── transferFrom: both TRUE arms + exact single decrement ───
    function test_e5_transferFrom_success_ledger_exact() public {
        vm.prank(funded);
        token.approve(recipient, 30 ether);
        vm.prank(recipient);
        assertTrue(token.transferFrom(funded, recipient, 30 ether));
        assertEq(token.balanceOf(funded), 70 ether);
        assertEq(token.balanceOf(recipient), 31 ether); // 1 pre-mint + 30
        assertEq(token.allowance(funded, recipient), 0); // decremented exactly once
    }
}
