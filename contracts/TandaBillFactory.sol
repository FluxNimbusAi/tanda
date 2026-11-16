// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

import {TandaBillV2, IERC20} from "./TandaBillV2.sol";

/// @title TandaBillFactory — one-transaction bill creation via minimal proxies (Gap-1 fix)
/// @notice Deploys EIP-1167 clones of a fixed implementation; each bill's owner is the human
///         creator (msg.sender), never the backend. No upgrades, no pause (kill-pass holds).
/// @dev    W6 proposal. Implementation is immutable by design — changing bill logic means a
///         new factory; old bills keep old rules (settled-escrow safety > feature velocity).
contract TandaBillFactory {
    /// @notice The shared TandaBillV2 implementation every bill clones.
    address public immutable implementation;

    /// @notice Registry of bills created through this factory (off-chain indexing UX).
    mapping(address => bool) public isBill;

    event BillCreated(address indexed bill, address indexed creator, address indexed token, uint256 seatCount);

    error CreateFailed();
    error NotBill();
    error NoSeats();
    error TooManySeats();

    constructor(address _implementation) {
        implementation = _implementation;
    }

    /// @notice Create a bill: clone → initialize(token, msg.sender, seats) — one transaction,
    ///         MiniKit sendTransaction-compatible. Caller must include themselves explicitly
    ///         in `seats` to hold a payout share — no implicit seat.
    function createBill(IERC20 token, address[] calldata seats) external returns (address bill) {
        if (seats.length == 0) revert NoSeats();
        if (seats.length > 256) revert TooManySeats();

        address impl = implementation;
        // EIP-1167: 10 B deployer header + runtime (10 B prefix + 20 B addr + 15 B footer) = 55 B.
        // encodePacked guarantees the byte layout — no hand-rolled mstore offsets.
        bytes memory init = abi.encodePacked(
            hex"3d602d80600a3d3981f3363d3d373d3d3d363d73",
            impl,
            hex"5af43d82803e903d91602b57fd5bf3"
        );
        assembly {
            bill := create(0, add(init, 0x20), mload(init))
        }
        if (bill == address(0)) revert CreateFailed();
        isBill[bill] = true;

        // Seats are established atomically inside initialize: the factory is msg.sender of
        // initialize(), not the bill owner, so the public addSeat owner gate cannot apply there.
        TandaBillV2(payable(bill)).initialize(token, msg.sender, seats);
        emit BillCreated(bill, msg.sender, address(token), seats.length);
    }

    /// @notice Trusted forwarder (MiniKit entrypoint-gate remediation): the static
    ///         factory is the single Contract Entrypoint; bill logic runs in the clone,
    ///         so per-clone escrow isolation and approve-to-clone semantics are intact.
    ///         The caller address is appended to calldata; the clone's _caller() decodes
    ///         it (msg.sender == factory proves this path). Revert data bubbles unchanged.
    function callBill(address bill, bytes calldata data) external {
        if (!isBill[bill]) revert NotBill();
        (bool success, bytes memory retdata) =
            bill.call(abi.encodePacked(data, uint160(msg.sender)));
        if (!success) {
            assembly {
                revert(add(retdata, 0x20), mload(retdata))
            }
        }
    }
}
