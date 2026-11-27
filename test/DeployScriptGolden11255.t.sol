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
    /// Foundry default sender. PROBE-60/61 (throwaway probes, deleted after
    /// verdict) measured: every CREATE executed inside a script run() under
    /// startBroadcast is charged to THIS account's nonce in the test process -
    /// NOT to the script contract's address (call shape) and NOT to
    /// address(this) (delegatecall shape). Proof: impl ==
    /// computeCreateAddress(defaultSender, 2), factory ==
    /// computeCreateAddress(defaultSender, 3) matched the script's own
    /// console lines exactly. Reverted runs roll the nonce back; successful
    /// creates keep advancing it.
    ///
    /// CRITICAL (PROBE-61, forge 1.9.0): the default vm.mockCall overload
    /// ETCHES 1 BYTE of code into every codeless callee (forge-std Vm.sol
    /// docs: "the other overload etches a single byte into an empty account
    /// to circumvent Solidity's extcodesize check"). If an etched address is
    /// also the NEXT broadcast-CREATE target, the create hits
    /// CreateCollision and the executor nonce-walks into a ~1.02B-gas OOG
    /// with a dataless revert. So every ENGINE-60 mock below (a) targets the
    /// exact live create address derived from vm.getNonce(DEF_SENDER), never
    /// a candidate range, and (b) uses mockCall(..., injectCode=false) so
    /// even the exact target stays codeless. Per Vm.sol docs, mocked calls
    /// that RETURN data still succeed on codeless accounts (return-data
    /// paths check returndatasize, not extcodesize) - all getters here
    /// return data. Ghost-PASS is impossible: a wrong create-address guess
    /// leaves the real deployed code answering the getter, so the expected
    /// require never fires and expectRevert fails loudly.
    address constant DEF_SENDER = 0x1804c8AB1F12E6bbf3894d4083f33e07309d1f38;

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

        // ─── TICK-1125-7 / ENGINE 26A: caller==deployer via DELEGATECALL ───
        // The 1125-5 limit was real for CALL shape: startBroadcast makes the
        // script contract the CREATE sender while msg.sender stays the test,
        // so L46 could only ever take its FAIL arm. delegatecall collapses the
        // script body into THIS contract's context: msg.sender, the CREATE
        // sender and the owner field all become address(this), unlocking
        // L46-SUCCESS + L47 line/success + L49/L50 console lines. Still inside
        // the ONE serialized function (USDC_ADDRESS single-writer law holds).
        vm.setEnv("USDC_ADDRESS", vm.toString(USDC_4801));
        v1 = new TandaDeploy();
        (bool delOk, bytes memory delRet) =
            address(v1).delegatecall(abi.encodeWithSignature("run()"));
        assertTrue(delOk, "delegated run(): owner/seats arms must pass");
        // Empty return data (run() returns nothing) doubles as revert-free proof.
        assertEq(delRet.length, 0, "delegated run() left revert data");
        // Measured harness semantics (this tick, twice): delOk==true IS the
        // L46-SUCCESS + L47-SUCCESS + L49/L50 witness — the call body runs to
        // completion, and case 3 above proves any owner-arm failure reverts
        // with "Owner mismatch" and would flip delOk false. The deployed bill
        // is NOT predictable via computeCreateAddress(address(this), n):
        // CREATEs executed inside vm.startBroadcast() are charged to the
        // broadcast recorder, not the test-context EVM nonce (measured 12->12),
        // so no post-state address assertion belongs here. Arm coverage is
        // proven by forge coverage on script/TandaDeploy.s.sol (see
        // proofs/gaps_after_26a.json).
        // Dead-defense pins (UNREACHABLE BY CONSTRUCTION, measured 1125-5):
        // - L45 FAIL: token() is the constructor arg echoed back; no lever.
        // - L47 FAIL: run() never adds seats before the check; invariant.
        // - V2 L28 FAIL: TandaBillFactory.implementation is `address public
        //   immutable` (contracts/TandaBillFactory.sol:13), set from the
        //   constructor; factory is deployed on the line above the require.

        // ─── ENGINE-60: the 3 dead-defense FAIL arms CRACKED ─────────────
        // "No lever" was true only at the CONSTRUCTION level. The guarded
        // reads (token/owner/activeSeatCount/implementation) are all EXTERNAL
        // getter calls, and vm.mockCall intercepts calls at the EVM boundary
        // regardless of what the deployed code would return. PROBE-60/61
        // measured the creator of every in-script CREATE as DEF_SENDER at the
        // LIVE nonce (see header above): the single precise target is
        // computeCreateAddress(DEF_SENDER, vm.getNonce(DEF_SENDER)) for V1's
        // one-create run(), and that plus n+1 for V2's factory (impl lands on
        // n, factory on n+1). Candidate-range mocking is FORBIDDEN here: the
        // default mockCall overload etches a byte into each codeless callee,
        // and an etched byte on the live create address triggers
        // CreateCollision -> executor nonce-walk -> ~1.02B-gas OOG with a
        // dataless revert (measured 2026-11-27, first iteration of this
        // block). injectCode=false + precise targeting keeps the create path
        // clean; if the guessed address were ever wrong, the REAL code would
        // answer the getter, the expected require would not fire, and
        // expectRevert would fail loudly — no ghost-PASS possible.
        // Still inside the ONE serialized function - USDC_ADDRESS
        // single-writer law holds.

        // 6) V1 L45 FAIL arm: token() getter -> foreign address.
        vm.setEnv("USDC_ADDRESS", vm.toString(USDC_4801));
        {
            TandaDeploy m1 = new TandaDeploy();
            address bill1 = vm.computeCreateAddress(DEF_SENDER, vm.getNonce(DEF_SENDER));
            vm.mockCall(
                bill1,
                abi.encodeWithSignature("token()"),
                abi.encode(address(0xB0A7)),
                false
            );
            vm.expectRevert(bytes("Token mismatch"));
            m1.run();
            vm.clearMockedCalls();
        }

        // 7) V1 L47 FAIL arm: L46 crossed honestly via owner() mock ==
        //    address(this) (caller==deployer collapse WITHOUT delegatecall),
        //    then activeSeatCount() mock returns 1. token() stays real so the
        //    L45 SUCCESS arm is exercised again inside this leg too.
        vm.setEnv("USDC_ADDRESS", vm.toString(USDC_4801));
        {
            TandaDeploy m2 = new TandaDeploy();
            address bill2 = vm.computeCreateAddress(DEF_SENDER, vm.getNonce(DEF_SENDER));
            vm.mockCall(
                bill2, abi.encodeWithSignature("owner()"), abi.encode(address(this)), false
            );
            vm.mockCall(
                bill2, abi.encodeWithSignature("activeSeatCount()"), abi.encode(uint256(1)), false
            );
            vm.expectRevert(bytes("Should start with 0 seats"));
            m2.run();
            vm.clearMockedCalls();
        }

        // 8) V2 L28 FAIL arm: factory.implementation() getter -> foreign impl.
        //    (script deploys impl at live nonce n, factory at n+1; the mock
        //    targets ONLY the factory so impl-side behavior stays real.)
        vm.setEnv("USDC_ADDRESS", vm.toString(USDC_4801));
        {
            TandaDeployV2 m3 = new TandaDeployV2();
            address facAddr = vm.computeCreateAddress(DEF_SENDER, vm.getNonce(DEF_SENDER) + 1);
            vm.mockCall(
                facAddr,
                abi.encodeWithSignature("implementation()"),
                abi.encode(address(0xDEAD)),
                false
            );
            vm.expectRevert(bytes("Impl mismatch"));
            m3.run();
            vm.clearMockedCalls();
        }
    }
}
