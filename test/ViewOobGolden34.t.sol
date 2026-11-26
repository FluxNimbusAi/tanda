// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

import {TandaBillV2, IERC20} from "../contracts/TandaBillV2.sol";
import {FastTandaBillV2} from "../contracts/FastTandaBillV2.sol";
import {TandaBillFactory} from "../contracts/TandaBillFactory.sol";
import {Test} from "forge-std/Test.sol";

/// @notice Minimal 6-decimal-style mock (raw units; semantics irrelevant to view legs).
contract OobMockToken {
    mapping(address => uint256) public balanceOf;
    mapping(address => mapping(address => uint256)) public allowance;

    function mint(address to, uint256 a) external { balanceOf[to] += a; }

    function transfer(address to, uint256 a) external returns (bool) {
        require(balanceOf[msg.sender] >= a, "insufficient");
        balanceOf[msg.sender] -= a;
        balanceOf[to] += a;
        return true;
    }

    function transferFrom(address f, address t, uint256 a) external returns (bool) {
        require(balanceOf[f] >= a, "insufficient");
        require(allowance[f][msg.sender] >= a, "allowance");
        balanceOf[f] -= a;
        balanceOf[t] += a;
        allowance[f][msg.sender] -= a;
        return true;
    }

    function approve(address sp, uint256 a) external returns (bool) {
        allowance[msg.sender][sp] = a;
        return true;
    }
}

