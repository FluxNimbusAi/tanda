// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

import {TandaBillV2, IERC20} from "../contracts/TandaBillV2.sol";
import {TandaBillFactory} from "../contracts/TandaBillFactory.sol";
import {Test} from "forge-std/Test.sol";

/// @notice XIXI-DESIGN-02 goldens (decision_q1 proof + decision_q2 patch verification),
///         verdict sha256 101c14f5a36445e8f10c9bc571b4ca0a140e85922c8e949a8a63c7c0396ffbf7,
///         Flux ratification 2026-11-21. Cards: t_33f03aaf (patch), t_f8ade5da (proof).
///         Factory-lineage setup per lane law (createBill via factory, never raw initialize).

/// @notice Q1 golden: reentering token - transfer() calls bill.claimSettlement again.
contract ReentrantToken {
    mapping(address => uint256) public balanceOf;
    mapping(address => mapping(address => uint256)) public allowance;
    bool public entered;
    bool public innerClaimReverted;
    address public bill;
    function setBill(address b) external { bill = b; }
    function mint(address to, uint256 a) external { balanceOf[to] += a; }
    function approve(address sp, uint256 a) external returns (bool) { allowance[msg.sender][sp] = a; return true; }
    function transferFrom(address f, address t, uint256 a) external returns (bool) {
        require(balanceOf[f] >= a && allowance[f][msg.sender] >= a, "no");
        balanceOf[f] -= a; balanceOf[t] += a; allowance[f][msg.sender] -= a; return true;
    }
    function transfer(address to, uint256 a) external returns (bool) {
        if (!entered) {
            entered = true;                    // first real payout only
                (bool ok2,) = bill.call(abi.encodeWithSignature("claimSettlement(uint256)", 0));
            innerClaimReverted = !ok2;
            entered = false;
        }
        require(balanceOf[msg.sender] >= a, "insufficient");
        balanceOf[msg.sender] -= a; balanceOf[to] += a; return true;
    }
}

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

contract CeiReentrancyGoldenTest is Base3 {
    function setUp() public {
        factory = new TandaBillFactory(address(new TandaBillV2()));
    }

    // Q1 PROOF golden (t_f8ade5da re-scope): claimedMask |= bit lands BEFORE the external
    // transfer (L396-398 current main). A token that re-enters claimSettlement mid-transfer
    // must see the reentrant call REVERT (PayoutAlreadyClaimed), the outer claim must
    // COMPLETE, and the seat must be paid EXACTLY ONCE.
    function test_reentrant_claim_inner_reverts_outer_completes_single_pay() public {
        ReentrantToken t = new ReentrantToken();
        t.mint(owner, 300e6);
        TandaBillV2 bill = _deployWith(address(t));
        t.setBill(address(bill));
        vm.prank(owner); t.approve(address(bill), 300e6);
        _expenseFundInit(bill, address(t), 300e6, 0);
        _confirmAll(bill);
        vm.warp(block.timestamp + 2 hours);
        _execute(bill);

        uint256 before = t.balanceOf(alice);
        vm.prank(alice); bill.claimSettlement(0);   // token hook reenters claimSettlement(0)

        assertTrue(t.innerClaimReverted(), "inner reentrant claim must have reverted (CEI mask-first)");
        assertEq(t.balanceOf(alice) - before, 100e6, "seat paid exactly once");
        assertTrue(_claimed(bill, 1));
    }

    function _claimed(TandaBillV2 bill, uint256 seat) internal view returns (bool) {
        (uint256 t0, uint64 t1, uint64 t2, uint256 t3, uint256 t4, uint256 claimedMask, uint64 t5, bool t6) = bill.settlements(0);
        t0;t1;t2;t3;t4;t5;t6; return (claimedMask & (1 << seat)) != 0;
    }
}
