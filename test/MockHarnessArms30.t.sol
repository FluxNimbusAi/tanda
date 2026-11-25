// SPDX-License-Identifier: MIT OR Apache-2.0
pragma solidity >=0.8.13 <0.9.0;

import {Test} from "../lib/forge-std/src/Test.sol";

// ─── ENGINE 30 (t_eng30mock) — mock-harness arm sweep ────────────────────────
// Ledger proofs/gaps_after_1125_7.json left 96 test-infrastructure arms open.
// These are NOT production paths: they are the adversarial/helper ERC20 mocks
// that every golden trusts. An untested revert string in a mock silently
// mis-calibrates any golden that asserts it. Every arm here is hit by DIRECT
// real-state calls (no vm.mockCall, no toolchain wall).
//
// Sweep discipline (audited against each mock source, not pre-seed guesses):
//   * success transfers are SELF-transfers so ZERO never holds balance — a
//     funded victim makes the following "insufficient" expectRevert a ghost
//     pass (pre-seed bug class, 4 sites caught at audit);
//   * every require / && operand gets BOTH paths: false via an empty-operand
//     call, true via an explicit successful call (the pre-seed never swept the
//     TRUE arms of allowance checks — gaps report counts paths, not lines);
//   * in combined `require(bal && allow, "no")` mocks the left-FALSE probe
//     runs BEFORE any token ever reaches ZERO, so the two short-circuit
//     operands stay distinguishable.
import {Mock25C} from "./AbiSelectorLock25C.t.sol";
import {LadderMockToken} from "./ClaimableViewLadder.t.sol";
import {InvMockToken} from "./EscrowInvariant.t.sol";
import {MockTokenRefundOrder} from "./MainlineRefundBranchOrder.t.sol";
import {SplitLockMockToken} from "./P13SplitLockCoverage.t.sol";
import {TestToken} from "./Permit2Funding.t.sol";
import {FlipFalseToken} from "./SafeERC20FalseReturnMatrix.t.sol";
import {LatchMockToken} from "./SeatGateLatchGolden.t.sol";
import {D25MockToken} from "./SeatLedgerIntegrity25D.t.sol";
import {MockToken as MockTokenV1} from "./TandaBill.t.sol";
import {MockToken as MockTokenV2, BlockableToken} from "./TandaBillV2.t.sol";
import {SeatGateMockToken} from "./Ugly2SeatGateGolden.t.sol";
import {BoundaryMockToken} from "./V2BoundaryLedgerMatrix.t.sol";
import {CornerMockToken} from "./V2DefensiveMaskCorners.t.sol";
import {ReentrantToken} from "./XixiDesign02CeiGolden.t.sol";
import {NoReturnToken, FalseReturnToken} from "./XixiDesign02Q2Stranding.t.sol";
import {NoReturnTokenF, FalseReturnTokenF} from "./XixiDesign02Q2StrandingFast.t.sol";

interface ISemibool {
    function mint(address to, uint256 a) external;
    function approve(address sp, uint256 a) external returns (bool);
    function transfer(address to, uint256 a) external returns (bool);
    function transferFrom(address f, address t, uint256 a) external returns (bool);
}

interface INoRet {
    function mint(address to, uint256 a) external;
    function approve(address sp, uint256 a) external;
    function transfer(address to, uint256 a) external;
    function transferFrom(address f, address t, uint256 a) external;
}

