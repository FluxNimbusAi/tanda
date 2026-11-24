// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

import {TandaBillV2, IERC20} from "../contracts/TandaBillV2.sol";
import {FastTandaBillV2} from "../contracts/FastTandaBillV2.sol";
import {IERC20 as IFastERC20} from "../contracts/FastTandaBillV2.sol";
import {TandaBillFactory} from "../contracts/TandaBillFactory.sol";
import {Test} from "forge-std/Test.sol";

/// @notice BS-3.2 / #185 LATCH goldens: (1) addSeat participates in the roster freeze
///         (H-01 asymmetry closed), (2) the freeze is per-round — it lifts only when every
///         settlement is terminal AND fully drained (claim leg or refund leg), which is what
///         makes the bill a "recurring, non-terminal ritual" per README instead of a one-shot.
///         Factory-lineage + self-contained mock (golden-lane pattern, Ugly2SeatGateGolden).

contract LatchMockToken {
    string public name = "Mock USDC";
    string public symbol = "mUSDC";
    uint8 public decimals = 6;
    mapping(address => uint256) public balanceOf;
    mapping(address => mapping(address => uint256)) public allowance;
    function mint(address to, uint256 amount) external { balanceOf[to] += amount; }
    function transfer(address to, uint256 amount) external returns (bool) {
        require(balanceOf[msg.sender] >= amount, "insufficient");
        balanceOf[msg.sender] -= amount; balanceOf[to] += amount; return true;
    }
    function transferFrom(address f, address t, uint256 amount) external returns (bool) {
        require(balanceOf[f] >= amount && allowance[f][msg.sender] >= amount, "no");
        balanceOf[f] -= amount; balanceOf[t] += amount; allowance[f][msg.sender] -= amount;
        return true;
    }
    function approve(address sp, uint256 a) external returns (bool) {
        allowance[msg.sender][sp] = a; return true;
    }
}

contract SeatGateLatchGoldenTest is Test {
    TandaBillFactory factory;
    LatchMockToken token;
    address owner = address(0xA11CE);
    address alice = address(0xB0B);
    address bob   = address(0xBEEF);
    address carol = address(0xCA40);

    bytes32 constant NUL_C = bytes32(uint256(0xC33));

    function setUp() public {
        factory = new TandaBillFactory(address(new TandaBillV2()));
        token = new LatchMockToken();
    }

    function _bill2() internal returns (TandaBillV2 bill) {
        address[] memory s = new address[](2);
        s[0] = owner; s[1] = alice;
        vm.prank(owner);
        bill = TandaBillV2(payable(factory.createBill(IERC20(address(token)), s)));
    }

    /// @dev owner fronts, funds, initiates settlement on current active roster.
    function _initiate(TandaBillV2 bill, uint256 amount) internal {
        vm.startPrank(owner);
        bill.addExpense(amount);
        token.mint(owner, amount);
        token.approve(address(bill), amount);
        bill.fundEscrow(amount);
        bill.initiateSettlement();
        vm.stopPrank();
    }

    /// @dev confirm+execute (window warp) for settlement id; does NOT claim.
    function _confirmAndExecute(TandaBillV2 bill, uint256 sid) internal {
        vm.prank(owner); bill.confirmSettlement(sid);
        vm.prank(alice); bill.confirmSettlement(sid);
        vm.warp(block.timestamp + bill.SETTLEMENT_WINDOW());
        bill.executeSettlement(sid);
    }

    // -- H1: addSeat is frozen while a settlement is pending ------------------
    function test_h1_addSeat_frozen_after_initiate() public {
        TandaBillV2 bill = _bill2();
        _initiate(bill, 2_000_000);
        vm.expectRevert(TandaBillV2.SettlementInitiatedAlready.selector);
        vm.prank(owner);
        bill.addSeat(bob);
        // ...and the already-guarded legs (regression symmetry):
        vm.expectRevert(TandaBillV2.SettlementInitiatedAlready.selector);
        vm.prank(owner);
        bill.removeSeat(1);
    }

    // -- H2: partial drain keeps freeze; full drain reopens roster -----------
    function test_h2_drain_reopens_roster() public {
        TandaBillV2 bill = _bill2();
        _initiate(bill, 2_000_000);
        _confirmAndExecute(bill, 0);

        vm.prank(owner); bill.claimSettlement(0);
        assertTrue(bill.settlementInitiated(), "alice share unclaimed -> still frozen");
        vm.expectRevert(TandaBillV2.SettlementInitiatedAlready.selector);
        vm.prank(owner); bill.addSeat(bob);

        vm.prank(alice); bill.claimSettlement(0);
        assertFalse(bill.settlementInitiated(), "fully drained -> reopened");

        vm.prank(owner); bill.addSeat(bob);          // ungated again
        vm.prank(owner); bill.registerSeat(NUL_C, carol, abi.encodePacked(vm.toString(address(bill)), ":", vm.toString(carol)));
        assertEq(bill.activeSeatCount(), 4);
    }

    // -- H3: multi-round ritual — round 2 settles the NEW roster -------------
    function test_h3_second_round_pays_new_roster() public {
        TandaBillV2 bill = _bill2();
        _initiate(bill, 2_000_000);
        _confirmAndExecute(bill, 0);
        vm.prank(owner); bill.claimSettlement(0);
        vm.prank(alice); bill.claimSettlement(0);

        vm.prank(owner); bill.addSeat(bob);           // reopen verified path
        _initiate(bill, 3_000_000);                    // round 2 over owner+alice+bob
        uint256[] memory p = bill.settlementPayouts(1);
        assertEq(p.length, 3);
        assertEq(p[0], 1_000_000);                     // equal thirds, dense vector
        assertEq(p[2], 1_000_000);
    }

    // -- H4: refund leg also lifts the freeze --------------------------------
    function test_h4_refund_reopens_roster() public {
        TandaBillV2 bill = _bill2();
        _initiate(bill, 2_000_000);
        vm.prank(owner); bill.confirmSettlement(0);   // alice never confirms
        (,, uint256 inAt,,,,,) = bill.settlements(0);
        vm.warp(inAt + bill.MAX_HOLD());
        vm.prank(owner); bill.refundSettlement(0);
        assertFalse(bill.settlementInitiated(), "refund -> drained -> reopened");
        vm.prank(owner); bill.addSeat(bob);           // works again
    }

    // -- H5: happy pre-settlement path unchanged (no regression) -------------
    function test_h5_addSeat_ok_before_any_initiate() public {
        TandaBillV2 bill = _bill2();
        vm.prank(owner); bill.addSeat(bob);
        assertEq(bill.activeSeatCount(), 3);
    }

    // -- H6: fast-twin parity for the addSeat freeze --------------------------
    function test_h6_fasttwin_addSeat_frozen() public {
        FastTandaBillV2 fast = new FastTandaBillV2();
        address[] memory s = new address[](1);
        s[0] = owner;
        fast.initialize(IFastERC20(address(token)), owner, s);
        vm.startPrank(owner);
        token.mint(owner, 100);
        token.approve(address(fast), 100);
        fast.addExpense(100);
        fast.fundEscrow(100);
        fast.initiateSettlement();
        vm.stopPrank();
        vm.expectRevert(FastTandaBillV2.SettlementInitiatedAlready.selector);
        vm.prank(owner);
        fast.addSeat(alice);
    }
}