/// @title ViewOobGolden34Test [ENGINE-34 2026-11-26]
/// @notice Pins the OUT-OF-RANGE settlementId convention of the three roster/settlement
///         views on BOTH twins. Found while scanning V2 L529-L558 for view-convention drift:
///           - claimablePayout  (V2 L529): DEFENSIVE — returns 0 when settlementId >= length.
///           - isSeatConfirmed  (V2 L548 / Fast L429): PANICS (Solidity Panic 0x32 storage
///             array OOB) when settlementId >= length AND wallet holds a seat (raw != 0);
///             returns FALSE for seatless wallets because the raw==0 short-circuit runs
///             BEFORE the array index.
///           - settlementPayouts (V2 L556 / Fast L437): PANICS on any OOB settlementId.
/// @dev    This suite DOCUMENTS, it does not fix. The asymmetry is an off-chain footgun:
///         UI/indexer polling isSeatConfirmed/settlementPayouts before the first
///         initiateSettlement (settlements.length == 0) receives a revert, not a value.
///         A source fix would rotate the canonical blob (V2 8ca54af5 in commit c468fda2,
///         impl 3683cfe0 == on-chain) — anchored change, Flux lane. Contracts untouched here.
///         Guard-ORDER legs (seatless wallet -> false even at OOB id) are pinned so any
///         future bounds-guard patch must preserve the short-circuit, not just the panic.
contract ViewOobGolden34Test is Test {
    OobMockToken token;
    TandaBillFactory factory;
    TandaBillV2 bill;

    address owner = address(0xA11CE);
    address alice = address(0xB0B);
    address bob   = address(0xBEEF);
    address carol = address(0xCA401); // never seated

    bytes4 constant PANIC_SIG = 0x4e487b71; // Panic(uint256)
    uint256 constant OOB_ARRAY = 0x32;       // storage array OOB code

    function _seats3() internal view returns (address[] memory s) {
        s = new address[](3); s[0] = owner; s[1] = alice; s[2] = bob;
    }

    function setUp() public {
        token = new OobMockToken();
        factory = new TandaBillFactory(address(new TandaBillV2()));
        token.mint(owner, 1_000_000 ether);
        address[] memory roster = _seats3();
        vm.prank(owner);
        bill = TandaBillV2(payable(factory.createBill(IERC20(address(token)), roster)));
    }

    /// @notice owner adds expense, funds escrow, initiates -> settlements.length becomes 1.
    function _oneSettlement() internal {
        vm.startPrank(owner);
        bill.addExpense(300 ether);
        token.approve(address(bill), 300 ether);
        bill.fundEscrow(300 ether);
        bill.initiateSettlement();
        vm.stopPrank();
    }

    // ─── Legs 1-3: pre-initiate world (settlements.length == 0) ──────────

    function test_g1_claimablePayout_oobId_returnsZero() public view {
        // Defensive convention holds even with zero settlements.
        assertEq(bill.claimablePayout(0, owner), 0);
        assertEq(bill.claimablePayout(999, alice), 0);
        assertEq(bill.claimablePayout(0, carol), 0);
    }

    function test_g2_isSeatConfirmed_oobId_seatedWallet_panics() public {
        vm.expectRevert(abi.encodeWithSelector(PANIC_SIG, OOB_ARRAY));
        bill.isSeatConfirmed(0, owner); // raw != 0 -> indexes settlements[0] -> Panic 0x32
    }

    function test_g3_isSeatConfirmed_oobId_seatlessWallet_false() public view {
        // Guard ORDER pin: raw==0 short-circuit runs BEFORE the array index.
        assertFalse(bill.isSeatConfirmed(0, carol));
        assertFalse(bill.isSeatConfirmed(999, carol));
    }

    function test_g4_settlementPayouts_oobId_panics() public {
        vm.expectRevert(abi.encodeWithSelector(PANIC_SIG, OOB_ARRAY));
        bill.settlementPayouts(0);
    }

    // ─── Legs 5-7: exactly one settlement exists (length == 1) ───────────

    function test_g5_validId_confirms_readTrue() public {
        _oneSettlement();
        vm.prank(owner); bill.confirmSettlement(0);
        assertTrue(bill.isSeatConfirmed(0, owner));
        assertFalse(bill.isSeatConfirmed(0, alice)); // seated but unconfirmed
        assertEq(bill.settlementPayouts(0).length, 3);
    }

    function test_g6_lengthBoundary_oobId_panics_validId_reads() public {
        _oneSettlement();
        // id 1 == length: the exact off-by-one boundary UIs hit first.
        vm.expectRevert(abi.encodeWithSelector(PANIC_SIG, OOB_ARRAY));
        bill.isSeatConfirmed(1, owner);
        vm.expectRevert(abi.encodeWithSelector(PANIC_SIG, OOB_ARRAY));
        bill.settlementPayouts(1);
        assertEq(bill.claimablePayout(1, owner), 0);
        // id 0 remains readable.
        assertFalse(bill.isSeatConfirmed(0, owner));
    }

    function test_g7_postExecute_claimablePayout_oob_stillZero() public {
        _oneSettlement();
        vm.startPrank(owner);
        bill.confirmSettlement(0);
        vm.stopPrank();
        vm.prank(alice); bill.confirmSettlement(0);
        vm.prank(bob);   bill.confirmSettlement(0);
        vm.warp(block.timestamp + uint256(bill.SETTLEMENT_WINDOW()) + 1);
        bill.executeSettlement(0);
        // executed: valid id readable, OOB id keeps the pinned split behavior.
        assertEq(bill.claimablePayout(0, owner), 100 ether);
        assertEq(bill.claimablePayout(5, owner), 0);
        vm.expectRevert(abi.encodeWithSelector(PANIC_SIG, OOB_ARRAY));
        bill.isSeatConfirmed(5, owner);
    }

    // ─── Legs 8-9: Fast twin parity (no claimablePayout on Fast — pinned below) ──

    function test_g8_fast_isSeatConfirmed_oobId_panics_seated() public {
        FastTandaBillV2 impl = new FastTandaBillV2();
        TandaBillFactory f2 = new TandaBillFactory(address(impl));
        token.mint(alice, 10 ether); token.mint(bob, 10 ether);
        address[] memory roster = _seats3();
        vm.prank(owner);
        FastTandaBillV2 fast = FastTandaBillV2(payable(f2.createBill(IERC20(address(token)), roster)));
        vm.expectRevert(abi.encodeWithSelector(PANIC_SIG, OOB_ARRAY));
        fast.isSeatConfirmed(0, alice); // settlements.length == 0 on the twin too
        assertFalse(fast.isSeatConfirmed(0, carol)); // twin shares short-circuit order
    }

    function test_g9_fast_settlementPayouts_oobId_panics() public {
        FastTandaBillV2 impl = new FastTandaBillV2();
        TandaBillFactory f2 = new TandaBillFactory(address(impl));
        address[] memory roster = _seats3();
        vm.prank(owner);
        FastTandaBillV2 fast = FastTandaBillV2(payable(f2.createBill(IERC20(address(token)), roster)));
        vm.expectRevert(abi.encodeWithSelector(PANIC_SIG, OOB_ARRAY));
        fast.settlementPayouts(0);
        // Absence pin: Fast twin exposes NO claimablePayout — surface parity is intentional
        // (claim path is the twin's difference; see FastTwinMatrixParity lineage).
        (bool ok, ) = address(fast).staticcall(
            abi.encodeWithSelector(bytes4(keccak256("claimablePayout(uint256,address)")), 0, owner)
        );
        assertFalse(ok, "Fast twin must NOT expose claimablePayout");
    }
}
