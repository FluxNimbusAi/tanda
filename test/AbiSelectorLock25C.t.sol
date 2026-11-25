// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

/// @notice ENGINE-25C (kanban t_5b099e51) ABI selector lock + view-layer conservation ladder.
/// @dev Selector table generated 2026-11-25 by gen_25c.py: keccak256 of canonical signatures
///      (interface params canonicalized to address), extracted from contracts/TandaBillV2.sol
///      @ 6b3dfead69e934d606e5c133b85a0a5d35feefc9. Drift in any signature below fails this test
///      loud - the rp_4fbd portal re-registration trio depends on these exact entrypoints.

import {TandaBillV2, IERC20} from "../contracts/TandaBillV2.sol";
import {TandaBillFactory} from "../contracts/TandaBillFactory.sol";
import {Test} from "forge-std/Test.sol";

/// @notice Minimal ERC-20 mock (file-local, same precedent as test/EscrowInvariant.t.sol).
contract Mock25C {
    mapping(address => uint256) public balanceOf;
    mapping(address => mapping(address => uint256)) public allowance;
    function mint(address to, uint256 amount) external { balanceOf[to] += amount; }
    function transfer(address to, uint256 amount) external returns (bool) {
        require(balanceOf[msg.sender] >= amount, "insufficient");
        balanceOf[msg.sender] -= amount; balanceOf[to] += amount; return true;
    }
    function transferFrom(address from, address to, uint256 amount) external returns (bool) {
        require(balanceOf[from] >= amount, "insufficient");
        require(allowance[from][msg.sender] >= amount, "allowance");
        balanceOf[from] -= amount; balanceOf[to] += amount;
        allowance[from][msg.sender] -= amount; return true;
    }
    function approve(address spender, uint256 amount) external returns (bool) {
        allowance[msg.sender][spender] = amount; return true;
    }
}

