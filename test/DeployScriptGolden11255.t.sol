// SPDX-License-Identifier: MIT OR Apache-2.0
pragma solidity >=0.8.13 <0.9.0;

import {Test} from "../lib/forge-std/src/Test.sol";
import {TandaDeploy} from "../script/TandaDeploy.s.sol";
import {TandaDeployV2} from "../script/TandaDeployV2.s.sol";

/// @notice TICK-1125-5 test-matrix deepening: deploy-script golden coverage.
/// @dev Canonical gap baseline (gaps_before_1125_5.json @2d926f607): every file in
///      contracts/ is gap-free; the only untested production surfaces are
///      script/TandaDeploy.s.sol (28 gap items) and script/TandaDeployV2.s.sol (19).
///      These scripts are the portal-migration lane's real risk surface (world
///      portal moved 11-24; entrypoint/USDC wiring happens here).
///      Shape facts measured in-lane (throwaway probe suites deleted after verdict):
///      - vm.setEnv is PROCESS-WIDE and Foundry 1.9 shards test functions across
///        threads: multiple functions writing USDC_ADDRESS race and read each
///        other's values (measured failure signature: 4/5 cross-contaminated
///        reverts in an isolated 5-function run). Hence EVERYTHING in this file
///        lives in ONE test function — serialized, deterministic. This file must
///        remain the only writer of USDC_ADDRESS under test/, with exactly one
///        test function.
///      - prank + startBroadcast are HARD-INCOMPATIBLE in the cheatcode layer
///        ("vm.startBroadcast: you have an active prank; broadcasting and pranks
///        are not compatible") and forge 1.9.0 ships only transact(bytes32) +
///        transact(uint256,bytes32) replay arities (measured: selectors
///        0x7d0f78f3 / 0x20a3cd86 -> unknown cheatcode; binary string audit lists
///        only the two txHash forms). No in-test lever makes run()'s caller ==
///        the broadcast deployer, so V1 `bill.owner() == msg.sender` (L46)
///        SUCCESS arm is harness-unreachable in `forge test` — pinned below as
///        the caller/deployer-split golden; true success arm lives in production
///        `forge script --broadcast` runs (anvil leg = CI scope, next tick card).
///      - vendored Vm has no txOrigin member (lib/forge-std/src/Vm.sol: prank
///        overloads L2665-2674 only).
contract DeployScriptGolden11255 is Test {
    /// Circle-native USDC on World Chain Sepolia (4801), per script header docs.
    address constant USDC_4801 = 0x66145f38cBAC35Ca6F1Dfb4914dF98F1614aeA88;

    /// Serialized gate matrix: one function -> no cross-thread env races.
    function test_deploy_script_gates_serialized() public {
        // ─── V1 fail arms (portal lane guards) ─────────────────────────
        // 1) zero-address env must hard-revert the deploy (L29 fail arm).
        vm.setEnv("USDC_ADDRESS", vm.toString(address(0)));
        TandaDeploy v1 = new TandaDeploy();
        vm.expectRevert(bytes("Set USDC_ADDRESS env var"));
        v1.run();

        // 2) empty-string env: envOr parse-fallback -> address(0) -> same require.
        vm.setEnv("USDC_ADDRESS", "");
        v1 = new TandaDeploy();
        vm.expectRevert(bytes("Set USDC_ADDRESS env var"));
        v1.run();

        // ─── V1 caller/deployer split (named harness limit, pinned) ────
        // 3) real USDC + bare call: run() executes through deploy, console block
        //    and the token golden (L45 SUCCESS arm) then reverts exactly on the
        //    owner arm (L46 FAIL arm: deployer==script != caller==test).
        vm.setEnv("USDC_ADDRESS", vm.toString(USDC_4801));
        v1 = new TandaDeploy();
        vm.expectRevert(bytes("Owner mismatch"));
        v1.run();

        // ─── V2 factory-lineage script (canonical 4801 W6 shape) ───────
        // 4) zero-address env must hard-revert (L21 fail arm).
        vm.setEnv("USDC_ADDRESS", vm.toString(address(0)));
        TandaDeployV2 v2 = new TandaDeployV2();
        vm.expectRevert(bytes("Set USDC_ADDRESS env var"));
        v2.run();

        // 5) happy path through L28: usdc require + impl->factory lineage
        //    golden both take their SUCCESS arms (V2 has no owner check).
        vm.setEnv("USDC_ADDRESS", vm.toString(USDC_4801));
        v2 = new TandaDeployV2();
        v2.run();
    }
}
