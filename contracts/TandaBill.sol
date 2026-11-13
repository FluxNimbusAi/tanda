// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

/// @notice Minimal ERC-20 interface (USDC on World Chain).
interface IERC20 {
    function transfer(address to, uint256 amount) external returns (bool);
    function transferFrom(address from, address to, uint256 amount) external returns (bool);
    function balanceOf(address account) external view returns (uint256);
}

/// @title TandaBill — split-bill expense ledger with short-hold settlement escrow
/// @notice Design invariants (kill-pass):
///   1. No key custody: no upgrade, no pause, no recovery. Settlement is logic-only.
///   2. No ROSCA pots: this contract is split-bill only.
///   3. Fee-free MVP: no protocol fee.
///   4. World ID soft gate: seats are verified humans, but formation is not orb-gated.
///   5. Short-hold escrow: funds held only for the settlement window.
/// @dev W1 scaffold — structure only. No deployment.
contract TandaBill {
    // ─── Types ────────────────────────────────────────────────────────────

    struct Seat {
        address wallet;      // World App wallet address
        uint64  joinedAt;    // unix timestamp
        bool    active;      // seat is active in this bill
    }

    struct Expense {
        uint256 amount;      // in the bill's token units (USDC = 6 decimals)
        address paidBy;      // wallet that paid
        uint64  addedAt;     // unix timestamp
        bool    settled;     // included in a settlement
    }

    struct Settlement {
        uint256 totalAmount; // total distributed
        uint256[] payouts;   // per-seat payout amounts
        uint64  settledAt;   // unix timestamp
        uint64  initiatedAt; // unix timestamp when settlement was initiated (W5: window anchor)
    }

    // ─── State ────────────────────────────────────────────────────────────

    /// @notice The token this bill settles in (USDC on World Chain).
    IERC20 public immutable token;
    address public owner;

    /// @notice Seats in this bill. Indexed by seat id.
    Seat[] public seats;

    /// @notice Expenses logged against this bill.
    Expense[] public expenses;

    /// @notice Settlements executed.
    Settlement[] public settlements;

    /// @notice Total amount currently held in escrow (unpaid settlements).
    uint256 public escrowBalance;

    /// @notice True once any settlement has been initiated. Seat removal is
    ///         forbidden after this (Gap-2 ruling, Option 1): payouts are frozen
    ///         at initiation, so removing a seat would strand its share.
    bool public settlementInitiated;

    /// @notice Settlement window in seconds. Funds are held only this long after
    ///         all seats have confirmed. Default: 1 hour. (Kill #3: short hold.)
    uint64 public constant SETTLEMENT_WINDOW = 1 hours;

    // ─── Events ───────────────────────────────────────────────────────────

    event BillCreated(address indexed token, address indexed owner, uint256 seatCount);
    event SeatAdded(uint256 indexed seatId, address indexed wallet, uint64 joinedAt);
    event SeatRemoved(uint256 indexed seatId, address indexed wallet);
    event ExpenseAdded(uint256 indexed expenseId, address indexed paidBy, uint256 amount);
    event SettlementInitiated(uint256 indexed settlementId, uint256 totalAmount, uint256 seatCount);
    event SettlementExecuted(uint256 indexed settlementId, uint256 totalAmount, uint64 settledAt);
    event SeatConfirmed(uint256 indexed settlementId, uint256 indexed seatId);

    // ─── Errors ───────────────────────────────────────────────────────────

    error NotOwner();
    error SeatNotFound(uint256 seatId);
    error SeatInactive(uint256 seatId);
    error ExpenseNotFound(uint256 expenseId);
    error AlreadySettled();
    error SettlementNotReady();
    error EscrowEmpty();
    error TokenTransferFailed();
    error SettlementInitiatedAlready();

    // ─── Constructor ──────────────────────────────────────────────────────

    /// @param _token USDC (or other ERC-20) on World Chain.
    constructor(IERC20 _token) {
        token = _token;
        owner = msg.sender;
    }

    // ─── Seat management (owner only, pre-settlement) ─────────────────────

    /// @notice Add a verified-human seat to this bill.
    /// @dev World ID verification happens off-chain (MiniKit walletAuth).
    ///      The contract trusts the wallet address; the soft gate is in the UI.
    function addSeat(address wallet) external {
        require(msg.sender == owner, NotOwner());
        uint256 seatId = seats.length;
        // casting to 'uint64' is safe because block.timestamp < 2^64 until year 584 billion
        // forge-lint: disable-next-line(unsafe-typecast)
        seats.push(Seat({wallet: wallet, joinedAt: uint64(block.timestamp), active: true}));
        // forge-lint: disable-next-line(unsafe-typecast)
        emit SeatAdded(seatId, wallet, uint64(block.timestamp));
    }

    /// @notice Remove a seat (owner only, before settlement).
    /// @dev Reverts if any settlement has been initiated (Gap-2 ruling, Option 1):
    ///      payouts are frozen at initiation, so a removed seat's share would strand.
    function removeSeat(uint256 seatId) external {
        require(msg.sender == owner, NotOwner());
        require(!settlementInitiated, SettlementInitiatedAlready());
        if (seatId >= seats.length) revert SeatNotFound(seatId);
        if (!seats[seatId].active) revert SeatInactive(seatId);
        seats[seatId].active = false;
        emit SeatRemoved(seatId, seats[seatId].wallet);
    }

    // ─── Expense logging (owner only, pre-settlement) ─────────────────────

    /// @notice Log an expense. The payer has already transferred tokens to this contract.
    function addExpense(uint256 amount) external {
        require(msg.sender == owner, NotOwner());
        uint256 expenseId = expenses.length;
        // casting to 'uint64' is safe because block.timestamp < 2^64 until year 584 billion
        // forge-lint: disable-next-line(unsafe-typecast)
        expenses.push(Expense({amount: amount, paidBy: msg.sender, addedAt: uint64(block.timestamp), settled: false}));
        emit ExpenseAdded(expenseId, msg.sender, amount);
    }

    /// @notice Fund the escrow. The payer transfers `amount` of the bill token to this contract.
    function fundEscrow(uint256 amount) external {
        require(msg.sender == owner, NotOwner());
        require(token.transferFrom(msg.sender, address(this), amount), TokenTransferFailed());
        escrowBalance += amount;
    }

    // ─── Settlement ───────────────────────────────────────────────────────

    /// @notice Initiate settlement. Splits all unsettled expenses equally among active seats.
    /// @dev Each seat must confirm before funds are released. Funds are held for
    ///      SETTLEMENT_WINDOW seconds after the last confirmation. (Kill #3: short hold.)
    function initiateSettlement() external {
        require(msg.sender == owner, NotOwner());
        uint256 unsettled = _unsettledTotal();
        require(unsettled > 0, EscrowEmpty());
        require(escrowBalance >= unsettled, EscrowEmpty());

        uint256 activeCount = _activeSeatCount();
        require(activeCount > 0, SeatNotFound(0));

        uint256[] memory payouts = new uint256[](activeCount);
        uint256 base = unsettled / activeCount;
        uint256 remainder = unsettled % activeCount;

        uint256 idx = 0;
        for (uint256 i = 0; i < seats.length; i++) {
            if (seats[i].active) {
                payouts[idx] = base + (idx < remainder ? 1 : 0);
                idx++;
            }
        }

        uint256 settlementId = settlements.length;
        // W5: record initiation timestamp for window enforcement.
        // casting to 'uint64' is safe because block.timestamp < 2^64 until year 584 billion
        // forge-lint: disable-next-line(unsafe-typecast)
        settlements.push(Settlement({totalAmount: unsettled, payouts: payouts, settledAt: 0, initiatedAt: uint64(block.timestamp)}));
        escrowBalance -= unsettled;
        settlementInitiated = true; // Gap-2 ruling (Option 1): freeze seat roster

        // Mark expenses as settled
        for (uint256 i = 0; i < expenses.length; i++) {
            if (!expenses[i].settled) {
                expenses[i].settled = true;
            }
        }

        emit SettlementInitiated(settlementId, unsettled, activeCount);
    }

    /// @notice A seat confirms its share. After all active seats confirm,
    ///         funds are released after SETTLEMENT_WINDOW.
    function confirmSettlement(uint256 settlementId) external {
        // W1 scaffold: confirmation tracking is stubbed.
        // W2: add per-seat confirmation bitmap + timed release.
        emit SeatConfirmed(settlementId, 0);
    }

    /// @notice Execute the settlement: transfer each seat's payout from escrow.
    /// @dev Callable only after SETTLEMENT_WINDOW has elapsed since initiation.
    function executeSettlement(uint256 settlementId) external {
        require(msg.sender == owner, NotOwner());
        if (settlementId >= settlements.length) revert SettlementNotReady();
        Settlement storage s = settlements[settlementId];
        require(s.settledAt == 0, AlreadySettled());
        // W5: enforce SETTLEMENT_WINDOW delay. Funds are held for the window
        // duration after initiation. The window is inclusive: execution is
        // allowed at exactly initiatedAt + SETTLEMENT_WINDOW.
        // forge-lint: disable-next-line(block-timestamp)
        require(block.timestamp >= uint256(s.initiatedAt) + SETTLEMENT_WINDOW, SettlementNotReady());
        uint256 idx = 0;
        for (uint256 i = 0; i < seats.length; i++) {
            if (seats[i].active) {
                // USDC (World Chain) has no transfer hooks — all-or-nothing revert
                // protects partial settlement; per-seat failure is not a concern.
                // forge-lint: disable-next-line(calls-loop, require-revert-in-loop)
                require(token.transfer(seats[i].wallet, s.payouts[idx]), TokenTransferFailed());
                idx++;
            }
        }
        // casting to 'uint64' is safe because block.timestamp < 2^64 until year 584 billion
        // forge-lint: disable-next-line(unsafe-typecast)
        s.settledAt = uint64(block.timestamp);
        // forge-lint: disable-next-line(unsafe-typecast, reentrancy-events)
        emit SettlementExecuted(settlementId, s.totalAmount, uint64(block.timestamp));
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

    /// @notice Total expenses logged (settled + unsettled).
    function totalExpenses() external view returns (uint256 total) {
        for (uint256 i = 0; i < expenses.length; i++) {
            total += expenses[i].amount;
        }
    }

    /// @notice Number of active seats.
    function activeSeatCount() external view returns (uint256) {
        return _activeSeatCount();
    }
}