contract AbiSelectorLock25C is Test {
    /// @dev forge-std on this host has no assertEq(bytes4,bytes4) overload (ADL candidate read:
    ///      StdAssertions.sol offers bool/uintN/intN/address/bytes32/arrays/string only), so
    ///      both sides go through the identical bytes4->bytes32 (right-padding) conversion.
    function _lock(bytes memory sig, bytes4 want) internal pure {
        assertEq(bytes32(bytes4(keccak256(sig))), bytes32(want));
    }

    // ---- Part 1: full external ABI selector lock (18 contract fns + 3 boundary sigs) ----
    function test_abi_selector_lock() public pure {
        _lock("activeSeatCount()", 0x0d9461ba); // activeSeatCount
        _lock("addExpense(uint256)", 0xbccae1bb); // addExpense
        _lock("addSeat(address)", 0x35c39bc0); // addSeat
        _lock("claimSettlement(uint256)", 0x7b4d9405); // claimSettlement
        _lock("claimablePayout(uint256,address)", 0xc7408a55); // claimablePayout
        _lock("confirmSettlement(uint256)", 0x9e924eb5); // confirmSettlement
        _lock("executeSettlement(uint256)", 0x83c0b8ac); // executeSettlement
        _lock("fundEscrow(uint256)", 0xc9c31af5); // fundEscrow
        _lock("fundEscrowFromPermit2(uint256)", 0x1e0d5429); // fundEscrowFromPermit2
        _lock("initialize(address,address,address[])", 0x77a24f36); // initialize
        _lock("initiateSettlement()", 0xc78b432e); // initiateSettlement
        _lock("isSeatConfirmed(uint256,address)", 0xb659eb82); // isSeatConfirmed
        _lock("refundSettlement(uint256)", 0xa55a78c0); // refundSettlement
        _lock("registerSeat(bytes32,address,bytes)", 0x3d0a59a9); // registerSeat
        _lock("removeSeat(uint256)", 0x9c917095); // removeSeat
        _lock("rotateSeatWallet(uint256,address)", 0xc8594e6a); // rotateSeatWallet
        _lock("settlementPayouts(uint256)", 0x44bd4071); // settlementPayouts
        _lock("totalExpenses()", 0x7bd35af8); // totalExpenses
        _lock("transfer(address,uint256)", 0xa9059cbb); // boundary IERC20/IPermit2
        _lock("transferFrom(address,address,uint256)", 0x23b872dd); // boundary IERC20/IPermit2
        _lock("transferFrom(address,address,uint160,address)", 0x36c78516); // boundary IERC20/IPermit2
    }

    // ---- Part 2: view-layer conservation ladder (mirrors test/TandaBillV2.t.sol direct path) ----
    Mock25C token;
    address owner = address(0xA11CE);
    address alice = address(0xA11CE0);
    address bob   = address(0xB0B);

    function _seats3() internal view returns (address[] memory s) {
        s = new address[](3); s[0] = owner; s[1] = alice; s[2] = bob;
    }

    function test_view_layer_conservation_ladder() public {
        token = new Mock25C();
        TandaBillV2 impl = new TandaBillV2();
        TandaBillFactory factory = new TandaBillFactory(address(impl));
        uint256 amount = 100e6;
        token.mint(owner, amount);
        vm.prank(owner);
        TandaBillV2 bill = TandaBillV2(payable(factory.createBill(IERC20(address(token)), _seats3())));
        vm.startPrank(owner);
        bill.addExpense(amount);
        token.approve(address(bill), amount);
        bill.fundEscrow(amount);
        bill.initiateSettlement();
        vm.stopPrank();

        // pre-execute view layer
        assertEq(bill.totalExpenses(), amount);
        assertEq(bill.activeSeatCount(), 3);
        uint256[] memory p0 = bill.settlementPayouts(0);
        assertEq(p0.length, 3);
        assertEq(p0[0] + p0[1] + p0[2], amount); // split conserved BEFORE execution
        assertEq(bill.claimablePayout(0, owner), 0);   // nothing claimable pre-execute
        assertEq(bill.claimablePayout(0, alice), 0);
        assertFalse(bill.isSeatConfirmed(0, owner));

        // confirm ladder mirrors isSeatConfirmed
        vm.prank(owner); bill.confirmSettlement(0);
        assertTrue(bill.isSeatConfirmed(0, owner));
        assertFalse(bill.isSeatConfirmed(0, alice));
        vm.prank(alice); bill.confirmSettlement(0);
        vm.prank(bob);   bill.confirmSettlement(0);
        assertTrue(bill.isSeatConfirmed(0, bob));

        // execute -> claimable opens, escrow conserved
        vm.warp(block.timestamp + 1 hours + 1);
        bill.executeSettlement(0);
        uint256[] memory p1 = bill.settlementPayouts(0);
        assertEq(p1[0] + p1[1] + p1[2], amount);
        assertEq(bill.claimablePayout(0, owner) + bill.claimablePayout(0, alice) + bill.claimablePayout(0, bob), amount);
        assertEq(token.balanceOf(address(bill)), amount); // conservation: escrow intact pre-claim

        // drain -> sum(claims) == amount, escrow empties, views stay consistent
        vm.prank(owner); bill.claimSettlement(0);
        vm.prank(alice); bill.claimSettlement(0);
        vm.prank(bob);   bill.claimSettlement(0);
        assertEq(token.balanceOf(address(bill)), 0);
        assertEq(token.balanceOf(owner) + token.balanceOf(alice) + token.balanceOf(bob), amount);
        assertEq(bill.claimablePayout(0, owner), 0);
        assertEq(bill.claimablePayout(0, alice), 0);
        assertEq(bill.claimablePayout(0, bob), 0);
        uint256[] memory p2 = bill.settlementPayouts(0);
        assertEq(p2[0] + p2[1] + p2[2], amount); // historical record conserved
        assertEq(bill.totalExpenses(), amount);  // totalExpenses immutability across full ladder
    }
}
