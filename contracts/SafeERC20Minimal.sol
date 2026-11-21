// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

/// @title SafeERC20Minimal - hardened ERC-20 transfer helpers (XIXI-DESIGN-02 decision_q2)
/// @notice Vendored minimal pattern equivalent to OpenZeppelin Contracts
///         token/utils/SafeERC20.sol (MIT), reduced to the two operations TandaBillV2
///         performs and kept interface-free (address-based) so it carries no import
///         cycle into TandaBillV2.sol. Design provenance: Xixi deep-audit verdict
///         sha256 101c14f5a36445e8f10c9bc571b4ca0a140e85922c8e949a8a63c7c0396ffbf7,
///         ratified by Flux 2026-11-21.
/// @dev  Why bare `require(token.transfer(...), bool)` is unsafe (HIGH-2, STRANDED):
///       - no-return-data tokens (USDT-class): the ABI decode REVERTS the whole call on
///         empty returndata -> the claim path becomes a permanent DoS once executed;
///       - false-return tokens (non-standard): `require(false)` reverts correctly BUT
///         fee-on-transfer tokens return TRUE while delivering less: with claimedMask
///         already set (P0.1a CEI ordering), a silent under-delivery strands the
///         difference with no retry path.
///       This library fixes the FIRST class (accepts empty returndata as success,
///       surfaces any other non-success as a typed revert). The fee-on-transfer
///       under-delivery class is accepted-by-design for MVP: World-Chain USDC (the
///       funded token per ADR-0010) is standard-return and NOT fee-on-transfer;
///       documented here so the assumption is visible, per decision_q2 risk_notes.
library SafeERC20Minimal {
    /// @notice The token call failed outright (reverted) or returned an explicit false.
    error SafeERC20Failed(address token, bytes reason);

    function safeTransfer(address token, address to, uint256 amount) internal {
        (bool success, bytes memory ret) = token.call(
            abi.encodeWithSelector(0xa9059cbb, to, amount) // transfer(address,uint256)
        );
        if (!success || (ret.length != 0 && !abi.decode(ret, (bool)))) {
            revert SafeERC20Failed(token, ret);
        }
    }

    function safeTransferFrom(address token, address from, address to, uint256 amount) internal {
        (bool success, bytes memory ret) = token.call(
            abi.encodeWithSelector(0x23b872dd, from, to, amount) // transferFrom(address,address,uint256)
        );
        if (!success || (ret.length != 0 && !abi.decode(ret, (bool)))) {
            revert SafeERC20Failed(token, ret);
        }
    }
}
