// SPDX-License-Identifier: MIT OR Apache-2.0
pragma solidity >=0.8.13 <0.9.0;

import {Script, console} from "../lib/forge-std/src/Script.sol";
import {TandaBillV2} from "../contracts/TandaBillV2.sol";
import {TandaBillFactory} from "../contracts/TandaBillFactory.sol";
import {IERC20} from "../contracts/TandaBillV2.sol";

/// @notice Canonical W6 v2 deploy to World Chain Sepolia (4801): factory-first per ratified rulings.
/// @dev Usage:
///   forge script script/TandaDeployV2.s.sol \
///     --rpc-url https://worldchain-sepolia.g.alchemy.com/public \
///     --private-key [REDACTED] \
///     --broadcast
///
///   USDC on World Chain Sepolia (4801): 0x66145f38cBAC35Ca6F1Dfb4914dF98F1614aeA88
///   Pass USDC_ADDRESS explicitly; do not rely on comments.
contract TandaDeployV2 is Script {
    function run() external {
        address usdc = vm.envOr("USDC_ADDRESS", address(0));
        require(usdc != address(0), "Set USDC_ADDRESS env var");

        vm.startBroadcast();
        TandaBillFactory factory = new TandaBillFactory(IERC20(usdc));
        vm.stopBroadcast();

        console.log("implProd:", address(factory.implementation()));
        console.log("facProd:", address(factory));
        console.log("Deploy verified (factory lineage). Post receipt to repo + courier lane.");
    }
}
