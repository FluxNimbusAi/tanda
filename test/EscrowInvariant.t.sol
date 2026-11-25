// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

import {TandaBillV2, IERC20} from "../contracts/TandaBillV2.sol";
import {TandaBillFactory} from "../contracts/TandaBillFactory.sol";
import {Test} from "forge-std/Test.sol";

/// @notice Minimal ERC-20 mock (same shape as test/TandaBillV2.t.sol MockToken, kept
///         file-local so the invariant suite compiles standalone).
contract InvMockToken {
    mapping(address => uint256) public balanceOf;
    mapping(address => mapping(address => uint256)) public allowance;

    function mint(address to, uint256 amount) external {
        balanceOf[to] += amount;
    }

    function transfer(address to, uint256 amount) external returns (bool) {
        require(balanceOf[msg.sender] >= amount, "insufficient");
        balanceOf[msg.sender] -= amount;
        balanceOf[to] += amount;
        return true;
    }

    function transferFrom(address from, address to, uint256 amount) external returns (bool) {
        require(balanceOf[from] >= amount, "insufficient");
        require(allowance[from][msg.sender] >= amount, "allowance");
        balanceOf[from] -= amount;
        balanceOf[to] += amount;
        allowance[from][msg.sender] -= amount;
        return true;
    }

    function approve(address spender, uint256 amount) external returns (bool) {
        allowance[msg.sender][spender] = amount;
        return true;
    }
}

