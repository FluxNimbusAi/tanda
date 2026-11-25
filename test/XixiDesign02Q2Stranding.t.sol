// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

import {TandaBillV2, IERC20} from "../contracts/TandaBillV2.sol";
import {SafeERC20Minimal} from "../contracts/SafeERC20Minimal.sol";
import {TandaBillFactory} from "../contracts/TandaBillFactory.sol";
import {Test} from "forge-std/Test.sol";

/// @notice XIXI-DESIGN-02 goldens (decision_q1 proof + decision_q2 patch verification),
///         verdict sha256 101c14f5a36445e8f10c9bc571b4ca0a140e85922c8e949a8a63c7c0396ffbf7,
///         Flux ratification 2026-11-21. Cards: t_33f03aaf (patch), t_f8ade5da (proof).
///         Factory-lineage setup per lane law (createBill via factory, never raw initialize).

// ─── adversarial tokens ────────────────────────────────────────────────

/// @notice USDT-class: transfer/transferFrom return NO data.
contract NoReturnToken {
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
contract FalseReturnToken {
    mapping(address => uint256) public balanceOf;
    mapping(address => mapping(address => uint256)) public allowance;
    function mint(address to, uint256 a) external { balanceOf[to] += a; }
    function approve(address sp, uint256 a) external returns (bool) { allowance[msg.sender][sp] = a; return true; }
    function transfer(address, uint256) external returns (bool) { return false; }
    function transferFrom(address, address, uint256) external returns (bool) { return false; }
}

/// @notice Fee-on-transfer: returns true, delivers less (1% burn). Accepted-with-note class.
contract FeeToken {
    mapping(address => uint256) public balanceOf;
    mapping(address => mapping(address => uint256)) public allowance;
    function mint(address to, uint256 a) external { balanceOf[to] += a; }
    function approve(address sp, uint256 a) external returns (bool) { allowance[msg.sender][sp] = a; return true; }
    function _move(address f, address t, uint256 a) internal {
        uint256 fee = a / 100;
        balanceOf[f] -= a; balanceOf[t] += a - fee; // 1% vanishes
    }
    function transfer(address to, uint256 a) external returns (bool) { _move(msg.sender, to, a); return true; }
    function transferFrom(address f, address t, uint256 a) external returns (bool) { _move(f, t, a); return true; }
}

/// @notice Reentrancy golden lives in XixiDesign02CeiGolden.t.sol:14-37 (executed at :84, assert
///         innerClaimReverted). The byte-identical local duplicate was removed ENGINE-27:
///         single adversarial-mock locus, no drift. Dead NoReturnToken.transfer revert arm
///         (ln 23 branch) is harness-unreachable: bill payout always has escrow >= amount, and
///         the mock has no burn path - pinned dead-defense, per 26A language.

abstract contract Base3 is Test {
    TandaBillFactory factory;
    address owner = address(0xA11CE);
    address alice = address(0xB0B);
    address bob   = address(0xBEEF);

    function _seats() internal view returns (address[] memory s) {
        s = new address[](3); s[0] = owner; s[1] = alice; s[2] = bob;
    }

    function _deployWith(address tok) internal returns (TandaBillV2 bill) {
        vm.prank(owner);
        bill = TandaBillV2(payable(factory.createBill(IERC20(tok), _seats())));
    }

    function _expenseFundInit(TandaBillV2 bill, address tok, uint256 amt, uint256 balMint) internal {
        // tok must already hold balance for owner with allowance path exercised per test
        vm.startPrank(owner);
        bill.addExpense(amt);
        bill.fundEscrow(amt);
        bill.initiateSettlement();
        vm.stopPrank();
    }

    function _confirmAll(TandaBillV2 bill) internal {
        _confirmAs(owner, bill); _confirmAs(alice, bill); _confirmAs(bob, bill);
    }
    function _confirmAs(address who, TandaBillV2 bill) internal {
        vm.prank(who); bill.confirmSettlement(0);
    }
    function _execute(TandaBillV2 bill) internal {
        vm.prank(owner); bill.executeSettlement(0);
    }
}


contract SafeERC20StrandingTest is Base3 {
    function setUp() public {
        factory = new TandaBillFactory(address(new TandaBillV2()));
    }

    function test_no_return_token_funds_and_claims() public {
        NoReturnToken t = new NoReturnToken();
        t.mint(owner, 300e6);
        TandaBillV2 bill = _deployWith(address(t));
        vm.prank(owner); t.approve(address(bill), 300e6);
        _expenseFundInit(bill, address(t), 300e6, 0);
        _confirmAll(bill);
        vm.warp(block.timestamp + 2 hours);
        _execute(bill);
        uint256 before = t.balanceOf(alice);
        vm.prank(alice); bill.claimSettlement(0);
        assertEq(t.balanceOf(alice) - before, 100e6);
        assertTrue(_claimed(bill, 1));
    }

    function test_false_return_token_reverts_typed() public {
        FalseReturnToken t = new FalseReturnToken();
        t.mint(owner, 300e6);
        TandaBillV2 bill = _deployWith(address(t));
        vm.startPrank(owner);
        bill.addExpense(300e6);
        t.approve(address(bill), 300e6);
        vm.expectRevert(abi.encodeWithSelector(SafeERC20Minimal.SafeERC20Failed.selector, address(t), abi.encode(false)));
        bill.fundEscrow(300e6);
        vm.stopPrank();
    }

    function test_fee_on_transfer_claims_complete_documented_shortfall() public {
        FeeToken t = new FeeToken();
        t.mint(owner, 300e6);
        TandaBillV2 bill = _deployWith(address(t));
        vm.prank(owner); t.approve(address(bill), 300e6);
        _expenseFundInit(bill, address(t), 300e6, 0);
        _confirmAll(bill);
        vm.warp(block.timestamp + 2 hours);
        _execute(bill);
        uint256 before = t.balanceOf(alice);
        vm.prank(alice); bill.claimSettlement(0);
        assertEq(t.balanceOf(alice) - before, 99e6);
    }

    function test_fund_escrow_reverting_token_surfaces_typed_golden() public {
        // ENGINE-27: revert-bubble class - token reverts INSIDE the low-level call.
        // SafeERC20Minimal must surface it as SafeERC20Failed(token, Error("no") data),
        // never as success. Prior goldens proved empty-ret success + explicit-false only.
        NoReturnToken t = new NoReturnToken();
        t.mint(owner, 300e6);
        TandaBillV2 bill = _deployWith(address(t));
        vm.startPrank(owner);
        bill.addExpense(300e6);
        vm.expectRevert(abi.encodeWithSelector(
            SafeERC20Minimal.SafeERC20Failed.selector,
            address(t),
            abi.encodeWithSelector(bytes4(0x08c379a0), "no")
        ));
        bill.fundEscrow(300e6);
        vm.stopPrank();
    }

    function _claimed(TandaBillV2 bill, uint256 seat) internal view returns (bool) {
        (uint256 t0, uint64 t1, uint64 t2, uint256 t3, uint256 t4, uint256 claimedMask, uint64 t5, bool t6) = bill.settlements(0);
        t0;t1;t2;t3;t4;t5;t6;
        return (claimedMask & (1 << seat)) != 0;
    }
}
