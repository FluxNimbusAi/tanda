// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

import {IERC20} from "../contracts/TandaBillV2.sol";
import {FastTandaBillV2} from "../contracts/FastTandaBillV2.sol";
import {TandaBillFactory} from "../contracts/TandaBillFactory.sol";
import {SafeERC20Minimal} from "../contracts/SafeERC20Minimal.sol";
import {Test} from "forge-std/Test.sol";

/// @notice Card t_15724978: port of the XIXI-DESIGN-02 goldens (test/XixiDesign02Q2Stranding.t.sol)
///         to the Fast twin. Pins the two-sided law at FastTandaBillV2:
///           1. FUNDING follows the canonical V2 twin (HIGH-2): bare require(token.transferFrom)
///              on a no-return-data token DoSes funding via ABI decode; SafeERC20Funding.safeTransferFrom
///              accepts empty returndata and surfaces explicit-false as typed SafeERC20Failed.
///           2. PAYOUT keeps the inline strict-bool library (shape_b law, Flux adjudication
///              XIXI-CARD-4): empty returndata at settlement is NOT success — executeSettlement
///              must revert, keeping the claim retryable instead of silently stranding value.
///         Divergence vs the V2 golden: Fast auto-pays inside executeSettlement (no claimSettlement),
///         so the NoReturnToken golden terminates at the payout guard, not at a claim delta.
///         Factory-lineage setup per lane law (createBill via factory, never raw initialize).

// ─── adversarial tokens (mirrors of the Q2 goldens, self-contained) ────────

/// @notice USDT-class: transfer/transferFrom return NO data.
contract NoReturnTokenF {
    mapping(address => uint256) public balanceOf;
    mapping(address => mapping(address => uint256)) public allowance;
    function mint(address to, uint256 a) external { balanceOf[to] += a; }
    function approve(address sp, uint256 a) external { allowance[msg.sender][sp] = a; }
    function transfer(address to, uint256 a) external {
        require(balanceOf[msg.sender] >= a, "insufficient");
        balanceOf[msg.sender] -= a; balanceOf[to] += a;
    }
    function transferFrom(address f, address t, uint256 a) external {
        require(balanceOf[f] >= a && allowance[f][msg.sender] >= a, "no");
        balanceOf[f] -= a; balanceOf[t] += a; allowance[f][msg.sender] -= a;
    }
}

/// @notice Non-standard: explicit false return with state UNCHANGED.
contract FalseReturnTokenF {
    mapping(address => uint256) public balanceOf;
    mapping(address => mapping(address => uint256)) public allowance;
    function mint(address to, uint256 a) external { balanceOf[to] += a; }
    function approve(address sp, uint256 a) external returns (bool) { allowance[msg.sender][sp] = a; return true; }
    function transfer(address, uint256) external returns (bool) { return false; }
    function transferFrom(address, address, uint256) external returns (bool) { return false; }
}

contract FastTwinStrandingTest is Test {
    TandaBillFactory factory;
    address owner = address(0xA11CE);
    address alice = address(0xB0B);
    address bob   = address(0xBEEF);

    function setUp() public {
        factory = new TandaBillFactory(address(new FastTandaBillV2()));
    }

    function _seats() internal view returns (address[] memory s) {
        s = new address[](3); s[0] = owner; s[1] = alice; s[2] = bob;
    }

    function _deployWith(address tok) internal returns (FastTandaBillV2 bill) {
        vm.prank(owner);
        bill = FastTandaBillV2(payable(factory.createBill(IERC20(tok), _seats())));
    }

    /// @notice Golden F-1 (HIGH-2 closed at the twin): a no-return-data token must FUND
    ///         the escrow. Pre-fix bare require(token.transferFrom) reverted the whole
    ///         call via ABI decode failure — funding permanently DoSed for USDT-class tokens.
    function test_fund_escrow_no_return_token_ok() public {
        NoReturnTokenF t = new NoReturnTokenF();
        t.mint(owner, 300e6);
        FastTandaBillV2 bill = _deployWith(address(t));
        vm.startPrank(owner);
        t.approve(address(bill), 300e6);
        bill.addExpense(300e6);
        bill.fundEscrow(300e6);
        vm.stopPrank();
        assertEq(bill.escrowBalance(), 300e6, "HIGH-2 twin closure: no-return pull must credit escrow");
        assertEq(t.balanceOf(address(bill)), 300e6);
    }

    /// @notice Golden F-2 (strict-bool guard fires): explicit-false return surfaces as the
    ///         typed SafeERC20Failed(token, ret) revert — same shape as the V2 golden
    ///         test_false_return_token_reverts_typed, proving twin selector-level parity.
    function test_fund_escrow_false_return_reverts_typed() public {
        FalseReturnTokenF t = new FalseReturnTokenF();
        t.mint(owner, 300e6);
        FastTandaBillV2 bill = _deployWith(address(t));
        vm.startPrank(owner);
        bill.addExpense(300e6);
        t.approve(address(bill), 300e6);
        vm.expectRevert(abi.encodeWithSelector(
            SafeERC20Minimal.SafeERC20Failed.selector, address(t), abi.encode(false)));
        bill.fundEscrow(300e6);
        vm.stopPrank();
    }

    /// @notice Golden F-3 (shape_b payout law holds on Fast): the SAME no-return token that
    ///         funds successfully MUST be rejected at executeSettlement by the inline
    ///         strict-bool library — the funding relaxation must not leak into payout sites.
    ///         This pins the intentional Fast/V2 divergence documented in the file header.
    function test_payout_strict_bool_guard_holds_on_fast() public {
        NoReturnTokenF t = new NoReturnTokenF();
        t.mint(owner, 300e6);
        FastTandaBillV2 bill = _deployWith(address(t));

        vm.startPrank(owner);
        t.approve(address(bill), 300e6);
        bill.addExpense(300e6);
        bill.fundEscrow(300e6);
        bill.initiateSettlement();
        vm.stopPrank();

        vm.prank(owner); bill.confirmSettlement(0);
        vm.prank(alice); bill.confirmSettlement(0);
        vm.prank(bob);   bill.confirmSettlement(0);
        vm.warp(block.timestamp + 61); // SETTLEMENT_WINDOW = 60s

        vm.expectRevert("SafeERC20: strict-bool transfer required");
        bill.executeSettlement(0);
    }
}