/// @title EscrowInvariantHandler
/// @notice Fuzz driver for TandaBillV2 sequence safety. Every handler function pranks a
///         fixed actor set (owner + 5 seat wallets), bounds arguments into cheap ranges,
///         and swallows expected reverts with try/catch (invariant fail_on_revert is off).
///         Records ONLY the accounting the invariants need (live settlement count and
///         per-settlement claimed totals); all truth assertions re-read the bill itself.
/// @dev    DIRECT-PATH LAW (why no factory.callBill indirection is needed): the bill's
///         factory anchor == the TandaBillFactory contract (initialize sets factory =
///         msg.sender, which is the factory during createBill), never the test or handler.
///         A pranked direct EOA call therefore takes _caller()'s fallback branch
///         (_caller() == msg.sender == the pranked actor) - the intended production direct
///         path, mirroring test/TandaBillV2.t.sol. Routing every leg through the forwarder
///         would pin _caller() to the single forwarding identity and freeze all role-
///         gated legs, making the whole fuzz vacuously green.
///         fundEscrow is intentionally exercised with third-party funders too (no owner
///         gate in the contract since v2.2); refund-to-owner is the documented Gap-3 MVP
///         behavior. Permit2 funding (fundEscrowFromPermit2) is out of scope: it needs the
///         etched singleton fixture and is golden-covered in test/Permit2Funding.t.sol.
contract EscrowInvariantHandler is Test {
    TandaBillV2 public bill;
    InvMockToken public token;
    address public ownerAddr;
    address[] public actors;
    uint256 public actorCount;

    uint256 public liveSettlementCount; // +1 only when initiateSettlement succeeded
    uint256 public rosterLen;           // seats.length total (incl. inactive after removals)
    mapping(uint256 => uint256) public claimedTotal; // settlementId => sum of payouts pulled
    uint256 private _nf = 1;            // deterministic non-zero nullifier counter

    constructor(
        address bill_,
        address token_,
        address owner_,
        address[] memory actorList,
        uint256 initialRosterLen
    ) {
        bill = TandaBillV2(bill_);
        token = InvMockToken(token_);
        ownerAddr = owner_;
        actors = actorList;
        actorCount = actorList.length;
        rosterLen = initialRosterLen;
        uint256 maxAmt = type(uint256).max;
        for (uint256 i = 0; i < actorList.length; i++) {
            token.mint(actorList[i], 1e24);
            vm.prank(actorList[i]);
            token.approve(bill_, maxAmt);
        }
        token.mint(owner_, 1e24);
        vm.prank(owner_);
        token.approve(bill_, maxAmt);
    }

    // ---- money legs ----

    function addExpense(uint256 a) external {
        vm.prank(ownerAddr);
        try bill.addExpense(bound(a, 1, 1e18)) {} catch {}
    }

    function fund(uint256 a, uint256 pick) external {
        address funder = pick % 4 == 0 ? ownerAddr : actors[pick % actorCount];
        vm.prank(funder);
        try bill.fundEscrow(bound(a, 1, 1e18)) {} catch {}
    }

    function initiate() external {
        vm.prank(ownerAddr);
        try bill.initiateSettlement() { liveSettlementCount += 1; } catch {}
    }

    function confirmNext(uint256 sPick, uint256 aPick) external {
        if (liveSettlementCount == 0) return;
        uint256 sid = sPick % liveSettlementCount;
        address w = actors[aPick % actorCount];
        vm.prank(w);
        try bill.confirmSettlement(sid) {} catch {}
    }

    function executeNext(uint256 sPick) external {
        if (liveSettlementCount == 0) return;
        uint256 sid = sPick % liveSettlementCount;
        // executeSettlement is intentionally caller-free (Gap-2 addendum): no prank.
        try bill.executeSettlement(sid) {} catch {}
    }

    function claim(uint256 sPick, uint256 aPick) external {
        if (liveSettlementCount == 0) return;
        uint256 sid = sPick % liveSettlementCount;
        address w = actors[aPick % actorCount];
        uint256 amt = bill.claimablePayout(sid, w); // real consumer API, same-seat pre-read
        vm.prank(w);
        try bill.claimSettlement(sid) { claimedTotal[sid] += amt; } catch {}
    }

    function refund(uint256 sPick) external {
        if (liveSettlementCount == 0) return;
        uint256 sid = sPick % liveSettlementCount;
        vm.prank(ownerAddr);
        try bill.refundSettlement(sid) {} catch {}
    }

    // ---- roster legs ----

    function addSeat(uint256 pick) external {
        vm.prank(ownerAddr);
        try bill.addSeat(actors[pick % actorCount]) { rosterLen += 1; } catch {}
    }

    function registerSeat(uint256 pick) external {
        bytes32 nf = keccak256(abi.encode(_nf++));
        address w = actors[pick % actorCount];
        // signal content is free-form for the contract (it only stores keccak256(signal));
        // bind nf+wallet so each grant carries a distinct signal hash.
        bytes memory sig = abi.encodePacked(nf, w);
        vm.prank(ownerAddr);
        try bill.registerSeat(nf, w, sig) { rosterLen += 1; } catch {}
    }

    function removeSeat(uint256 pick) external {
        if (rosterLen == 0) return;
        vm.prank(ownerAddr);
        try bill.removeSeat(pick % rosterLen) {} catch {}
    }

    function rotate(uint256 seatPick, uint256 actorPick, uint256 asOwner) external {
        if (rosterLen == 0) return;
        uint256 seatId = seatPick % rosterLen;
        (address curWallet, uint64 joinedAt, bool active) = bill.seats(seatId);
        curWallet; joinedAt; active; // referenced to silence unused warnings
        address newW = actors[actorPick % actorCount];
        address caller = asOwner % 2 == 0 ? ownerAddr : curWallet;
        vm.prank(caller);
        try bill.rotateSeatWallet(seatId, newW) {} catch {}
    }

    // ---- time leg ----

    function warp(uint256 d) external {
        // forward-only, bounded to 3 days so both SETTLEMENT_WINDOW (1h) and
        // MAX_HOLD (72h) legs become reachable inside a fuzz run.
        vm.warp(block.timestamp + bound(d, 0, 3 days));
    }
}

