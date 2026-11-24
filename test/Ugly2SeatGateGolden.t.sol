// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

import {TandaBillV2, IERC20} from "../contracts/TandaBillV2.sol";
import {TandaBillFactory} from "../contracts/TandaBillFactory.sol";
import {Test} from "forge-std/Test.sol";

/// @notice UGLY-2 SEAT-GATE-LIVE part (b) goldens: registerSeat(nullifier, wallet, signal)
///         + on-chain used-nullifier ledger (one human one seat, enforced by contract).
///         XixiDesign02 lane pattern: factory-lineage setup (createBill via factory,
///         never raw initialize). Card t_5d8189f1. Brief: Flux Ugly2, testnet in-boundary;
///         [HUMAN_GATE] applies only to the mainnet verifier deploy (parts a/c).

/// @dev Minimal mock token (same surface as test/TandaBillV2.t.sol MockToken, re-declared
///      locally to keep this file self-contained per golden-lane pattern).
contract SeatGateMockToken {
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

contract Ugly2SeatGateGoldenTest is Test {
    TandaBillFactory factory;
    SeatGateMockToken token;
    address owner = address(0xA11CE);
    address alice = address(0xB0B);
    address bob   = address(0xBEEF);

    bytes32 constant NUL_A = bytes32(uint256(0x1111111111111111111111111111111111111111111111111111111111111111));
    bytes32 constant NUL_B = bytes32(uint256(0x2222222222222222222222222222222222222222222222222222222222222222));

    /// @dev local event redeclaration for expectEmit payloads (events are not emit-qualified cross-contract)
    event SeatGranted(uint256 indexed seatId, address indexed wallet, bytes32 indexed nullifier,
                      bytes32 signalHash);

    function setUp() public {
        factory = new TandaBillFactory(address(new TandaBillV2()));
        token = new SeatGateMockToken();
    }

    function _bill() internal returns (TandaBillV2 bill) {
        address[] memory s = new address[](1);
        s[0] = owner;
        vm.prank(owner);
        bill = TandaBillV2(payable(factory.createBill(IERC20(address(token)), s)));
    }

    function _signal(address bill, address wallet) internal pure returns (bytes memory) {
        return abi.encodePacked(_hexAddr(bill), ":", _hexAddr(wallet));
    }
    function _hexAddr(address a) internal pure returns (string memory) {
        return vm.toString(a); // forge-std: lowercase 0x... form
    }

    // -- G1: happy path - ledger write, dual emit, roster consistency ----------
    function test_g1_happy_grant_emits_and_records() public {
        TandaBillV2 bill = _bill();
        bytes memory sig = _signal(address(bill), alice);
        bytes32 sigHash = keccak256(sig);

        vm.expectEmit(true, true, true, false, address(bill));
        emit SeatGranted(1, alice, NUL_A, sigHash); // local redeclare (golden-lane pattern)
        vm.prank(owner);
        bill.registerSeat(NUL_A, alice, sig);

        assertEq(bill.seatNullifierOf(NUL_A), alice, "nullifier ledger");
        assertEq(bill.seatNullifierSignalHash(NUL_A), sigHash, "signal hash ledger");
        (address w, uint64 joined, bool active) = bill.seats(1);
        assertEq(w, alice); assertEq(active, true); assertEq(joined, uint64(block.timestamp));
        assertEq(bill.activeSeatCount(), 2);
        assertEq(bill.seatIdOf(alice), 2, "seatIdOf 1-indexed");
    }

    // -- G2: replay - same nullifier, different wallet: burned forever --------
    function test_g2_nullifier_replay_reverts() public {
        TandaBillV2 bill = _bill();
        vm.prank(owner);
        bill.registerSeat(NUL_A, alice, _signal(address(bill), alice));
        vm.expectRevert(abi.encodeWithSelector(TandaBillV2.NullifierUsed.selector, NUL_A));
        vm.prank(owner);
        bill.registerSeat(NUL_A, bob, _signal(address(bill), bob));
    }

    // -- G3: duplicate wallet via different nullifier --------------------------
    function test_g3_duplicate_wallet_reverts() public {
        TandaBillV2 bill = _bill();
        vm.prank(owner);
        bill.registerSeat(NUL_A, alice, _signal(address(bill), alice));
        vm.expectRevert(abi.encodeWithSelector(TandaBillV2.DuplicateSeat.selector, alice));
        vm.prank(owner);
        bill.registerSeat(NUL_B, alice, _signal(address(bill), alice));
    }

    // -- G4: input sanitation arms ---------------------------------------------
    function test_g4_zero_nullifier_reverts() public {
        TandaBillV2 bill = _bill();
        vm.expectRevert(TandaBillV2.ZeroNullifier.selector);
        vm.prank(owner);
        bill.registerSeat(bytes32(0), alice, _signal(address(bill), alice));
    }
    function test_g4_zero_wallet_reverts() public {
        TandaBillV2 bill = _bill();
        vm.expectRevert(TandaBillV2.ZeroWallet.selector);
        vm.prank(owner);
        bill.registerSeat(NUL_A, address(0), _signal(address(bill), address(0)));
    }

    // -- G5: owner gate - direct stranger AND forwarder-path stranger ----------
    function test_g5_not_owner_direct_reverts() public {
        TandaBillV2 bill = _bill();
        vm.expectRevert(TandaBillV2.NotOwner.selector);
        vm.prank(alice);
        bill.registerSeat(NUL_A, alice, _signal(address(bill), alice));
    }
    function test_g5_not_owner_forwarded_reverts() public {
        TandaBillV2 bill = _bill();
        bytes memory cd = abi.encodeCall(TandaBillV2.registerSeat, (NUL_A, alice, _signal(address(bill), alice)));
        vm.expectRevert(TandaBillV2.NotOwner.selector);
        vm.prank(alice);
        factory.callBill(address(bill), cd); // _caller() must recover alice, not owner
    }
    function test_g5_owner_via_forwarder_succeeds() public {
        TandaBillV2 bill = _bill();
        bytes memory cd = abi.encodeCall(TandaBillV2.registerSeat, (NUL_A, alice, _signal(address(bill), alice)));
        vm.prank(owner);
        factory.callBill(address(bill), cd);
        assertEq(bill.seatNullifierOf(NUL_A), alice, "forwarder grant landed");
    }

    // -- G6: settlement freeze - Sybil gate must not seed post-snapshot seats --
    function test_g6_frozen_after_settlement_initiation() public {
        TandaBillV2 bill = _bill();
        vm.startPrank(owner);
        bill.addExpense(1_000_000);
        token.mint(owner, 1_000_000);
        token.approve(address(bill), 1_000_000);
        bill.fundEscrow(1_000_000);
        bill.initiateSettlement();
        vm.expectRevert(TandaBillV2.SettlementInitiatedAlready.selector);
        bill.registerSeat(NUL_A, alice, _signal(address(bill), alice));
        vm.stopPrank();
    }

    // -- G7: remove-then-regrant semantics --------------------------------------
    // Removed wallet is re-seatable with a FRESH nullifier; the old nullifier
    // stays burned (human already consumed their one grant on this bill).
    function test_g7_remove_then_regrant_fresh_nullifier() public {
        TandaBillV2 bill = _bill();
        vm.startPrank(owner);
        bill.registerSeat(NUL_A, alice, _signal(address(bill), alice));
        bill.removeSeat(1);
        // old nullifier stays burned even though its seat is gone
        vm.expectRevert(abi.encodeWithSelector(TandaBillV2.NullifierUsed.selector, NUL_A));
        bill.registerSeat(NUL_A, alice, _signal(address(bill), alice));
        // same wallet may re-join under a fresh proof path
        bill.registerSeat(NUL_B, alice, _signal(address(bill), alice));
        vm.stopPrank();
        assertEq(bill.seatNullifierOf(NUL_B), alice);
        assertEq(bill.activeSeatCount(), 2);
    }

    // -- G8: empty signal allowed on-chain (verifier relays exact-match law) but
    //        hash recorded - storage binding is keccak of whatever bytes arrived.
    function test_g8_empty_signal_hash_recorded() public {
        TandaBillV2 bill = _bill();
        bytes memory emptySig = "";
        vm.prank(owner);
        bill.registerSeat(NUL_A, alice, emptySig);
        assertEq(bill.seatNullifierSignalHash(NUL_A), keccak256(emptySig), "sha3 of empty bytes");
    }

    // -- G9: capacity - registerSeat obeys MAX_SEATS roster cap ------------------
    function test_g9_too_many_seats_reverts() public {
        TandaBillV2 bill = _bill();
        uint256 cap = bill.MAX_SEATS();
        assertEq(cap, 256, "roster cap == mask width");
        vm.startPrank(owner);
        for (uint256 i = 1; i < cap; i++) {
            bill.addSeat(address(uint160(0x10000 + i))); // fill via legacy path to seats.length == cap
        }
        (address w9, uint64 j9, bool a9) = bill.seats(cap - 1);
        w9; j9;
        assertTrue(a9);
        assertEq(bill.seatIdOf(address(uint160(0x10000 + cap - 1))), cap, "fill reached cap");
        vm.expectRevert(TandaBillV2.TooManySeats.selector);
        bill.registerSeat(NUL_A, alice, _signal(address(bill), alice));
        vm.stopPrank();
    }
}
