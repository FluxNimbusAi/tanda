// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

import {TandaBillV2, IERC20} from "../contracts/TandaBillV2.sol";
import {FastTandaBillV2} from "../contracts/FastTandaBillV2.sol";
import {TandaBillFactory} from "../contracts/TandaBillFactory.sol";
import {Test} from "forge-std/Test.sol";

/// @notice ENGINE-32 (hostile-matrix leg of t_5d8189f1, brief PORTAL_TRIO_STAGING_RUNBOOK
///         L62-63): the seat gate must be non-escapable through the FACTORY CLONE PATH.
///         The factory is a static EIP-1167 deployer cloning `address public immutable
///         implementation` (constructor-pinned), so the only trust point is which impl a
///         factory was built against. Laws pinned:
///         F1 burn ledger is LIVE on every factory-created V2 bill (forwarder grant lands,
///            storage readable through the delegate);
///         F2 double-nullifier replay on a clone reverts NullifierUsed;
///         F3 fresh nullifier for an already-seated wallet reverts DuplicateSeat
///            (one wallet = one seat even with brand-new proofs);
///         F4 tripwire: FastTandaBillV2 — factory-compatible (same initialize signature)
///            but gate-free — reverts any registerSeat call. A factory rotated/constructed
///            at a gate-free impl would produce gate-free bills; production is pinned in
///            docs/DEPLOY_STATE.json (factory 0x010872d47bd7bb001037577a15d090556bfd24c3
///            -> impl 0xd0cc3595679a36b64c860568217b623605980e6a, runtime keccak
///            0x3683cfe0de28d6e06e53f74b6879789a81a6286a0ea1d69b1997880999eba0d8,
///            clean-build zero-diff vs TandaBillV2 main). If the trunk impl ever loses
///            the gate, F1 fails first — that is the canary.
contract GateMockToken {
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
        allowance[fallbackGuard(sp)][sp] = a; return true;
    }
    function fallbackGuard(address a) internal pure returns (address) { return a; }
}

