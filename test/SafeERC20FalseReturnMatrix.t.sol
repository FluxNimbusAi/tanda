// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

import {TandaBillV2, IERC20} from "../contracts/TandaBillV2.sol";
import {SafeERC20Minimal} from "../contracts/SafeERC20Minimal.sol";
import {TandaBillFactory} from "../contracts/TandaBillFactory.sol";
import {Test} from "forge-std/Test.sol";

/// @notice Card t_669aad01 matrix: SafeERC20Minimal FALSE-RETURN class (token RETURNS
///         false, does NOT revert) proven at all three V2 consumer legs:
///           LEG-1 fundEscrow          L245 safeTransferFrom
///           LEG-2 claimSettlement     L402 safeTransfer (payout)
///           LEG-3 refundSettlement    L419 safeTransfer (refund sweep)
///         Goldens = exact revert data abi.encodeWithSelector(SafeERC20Failed.selector,
///         token, abi.encode(false)) — selector + reason payload, per library L25/L32/L41.
///         Sibling XixiDesign02Q2Stranding.t.sol covers only the funding leg with an
///         always-false token; L402/L419 are UNREACHABLE with it (escrow could never be
///         funded), hence the flippable hostile token here.

/// @notice Standard ERC-20 until flip(true); then transfer/transferFrom RETURN false
///         with state UNCHANGED (no revert) — the exact non-reverting false class.
contract FlipFalseToken {
    string public name = "Flip mUSDC";
    uint8 public decimals = 6;
    bool public fail;
    mapping(address => uint256) public balanceOf;
    mapping(address => mapping(address => uint256)) public allowance;

    function flip(bool v) external { fail = v; }
    function mint(address to, uint256 a) external { balanceOf[to] += a; }
    function approve(address sp, uint256 a) external returns (bool) { allowance[msg.sender][sp] = a; return true; }

    function transfer(address to, uint256 a) external returns (bool) {
        if (fail) return false;
        require(balanceOf[msg.sender] >= a, "insufficient");
        balanceOf[msg.sender] -= a; balanceOf[to] += a;
        return true;
    }

    function transferFrom(address f, address t, uint256 a) external returns (bool) {
        if (fail) return false;
        require(balanceOf[f] >= a && allowance[f][msg.sender] >= a, "no");
        balanceOf[f] -= a; balanceOf[t] += a; allowance[f][msg.sender] -= a;
        return true;
    }
}

/// @notice Direct internal-library probe: proves the golden shape at the library
///         surface itself, independent of any consumer leg.
contract SafeERC20Harness {
    function callSafeTransfer(address token, address to, uint256 amount) external {
        SafeERC20Minimal.safeTransfer(token, to, amount);
    }
    function callSafeTransferFrom(address token, address from, address to, uint256 amount) external {
        SafeERC20Minimal.safeTransferFrom(token, from, to, amount);
    }
}

