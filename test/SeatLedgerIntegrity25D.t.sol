// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

import {TandaBillV2, IERC20} from "../contracts/TandaBillV2.sol";
import {TandaBillFactory} from "../contracts/TandaBillFactory.sol";
import {Test} from "forge-std/Test.sol";

/// @notice ENGINE 25D — seat burn-ledger integrity deepening on TandaBillV2.
///         Closes coverage gaps left by UGLY-2 goldens (g1..g9) and LATCH-2
///         goldens (h1..h6): registerSeat x rotateSeatWallet interaction,
///         multi-violation revert PRECEDENCE, burn survival across a full
///         drain/reset round, and an append-only ledger invariant under a
///         deterministic mutation-sequence fuzz.
contract D25MockToken {
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

contract SeatLedgerIntegrity25DTest is Test {
    TandaBillFactory factory;
    D25MockToken token;
    address owner = address(0xA11CE);
    address alice = address(0xB0B);
    address bob   = address(0xBEEF);
    address carol = address(0xCA40);
    address dave  = address(0xDA7E);

    bytes32 constant NUL_A = bytes32(uint256(0xA1A1));
    bytes32 constant NUL_B = bytes32(uint256(0xB1B1));
    bytes32 constant NUL_C = bytes32(uint256(0xC1C1));

    function setUp() public {
        factory = new TandaBillFactory(address(new TandaBillV2()));
        token = new D25MockToken();
    }

    function _bill(address[] memory initial) internal returns (TandaBillV2 bill) {
        vm.prank(owner);
        bill = TandaBillV2(payable(factory.createBill(IERC20(address(token)), initial)));
    }

    function _sig(address bill, address wallet) internal pure returns (bytes memory) {
        return abi.encodePacked(vm.toString(bill), ":", vm.toString(wallet));
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

    /// @dev h4-shape refund: owner-only confirmation, hold-warp, refund, freeze lifts.
    function _refund(TandaBillV2 bill, uint256 sid) internal {
        vm.prank(owner); bill.confirmSettlement(sid);
        (,, uint256 inAt,,,,,) = bill.settlements(sid);
        vm.warp(inAt + bill.MAX_HOLD());
        vm.prank(owner); bill.refundSettlement(sid);
    }

    // -- D1: rotateSeatWallet must NEVER touch the burn ledger ----------------
    // Forensic law: the ledger records WHO WAS GRANTED (human identity), not who
    // currently holds the payout seat. Rotation relocates the seat; the burned
    // nullifier stays pinned to the original grantee wallet forever.
    function test_d1_rotation_never_touches_burn_ledger() public {
        address[] memory s = new address[](1);
        s[0] = owner;
        TandaBillV2 bill = _bill(s);
        bytes memory sigA = _sig(address(bill), alice);
        vm.startPrank(owner);
        bill.registerSeat(NUL_A, alice, sigA);           // seat 1 = alice via World ID
        bill.rotateSeatWallet(1, bob);                    // owner-driven recovery rotate
        vm.stopPrank();

        // ledger byte-frozen: wallet AND signal hash unchanged after rotation
        assertEq(bill.seatNullifierOf(NUL_A), alice, "burn stays pinned to grantee");
        assertEq(bill.seatNullifierSignalHash(NUL_A), keccak256(sigA), "signal hash frozen");
        assertEq(bill.seatIdOf(bob), 2, "rotated-in wallet seats at idx 1");
        assertEq(bill.seatIdOf(alice), 0, "rotated-out wallet free");

        // displaced human: burned nullifier cannot be reused by ANYONE...
        vm.prank(owner);
        vm.expectRevert(abi.encodeWithSelector(TandaBillV2.NullifierUsed.selector, NUL_A));
        bill.registerSeat(NUL_A, carol, _sig(address(bill), carol));
        // ...including the grantee themselves; fresh proof re-enters fine
        vm.prank(owner);
        vm.expectRevert(abi.encodeWithSelector(TandaBillV2.NullifierUsed.selector, NUL_A));
        bill.registerSeat(NUL_A, alice, _sig(address(bill), alice));
        vm.prank(owner); bill.registerSeat(NUL_B, alice, _sig(address(bill), alice));
        assertEq(bill.seatNullifierOf(NUL_B), alice, "fresh-nullifier re-entry granted");
    }

    // -- D2: multi-violation revert PRECEDENCE matrix --------------------------
    // Contract doc pins order: owner -> freeze -> zero nullifier -> zero wallet
    // -> replay -> duplicate -> capacity. Goldens only test single violations;
    // here every call carries TWO+ co-occurring violations; the outermost wins.
    function test_d2_revert_precedence_matrix() public {
        address[] memory s = new address[](2);
        s[0] = owner; s[1] = alice;
        TandaBillV2 bill = _bill(s);

        // (a) non-owner + zero-nullifier + zero-wallet  -> NotOwner
        vm.prank(bob);
        vm.expectRevert(TandaBillV2.NotOwner.selector);
        bill.registerSeat(bytes32(0), address(0), "");

        // (b) owner + frozen + zero-nullifier + zero-wallet -> SettlementInitiatedAlready
        _initiate(bill, 1_000_000);
        vm.prank(owner);
        vm.expectRevert(TandaBillV2.SettlementInitiatedAlready.selector);
        bill.registerSeat(bytes32(0), address(0), "");

        // lift freeze via the refund leg (h4 pattern), then un-frozen precedence:
        _refund(bill, 0);
        assertFalse(bill.settlementInitiated(), "refund lifted freeze");

        // (c) owner + zero-nullifier + zero-wallet -> ZeroNullifier
        vm.prank(owner);
        vm.expectRevert(TandaBillV2.ZeroNullifier.selector);
        bill.registerSeat(bytes32(0), address(0), "");

        // (d) owner + zero-nullifier + live wallet -> ZeroNullifier (still outermost)
        vm.prank(owner);
        vm.expectRevert(TandaBillV2.ZeroNullifier.selector);
        bill.registerSeat(bytes32(0), alice, "");

        // (e) replay + duplicate-wallet co-occurring -> NullifierUsed before DuplicateSeat
        //     (bob seated via NUL_A; replay of NUL_A onto bob violates both legs)
        vm.prank(owner); bill.registerSeat(NUL_A, bob, _sig(address(bill), bob));
        vm.prank(owner);
        vm.expectRevert(abi.encodeWithSelector(TandaBillV2.NullifierUsed.selector, NUL_A));
        bill.registerSeat(NUL_A, bob, _sig(address(bill), bob));

        // (f) capacity + duplicate-wallet -> DuplicateSeat; capacity + fresh -> TooManySeats.
        //     Array so far: owner(0) alice(1) bob(2) = 3 live entries; fill 253 synthetic.
        vm.startPrank(owner);
        uint256 cap = bill.MAX_SEATS();
        for (uint256 i = 3; i < cap; i++) { bill.addSeat(address(uint160(0x25000 + i))); }
        vm.stopPrank();
        vm.prank(owner);
        vm.expectRevert(abi.encodeWithSelector(TandaBillV2.DuplicateSeat.selector, alice));
        bill.registerSeat(NUL_B, alice, _sig(address(bill), alice));
        vm.prank(owner);
        vm.expectRevert(TandaBillV2.TooManySeats.selector);
        bill.registerSeat(NUL_B, dave, _sig(address(bill), dave));
    }

    // -- D3: burn ledger survives a full round reset (LATCH-2 x UGLY-2) --------
    // After settlement executes and EVERY seat claims (freeze lifts for round 2),
    // round-1 nullifiers must stay burned: the per-round roster is a latch reset,
    // not a Sybil-ledger reset. Fresh nullifiers may enter; old ones never.
    function test_d3_burn_survives_full_drain_round_reset() public {
        address[] memory s = new address[](2);
        s[0] = owner; s[1] = alice;
        TandaBillV2 bill = _bill(s);
        vm.prank(owner); bill.registerSeat(NUL_A, bob, _sig(address(bill), bob)); // seat 2

        _initiate(bill, 3_000_000);
        vm.prank(owner); bill.confirmSettlement(0);
        vm.prank(alice); bill.confirmSettlement(0);
        vm.prank(bob);   bill.confirmSettlement(0);
        vm.warp(block.timestamp + bill.SETTLEMENT_WINDOW());
        bill.executeSettlement(0);
        vm.prank(owner); bill.claimSettlement(0);
        vm.prank(alice); bill.claimSettlement(0);
        vm.prank(bob);   bill.claimSettlement(0);
        assertFalse(bill.settlementInitiated(), "fully drained -> round reset");

        // burned nullifier stays dead forever...
        vm.prank(owner);
        vm.expectRevert(abi.encodeWithSelector(TandaBillV2.NullifierUsed.selector, NUL_A));
        bill.registerSeat(NUL_A, bob, _sig(address(bill), bob));
        // ...while a fresh human enters the reopened roster (roster unchanged by claims)
        vm.prank(owner); bill.registerSeat(NUL_C, carol, _sig(address(bill), carol));
        assertEq(bill.activeSeatCount(), 4, "owner+alice+bob+carol all still seated");
        assertEq(bill.seatNullifierOf(NUL_C), carol);
    }

    // -- D4: deterministic mutation-sequence fuzz: ledger is append-only -------
    // 180 seed-derived ops over register/add/remove/rotate. Shadow model asserts
    // every round: (I1) a burned nullifier never changes value and its recorded
    // signal hash is immutable, (I2) the zero slot was never written, (I3)
    // seatIdOf[w] != 0 iff the seat it points to is active and holds w,
    // (I4) activeSeatCount agrees with model AND read-back, (I5) illegal ops
    // revert (guarded via try/catch probes).
    // ── D4 state (file-level to keep stack shallow without via-ir) ──────────
    TandaBillV2 private b4;
    address[5] private actors4;
    bytes32[] private burnN;   // burned nullifiers, append-only shadow
    address[] private burnW;   // grantee wallet per burned nullifier (pinned)
    bytes32[] private burnH;   // keccak(signal) per burned nullifier (pinned)
    uint256 private _burnIdx;  // shadow burn count (arrays sized 200, nf <= 144)
    uint256 private mLen4;     // shadow seats-array length (never shrinks)
    uint256 private mAct4;     // shadow active-seat count

    function test_d4_fuzz_burn_appendonly(uint96 seed) public {
        address[] memory s = new address[](1);
        s[0] = owner;
        b4 = _bill(s);
        actors4 = [alice, bob, carol, dave, address(0x515E)];
        burnN = new bytes32[](200);
        burnW = new address[](200);
        burnH = new bytes32[](200);
        mLen4 = 1;             // owner seated at idx 0 by initialize
        mAct4 = 1;
        _burnIdx = 0;
        uint256 nf = 0;

        for (uint256 i = 0; i < 180; i++) {
            uint256 r = uint256(keccak256(abi.encode(seed, i)));
            uint256 op = r % 5;
            address w = actors4[r / 5 % 5];
            if (op == 0) {
                unchecked { ++nf; }
                bytes32 n = keccak256(abi.encode("NUL", nf));
                bytes memory sig = _sig(address(b4), w);
                if (b4.seatIdOf(w) == 0) {
                    vm.prank(owner);
                    b4.registerSeat(n, w, sig);
                    _burnPush(n, w, keccak256(sig));
                    mLen4++; mAct4++;
                } else {
                    vm.prank(owner);
                    assertTrue(!_tryRegister(n, w, sig), "op0: seated-wallet register must revert");
                }
            } else if (op == 1) {
                if (b4.seatIdOf(w) == 0) {
                    vm.prank(owner); b4.addSeat(w);
                    mLen4++; mAct4++;
                } else {
                    vm.prank(owner);
                    assertTrue(!_tryAdd(w), "op1: dup addSeat must revert");
                }
            } else if (op == 2) {
                uint256 idx = r / 25 % 12;
                bool act = false;
                if (idx < mLen4) { (,, act) = b4.seats(idx); }
                if (act) {
                    vm.prank(owner); b4.removeSeat(idx);
                    mAct4--;
                } else {
                    vm.prank(owner);
                    assertTrue(!_tryRemove(idx), "op2: inactive/oob remove must revert");
                }
            } else if (op == 3) {
                uint256 idx = r / 25 % 12;
                bool act = false;
                if (idx < mLen4) { (,, act) = b4.seats(idx); }
                if (act && b4.seatIdOf(w) == 0) {
                    vm.prank(owner); b4.rotateSeatWallet(idx, w);
                    // rotation: array len & active count unchanged, only wallet moves
                } else {
                    vm.prank(owner);
                    assertTrue(!_tryRotate(idx, w), "op3: illegal rotate must revert");
                }
            } else {
                // op4: assert-sweep-only round
            }
            _sweep();
        }
    }

    function _burnPush(bytes32 n, address w, bytes32 h) private {
        uint256 cnt = _burnIdx;
        burnN[cnt] = n; burnW[cnt] = w; burnH[cnt] = h;
        _burnIdx = cnt + 1;
    }

    function _sweep() private view {
        for (uint256 k = 0; k < _burnIdx; k++) {
            assertEq(b4.seatNullifierOf(burnN[k]), burnW[k], "I1 burn append-only");
            assertEq(b4.seatNullifierSignalHash(burnN[k]), burnH[k], "I1b signal immutable");
        }
        assertEq(b4.seatNullifierOf(bytes32(0)), address(0), "I2 zero slot never written");
        uint256 activeCount;
        for (uint256 t = 0; t < mLen4; t++) {
            (address sw, , bool a2) = b4.seats(t);
            if (a2) {
                activeCount++;
                assertEq(b4.seatIdOf(sw), t + 1, "I3 active seat backlink");
            }
        }
        assertEq(activeCount, mAct4, "I4a model agrees");
        assertEq(b4.activeSeatCount(), activeCount, "I4b contract agrees");
    }

    // ── small helpers ────────────────────────────────────────────────────────
    function _tryRegister(bytes32 n, address w, bytes memory sig) internal returns (bool) {
        try b4.registerSeat(n, w, sig) { return true; } catch { return false; }
    }
    function _tryAdd(address w) internal returns (bool) {
        try b4.addSeat(w) { return true; } catch { return false; }
    }
    function _tryRemove(uint256 idx) internal returns (bool) {
        try b4.removeSeat(idx) { return true; } catch { return false; }
    }
    function _tryRotate(uint256 idx, address w) internal returns (bool) {
        try b4.rotateSeatWallet(idx, w) { return true; } catch { return false; }
    }
}
