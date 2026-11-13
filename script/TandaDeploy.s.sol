// SPDX-License-Identifier: MIT OR Apache-2.0
pragma solidity >=0.8.13 <0.9.0;

import {Script, console} from "../lib/forge-std/src/Script.sol";
import {TandaBill, IERC20} from "../contracts/TandaBill.sol";

/// @notice Deploy TandaBill to World Chain (or any EVM chain).
/// @dev Usage:
///   forge script script/TandaDeploy.s.sol \
///     --rpc-url $RPC_URL \
///     --private-key $PRIVATE_KEY \
///     --broadcast
///
///   World Chain mainnet RPC: https://worldchain-mainnet.public.blastapi.io
///   World Chain Sepolia testnet: https://worldchain-sepolia.public.blastapi.io
///
///   USDC on World Chain: 0x090E3513A98C7E5A67402872215208FA80aFa7c7 (verify before deploy)
///
///   The constructor takes the ERC20 token address. The deployer becomes `owner`
///   (can call executeSettlement). For a multi-user app, consider transferring
///   ownership to a timelock or multisig post-deploy.
contract TandaDeploy is Script {
    function run() external {
        // ─── Parameters ───────────────────────────────────────────────
        address usdc = vm.envOr("USDC_ADDRESS", address(0));
        require(usdc != address(0), "Set USDC_ADDRESS env var");

        console.log("Deploying TandaBill");
        console.log("Token:", usdc);

        // ─── Deploy ───────────────────────────────────────────────────
        vm.startBroadcast();
        TandaBill bill = new TandaBill(IERC20(usdc));
        vm.stopBroadcast();

        address addr = address(bill);
        console.log("TandaBill deployed at:", addr);
        console.log("Owner (deployer):", msg.sender);
        console.log("Settlement window:", bill.SETTLEMENT_WINDOW(), "seconds");

        // ─── Verify ───────────────────────────────────────────────────
        require(address(bill.token()) == usdc, "Token mismatch");
        require(bill.owner() == msg.sender, "Owner mismatch");
        require(bill.activeSeatCount() == 0, "Should start with 0 seats");

        console.log("Deploy verified.");
        console.log("Next: fundEscrow -> addSeat -> addExpense -> initiateSettlement -> executeSettlement");
    }
}
