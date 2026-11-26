// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

import {TandaBillV2, IERC20} from "../contracts/TandaBillV2.sol";
import {FastTandaBillV2} from "../contracts/FastTandaBillV2.sol";
import {TandaBillFactory} from "../contracts/TandaBillFactory.sol";
import {MockToken} from "./TandaBillV2.t.sol";
import {Test} from "forge-std/Test.sol";

/// @title Engine36MaskRankFuzz [ENG-20261126-E36]
/// @notice First randomized (testFuzz) lane in the suite. Pins the snapshot-consistency
///         oracle shared by both twins: for ANY fuzzer-built roster with HOLED
///         expectedMasks (seat removals after enrollment) and ANY uneven expense amount,
///         initiateSettlement must produce a dense payout vector whose rank mapping,
///         sum, fairness bound and confirm/claim views agree with an independent
///         test-side oracle computed from raw seats(i) enumeration.
/// @dev    Hand-written goldens (ClaimableViewLadder, V2BoundaryLedgerMatrix,
///         FastTwinMatrixParity) pin fixed shapes; this suite explores the shape space.
///         Twin API deltas honored: V2 pulls (claimSettlement + claimedMask),
///         Fast pushes at execute (settlements() is a 7-tuple there).
///         Factory-lineage deploy (lane law: NEVER raw initialize from tests).
///         Pinned asymmetry: V2's settlementInitiated latch reopens on full drain
///         (BS-3.2/#185 LATCH-2); the Fast twin has no claim phase and therefore NO
///         reopen leg anywhere in source - its latch stays raised for the life of the
///         bill. The F-leg asserts THAT, not a symmetric fantasy.
contract Engine36MaskRankFuzzTest is Test {
    MockToken token;
    address owner = address(0xA11CE);
    TandaBillFactory factoryAnchor;

    function setUp() public {
        token = new MockToken();
        token.mint(owner, type(uint240).max);
    }

    // ─── helpers ──────────────────────────────────────────────────────────

    function _popcount(uint256 m) internal pure returns (uint256 c) {
        for (uint256 i = 0; i < 256; i++) {
            if ((m >> i) & 1 == 1) c++;
        }
    }

    /// @dev Factory-lineage deploy (lane law: NEVER raw initialize from tests).
    ///      Caller must set vm.prank(owner) immediately before.
    function _deploy(IERC20 t, address[] memory roster) internal returns (address) {
        return factoryAnchor.createBill(t, roster);
    }

    /// @dev Build a bill whose roster has holes: seats added, then the seats whose bit
    ///      is set in `removeBits` removed. Owner is always seat 0 and never removed.
    function _buildV2(uint256 seed, uint256 n, uint256 removeBits, uint256 amount)
        internal returns (TandaBillV2 bill, address[16] memory w, bool[16] memory active, uint256 k)
    {
        require(n >= 1 && n <= 16);
        for (uint256 i = 0; i < n; i++) {
            w[i] = i == 0 ? owner : address(uint160(uint256(keccak256(abi.encode(seed, i))) | 1));
            active[i] = true;
        }
        address[] memory roster = new address[](n);
        for (uint256 i = 0; i < n; i++) roster[i] = w[i];
        vm.prank(owner);
        bill = TandaBillV2(payable(_deploy(IERC20(address(token)), roster)));
        for (uint256 i = 1; i < n; i++) {
            if ((removeBits >> i) & 1 == 1) {
                vm.prank(owner); bill.removeSeat(i);
                active[i] = false;
            }
        }
        vm.startPrank(owner);
        bill.addExpense(amount);
        token.approve(address(bill), amount);
        bill.fundEscrow(amount);
        bill.initiateSettlement();
        vm.stopPrank();
        k = 0;
        for (uint256 i = 0; i < n; i++) if (active[i]) k++;
    }

    // ─── V2 (pull twin) ───────────────────────────────────────────────────

    function testFuzz_e36_v2_maskRankOracle(uint256 seed, uint256 rawAmount, uint256 nRaw, uint256 removeBits) public {
        seed = bound(seed, 1, type(uint160).max);
        uint256 n = bound(nRaw, 1, 16);
        uint256 amount = bound(rawAmount, 1, 240e6);

        factoryAnchor = new TandaBillFactory(address(new TandaBillV2()));
        (TandaBillV2 bill, address[16] memory w, bool[16] memory active, uint256 k) =
            _buildV2(seed, n, removeBits, amount);
        uint256[] memory payouts = bill.settlementPayouts(0);

        _v2VectorInvariants(bill, active, n, k, amount, payouts);
        _v2ZeroViews(bill, w, n);
        _v2ConfirmAndExecute(bill, w, active, n);
        _v2RankRemap(bill, w, active, n, amount, payouts);
        _v2HalfPullAndDrain(bill, w, active, n, amount, payouts);
    }

    /// @dev INV-A/B/C/D: mask width == active count == dense length; exact sum;
    ///      head-biased base/base+1 remainder; expectedMask bits vs roster oracle.
    ///      Phase split exists because legacy codegen (no viaIR - W5 size/gas gate pins
    ///      the default profile) hits Stack too deep on the flat ~20-local form.
    function _v2VectorInvariants(TandaBillV2 bill, bool[16] memory active, uint256 n,
        uint256 k, uint256 amount, uint256[] memory payouts) internal
    {
        // settlements() omits the dynamic payouts array; read the accessor in the caller.
        (uint256 totalAmount, , , uint256 expectedMask, , , , ) = bill.settlements(0);
        assertEq(totalAmount, amount, "A: total");
        assertEq(_popcount(expectedMask), k, "A: popcount vs oracle roster");
        assertEq(payouts.length, k, "A: dense length");
        assertEq(bill.activeSeatCount(), k, "A: view agrees");

        uint256 sum;
        for (uint256 i = 0; i < payouts.length; i++) sum += payouts[i];
        assertEq(sum, amount, "B: vector sum != total");

        uint256 base = amount / k;
        uint256 rem = amount % k;
        for (uint256 i = 0; i < k; i++) {
            assertApproxEqAbs(payouts[i], base, 1, "C: fairness bound");
            assertEq(payouts[i], base + (i < rem ? 1 : 0), "C: rank-order remainder");
        }
        for (uint256 i = 0; i < n; i++) {
            assertEq((expectedMask >> i) & 1, active[i] ? 1 : 0, "D: mask bit vs roster");
        }
    }

    /// @dev Pre-execute views: claimable uniformly zero, no confirms, no stamps.
    ///      Plus the ENGINE-35 bounds-guard legs: OOB settlementId answers 0/false/empty,
    ///      never Panic(0x32) - fuzzed here for free because the oracle already has the shape.
    function _v2ZeroViews(TandaBillV2 bill, address[16] memory w, uint256 n) internal {
        (, uint64 settledAt, , , uint256 confirmedMask, uint256 claimedMask, uint64 fullyConfirmedAt, ) =
            bill.settlements(0);
        assertEq(settledAt, 0);
        assertEq(fullyConfirmedAt, 0);
        assertEq(confirmedMask, 0);
        assertEq(claimedMask, 0);
        for (uint256 i = 0; i < n; i++) {
            assertEq(bill.claimablePayout(0, w[i]), 0, "V2: claimable before execute");
            assertEq(bill.isSeatConfirmed(0, w[i]), false, "V2: confirmed before confirm");
        }
        assertEq(bill.claimablePayout(1, w[0]), 0, "V2: claimable OOB -> 0");
        assertFalse(bill.isSeatConfirmed(1, w[0]), "V2: isSeatConfirmed OOB -> false");
        assertEq(bill.settlementPayouts(1).length, 0, "V2: settlementPayouts OOB -> empty");
    }

    /// @dev Full confirm over the HOLED roster, then exact boundary execute (>= WINDOW):
    ///      revert one tick before, success exactly at fullyConfirmedAt + SETTLEMENT_WINDOW.
    function _v2ConfirmAndExecute(TandaBillV2 bill, address[16] memory w, bool[16] memory active, uint256 n) internal {
        (, , , uint256 expectedMask, , , , ) = bill.settlements(0);
        for (uint256 i = 0; i < n; i++) {
            if (active[i]) { vm.prank(w[i]); bill.confirmSettlement(0); }
        }
        (, , , , uint256 confirmedMask, , uint64 fullyConfirmedAt, ) = bill.settlements(0);
        assertEq(confirmedMask, expectedMask, "V2: partial ladder left confirms");
        assertTrue(fullyConfirmedAt != 0, "V2: fc stamp");

        vm.prank(owner); vm.expectRevert(TandaBillV2.WindowNotElapsed.selector);
        bill.executeSettlement(0);
        vm.warp(uint256(fullyConfirmedAt) + uint256(bill.SETTLEMENT_WINDOW()));
        vm.prank(owner); bill.executeSettlement(0);
    }

    /// @dev INV-E (pull twin): per-seat claimable == dense rank value; ladder sums to total.
    function _v2RankRemap(TandaBillV2 bill, address[16] memory w, bool[16] memory active,
        uint256 n, uint256 amount, uint256[] memory payouts) internal
    {
        uint256 claimableSum;
        uint256 rank;
        for (uint256 i = 0; i < n; i++) {
            if (!active[i]) continue;
            uint256 cp = bill.claimablePayout(0, w[i]);
            assertEq(cp, payouts[rank], "V2: rank remap");
            claimableSum += cp;
            rank++;
        }
        assertEq(claimableSum, amount, "V2: claimable ladder sums to total");
    }

    /// @dev Pull even-rank seats -> mask/sum/residual/balance consistency, LATCH-2 hold
    ///      condition, then drain the rest -> latch reopens, bill at zero.
    ///      k==1 is a legal fuzz shape (n==1, or every peer removed): the even-rank loop
    ///      drains the single share in one pull, so the latch reopens IMMEDIATELY.
    ///      The honest pin is "latch holds iff unclaimed shares remain".
    function _v2HalfPullAndDrain(TandaBillV2 bill, address[16] memory w, bool[16] memory active,
        uint256 n, uint256 amount, uint256[] memory payouts) internal
    {
        uint256 rank;
        uint256 pulledMaskExpected;
        uint256 pulledSum;
        for (uint256 i = 0; i < n; i++) {
            if (!active[i]) continue;
            if (rank % 2 == 0) {
                vm.prank(w[i]); bill.claimSettlement(0);
                pulledMaskExpected |= (1 << i);
                pulledSum += payouts[rank];
            }
            rank++;
        }
        (, , , , , uint256 claimedMask, , ) = bill.settlements(0);
        assertEq(claimedMask, pulledMaskExpected, "V2: claimedMask tracks pulls");

        uint256 residual;
        rank = 0;
        for (uint256 i = 0; i < n; i++) {
            if (!active[i]) continue;
            uint256 cp = bill.claimablePayout(0, w[i]);
            assertEq(cp, (rank % 2 == 0) ? 0 : payouts[rank], "V2: post-claim view");
            residual += cp;
            rank++;
        }
        assertEq(residual, amount - pulledSum, "V2: residual == unclaimed");
        assertEq(token.balanceOf(address(bill)), residual, "V2: bill holds exactly unclaimed");
        assertEq(bill.settlementInitiated(), payouts.length > 1, "V2: latch holds iff shares remain");

        rank = 0;
        for (uint256 i = 0; i < n; i++) {
            if (!active[i]) continue;
            if (rank % 2 == 1) { vm.prank(w[i]); bill.claimSettlement(0); }
            rank++;
        }
        assertFalse(bill.settlementInitiated(), "V2: drained latch");
        assertEq(token.balanceOf(address(bill)), 0, "V2: bill drained");
    }

    // ─── Fast twin (push at execute) ──────────────────────────────────────


    /// @dev Deploy + holed roster + fund + initiate for the Fast twin (mirrors _buildV2).
    function _buildFast(uint256 seed, uint256 n, uint256 removeBits, uint256 amount)
        internal returns (FastTandaBillV2 bill, address[16] memory w, bool[16] memory active, uint256 k)
    {
        require(n >= 1 && n <= 16);
        for (uint256 i = 0; i < n; i++) {
            w[i] = i == 0 ? owner : address(uint160(uint256(keccak256(abi.encode(seed, i))) | 1));
            active[i] = true;
        }
        address[] memory roster = new address[](n);
        for (uint256 i = 0; i < n; i++) roster[i] = w[i];
        vm.prank(owner);
        bill = FastTandaBillV2(payable(_deploy(IERC20(address(token)), roster)));
        for (uint256 i = 1; i < n; i++) {
            if ((removeBits >> i) & 1 == 1) { vm.prank(owner); bill.removeSeat(i); active[i] = false; }
        }
        k = 0;
        for (uint256 i = 0; i < n; i++) if (active[i]) k++;
        vm.startPrank(owner);
        bill.addExpense(amount);
        token.approve(address(bill), amount);
        bill.fundEscrow(amount);
        bill.initiateSettlement();
        vm.stopPrank();
    }

    /// @dev Confirm ladder over the holed roster, then exact-window-boundary execute.
    function _fastConfirmAndExecute(FastTandaBillV2 bill, address[16] memory w, bool[16] memory active, uint256 n) internal {
        for (uint256 i = 0; i < n; i++) {
            if (active[i]) { vm.prank(w[i]); bill.confirmSettlement(0); }
        }
        (, , , uint256 expNow, uint256 confNow, uint64 fullyConfirmedAt, ) = bill.settlements(0);
        assertEq(confNow, expNow, "F: ladder");
        vm.prank(owner); vm.expectRevert(FastTandaBillV2.WindowNotElapsed.selector);
        bill.executeSettlement(0);
        vm.warp(uint256(fullyConfirmedAt) + uint256(bill.SETTLEMENT_WINDOW()));
        vm.prank(owner); bill.executeSettlement(0);
    }

    /// @dev Push twin: every active expected seat received exactly its dense rank payout.
    ///      DELTA-based on purpose: seat 0 IS the owner, whose balance starts at the
    ///      setUp mint (2^240-1) - an absolute balance==payout pin can never hold there.
    ///      Snapshot is taken after funding, so the owner's escrow leg is already out.
    function _fastPushVerify(FastTandaBillV2 bill, address[16] memory w, bool[16] memory active,
        uint256 n, uint256[16] memory balBefore) internal
    {
        uint256[] memory payouts = bill.settlementPayouts(0);
        uint256 rank = 0;
        for (uint256 i = 0; i < n; i++) {
            if (!active[i]) continue;
            assertEq(token.balanceOf(w[i]) - balBefore[i], payouts[rank], "F: push delta");
            rank++;
        }
        // owner funded escrow; bill fully drained at execute (push semantics)
        assertEq(token.balanceOf(address(bill)), 0, "F: bill drained at execute");
        // Source-truth pin (grep: Fast has ONLY 'settlementInitiated = true', no reset
        // leg in execute/refund) - the raised latch here is deliberate asymmetry vs the
        // V2 pull twin's BS-3.2/#185 LATCH-2 reopen, exactly as the @dev header claims.
        assertTrue(bill.settlementInitiated(), "F: latch stays raised - no reopen leg in Fast");
    }

    /// @dev Post-initiation settlement oracle for the Fast twin (dense-vector invariants A-D).
    function _fastOracle(FastTandaBillV2 bill, bool[16] memory active, uint256 n, uint256 k, uint256 amount) internal {
        (uint256 totalAmount, , , uint256 expectedMask, uint256 confirmedMask, uint64 fc0, ) = bill.settlements(0);
        uint256[] memory payouts = bill.settlementPayouts(0);
        assertEq(totalAmount, amount, "F-A: total");
        assertEq(_popcount(expectedMask), k, "F-A: popcount");
        assertEq(payouts.length, k, "F-A: dense length");
        assertEq(bill.activeSeatCount(), k, "F-A: view agrees");
        uint256 sum;
        for (uint256 i = 0; i < payouts.length; i++) sum += payouts[i];
        assertEq(sum, amount, "F-B: sum");
        uint256 base = amount / k;
        uint256 rem = amount % k;
        for (uint256 i = 0; i < k; i++) assertEq(payouts[i], base + (i < rem ? 1 : 0), "F-C: rank remainder");
        for (uint256 i = 0; i < n; i++) assertEq((expectedMask >> i) & 1, active[i] ? 1 : 0, "F-D: mask bits");
        assertEq(fc0, 0);
        assertEq(confirmedMask, 0);
        // ENGINE-35 bounds-guard legs (Fast twin): OOB settlementId answers empty/false.
        assertEq(bill.settlementPayouts(1).length, 0, "F: settlementPayouts OOB -> empty");
        assertFalse(bill.isSeatConfirmed(1, address(0x1)), "F: isSeatConfirmed OOB -> false");
    }

    function testFuzz_e36_fast_maskRankOracle(uint256 seed, uint256 rawAmount, uint256 nRaw, uint256 removeBits) public {
        seed = bound(seed, 1, type(uint160).max);
        uint256 n = bound(nRaw, 1, 16);
        uint256 amount = bound(rawAmount, 1, 240e6);

        factoryAnchor = new TandaBillFactory(address(new FastTandaBillV2()));
        (FastTandaBillV2 bill, address[16] memory w, bool[16] memory active, uint256 k) =
            _buildFast(seed, n, removeBits, amount);

        _fastOracle(bill, active, n, k, amount);
        uint256[16] memory balBefore;
        for (uint256 i = 0; i < n; i++) balBefore[i] = token.balanceOf(w[i]);
        _fastConfirmAndExecute(bill, w, active, n);
        _fastPushVerify(bill, w, active, n, balBefore);
    }
}