/// @title EscrowInvariantTest
/// @notice ENGINE 25B (2026-11-25): sequence-level safety net ABOVE the saturated branch
///         matrices (t_66303ab9, t_1086a045 closed contracts/* at 100% coverage). Five
///         carded product invariants hold under arbitrary interleavings of all 12 product
///         entrypoints, pranked actors, and time warps; plus a roster-mapping invariant, an
///         oracle cross-check that overdetermines the money model, a deterministic golden
///         and six falsification controls that make a vacuously-green harness impossible:
///         every invariant is a thin assert over a shared _holds_* evaluator, and each
///         control corrupts exactly ONE side of the money model via vm.store, asserting the
///         evaluator flips to false. Handler counters roll back with each invariant run's
///         snapshot, so per-sequence reachability cannot be asserted inside an invariant -
///         the golden plus the controls' engagement proof carry that instead.
contract EscrowInvariantTest is Test {
    EscrowInvariantHandler internal handler;
    TandaBillV2 internal bill;
    InvMockToken internal token;
    address internal owner;
    address[5] internal actorsArr;

    function setUp() public {
        token = new InvMockToken();
        owner = makeAddr("owner");

        address[] memory actors = new address[](5);
        actors[0] = makeAddr("s0");
        actors[1] = makeAddr("s1");
        actors[2] = makeAddr("s2");
        actors[3] = makeAddr("s3");
        actors[4] = makeAddr("s4");
        actorsArr = [actors[0], actors[1], actors[2], actors[3], actors[4]];

        // Factory lineage law: impl -> factory -> createBill (never direct initialize()).
        address impl = address(new TandaBillV2());
        TandaBillFactory fac = new TandaBillFactory(impl);
        address[] memory initial = new address[](2);
        initial[0] = actors[0];
        initial[1] = actors[1];
        vm.prank(owner);
        address billAddr = fac.createBill(IERC20(address(token)), initial);
        bill = TandaBillV2(billAddr);

        handler = new EscrowInvariantHandler(billAddr, address(token), owner, actors, initial.length);

        // Curated selectors: the fuzzer touches product entrypoints on the handler only,
        // never inherited Test internals.
        bytes4[] memory sels = new bytes4[](12);
        sels[0] = handler.addExpense.selector;
        sels[1] = handler.fund.selector;
        sels[2] = handler.initiate.selector;
        sels[3] = handler.confirmNext.selector;
        sels[4] = handler.executeNext.selector;
        sels[5] = handler.claim.selector;
        sels[6] = handler.refund.selector;
        sels[7] = handler.addSeat.selector;
        sels[8] = handler.registerSeat.selector;
        sels[9] = handler.removeSeat.selector;
        sels[10] = handler.rotate.selector;
        sels[11] = handler.warp.selector;
        targetSelector(FuzzSelector({addr: address(handler), selectors: sels}));
        targetContract(address(handler));
    }

    // ---- shared evaluators (single source of truth for fuzz + falsification) ----

    /// @dev INV-1 predicate: contract token balance == live escrow + reserved value of
    ///      every non-refunded settlement that has not yet been pulled by its seats.
    function _holds_conservation() internal view returns (bool) {
        uint256 n = handler.liveSettlementCount();
        uint256 pending;
        for (uint256 i = 0; i < n; i++) {
            (uint256 totalAmount, , , , , , , bool refunded) = bill.settlements(i);
            if (!refunded) {
                pending += totalAmount - handler.claimedTotal(i);
            }
            totalAmount;
        }
        return token.balanceOf(address(bill)) == bill.escrowBalance() + pending;
    }

    /// @dev INV-2 predicate: every dense payout vector sums exactly to totalAmount
    ///      (base*count + remainder rule, no peanut leakage on uneven splits).
    function _holds_payout_sum() internal view returns (bool) {
        uint256 n = handler.liveSettlementCount();
        for (uint256 i = 0; i < n; i++) {
            (uint256 totalAmount, , , , , , , ) = bill.settlements(i);
            uint256[] memory p = bill.settlementPayouts(i);
            uint256 sum;
            for (uint256 j = 0; j < p.length; j++) sum += p[j];
            if (sum != totalAmount) return false;
        }
        return true;
    }

    /// @dev INV-3 predicate: claimedMask stays inside the initiation snapshot and the
    ///      handler-recorded claimed value never exceeds the reservation.
    function _holds_claim_bounds() internal view returns (bool) {
        uint256 n = handler.liveSettlementCount();
        for (uint256 i = 0; i < n; i++) {
            (uint256 totalAmount, , , uint256 expectedMask, , uint256 claimedMask, , ) =
                bill.settlements(i);
            if ((claimedMask & ~expectedMask) != 0) return false;
            if (handler.claimedTotal(i) > totalAmount) return false;
        }
        return true;
    }

    /// @dev INV-4 predicate: a settlement is executed XOR refunded, never both.
    function _holds_terminal_exclusion() internal view returns (bool) {
        uint256 n = handler.liveSettlementCount();
        for (uint256 i = 0; i < n; i++) {
            (, uint64 settledAt, , , , , , bool refunded) = bill.settlements(i);
            if (settledAt != 0 && refunded) return false;
        }
        return true;
    }

    /// @dev true when every settlement is refunded, or executed with all expected shares
    ///      claimed (product mirror of _allSettlementsDrained, contract-side reads).
    function _allDrained(uint256 n) internal view returns (bool) {
        for (uint256 i = 0; i < n; i++) {
            (, uint64 settledAt, , uint256 expectedMask, , uint256 claimedMask, , bool refunded) =
                bill.settlements(i);
            if (!refunded && (settledAt == 0 || claimedMask != expectedMask)) return false;
        }
        return true;
    }

    /// @dev INV-5 predicate (LATCH-2, BS-3.2/#185): settlementInitiated is true EXACTLY
    ///      while at least one settlement is non-refunded and (unexecuted or not fully
    ///      drained). Both drift directions fail: stuck-frozen and premature reopen.
    function _holds_latch() internal view returns (bool) {
        uint256 n = handler.liveSettlementCount();
        return bill.settlementInitiated() == (!_allDrained(n) && n > 0);
    }

    /// @dev INV-6 predicate: seatIdOf is the O(1) confirm/claim anchor - every active
    ///      seat wallet maps back to its own index + 1 (rotation and re-invite legs).
    function _holds_roster() internal view returns (bool) {
        uint256 len = handler.rosterLen();
        for (uint256 i = 0; i < len; i++) {
            (address w, , bool active) = bill.seats(i);
            if (active && bill.seatIdOf(w) != i + 1) return false;
        }
        return true;
    }

    /// @dev contract-derived claimed sum for settlement i: claimedMask bits mapped through
    ///      the dense payout-rank rule (independent mirror of _payoutAt).
    function _contractClaimedSum(uint256 i) internal view returns (uint256 sum) {
        (, , , uint256 expectedMask, , uint256 claimedMask, , ) = bill.settlements(i);
        uint256[] memory p = bill.settlementPayouts(i);
        uint256 m = claimedMask & expectedMask; // defensive; INV-3 pins the difference to 0
        uint256 seatId;
        while (m != 0) {
            if (m & 1 == 1) {
                uint256 rank;
                for (uint256 b = 0; b < seatId; b++) {
                    if ((expectedMask & (uint256(1) << b)) != 0) rank += 1;
                }
                sum += p[rank];
            }
            m >>= 1;
            seatId += 1;
        }
    }

    /// @dev INV-1b predicate: the handler's independently recorded claim totals (tracked
    ///      from claimablePayout pre-reads, never from raw contract state) equal the
    ///      contract-derived claimed sums; a refunded settlement was never claimed. Two
    ///      independent derivations of the money model must agree at every sequence step.
    function _holds_oracle() internal view returns (bool) {
        uint256 n = handler.liveSettlementCount();
        for (uint256 i = 0; i < n; i++) {
            (, , , , , , , bool refunded) = bill.settlements(i);
            uint256 sum = _contractClaimedSum(i);
            if (refunded) {
                // refund requires settledAt == 0, so no seat could have claimed first
                if (sum != 0 || handler.claimedTotal(i) != 0) return false;
            } else if (handler.claimedTotal(i) != sum) {
                return false;
            }
        }
        return true;
    }

    // ---- the five carded invariants + roster + oracle cross-check ----

    /// INV-1 escrow conservation.
    function invariant_escrow_conservation() public view {
        assertTrue(_holds_conservation(), "escrow conservation broken");
    }

    /// INV-2 payout vector sum == settlement total.
    function invariant_payout_sum_matches_total() public view {
        assertTrue(_holds_payout_sum(), "payout vector does not sum to total");
    }

    /// INV-3 claim bounds (mask snapshot + over-claim).
    function invariant_claim_bounds() public view {
        assertTrue(_holds_claim_bounds(), "claim bounds violated");
    }

    /// INV-4 terminal exclusion (executed XOR refunded).
    function invariant_no_double_terminal() public view {
        assertTrue(_holds_terminal_exclusion(), "settlement both executed and refunded");
    }

    /// INV-5 LATCH-2 freeze semantics.
    function invariant_freeze_latch() public view {
        assertTrue(_holds_latch(), "LATCH-2 freeze drift");
    }

    /// INV-6 roster mapping consistency.
    function invariant_roster_consistency() public view {
        assertTrue(_holds_roster(), "seatIdOf drift on active seat");
    }

    /// INV-1b claim-oracle cross-check.
    function invariant_handler_oracle_matches_contract() public view {
        assertTrue(_holds_oracle(), "claim oracle drift");
    }

    // ---- deterministic reachability golden (anti-vacuity part 1) ----
    //
    // Drives every product leg once, in the honest order, against a fresh setUp bill:
    // addExpense, third-party fundEscrow, pre-initiation rotate, initiate, freeze-gate
    // revert, confirm (both seats), window warp, execute (caller-free), claim (both),
    // LATCH-2 reopen + post-reopen addSeat, registerSeat, MAX_HOLD refund. If harness
    // wiring rots (wrong anchor, broken prank, gate drift) this fails loudly even when
    // the fuzz invariants pass on sequences that never reached the money legs.

    function test_golden_full_lifecycle_all_legs_reachable() public {
        address s0 = actorsArr[0];
        address s1 = actorsArr[1];
        address s2 = actorsArr[2];
        address s3 = actorsArr[3];
        address s4 = actorsArr[4];
        uint256 bal0 = token.balanceOf(s0);

        // ---- Round 1: expense funded by a THIRD PARTY (s0), seat 0 rotated pre-initiation.
        vm.prank(owner);
        bill.addExpense(1000);
        vm.prank(s0);
        bill.fundEscrow(1000);
        assertEq(bill.escrowBalance(), 1000, "fund leg dead");
        assertEq(token.balanceOf(address(bill)), 1000, "funding pull wrong");
        assertEq(token.balanceOf(s0), bal0 - 1000, "third-party funder not debited");

        vm.prank(owner);
        bill.rotateSeatWallet(0, s4); // owner recovery leg, pre-settlement
        assertEq(bill.seatIdOf(s4), 1, "rotate leg dead");
        assertEq(bill.seatIdOf(s0), 0, "rotate stale mapping");

        vm.prank(owner);
        bill.initiateSettlement();
        assertEq(bill.settlementInitiated(), true, "latch not set on initiate");

        // Freeze gate live: roster mutation must revert mid-round.
        vm.prank(owner);
        vm.expectRevert(TandaBillV2.SettlementInitiatedAlready.selector);
        bill.addSeat(s2);

        vm.prank(s4);
        bill.confirmSettlement(0);
        vm.prank(s1);
        bill.confirmSettlement(0); // last expected seat arms the window
        (, , , , , , uint64 fullyConfirmedAt, ) = bill.settlements(0);
        assertTrue(fullyConfirmedAt != 0, "confirm leg dead (window never armed)");

        vm.warp(block.timestamp + 1 hours + 1);
        bill.executeSettlement(0); // caller-free leg (Gap-2 addendum): from test contract
        (, uint64 settledAt0, , , , , , ) = bill.settlements(0);
        assertTrue(settledAt0 != 0, "execute leg dead");

        vm.prank(s4);
        bill.claimSettlement(0);
        vm.prank(s1);
        bill.claimSettlement(0);
        assertEq(token.balanceOf(s4), bal0 + 500, "rotated seat payout wrong");
        assertEq(token.balanceOf(s1), bal0 + 500, "seat payout wrong");
        assertEq(token.balanceOf(address(bill)), 0, "escrow not drained");
        assertEq(bill.escrowBalance(), 0, "escrowBalance not drained");
        // LATCH-2: all drained -> roster freeze lifts for the next round.
        assertEq(bill.settlementInitiated(), false, "LATCH-2 reopen failed");
        vm.prank(owner);
        bill.addSeat(s2); // now legal again (reopened roster)
        assertEq(bill.seatIdOf(s2), 3, "post-reopen addSeat dead");

        // ---- Round 2: registerSeat (World ID leg) + MAX_HOLD refund path.
        bytes32 nf = keccak256("nullifier-s3-round2");
        vm.prank(owner);
        bill.registerSeat(nf, s3, abi.encodePacked(nf, s3));
        assertEq(bill.seatIdOf(s3), 4, "registerSeat leg dead");
        assertEq(bill.seatNullifierOf(nf), s3, "nullifier burn leg dead");

        vm.prank(owner);
        bill.addExpense(600);
        vm.prank(s1);
        bill.fundEscrow(600);
        vm.prank(owner);
        bill.initiateSettlement(); // active seats {s4, s1, s2, s3} -> payouts 150 x 4
        (uint256 total2, , , uint256 mask2, , , , ) = bill.settlements(1);
        assertEq(total2, 600, "round-2 total wrong");
        assertEq(mask2, 0xF, "round-2 expectedMask wrong");

        // s2/s3 never confirm -> MAX_HOLD refund leg (fullyConfirmedAt stays 0):
        uint256 ownerBalRef = token.balanceOf(owner);
        vm.warp(block.timestamp + 72 hours + 1);
        vm.prank(owner);
        bill.refundSettlement(1);
        assertEq(token.balanceOf(owner), ownerBalRef + 600, "refund leg dead");
        (, , , , , , , bool refunded2) = bill.settlements(1);
        assertTrue(refunded2, "refund flag not set");
        assertEq(bill.settlementInitiated(), false, "refund did not drain LATCH-2");
        assertEq(token.balanceOf(address(bill)), 0, "post-refund escrow not zero");
    }

    // ---- falsification controls (anti-vacuity part 2: mutation testing) ----
    //
    // An invariant that can never fail is decoration. Each control drives a REAL round
    // through the fuzz handler itself (engagement proof: initiate + both claims recorded),
    // asserts every evaluator HOLDS on the honest drained state (which pins the exact live
    // storage route), corrupts EXACTLY ONE side via vm.store, then asserts that evaluator
    // FLIPS. A wrong slot would be a harmless no-op and the control would fail, not
    // ghost-pass - and it DID exactly that on first authoring, catching two assumed-slot
    // errors before merge. Layout below is `forge inspect --json storageLayout` PROBE-
    // VERIFIED 2026-11-25 (packing shifts naive declaration counts):
    //
    // TandaBillV2 slots: 0 token | 1 owner+(_initialized byte20) | 2 seats[] | 3 seatIdOf
    //   4 expenses[] | 5 settlements[] | 6 escrowBalance | 7 settlementInitiated(bit0)+
    //   factory(bits 8..167) | 8 seatNullifierOf | 9 seatNullifierSignalHash
    // Settlement struct (7 words/element): w0 totalAmount | w1 payouts ptr | w2 settledAt
    //   (bytes0-7)+initiatedAt(bytes8-15) | w3 expectedMask | w4 confirmedMask |
    //   w5 claimedMask | w6 fullyConfirmedAt(bytes0-7)+refunded(byte8)
    // Handler slots: IS_TEST+bill @31 (inherited Test consumes 0-30) | 32 token |
    //   33 ownerAddr | 34 actors[] | 35 actorCount | 36 liveSettlementCount | 37 rosterLen |
    //   38 claimedTotal mapping | 39 _nf
    // InvMockToken slots: 0 balanceOf mapping | 1 allowance mapping

    /// @dev Drive expense + third-party fund + initiate through the FUZZ HANDLER itself,
    ///      then both seats confirm + warp + execute + claim (claims via handler too, so
    ///      the oracle records them), leaving a fully drained settlement 0 with n == 1 and
    ///      every invariant loop engaged (non-vacuous by construction).
    function _engageHandlerRound() internal {
        handler.addExpense(900);
        handler.fund(900, 1); // pick=1 -> actor s0 funds (third-party funder leg)
        handler.initiate();
        assertEq(handler.liveSettlementCount(), 1, "engagement: initiate dead");
        (uint256 total, , , , , , , ) = bill.settlements(0);
        assertEq(total, 900, "engagement: settlement not real");
        // Pin exact seats (handler confirmNext picks a fuzzed actor): both expected seats.
        vm.prank(actorsArr[0]);
        bill.confirmSettlement(0);
        vm.prank(actorsArr[1]);
        bill.confirmSettlement(0);
        vm.warp(block.timestamp + 1 hours + 1);
        bill.executeSettlement(0);
        handler.claim(0, 0);    // s0 claim via handler (oracle records 450)
        handler.claim(0, 1);    // s1 claim via handler (oracle records 450 more)
        assertEq(handler.claimedTotal(0), 900, "engagement: oracle dead");
        assertEq(bill.settlementInitiated(), false, "engagement: LATCH-2 reopen dead");
    }

    function test_falsify_controls_detect_every_corruption() public {
        _engageHandlerRound();

        // Honest drained state: ALL evaluators hold (loops ran, n == 1).
        assertTrue(_holds_conservation(), "control setup: conservation false pre-store");
        assertTrue(_holds_payout_sum(), "control setup: payout sum false pre-store");
        assertTrue(_holds_claim_bounds(), "control setup: claim bounds false pre-store");
        assertTrue(_holds_terminal_exclusion(), "control setup: terminal false pre-store");
        assertTrue(_holds_latch(), "control setup: latch false pre-store");
        assertTrue(_holds_roster(), "control setup: roster false pre-store");
        assertTrue(_holds_oracle(), "control setup: oracle false pre-store");

        // --- Control A (INV-1): mint 7 tokens into the bill behind the books.
        uint256 bal = token.balanceOf(address(bill));
        assertEq(bal, 0, "engagement: escrow not drained");
        bytes32 balSlot = keccak256(abi.encode(address(bill), uint256(0)));
        vm.store(address(token), balSlot, bytes32(bal + 7));
        assertFalse(_holds_conservation(), "INV-1 blind to balance leak (vacuous check!)");
        vm.store(address(token), balSlot, bytes32(bal)); // restore exact
        assertTrue(_holds_conservation(), "restore failed");

        // --- Control B (INV-1b): inflate the handler's recorded claim total for
        // settlement 0 while leaving contract state honest. claimedTotal base slot = 38.
        bytes32 oracleSlot = keccak256(abi.encode(uint256(0), uint256(38)));
        vm.store(address(handler), oracleSlot, bytes32(uint256(999999)));
        assertFalse(_holds_oracle(), "INV-1b blind to oracle drift (vacuous check!)");
        vm.store(address(handler), oracleSlot, bytes32(uint256(900))); // restore honest oracle

        // --- Control C (INV-5): flip settlementInitiated bit0 of slot 7 to 1 although
        // every settlement is terminal and fully drained (stuck-frozen drift). Load-
        // modify-write preserves the co-packed factory address (packing probe law).
        bytes32 s7 = vm.load(address(bill), bytes32(uint256(7)));
        assertTrue(uint256(s7) & 1 == 0 && uint256(s7) != 0, "engagement: slot7 shape drift");
        vm.store(address(bill), bytes32(uint256(7)), bytes32(uint256(s7) | 1));
        assertFalse(_holds_latch(), "INV-5 blind to latch drift (vacuous check!)");
        vm.store(address(bill), bytes32(uint256(7)), s7); // restore exact
        assertTrue(_holds_latch(), "latch restore failed");

        // --- Control D (INV-4): stamp refunded (struct word 6, bit 64 - packed after
        // fullyConfirmedAt) onto the EXECUTED settlement 0.
        bytes32 sbase = keccak256(abi.encode(uint256(5))); // settlements[] base slot 5
        bytes32 w6 = bytes32(uint256(sbase) + 6);
        bytes32 old6 = vm.load(address(bill), w6);
        vm.store(address(bill), w6, bytes32(uint256(old6) | (uint256(1) << 64)));
        assertFalse(_holds_terminal_exclusion(), "INV-4 blind to double-terminal (vacuous!)");

        // --- Control E (INV-3): set a claimedMask bit outside expectedMask (bit 9 added
        // to the honest 0x3 -> 0x203) on settlement 0.
        vm.store(address(bill), w6, old6); // undo D
        bytes32 cmWord = bytes32(uint256(sbase) + 5);
        (, , , uint256 expected0, , uint256 claimed0, , ) = bill.settlements(0);
        assertEq(claimed0, expected0, "engagement: mask not fully claimed");
        vm.store(address(bill), cmWord, bytes32(claimed0 | (uint256(1) << 9)));
        assertFalse(_holds_claim_bounds(), "INV-3 blind to out-of-snapshot claim (vacuous!)");

        // --- Control F (INV-6): repoint seatIdOf[s1] (mapping base slot 3) at the wrong
        // seat: id 3 = seat index 2, whose wallet is not s1.
        bytes32 seatIdOfBase = keccak256(abi.encode(actorsArr[1], uint256(3)));
        vm.store(address(bill), seatIdOfBase, bytes32(uint256(3)));
        assertFalse(_holds_roster(), "INV-6 blind to seatIdOf drift (vacuous!)");
    }
}