contract SafeERC20FalseReturnMatrixTest is Test {
    TandaBillFactory factory;
    FlipFalseToken token;
    TandaBillV2 bill;
    SafeERC20Harness harness;

    address owner = address(0xA11CE);
    address alice = address(0xB0B);
    address bob   = address(0xBEEF);

    /// Golden revert data: SafeERC20Failed(address token, bytes reason) with
    /// reason = the token's raw 32-byte returndata abi.encode(false).
    bytes internal golden;

    function setUp() public {
        factory = new TandaBillFactory(address(new TandaBillV2()));
        token = new FlipFalseToken();
        harness = new SafeERC20Harness();
        golden = abi.encodeWithSelector(
            SafeERC20Minimal.SafeERC20Failed.selector, address(token), abi.encode(false)
        );
        vm.prank(owner);
        bill = TandaBillV2(payable(factory.createBill(IERC20(address(token)), _seats())));
        token.mint(owner, 300e6);
        vm.prank(owner);
        token.approve(address(bill), 300e6);
    }

    function _seats() internal view returns (address[] memory s) {
        s = new address[](3); s[0] = owner; s[1] = alice; s[2] = bob;
    }

    // Expense + fund + initiate while the token still behaves (fail=false).
    function _fundInit() internal {
        vm.startPrank(owner);
        bill.addExpense(300e6);
        bill.fundEscrow(300e6);
        bill.initiateSettlement();
        vm.stopPrank();
    }

    function _confirmExecute() internal {
        vm.prank(owner); bill.confirmSettlement(0);
        vm.prank(alice); bill.confirmSettlement(0);
        vm.prank(bob);   bill.confirmSettlement(0);
        vm.warp(block.timestamp + 2 hours); // SETTLEMENT_WINDOW = 1 hours
        vm.prank(owner); bill.executeSettlement(0);
    }

    // ── LEG-0: library surface itself, both functions, golden selector+reason ──

    function test_matrix_lib_safeTransfer_falseReturn_golden() public {
        token.flip(true);
        vm.expectRevert(golden);
        harness.callSafeTransfer(address(token), alice, 1e6);
    }

    function test_matrix_lib_safeTransferFrom_falseReturn_golden() public {
        token.flip(true);
        vm.expectRevert(golden);
        harness.callSafeTransferFrom(address(token), owner, alice, 1e6);
    }

    // ── LEG-1: V2 L245 fundEscrow -> safeTransferFrom ──

    function test_matrix_fundEscrow_L245_falseReturn_golden_and_untouched() public {
        token.flip(true);
        vm.startPrank(owner);
        bill.addExpense(300e6);
        vm.expectRevert(golden);
        bill.fundEscrow(300e6);
        vm.stopPrank();
        assertEq(bill.escrowBalance(), 0);        // L246 `escrowBalance += amount` never ran
        assertEq(token.balanceOf(owner), 300e6);  // false-return kept token state
        assertEq(token.balanceOf(address(bill)), 0);
    }

    // ── LEG-2: V2 L402 claimSettlement payout -> safeTransfer ──

    function test_matrix_payout_L402_falseReturn_golden_retryable() public {
        _fundInit();
        _confirmExecute();
        token.flip(true); // escrow funded+executed; token turns hostile at payout time
        uint256 billBal = token.balanceOf(address(bill));

        vm.prank(alice); // seatId 1 (owner=0, alice=1, bob=2)
        vm.expectRevert(golden);
        bill.claimSettlement(0);

        (,,,,, uint256 claimedMask,,) = bill.settlements(0);
        assertEq(claimedMask & (1 << 1), 0);      // CEI rollback: bit NOT left set
        assertEq(token.balanceOf(alice), 0);
        assertEq(token.balanceOf(address(bill)), billBal); // nothing left the bill

        // Retry path exists once the false-return clears (claim not consumed).
        token.flip(false);
        vm.prank(alice);
        bill.claimSettlement(0);
        (,,,,, claimedMask,,) = bill.settlements(0);
        assertEq(claimedMask & (1 << 1), 1 << 1);
        assertEq(token.balanceOf(alice), 100e6);  // 300e6 / 3 seats
    }

    // ── LEG-3: V2 L419 refundSettlement sweep -> safeTransfer ──

    function test_matrix_refund_L419_falseReturn_golden_retryable() public {
        _fundInit();                              // NO confirmations -> MAX_HOLD escape path
        vm.warp(block.timestamp + 73 hours);      // MAX_HOLD = 72 hours
        token.flip(true);
        uint256 billBal = token.balanceOf(address(bill));

        vm.prank(owner);
        vm.expectRevert(golden);
        bill.refundSettlement(0);

        (,,,,,, , bool refunded) = bill.settlements(0);
        assertFalse(refunded);                    // CEI rollback: L418 flag reverted with the sweep
        assertEq(token.balanceOf(owner), 0);
        assertEq(token.balanceOf(address(bill)), billBal);

        // Retry after the false-return clears.
        token.flip(false);
        vm.prank(owner);
        bill.refundSettlement(0);
        (,,,,,, , refunded) = bill.settlements(0);
        assertTrue(refunded);
        assertEq(token.balanceOf(owner), 300e6);
        assertEq(token.balanceOf(address(bill)), 0);
    }

    // ── CENSUS guard: TokenTransferFailed (V2 L131) is a DEAD ABI decl — zero revert
    //    sites in source; the live failed-transfer surface is SafeERC20Failed. The exact-
    //    data golden match above already excludes it; this pins selector inequality too. ──

    function test_census_tokenTransferFailed_not_the_live_surface() public {
        bytes4 dead = TandaBillV2.TokenTransferFailed.selector;
        bytes4 live = SafeERC20Minimal.SafeERC20Failed.selector;
        assertTrue(dead != live);
        token.flip(true);
        vm.prank(owner);
        bill.addExpense(300e6);
        vm.startPrank(owner);
        vm.expectRevert(golden); // exact bytes: dead selector (no args) can never match
        bill.fundEscrow(300e6);
        vm.stopPrank();
    }
}
