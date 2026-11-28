// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

import {IERC20, TandaBillV2} from "../contracts/TandaBillV2.sol";
import {TandaBillFactory} from "../contracts/TandaBillFactory.sol";
import {Test} from "forge-std/Test.sol";

/// @notice ENGINE-73 (card t_dfadd418): V2 pull-model reentry IMMUNITY control under the
///         Engine71 hook-before-debit harness (cross-twin parity).
///         Engine71 proved the Fast-twin DEFECT (push loop before settledAt write) but the
///         "V2 pull model immune" claim was code-location adjudication only (V2:418 zero
///         transfers; V2:459 claimedMask before safeTransfer; V2:487 refunded before
///         transfer). This suite turns that claim into executable evidence on the SAME
///         maximally hostile token shape:
///           T1 executeSettlement performs ZERO token calls -> hook never fires.
///           T2 token-originated re-entry into executeSettlement during a claim dies on the
///              settledAt gate (written before any payout exists). Execute is permissionless,
///              so msg.sender=token passes the identity layer: pure state-gate fight.
///           T3 contract-seat self-reentry during its own claim passes the _caller()
///              identity gate (msg.sender IS the seat wallet) and dies on the claimedMask
///              bit alone -> THE claim-path CEI evidence.
///           T4 conservation contrast: over-funded escrow F = 3T pays out EXACTLY T under
///              the full hostile round (Fast defect shape drained 2T, Engine71 test 1).
///           T5 refund leg: OWNER-side contract re-enters refundSettlement during the refund
///              transfer; msg.sender IS the owner so the NotOwner gate passes and only the
///              `refunded` flag written before safeTransfer can stop it -> refund-path CEI.
///         Owner AND seat 1 are BOTH contract wallets so every reentry leg is identity-true
///         (a token-originated inner claim/refund would die on _caller() identity and mask
///         the CEI evidence). Factory-lineage setup per lane law, never raw initialize.

interface IExec { function executeSettlement(uint256 id) external; }
interface IHookee { function fireback(address bill, uint8 mode) external; }
interface IBill {
    function claimSettlement(uint256 id) external;
    function refundSettlement(uint256 id) external;
}

/// @notice Hook-before-debit token (Engine71 shape, three hostile modes):
///         mode 1 = token itself re-enters executeSettlement(0) (permissionless path);
///         mode 2 = recipient-side fireback -> owner wallet re-enters refundSettlement(0);
///         mode 3 = recipient-side fireback -> seat wallet re-enters claimSettlement(0).
///         The hook always fires BEFORE the debit - maximally hostile ERC-20.
contract HookExecToken {
    mapping(address => uint256) public balanceOf;
    mapping(address => mapping(address => uint256)) public allowance;
    address public bill;
    uint8 public mode;
    bool public entered;
    bool public innerSucceeded;
    bool public innerReverted;
    bytes public innerError;

    function setBill(address b) external { bill = b; }
    function setMode(uint8 m) external { mode = m; }
    function mint(address to, uint256 a) external { balanceOf[to] += a; }
    function approve(address sp, uint256 a) external returns (bool) { allowance[msg.sender][sp] = a; return true; }
    function resetHook() external { entered = false; innerSucceeded = false; innerReverted = false; innerError = ""; }

    function _fire(address recipient) internal {
        if (!entered) {
            entered = true;
            if (mode == 1) {
                try IExec(bill).executeSettlement(0) { innerSucceeded = true; }
                catch (bytes memory err) { innerReverted = true; innerError = err; }
            } else if (mode == 2 || mode == 3) {
                try IHookee(recipient).fireback(bill, mode) { innerSucceeded = true; } catch { innerReverted = true; }
            }
        }
    }

    function transfer(address to, uint256 a) external returns (bool) {
        _fire(to); // hook-before-debit
        require(balanceOf[msg.sender] >= a, "insufficient");
        balanceOf[msg.sender] -= a;
        balanceOf[to] += a;
        return true;
    }

    function transferFrom(address f, address t, uint256 a) external returns (bool) {
        require(balanceOf[f] >= a && allowance[f][msg.sender] >= a, "no");
        balanceOf[f] -= a;
        balanceOf[t] += a;
        allowance[f][msg.sender] -= a;
        return true;
    }
}

/// @notice Contract wallet used for owner (seat 0) and attacker seat (seat 1). Its fireback()
///         is invoked by the token BEFORE debiting; it re-enters the bill with ITS OWN
///         msg.sender, so the _caller() identity gates pass and the state gates
///         (claimedMask bit / refunded flag) are the sole remaining defense.
contract HookWallet is IHookee {
    bool public firedBack;
    bool public innerSucceeded;
    bool public innerReverted;
    bytes public innerError;

    function fireback(address bill, uint8 mode) external {
        firedBack = true;
        if (mode == 2) {
            try IBill(bill).refundSettlement(0) { innerSucceeded = true; }
            catch (bytes memory err) { innerReverted = true; innerError = err; }
        } else {
            try IBill(bill).claimSettlement(0) { innerSucceeded = true; }
            catch (bytes memory err) { innerReverted = true; innerError = err; }
        }
    }
    function reset() external { firedBack = false; innerSucceeded = false; innerReverted = false; innerError = ""; }
}

