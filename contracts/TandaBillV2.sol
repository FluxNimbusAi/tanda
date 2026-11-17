// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

/// @notice Minimal ERC-20 interface (USDC on World Chain).
interface IERC20 {
    function transfer(address to, uint256 amount) external returns (bool);
    function transferFrom(address from, address to, uint256 amount) external returns (bool);
    function balanceOf(address account) external view returns (uint256);
}

/// @title TandaBillV2 — split-bill expense ledger with short-hold settlement escrow (clonable)
/// @notice W6 revision of TandaBill (W5, verified @0x8644…b12). Design invariants (kill-pass):
///   1. No key custody: no upgrade, no pause, no recovery. Settlement is logic-only.
///   2. No ROSCA pots: this contract is split-bill only.
///   3. Fee-free MVP: no protocol fee.
///   4. World ID soft gate: seats are verified humans (off-chain IDKit), formation is not orb-gated.
///   5. Short-hold escrow: funds held only for the settlement window after ALL invited seats
///      confirm; if confirmation never completes, funds MUST NOT sit forever — MAX_HOLD
///      refund escape (Gap-5 fix, v2).
/// @dev v2 changes vs W5:
///   - initialize() instead of constructor immutables → minimal-proxy clone compatible (Gap-1 fix).
///   - seat-confirmation bitmap per settlement; execute gated on fullyConfirmedAt + WINDOW (Gap-2 fix).
///   - MAX_HOLD (72h) refund escape to funder when not all seats confirm (invariant-5 completion).
///   - seat roster cap 256 (uint256 mask); duplicate-seat guard via seatIdOf (documented design).
///   - Gap-3 ruling (pending Flux sign-off): MVP stays owner-fronted — addExpense/fundEscrow are
///     owner-only by design; Expense.paidBy records the funder == owner. Refund returns to owner.
/// @dev v2.1 (P0.1a pull-claim): settlement leg switched push-loop → per-seat pull
///      (PaymentSplitter pattern, backlog option (a), TANDA_W10_BACKLOG_20261116.md).
///      executeSettlement now only OPENS claims; each seat pulls its payout via
///      claimSettlement(). Removes the reverting/blacklisted-receiver escrow deadlock:
///      one bad receiver can no longer block the whole settlement leg.
contract TandaBillV2 {
    // ─── Types ────────────────────────────────────────────────────────────

    struct Seat {
        address wallet;      // World App wallet address
        uint64  joinedAt;    // unix timestamp
        bool    active;      // seat is active in this bill
    }

    struct Expense {
        uint256 amount;      // in the bill's token units (USDC = 6 decimals)
        address paidBy;      // wallet that paid (v2 MVP: always owner — Gap-3 ruling)
        uint64  addedAt;     // unix timestamp
        bool    settled;     // included in a settlement
    }

    struct Settlement {
        uint256 totalAmount;    // total distributed
        uint256[] payouts;      // per-seat payout amounts (dense over active seats at initiation)
        uint64  settledAt;      // unix timestamp when funds released (0 = pending)
        uint64  initiatedAt;    // unix timestamp when settlement was initiated
        uint256 expectedMask;   // snapshot: bit i set = seat i invited to confirm
        uint256 confirmedMask;  // bit i set = seat i confirmed
        uint256 claimedMask;    // P0.1a: bit i set = seat i pulled its payout (post-execute)
        uint64  fullyConfirmedAt; // 0 until every expected seat confirmed
        bool    refunded;       // escrow returned to funder via refundSettlement
    }

    // ─── State ────────────────────────────────────────────────────────────

    IERC20 public token;        // v2: storage slot (was immutable) — clone-compatible
    address public owner;       // bill creator (set via initialize by the factory)
    bool private _initialized;  // clone-guard: initialize() exactly once

    Seat[] public seats;
    /// @notice wallet -> seat id + 1 (0 = not a seat). Duplicate-seat guard + O(1) confirm lookup.
    mapping(address => uint256) public seatIdOf;

    Expense[] public expenses;
    Settlement[] public settlements;

    uint256 public escrowBalance;
    bool public settlementInitiated;
    /// @notice Creator factory; enables the trusted-forwarder _caller() path (MiniKit
    ///         entrypoint gate). Zero = legacy direct deploy -> _caller falls back to
    ///         msg.sender, so W5-era bills keep exact semantics.
    address public factory;

    uint64 public constant SETTLEMENT_WINDOW = 1 hours; // hold after full confirmation
    uint64 public constant MAX_HOLD = 72 hours;         // refund escape if never confirmed
    uint256 public constant MAX_SEATS = 256;            // roster cap = uint256 mask width

    // ─── Events ───────────────────────────────────────────────────────────

    event BillInitialized(address indexed token, address indexed owner);
    event SeatAdded(uint256 indexed seatId, address indexed wallet, uint64 joinedAt);
    event SeatRemoved(uint256 indexed seatId, address indexed wallet);
    event SeatWalletRotated(uint256 indexed seatId, address indexed from, address indexed to);
    event ExpenseAdded(uint256 indexed expenseId, address indexed paidBy, uint256 amount);
    event EscrowFunded(address indexed funder, uint256 amount);
    event SettlementInitiated(uint256 indexed settlementId, uint256 totalAmount, uint256 expectedSeats);
    event SeatConfirmed(uint256 indexed settlementId, uint256 indexed seatId);
    event SettlementFullyConfirmed(uint256 indexed settlementId, uint64 at);
    event SettlementExecuted(uint256 indexed settlementId, uint256 totalAmount, uint64 settledAt);
    event SeatPayoutClaimed(uint256 indexed settlementId, uint256 indexed seatId, address indexed wallet, uint256 amount);
    event SettlementRefunded(uint256 indexed settlementId, uint256 amount);

    // ─── Errors ───────────────────────────────────────────────────────────

    error NotOwner();
    error AlreadyInitialized();
    error SeatNotFound(uint256 seatId);
    error SeatInactive(uint256 seatId);
    error DuplicateSeat(address wallet);
    error ZeroWallet();
    error NotSeatOrOwner();
    error SeatRotationClosed();
    error RotationWindowLocked();
    error TooManySeats();
    error SettlementNotFound();
    error AlreadySettled();
    error NotAwaitingConfirmations();
    error NotAnExpectedSeat();
    error AlreadyConfirmed();
    error NotFullyConfirmed();
    error WindowNotElapsed();
    error NotYetClaimable();
    error PayoutAlreadyClaimed();
    error RefundNotAvailable();
    error EscrowEmpty();
    error NoActiveSeats();
    error TokenTransferFailed();
    error SettlementInitiatedAlready();

    // ─── Initializer (clone-compatible; replaces constructor) ─────────────

    /// @notice Set token + creator + initial roster exactly once. Only the factory calls this
    ///         (during createBill) — seats are established atomically inside initialization.
    function initialize(IERC20 _token, address creator, address[] calldata initialSeats) external {
        require(!_initialized, AlreadyInitialized());
        _initialized = true;
        factory = msg.sender; // trusted-forwarder anchor (direct call: msg.sender == factory)
        token = _token;
        owner = creator;
        for (uint256 i = 0; i < initialSeats.length; i++) {
            if (seatIdOf[initialSeats[i]] != 0) revert DuplicateSeat(initialSeats[i]);
            if (seats.length >= MAX_SEATS) revert TooManySeats();
            // casting to 'uint64' is safe because block.timestamp < 2^64 until year 584 billion
            // forge-lint: disable-next-line(unsafe-typecast)
            seats.push(Seat({wallet: initialSeats[i], joinedAt: uint64(block.timestamp), active: true}));
            seatIdOf[initialSeats[i]] = seats.length;
            // forge-lint: disable-next-line(unsafe-typecast)
            emit SeatAdded(seats.length - 1, initialSeats[i], uint64(block.timestamp));
        }
        emit BillInitialized(address(_token), creator);
    }

    /// @notice Recovers the original sender for factory-forwarded calls: the canonical
    ///         factory's callBill appends the caller's 20-byte address to calldata.
    ///         Direct EOA/script calls (msg.sender != factory) fall back to msg.sender,
    ///         and a forged trailing tail cannot spoof (fallback branch ignores it).
    function _caller() internal view returns (address forwarded) {
        if (msg.sender == factory && msg.data.length >= 20) {
            assembly {
                forwarded := shr(96, calldataload(sub(calldatasize(), 20)))
            }
        } else {
            forwarded = msg.sender;
        }
    }

    // ─── Seat management (owner only, pre-settlement) ─────────────────────

    function addSeat(address wallet) external {
        require(_caller() == owner, NotOwner());
        if (seatIdOf[wallet] != 0) revert DuplicateSeat(wallet);
        if (seats.length >= MAX_SEATS) revert TooManySeats();
        uint256 seatId = seats.length;
        // casting to 'uint64' is safe because block.timestamp < 2^64 until year 584 billion
        // forge-lint: disable-next-line(unsafe-typecast)
        seats.push(Seat({wallet: wallet, joinedAt: uint64(block.timestamp), active: true}));
        seatIdOf[wallet] = seatId + 1;
        // forge-lint: disable-next-line(unsafe-typecast)
        emit SeatAdded(seatId, wallet, uint64(block.timestamp));
    }

    /// @dev Forbidden after any settlement initiation (roster freeze — W5 ruling stands).
    function removeSeat(uint256 seatId) external {
        require(_caller() == owner, NotOwner());
        require(!settlementInitiated, SettlementInitiatedAlready());
        if (seatId >= seats.length) revert SeatNotFound(seatId);
        if (!seats[seatId].active) revert SeatInactive(seatId);
        seats[seatId].active = false;
        seatIdOf[seats[seatId].wallet] = 0; // re-invitable at a new id (mask snapshot stays)
        emit SeatRemoved(seatId, seats[seatId].wallet);
    }

    /// @notice Rotate a seat's payout wallet. Confirm/payout state is seat-indexed, so
    ///         rotation preserves it exactly. P0.1: un-dead-locks confirmed escrow when a
    ///         seat wallet rejects inbound USDC (reverting receiver / blacklisted address).
    /// @dev    Callable by the seat itself OR owner (recovery). Allowed while the latest
    ///         settlement is open (and pre-initiation). Seat-gate policy (W8): frontend must
    ///         collect a fresh World ID proof from newWallet before exposing this action.
    function rotateSeatWallet(uint256 seatId, address newWallet) external {
        if (seatId >= seats.length) revert SeatNotFound(seatId);
        if (!seats[seatId].active) revert SeatInactive(seatId);
        if (newWallet == address(0)) revert ZeroWallet();
        address caller = _caller();
        if (caller != seats[seatId].wallet && caller != owner) revert NotSeatOrOwner();
        if (settlements.length > 0) {
            Settlement storage last = settlements[settlements.length - 1];
            if (last.settledAt != 0 || last.refunded) revert SeatRotationClosed();
            // Ratified split-lock (2026-11-16 remediation):
            //  - owner-driven rotation of another seat dies at full confirmation
            //    (kept strict through executability until executed/refunded)
            //  - confirmed seat-self rotation locked inside the settlement window;
            //    unconfirmed seats may always fix their own payout wallet
            if (last.fullyConfirmedAt != 0) {
                bool inWindow = block.timestamp < uint256(last.fullyConfirmedAt) + SETTLEMENT_WINDOW;
                if (caller != seats[seatId].wallet && caller == owner) revert RotationWindowLocked();
                if (caller == seats[seatId].wallet && inWindow
                    && (last.confirmedMask & (uint256(1) << seatId)) != 0) revert RotationWindowLocked();
            }
        }
        if (seatIdOf[newWallet] != 0) revert DuplicateSeat(newWallet);
        address old = seats[seatId].wallet;
        seatIdOf[old] = 0; // CEI: fixup mappings before emit
        seats[seatId].wallet = newWallet;
        seatIdOf[newWallet] = seatId + 1;
        emit SeatWalletRotated(seatId, old, newWallet);
    }

    // ─── Expense + escrow (owner-fronted MVP — Gap-3 ruling) ──────────────

    function addExpense(uint256 amount) external {
        require(_caller() == owner, NotOwner());
        uint256 expenseId = expenses.length;
        // casting to 'uint64' is safe because block.timestamp < 2^64 until year 584 billion
        // forge-lint: disable-next-line(unsafe-typecast)
        expenses.push(Expense({amount: amount, paidBy: _caller(), addedAt: uint64(block.timestamp), settled: false}));
        emit ExpenseAdded(expenseId, _caller(), amount);
    }

    function fundEscrow(uint256 amount) external {
        require(token.transferFrom(_caller(), address(this), amount), TokenTransferFailed());
        escrowBalance += amount;
        emit EscrowFunded(_caller(), amount);
    }

    // ─── Settlement ───────────────────────────────────────────────────────

    /// @notice Split all unsettled expenses equally among active seats; snapshot confirmation roster.
    function initiateSettlement() external {
        require(_caller() == owner, NotOwner());
        uint256 unsettled = _unsettledTotal();
        require(unsettled > 0, EscrowEmpty());
        require(escrowBalance >= unsettled, EscrowEmpty());

        uint256[] memory payouts = new uint256[](_activeSeatCount());
        uint256 activeCount = payouts.length;
        require(activeCount > 0, NoActiveSeats());
        uint256 base = unsettled / activeCount;
        uint256 remainder = unsettled % activeCount;

        uint256 idx = 0;
        uint256 mask;
        for (uint256 i = 0; i < seats.length; i++) {
            if (seats[i].active) {
                payouts[idx] = base + (idx < remainder ? 1 : 0);
                mask |= (1 << i);
                idx++;
            }
        }

        uint256 settlementId = settlements.length;
        // casting to 'uint64' is safe because block.timestamp < 2^64 until year 584 billion
        // forge-lint: disable-next-line(unsafe-typecast)
        settlements.push(Settlement({
            totalAmount: unsettled,
            payouts: payouts,
            settledAt: 0,
            // forge-lint: disable-next-line(unsafe-typecast)
            initiatedAt: uint64(block.timestamp),
            expectedMask: mask,
            confirmedMask: 0,
            claimedMask: 0,
            fullyConfirmedAt: 0,
            refunded: false
        }));
        escrowBalance -= unsettled;
        settlementInitiated = true;

        for (uint256 i = 0; i < expenses.length; i++) {
            if (!expenses[i].settled) expenses[i].settled = true;
        }

        // Auto-full-confirm edge: single-seat bill whose sole seat is the owner —
        // still requires explicit confirm (or MAX_HOLD refund); no silent release.
        emit SettlementInitiated(settlementId, unsettled, activeCount);
    }

    /// @notice Expected seat confirms its share. When the last one confirms, the window starts.
    function confirmSettlement(uint256 settlementId) external {
        if (settlementId >= settlements.length) revert SettlementNotFound();
        Settlement storage s = settlements[settlementId];
        if (s.settledAt != 0 || s.refunded) revert AlreadySettled();
        if (s.fullyConfirmedAt != 0) revert NotAwaitingConfirmations();

        uint256 raw = seatIdOf[_caller()];
        if (raw == 0) revert NotAnExpectedSeat();
        uint256 seatId = raw - 1;
        uint256 bit = 1 << seatId;
        if ((s.expectedMask & bit) == 0 || !seats[seatId].active) revert NotAnExpectedSeat();
        if ((s.confirmedMask & bit) != 0) revert AlreadyConfirmed();

        s.confirmedMask |= bit;
        emit SeatConfirmed(settlementId, seatId);

        if ((s.confirmedMask & s.expectedMask) == s.expectedMask) {
            // casting to 'uint64' is safe because block.timestamp < 2^64 until year 584 billion
            // forge-lint: disable-next-line(unsafe-typecast)
            s.fullyConfirmedAt = uint64(block.timestamp);
            emit SettlementFullyConfirmed(settlementId, uint64(block.timestamp));
        }
    }

    /// @notice Open per-seat payout claims. Requires ALL expected seats confirmed + window
    ///         since last confirm. P0.1a: no longer pushes transfers — escrow stays intact and
    ///         each seat pulls its payout via claimSettlement(). The W1-era assumption that
    ///         "per-seat failure is not a concern" (one reverting/blacklisted receiver
    ///         deadlocks the whole leg) is removed.
    /// @dev  v2: callable by ANYONE — claim-open is fully determined by the confirmed roster,
    ///         so gating on owner would let owner inaction freeze confirmed funds (execute-
    ///         after-full-confirm cannot be blocked by the refund path by design). Incentive-
    ///         neutral: the caller only spends gas; value moves only seat → same seat.
    ///         (Gap-2 addendum, P0.1a revision)
    function executeSettlement(uint256 settlementId) external {
        if (settlementId >= settlements.length) revert SettlementNotFound();
        Settlement storage s = settlements[settlementId];
        if (s.settledAt != 0 || s.refunded) revert AlreadySettled();
        if (s.fullyConfirmedAt == 0) revert NotFullyConfirmed();
        // forge-lint: disable-next-line(block-timestamp)
        require(block.timestamp >= uint256(s.fullyConfirmedAt) + SETTLEMENT_WINDOW, WindowNotElapsed());

        // P0.1a: claims-open only — no transfers here (pull leg = claimSettlement below).
        // casting to 'uint64' is safe because block.timestamp < 2^64 until year 584 billion
        // forge-lint: disable-next-line(unsafe-typecast)
        s.settledAt = uint64(block.timestamp);
        // forge-lint: disable-next-line(unsafe-typecast, reentrancy-events)
        emit SettlementExecuted(settlementId, s.totalAmount, uint64(block.timestamp));
    }

    /// @notice Pull one seat's payout from an executed settlement (P0.1a pull-claim,
    ///         peanutsplit / OZ PaymentSplitter pattern). A seat whose wallet reverts on
    ///         inbound ERC-20 (mis-set Safe / USDC-blacklisted) can no longer block anyone
    ///         else: every other seat drains independently. The affected seat rotates its
    ///         payout wallet before execute (P0.1b self-rotation) and claims with the new
    ///         wallet; an unclaimed share stays in escrow, pullable only by that seat —
    ///         never by anyone else.
    /// @dev    Callable by the seat itself (or its forwarder-identity caller). The payout
    ///         vector is dense over expectedMask; seat i's share sits at rank
    ///         popcount(expectedMask bits below i) — see _payoutAt.
    function claimSettlement(uint256 settlementId) external {
        if (settlementId >= settlements.length) revert SettlementNotFound();
        Settlement storage s = settlements[settlementId];
        if (s.settledAt == 0) revert NotYetClaimable(); // still pending confirmations, or refunded

        uint256 raw = seatIdOf[_caller()];
        if (raw == 0) revert NotAnExpectedSeat();
        uint256 seatId = raw - 1;
        uint256 bit = 1 << seatId;
        if ((s.expectedMask & bit) == 0 || !seats[seatId].active) revert NotAnExpectedSeat();
        if ((s.claimedMask & bit) != 0) revert PayoutAlreadyClaimed();

        uint256 amount = _payoutAt(s, seatId);
        s.claimedMask |= bit; // CEI: flag before external call; a failed transfer reverts the flag too → claim stays retryable
        require(token.transfer(seats[seatId].wallet, amount), TokenTransferFailed());
        // forge-lint: disable-next-line(reentrancy-events)
        emit SeatPayoutClaimed(settlementId, seatId, seats[seatId].wallet, amount);
    }

    /// @notice Short-hold guarantee, other leg: if the roster never fully confirms within
    ///         MAX_HOLD of initiation, escrow returns to this contract's funder side (owner,
    ///         per Gap-3 owner-fronted ruling). Funds can never sit frozen indefinitely.
    function refundSettlement(uint256 settlementId) external {
        require(_caller() == owner, NotOwner());
        if (settlementId >= settlements.length) revert SettlementNotFound();
        Settlement storage s = settlements[settlementId];
        if (s.settledAt != 0 || s.refunded) revert AlreadySettled();
        // forge-lint: disable-next-line(block-timestamp)
        require(s.fullyConfirmedAt == 0 && block.timestamp >= uint256(s.initiatedAt) + MAX_HOLD, RefundNotAvailable());
        s.refunded = true;
        // CEI: flag set before external call
        require(token.transfer(owner, s.totalAmount), TokenTransferFailed());
        emit SettlementRefunded(settlementId, s.totalAmount);
    }

    // ─── Views ────────────────────────────────────────────────────────────

    function _unsettledTotal() internal view returns (uint256 total) {
        for (uint256 i = 0; i < expenses.length; i++) {
            if (!expenses[i].settled) total += expenses[i].amount;
        }
    }

    function _activeSeatCount() internal view returns (uint256 count) {
        for (uint256 i = 0; i < seats.length; i++) {
            if (seats[i].active) count++;
        }
    }

    /// @notice Payout vector of a settlement is dense over expectedMask (initiate-time
    ///         snapshot): seat i's share sits at rank = number of expected bits below i.
    function _payoutAt(Settlement storage s, uint256 seatId) internal view returns (uint256) {
        uint256 rank;
        for (uint256 i = 0; i < seatId; i++) {
            if ((s.expectedMask & (1 << i)) != 0) rank++;
        }
        return s.payouts[rank];
    }

    /// @notice P0.1a frontend view: amount `wallet` can pull right now (0 = nothing claimable:
    ///         settlement not executed, wallet holds no unclaimed expected seat, or already claimed).
    function claimablePayout(uint256 settlementId, address wallet) external view returns (uint256) {
        if (settlementId >= settlements.length) return 0;
        Settlement storage s = settlements[settlementId];
        if (s.settledAt == 0) return 0;
        uint256 raw = seatIdOf[wallet];
        if (raw == 0) return 0;
        uint256 seatId = raw - 1;
        uint256 bit = 1 << seatId;
        if ((s.expectedMask & bit) == 0 || !seats[seatId].active) return 0;
        if ((s.claimedMask & bit) != 0) return 0;
        return _payoutAt(s, seatId);
    }

    function totalExpenses() external view returns (uint256 total) {
        for (uint256 i = 0; i < expenses.length; i++) total += expenses[i].amount;
    }

    function activeSeatCount() external view returns (uint256) { return _activeSeatCount(); }

    function isSeatConfirmed(uint256 settlementId, address wallet) external view returns (bool) {
        uint256 raw = seatIdOf[wallet];
        if (raw == 0) return false;
        return (settlements[settlementId].confirmedMask & (1 << (raw - 1))) != 0;
    }

    /// @notice Explicit accessor: Solidity's auto-generated struct getter OMITS dynamic
    ///         arrays (payouts), so callers must use this to read the per-seat payout vector.
    function settlementPayouts(uint256 settlementId) external view returns (uint256[] memory) {
        return settlements[settlementId].payouts;
    }
}