contract MockHarnessArms30 is Test {
    address private constant FUNDED = address(0xF00D30);
    address private constant ZERO = address(0x2E00);

    /// @notice separate-require class: transfer "insufficient"; transferFrom
    /// "insufficient" then "allowance". All six require paths swept.
    function _sweepSep(ISemibool t) internal {
        t.mint(FUNDED, 1000);
        vm.prank(FUNDED);
        assertTrue(t.transfer(FUNDED, 10));            // transfer require TRUE
        vm.prank(ZERO);
        vm.expectRevert(bytes("insufficient"));
        t.transfer(FUNDED, 1);                         // transfer require FALSE
        vm.prank(FUNDED);
        t.approve(address(this), 500);
        assertTrue(t.transferFrom(FUNDED, FUNDED, 3)); // balance TRUE, allowance TRUE (self: ZERO stays empty)
        vm.prank(ZERO);
        t.approve(address(this), 500);
        vm.expectRevert(bytes("insufficient"));
        t.transferFrom(ZERO, FUNDED, 1);               // balance FALSE
        vm.prank(FUNDED);
        t.approve(address(this), 0);                   // revoke
        vm.expectRevert(bytes("allowance"));
        t.transferFrom(FUNDED, ZERO, 1);               // balance TRUE, allowance FALSE
    }

    /// @notice combined `require(bal && allow, "no")` transferFrom class with a
    /// separate "insufficient" transfer require (transferErr names it).
    /// Left-FALSE probe runs while ZERO is still empty; success probe uses
    /// FUNDED as source so both operands pass on distinct calls.
    function _sweepCombined(ISemibool t, string memory transferErr) internal {
        t.mint(FUNDED, 1000);
        vm.prank(FUNDED);
        assertTrue(t.transfer(FUNDED, 10));            // transfer require TRUE
        vm.prank(ZERO);
        vm.expectRevert(bytes(transferErr));
        t.transfer(FUNDED, 1);                         // transfer require FALSE
        vm.prank(ZERO);
        t.approve(address(this), 500);
        vm.expectRevert(bytes("no"));
        t.transferFrom(ZERO, FUNDED, 1);               // left operand FALSE (bal 0)
        vm.prank(FUNDED);
        t.approve(address(this), 500);
        assertTrue(t.transferFrom(FUNDED, ZERO, 1));   // both operands TRUE
        vm.prank(FUNDED);
        t.approve(address(this), 0);
        vm.expectRevert(bytes("no"));
        t.transferFrom(FUNDED, ZERO, 1);               // left TRUE, right FALSE
    }

    /// @notice no-return-value (USDT-class) revert sweep: transfer
    /// "insufficient", combined tf "no", both operands + success, no returns.
    function _sweepNoRet(INoRet t) internal {
        t.mint(FUNDED, 1000);
        vm.prank(FUNDED);
        t.transfer(FUNDED, 10);                        // success (self)
        vm.prank(ZERO);
        vm.expectRevert(bytes("insufficient"));
        t.transfer(FUNDED, 1);
        vm.prank(ZERO);
        t.approve(address(this), 500);
        vm.expectRevert(bytes("no"));
        t.transferFrom(ZERO, FUNDED, 1);               // left FALSE
        vm.prank(FUNDED);
        t.approve(address(this), 500);
        t.transferFrom(FUNDED, ZERO, 1);               // both TRUE
        vm.prank(FUNDED);
        t.approve(address(this), 0);
        vm.expectRevert(bytes("no"));
        t.transferFrom(FUNDED, ZERO, 1);               // right FALSE
    }

    // ── separate-require class (10 mocks) ────────────────────────────────────
    function testMock25CSepArms() public { _sweepSep(ISemibool(address(new Mock25C()))); }
    function testLadderSepArms() public { _sweepSep(ISemibool(address(new LadderMockToken()))); }
    function testInvSepArms() public { _sweepSep(ISemibool(address(new InvMockToken()))); }
    function testRefundOrderSepArms() public { _sweepSep(ISemibool(address(new MockTokenRefundOrder()))); }
    function testTestTokenSepArms() public { _sweepSep(ISemibool(address(new TestToken()))); }
    function testMockV1SepArms() public { _sweepSep(ISemibool(address(new MockTokenV1()))); }
    function testMockV2SepArms() public { _sweepSep(ISemibool(address(new MockTokenV2()))); }
    function testBlockableSepArms() public { _sweepSep(ISemibool(address(new BlockableToken()))); }
    function testBoundarySepArms() public { _sweepSep(ISemibool(address(new BoundaryMockToken()))); }
    function testCornerSepArms() public { _sweepSep(ISemibool(address(new CornerMockToken()))); }

    // ── combined-&& transferFrom class ───────────────────────────────────────
    function testLatchCombinedArms() public { _sweepCombined(ISemibool(address(new LatchMockToken())), "insufficient"); }
    function testD25CombinedArms() public { _sweepCombined(ISemibool(address(new D25MockToken())), "insufficient"); }
    function testSeatGateCombinedArms() public { _sweepCombined(ISemibool(address(new SeatGateMockToken())), "insufficient"); }
    function testCeiReentrantCombinedArms() public { _sweepCombined(ISemibool(address(new ReentrantToken())), "insufficient"); }

    function testFlipFalseArms() public {
        FlipFalseToken f = new FlipFalseToken();
        f.flip(false); // disarm the early return-false so the require arms are live
        _sweepCombined(ISemibool(address(f)), "insufficient");
    }

    // ── false-return class (no reverts; return-false paths) ──────────────────
    function testSplitLockFalseArms() public {
        SplitLockMockToken t = new SplitLockMockToken();
        t.mint(FUNDED, 1000);
        vm.prank(FUNDED);
        assertTrue(t.transfer(FUNDED, 10));                 // L21 condition FALSE (success)
        vm.prank(ZERO);
        assertFalse(t.transfer(FUNDED, 1));                 // L21 condition TRUE (return false)
        vm.prank(FUNDED);
        assertTrue(t.approve(address(this), 5));            // approve success line + return true
        assertFalse(t.transferFrom(FUNDED, ZERO, 10));      // allowed!=max TRUE, L30 allowed<amt TRUE
        assertTrue(t.transferFrom(FUNDED, ZERO, 3));        // L30 FALSE, L33 FALSE (success)
        vm.prank(FUNDED);
        t.approve(address(this), type(uint256).max);
        assertFalse(t.transferFrom(FUNDED, FUNDED, 99999)); // L29 FALSE (max skip), L33 TRUE
    }

    function testFalseReturnQ2Arms() public {
        FalseReturnToken t = new FalseReturnToken();
        t.mint(FUNDED, 10);
        vm.prank(FUNDED);
        assertTrue(t.approve(address(this), 10));
        assertFalse(t.transfer(FUNDED, 1));
        assertFalse(t.transferFrom(FUNDED, ZERO, 1));
    }

    function testFalseReturnFastArms() public {
        FalseReturnTokenF t = new FalseReturnTokenF();
        t.mint(FUNDED, 10);
        vm.prank(FUNDED);
        assertTrue(t.approve(address(this), 10));
        assertFalse(t.transfer(FUNDED, 1));
        assertFalse(t.transferFrom(FUNDED, ZERO, 1));
    }

    // ── no-return-value class ────────────────────────────────────────────────
    function testNoReturnQ2Arms() public { _sweepNoRet(INoRet(address(new NoReturnToken()))); }
    function testNoReturnFastArms() public { _sweepNoRet(INoRet(address(new NoReturnTokenF()))); }
}