contract Engine73V2ReentryParityTest is Test {
    TandaBillFactory factory;
    HookWallet ownerHook = new HookWallet(); // creator + seat 0 + funder (Gap-3 owner-fronted)
    HookWallet seatHook  = new HookWallet(); // seat 1, identity-true attacker
    address owner = address(ownerHook);

    function setUp() public {
        factory = new TandaBillFactory(address(new TandaBillV2()));
    }

    function _seats() internal view returns (address[] memory s) {
        s = new address[](2); s[0] = address(ownerHook); s[1] = address(seatHook);
    }

    function _deployWith(address tok) internal returns (TandaBillV2 bill) {
        vm.prank(owner);
        bill = TandaBillV2(payable(factory.createBill(IERC20(tok), _seats())));
    }

    /// @notice Lifecycle to fully-confirmed + window-elapsed when fullConfirm=true;
    ///         fullConfirm=false leaves fullyConfirmedAt == 0 (refund-path precondition).
    ///         expense 100e6 -> payouts [50e6, 50e6]; funding caller-supplied.
    function _confirmRound(TandaBillV2 bill, HookExecToken t, uint256 expense, uint256 funding, bool fullConfirm) internal {
        vm.startPrank(owner);
        t.mint(owner, funding);
        t.approve(address(bill), funding);
        bill.addExpense(expense);
        bill.fundEscrow(funding);
        bill.initiateSettlement();
        vm.stopPrank();
        vm.prank(owner); bill.confirmSettlement(0);
        if (fullConfirm) {
            vm.prank(address(seatHook)); bill.confirmSettlement(0);
            vm.warp(block.timestamp + 3601); // SETTLEMENT_WINDOW = 1 hours
        }
    }

    /// @notice T1: executeSettlement (V2:418) performs ZERO token calls. Under the identical
    ///         Engine71 harness (Fast fired on its FIRST push, Fast:382), mainline execute
    ///         must not touch the token at all and must not move any value.
    function test_e73_v2_execute_fires_zero_hook() public {
        HookExecToken t = new HookExecToken();
        TandaBillV2 bill = _deployWith(address(t));
        t.setBill(address(bill));
        t.setMode(1);
        _confirmRound(bill, t, 100e6, 300e6, true);

        uint256 before = t.balanceOf(address(bill));
        bill.executeSettlement(0);
        assertEq(t.entered(), false, "execute must perform zero token calls");
        assertEq(t.innerSucceeded(), false);
        assertEq(t.innerReverted(), false);
        assertEq(t.balanceOf(address(bill)), before, "execute must move zero value");
        (, uint64 settledAt, , , , , , ) = bill.settlements(0);
        assertTrue(settledAt != 0, "settledAt lands on execute");
    }

    /// @notice T2: token-originated re-entry into executeSettlement during the first claim
    ///         transfer must die on the settledAt gate. No re-open: escrow drains exactly
    ///         the two shares and the surplus stays put.
    function test_e73_v2_claim_reexecute_dies_settled_gate() public {
        HookExecToken t = new HookExecToken();
        TandaBillV2 bill = _deployWith(address(t));
        t.setBill(address(bill));
        t.setMode(1);
        _confirmRound(bill, t, 100e6, 300e6, true);
        bill.executeSettlement(0);

        vm.prank(owner); bill.claimSettlement(0);
        assertTrue(t.entered(), "claim transfer must fire the hook");
        assertTrue(t.innerReverted(), "re-entered execute must revert (AlreadySettled)");
        assertFalse(t.innerSucceeded());
        assertEq(bytes32(bytes4(t.innerError())), bytes32(TandaBillV2.AlreadySettled.selector),
            "inner execute must die on the settledAt gate specifically");

        t.resetHook();
        vm.prank(address(seatHook)); bill.claimSettlement(0);
        assertEq(t.balanceOf(owner), 50e6);
        assertEq(t.balanceOf(address(seatHook)), 50e6);
        assertEq(t.balanceOf(address(bill)), 200e6, "surplus stays put: no drain under reentry");
        (, , , , , uint256 claimedMask, , ) = bill.settlements(0);
        assertEq(claimedMask, 0x3, "exactly two claim bits");
    }

    /// @notice T3 (THE claim-path CEI evidence): seat 1 self-re-enters claimSettlement during
    ///         its own payout transfer. msg.sender IS the seat wallet -> _caller() identity
    ///         gate PASSES -> only the claimedMask bit written before safeTransfer (V2:459)
    ///         can stop it. Inner must revert; wallet holds exactly one share; victim leg
    ///         (owner claim) unharmed.
    function test_e73_v2_claim_self_reentry_dies_on_mask_bit() public {
        HookExecToken t = new HookExecToken();
        TandaBillV2 bill = _deployWith(address(t));
        t.setBill(address(bill));
        t.setMode(3);
        _confirmRound(bill, t, 100e6, 300e6, true);
        bill.executeSettlement(0);

        t.resetHook(); seatHook.reset();
        vm.prank(address(seatHook)); bill.claimSettlement(0);
        assertTrue(seatHook.firedBack(), "hook must reach the contract seat");
        assertTrue(seatHook.innerReverted(), "self-reentry must die on claimedMask bit");
        assertFalse(seatHook.innerSucceeded());
        assertEq(bytes32(bytes4(seatHook.innerError())), bytes32(TandaBillV2.PayoutAlreadyClaimed.selector),
            "inner claim must die on the claimedMask CEI bit, not on identity (NotAnExpectedSeat)");
        assertEq(t.balanceOf(address(seatHook)), 50e6, "exactly one share for the attacking seat");

        // victim leg unharmed: owner still claims its own full share
        t.resetHook(); ownerHook.reset();
        vm.prank(owner); bill.claimSettlement(0);
        assertEq(t.balanceOf(owner), 50e6);
        assertEq(t.balanceOf(address(bill)), 200e6);
    }

    /// @notice T4 (conservation contrast vs Fast defect): F = 3x expense, BOTH seats armed
    ///         (mode 3 self-reentry on each transfer). Full hostile round must move EXACTLY
    ///         T total. The Fast twin under the identical F=3T shape drained 2T (E71 test 1).
    function test_e73_v2_overfunded_conservation_exactly_T() public {
        HookExecToken t = new HookExecToken();
        TandaBillV2 bill = _deployWith(address(t));
        t.setBill(address(bill));
        t.setMode(3);
        _confirmRound(bill, t, 100e6, 300e6, true);
        bill.executeSettlement(0);

        vm.prank(owner); bill.claimSettlement(0);
        t.resetHook();
        vm.prank(address(seatHook)); bill.claimSettlement(0);

        assertEq(t.balanceOf(owner) + t.balanceOf(address(seatHook)), 100e6,
            "outflow EXACTLY T under full hostile round (Fast twin: 2T)");
        assertEq(t.balanceOf(address(bill)), 200e6, "F-T surplus stays escrowed, unextractable by seats");
        assertTrue(seatHook.firedBack());
        assertTrue(seatHook.innerReverted());
        (, uint64 settledAt, , , , uint256 claimedMask, , ) = bill.settlements(0);
        assertEq(claimedMask, 0x3);
        assertTrue(settledAt != 0);
    }

    /// @notice T5 (refund-path CEI evidence): not-fully-confirmed round, warp past MAX_HOLD,
    ///         owner refunds; owner-side contract re-enters refundSettlement during the
    ///         refund transfer. msg.sender IS the owner -> NotOwner gate passes -> only the
    ///         `refunded` flag written before safeTransfer (V2:487 CEI) can stop it.
    function test_e73_v2_refund_reentry_dies_on_flag() public {
        HookExecToken t = new HookExecToken();
        TandaBillV2 bill = _deployWith(address(t));
        t.setBill(address(bill));
        t.setMode(2);
        _confirmRound(bill, t, 100e6, 300e6, false); // only owner confirmed
        ownerHook.reset();
        vm.warp(block.timestamp + 72 hours + 1);      // MAX_HOLD = 72 hours

        vm.prank(owner); bill.refundSettlement(0);

        assertTrue(ownerHook.firedBack(), "refund transfer must fire into the owner wallet");
        assertTrue(ownerHook.innerReverted(), "re-entered refund must revert (AlreadySettled on refunded flag)");
        assertFalse(ownerHook.innerSucceeded());
        assertEq(bytes32(bytes4(ownerHook.innerError())), bytes32(TandaBillV2.AlreadySettled.selector),
            "inner refund must die on the refunded CEI flag, not on identity (NotOwner)");
        assertEq(t.balanceOf(owner), 100e6, "owner refunded exactly the settlement total, once");
        assertEq(t.balanceOf(address(bill)), 200e6, "surplus untouched");
        (, uint64 settledAt, , , , uint256 claimedMask, , bool refunded) = bill.settlements(0);
        assertEq(claimedMask, 0, "no payout bits armed on the refund path");
        assertEq(settledAt, 0);
        assertTrue(refunded);
    }
}