contract FactoryCloneGateGoldenTest is Test {
    TandaBillFactory factory;        // V2 impl  -> gate-bearing clones
    TandaBillFactory fastFactory;    // Fast impl -> gate-free clones (tripwire only)
    address implV2;                  // pinned anchors, captured at construction
    address implFast;
    GateMockToken token;
    address owner = address(0xA11CE);
    address alice = address(0xB0B);
    address bob   = address(0xBEEF);

    bytes32 constant NUL_A = bytes32(uint256(0xAAAA));
    bytes32 constant NUL_B = bytes32(uint256(0xBBBB));

    function setUp() public {
        implV2   = address(new TandaBillV2());
        implFast = address(new FastTandaBillV2());
        factory     = new TandaBillFactory(implV2);
        fastFactory = new TandaBillFactory(implFast);
        token = new GateMockToken();
    }

    /// @dev factory-lineage bill (never raw initialize), per golden-lane pattern.
    function _billAt(TandaBillFactory f) internal returns (address bill) {
        address[] memory s = new address[](1);
        s[0] = owner;
        vm.prank(owner);
        bill = f.createBill(IERC20(address(token)), s);
        // clone law: deployed runtime is EXACTLY the EIP-1167 minimal proxy embedding the
        // factory's constructor-pinned impl. (Pre-seed bug: vm.load(bill, 10) - minimal
        // proxies store the impl in CODE bytes 10..30, never in storage.)
        bytes memory want = abi.encodePacked(
            hex"363d3d373d3d3d363d73", f.implementation(),
            hex"5af43d82803e903d91602b57fd5bf3");
        assertEq(bill.code, want, "clone delegates to pinned impl (EIP-1167 exact)");
    }
    function _bill() internal returns (TandaBillV2) {
        return TandaBillV2(payable(_billAt(factory)));
    }

    function _sig(address bill, address w) internal pure returns (bytes memory) {
        return abi.encodePacked(vm.toString(bill), ":", vm.toString(w));
    }

    // -- F1: gate is live through the delegate --------------------------------
    function test_f1_forwarder_grant_lands_on_clone() public {
        TandaBillV2 bill = _bill();
        bytes memory cd = abi.encodeCall(TandaBillV2.registerSeat,
            (NUL_A, alice, _sig(address(bill), alice)));
        vm.prank(owner);
        factory.callBill(address(bill), cd);
        assertEq(bill.seatNullifierOf(NUL_A), alice, "burn ledger live on clone");
        assertTrue(bill.seatIdOf(alice) > 0, "roster seat exists through delegate");
    }

    // -- F2: double-nullifier replay cannot re-seat on a clone -----------------
    function test_f2_replay_reverts_on_clone() public {
        TandaBillV2 bill = _bill();
        vm.prank(owner);
        bill.registerSeat(NUL_A, alice, _sig(address(bill), alice));
        // replay same nullifier for a DIFFERENT wallet: ledger must remember alice.
        vm.expectRevert(abi.encodeWithSelector(TandaBillV2.NullifierUsed.selector, NUL_A));
        vm.prank(owner);
        bill.registerSeat(NUL_A, bob, _sig(address(bill), bob));
    }

    // -- F3: fresh nullifier does not launder a duplicate wallet ---------------
    function test_f3_fresh_nullifier_duplicate_wallet_reverts() public {
        TandaBillV2 bill = _bill();
        vm.prank(owner);
        bill.registerSeat(NUL_A, alice, _sig(address(bill), alice));
        vm.expectRevert(abi.encodeWithSelector(TandaBillV2.DuplicateSeat.selector, alice));
        vm.prank(owner);
        bill.registerSeat(NUL_B, alice, _sig(address(bill), alice));
    }

    // -- F4: tripwire - the gate-free twin cannot serve the gate ---------------
    function test_f4_fast_twin_clone_has_no_gate() public {
        address fastBill = _billAt(fastFactory); // factory-compatible: proves rotation risk
        // Pre-seed bug: legs were unpranked calls from the test contract - V2's direct-EOA
        // path would fail NotOwner, making the discriminator a tautological false. Prank owner.
        vm.prank(owner);
        (bool ok,) = fastBill.call(abi.encodeCall(TandaBillV2.registerSeat,
            (NUL_A, alice, _sig(fastBill, alice))));
        assertFalse(ok, "gate-free impl must not serve registerSeat");
        // discriminator: identical low-level shape SUCCEEDS on the V2 clone
        address v2Bill = _billAt(factory);
        vm.prank(owner);
        (bool ok2,) = v2Bill.call(abi.encodeCall(TandaBillV2.registerSeat,
            (NUL_A, alice, _sig(v2Bill, alice))));
        assertTrue(ok2, "V2 clone serves the gate (F4 is not a tautology)");
        assertEq(TandaBillV2(payable(v2Bill)).seatNullifierOf(NUL_A), alice,
            "gate actually burned through the direct owner path");
    }

    // -- F4b: immutable anchor - factory target can never be rotated -----------
    function test_f4b_implementation_is_immutable() public {
        // Pre-seed bug: asserted implementation()==address(0) ("sentinel skip") - false,
        // the field is address public immutable set to the real impl at construction.
        assertEq(factory.implementation(), implV2, "V2 factory pinned at construction");
        assertEq(fastFactory.implementation(), implFast, "Fast factory pinned at construction");
        assertTrue(implV2 != address(0) && implFast != address(0), "impls are live deploys");
        assertTrue(implV2 != implFast, "factories pin DISTINCT impls");
        // no rotation path exists: creating bills never moves the anchor
        address bill = _billAt(factory);
        assertEq(factory.implementation(), implV2, "anchor immutable across createBill");
        bill; // silence unused
        // forwarder is clone-scoped: callBill cannot be pointed at the impl itself
        vm.expectRevert(TandaBillFactory.NotBill.selector);
        vm.prank(owner);
        factory.callBill(implV2, "");
    }
}
