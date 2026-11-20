// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

import {TandaBillV2, IERC20} from "../contracts/TandaBillV2.sol";
import {FastTandaBillV2} from "../contracts/FastTandaBillV2.sol";
import {TandaBillFactory} from "../contracts/TandaBillFactory.sol";
import {Test} from "forge-std/Test.sol";

/// @notice Test ERC-20 (6-decimal USDC shape, same semantics as MockToken in
///         TandaBillV2.t.sol). Production Permit2 pulls via
///         token.transferFrom(user -> bill) with msg.sender == permit2, so the
///         user's token-layer approve(Permit2, x) (bundle step 1) is exercised for real.
contract TestToken {
    uint8 public decimals = 6;
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

/// @notice AllowanceTransfer write/read surface used by the single-tap bundle (steps 2 + 3).
interface IPermit2Test {
    struct PackedAllowance {
        uint160 amount;
        uint48 expiration;
        uint48 nonce;
    }

    function approve(address token, address spender, uint160 amount, uint48 expiration) external;

    function allowance(address owner, address token, address spender)
        external
        view
        returns (PackedAllowance memory);
}

/// @notice Permit2 revert vocabulary pinned by the goldens (src/libraries/Allowance.sol).
interface IPermit2Errors {
    error AllowanceExpired(uint256 expiration);
    error InsufficientAllowance(uint256 amount);
}

/// @title Permit2Funding — ADR-0010 golden suite (W2.5-1, card t_fb1c0ea8)
/// @notice fundEscrowFromPermit2 single-tap escrow funding against the PRODUCTION Permit2
///         runtime (test/lib/permit2-4801.hex: 9152 B fetched from World Chain Sepolia 4801,
///         byte-identical dual-RPC sha256, pinned in-test). Legacy fundEscrow() coexistence
///         is asserted on the same clones. Factory-lineage setup per the canonical test scheme.
contract Permit2FundingTest is Test {
    IPermit2Test internal constant permit2 = IPermit2Test(0x000000000022D473030F116dDEE9F6B43aC78BA3);

    /// @dev sha256 of the raw runtime bytes; verified against
    ///      https://worldchain-sepolia.g.alchemy.com/public AND https://4801.rpc.thirdweb.com
    ///      on 2026-11-19 (both RPCs and the fixture agree byte-for-byte).
    bytes32 internal constant PERMIT2_RUNTIME_SHA =
        0x9284b0799f02db6587342dd312dbff8108ffbf8b874100d2d6d377a0220c4fcc;

    // Mirrors TandaBillV2.EscrowFunded — indexer/ABI shape must stay identical (ADR-0010).
    event EscrowFunded(address indexed funder, uint256 amount);

    TestToken internal token;
    TandaBillFactory internal factory;
    TandaBillV2 internal bill;

    address internal owner = address(0xA11CE); // creator = seat 0 (canonical scheme)
    address internal seat1 = address(0xB0B);
    address internal outsider = address(0xDEAD);

    function setUp() public {
        bytes memory p2Code = vm.parseBytes(vm.readFile("test/lib/permit2-4801.hex"));
        assertEq(sha256(p2Code), PERMIT2_RUNTIME_SHA, "permit2 fixture drift vs live 4801");
        vm.etch(address(permit2), p2Code);
        assertEq(address(permit2).code.length, 9152, "etch size");

        token = new TestToken();
        factory = new TandaBillFactory(address(new TandaBillV2()));
        address[] memory seats = new address[](2);
        seats[0] = owner;
        seats[1] = seat1;
        vm.prank(owner);
        bill = TandaBillV2(payable(factory.createBill(IERC20(address(token)), seats)));

        vm.warp(1_730_000_000); // realistic timestamp; expiration=0 = same-block fuse (E4)
    }

    /// @dev Bundle steps 1+2 as World App would inject them: token->Permit2, Permit2->clone.
    function _bundleApprove(address who, address spender, uint256 amount, uint48 expiration) internal {
        vm.startPrank(who);
        token.approve(address(permit2), amount);
        permit2.approve(address(token), spender, uint160(amount), expiration);
        vm.stopPrank();
    }

    // ─── Selector / constant surface pins (frontend + Developer-Portal allowlist) ──

    function test_SurfacePin_SelectorAndConstant() public view {
        assertEq(
            bill.fundEscrowFromPermit2.selector,
            bytes4(keccak256("fundEscrowFromPermit2(uint256)")),
            "selector pin"
        );
        assertEq(bill.PERMIT2(), address(permit2), "PERMIT2 constant pin");
    }

    // ─── Golden 1: single-tap happy path, same block (E3/E4) ──────────────────────

    function test_HappyPath_FundsEscrowInSameBlock() public {
        token.mint(owner, 1000);
        _bundleApprove(owner, address(bill), 500, 0);

        vm.expectEmit(true, false, false, true);
        emit EscrowFunded(owner, 500);
        vm.prank(owner);
        bill.fundEscrowFromPermit2(500);

        assertEq(bill.escrowBalance(), 500, "escrow credited");
        assertEq(token.balanceOf(address(bill)), 500, "bill holds funds");
        assertEq(token.balanceOf(owner), 500, "payer debited once");
        assertEq(permit2.allowance(owner, address(token), address(bill)).amount, 0, "exact consume");
    }

    // ─── Golden 2: expiration=0 same-block fuse ⇒ next-block replay dead (E4) ─────

    function test_SameBlockFuse_ExpiresNextBlock() public {
        token.mint(owner, 500);
        _bundleApprove(owner, address(bill), 500, 0);

        vm.warp(block.timestamp + 1); // next block: captured bundle replay
        vm.expectPartialRevert(IPermit2Errors.AllowanceExpired.selector);
        vm.prank(owner);
        bill.fundEscrowFromPermit2(500);

        assertEq(bill.escrowBalance(), 0, "no funds moved on expired fuse");
    }

    // ─── Golden 3: exact consumption, then InsufficientAllowance (dust table) ──────

    function test_ExactConsumption_PartialPulls() public {
        token.mint(owner, 10);
        _bundleApprove(owner, address(bill), 10, 0);

        vm.prank(owner);
        bill.fundEscrowFromPermit2(6);
        assertEq(permit2.allowance(owner, address(token), address(bill)).amount, 4, "no over-pull");

        vm.prank(owner);
        bill.fundEscrowFromPermit2(4);
        assertEq(bill.escrowBalance(), 10, "exact total");
        assertEq(permit2.allowance(owner, address(token), address(bill)).amount, 0);

        vm.expectPartialRevert(IPermit2Errors.InsufficientAllowance.selector);
        vm.prank(owner);
        bill.fundEscrowFromPermit2(1);
    }

    // ─── Golden 4: uint160.max is the unlimited-allowance sentinel (E5 domain) ─────

    function test_UnlimitedDomain_TypeUint160MaxPull() public {
        token.mint(owner, type(uint160).max);
        _bundleApprove(owner, address(bill), type(uint160).max, 0);

        vm.prank(owner);
        bill.fundEscrowFromPermit2(type(uint160).max);
        assertEq(bill.escrowBalance(), type(uint160).max, "boundary inclusive");
    }

    // ─── Golden 5: amount > type(uint160).max reverts, state untouched (E5) ────────

    function test_TooLarge_BoundedRevert() public {
        token.mint(owner, 5);
        _bundleApprove(owner, address(bill), 5, 0);

        vm.expectRevert(abi.encodeWithSelector(TandaBillV2.Permit2AmountTooLarge.selector));
        vm.prank(owner);
        bill.fundEscrowFromPermit2(uint256(type(uint160).max) + 1);

        assertEq(bill.escrowBalance(), 0, "guard fires before any pull");
        assertEq(token.balanceOf(owner), 5, "token state untouched");
    }

    // ─── Golden 6: forwarder identity — pull only ever moves the CALLER's money (E8) ─

    function test_ForwarderIdentity_NoSpoofing() public {
        token.mint(outsider, 700);
        _bundleApprove(outsider, address(bill), 700, 0);

        // owner cannot pull outsider's allowance (keyed [payer][token][bill], payer=_caller)
        vm.expectPartialRevert(IPermit2Errors.AllowanceExpired.selector);
        vm.prank(owner);
        bill.fundEscrowFromPermit2(700);
        assertEq(token.balanceOf(outsider), 700, "peer allowance unreachable");

        // routed through the factory forwarder (MiniKit path): payer resolves to the human
        vm.expectEmit(true, false, false, true);
        emit EscrowFunded(outsider, 700);
        vm.prank(outsider);
        factory.callBill(address(bill), abi.encodeCall(TandaBillV2.fundEscrowFromPermit2, (700)));

        assertEq(bill.escrowBalance(), 700, "forwarded funding");
        assertEq(token.balanceOf(outsider), 0, "outsider debited exactly once");
    }

    // ─── Golden 7: per-clone escrow isolation — allowance named for bill A is
    //     unreachable from bill B of the same factory (E8) ─────────────────────────

    function test_PerBillIsolation() public {
        address[] memory seats = new address[](2);
        seats[0] = owner;
        seats[1] = seat1;
        vm.prank(owner);
        address billB = factory.createBill(IERC20(address(token)), seats);

        token.mint(outsider, 700);
        _bundleApprove(outsider, address(bill), 700, 0); // spender = bill ONLY

        vm.expectPartialRevert(IPermit2Errors.AllowanceExpired.selector);
        vm.prank(outsider);
        TandaBillV2(payable(billB)).fundEscrowFromPermit2(700);

        assertEq(TandaBillV2(payable(billB)).escrowBalance(), 0, "no cross-clone spend");
        assertEq(token.balanceOf(outsider), 700, "outsider untouched");
    }

    // ─── Golden 8: amount=0 parity with legacy fundEscrow(0) (dust table) ──────────

    function test_ZeroAmount_Parity() public {
        token.mint(owner, 1);
        _bundleApprove(owner, address(bill), 0, 0);

        vm.expectEmit(true, false, false, true);
        emit EscrowFunded(owner, 0);
        vm.prank(owner);
        bill.fundEscrowFromPermit2(0);
        assertEq(bill.escrowBalance(), 0);

        vm.prank(owner);
        bill.fundEscrow(0); // legacy twin behavior identical
        assertEq(bill.escrowBalance(), 0);
    }

    // ─── Golden 9: legacy approve+fundEscrow path byte-intact AND coexistent ───────

    function test_LegacyCoexistence() public {
        // legacy: approve to the CLONE directly (no Permit2 involved)
        token.mint(owner, 1000);
        vm.startPrank(owner);
        token.approve(address(bill), 400);
        bill.fundEscrow(400);
        vm.stopPrank();

        // permit2: approve to Permit2, bill pulls via allowance
        _bundleApprove(owner, address(bill), 600, 0);
        vm.prank(owner);
        bill.fundEscrowFromPermit2(600);

        assertEq(bill.escrowBalance(), 1000, "both legs sum");
        assertEq(token.balanceOf(address(bill)), 1000, "bill custody exact");
        assertEq(token.allowance(owner, address(bill)), 0, "legacy consumed");
        assertEq(permit2.allowance(owner, address(token), address(bill)).amount, 0, "p2 consumed");
    }

    // ─── Golden 10: 1-wei Permit2-funded dust split + full lifecycle ───────────────

    function test_OneWeiDust_FullLifecycle() public {
        vm.prank(owner);
        bill.addExpense(1);

        token.mint(owner, 1);
        _bundleApprove(owner, address(bill), 1, 0);
        vm.prank(owner);
        bill.fundEscrowFromPermit2(1);

        vm.prank(owner);
        bill.initiateSettlement();
        uint256[] memory payouts = bill.settlementPayouts(0);
        assertEq(payouts[0], 1, "dust split [1, 0]");
        assertEq(payouts[1], 0);

        vm.prank(owner);
        bill.confirmSettlement(0);
        vm.prank(seat1);
        bill.confirmSettlement(0);
        vm.warp(block.timestamp + 1 hours); // V2 SETTLEMENT_WINDOW
        vm.prank(outsider);
        bill.executeSettlement(0);

        vm.prank(owner);
        bill.claimSettlement(0);
        assertEq(token.balanceOf(owner), 1, "owner pulled share");
        vm.prank(seat1);
        bill.claimSettlement(0);
        assertEq(token.balanceOf(seat1), 0, "zero-wei leg claimable, pays 0");
    }

    // ─── Golden 11: full-value lifecycle on a Permit2-funded escrow ────────────────

    function test_FullLifecycle_Permit2Funded() public {
        vm.prank(owner);
        bill.addExpense(300);

        token.mint(owner, 300);
        _bundleApprove(owner, address(bill), 300, 0);
        vm.prank(owner);
        bill.fundEscrowFromPermit2(300);

        vm.prank(owner);
        bill.initiateSettlement();
        vm.prank(owner);
        bill.confirmSettlement(0);
        vm.prank(seat1);
        bill.confirmSettlement(0);
        vm.warp(block.timestamp + 1 hours);
        vm.prank(outsider);
        bill.executeSettlement(0);

        assertEq(bill.claimablePayout(0, owner), 150);
        vm.prank(owner);
        bill.claimSettlement(0);
        vm.prank(seat1);
        bill.claimSettlement(0);
        assertEq(token.balanceOf(owner), 150, "owner net: paid 300, got 150 back");
        assertEq(token.balanceOf(seat1), 150, "seat1 received share");
        assertEq(token.balanceOf(address(bill)), 0, "escrow drained exactly");
    }

    // ─── Golden 12: Fast twin parity — same function, same constant, same guard ────

    function test_FastTwinParity() public {
        TandaBillFactory fastFactory = new TandaBillFactory(address(new FastTandaBillV2()));
        address[] memory seats = new address[](2);
        seats[0] = owner;
        seats[1] = seat1;
        vm.prank(owner);
        FastTandaBillV2 fbill = FastTandaBillV2(payable(fastFactory.createBill(IERC20(address(token)), seats)));

        assertEq(fbill.PERMIT2(), address(permit2), "twin constant");
        assertEq(
            fbill.fundEscrowFromPermit2.selector,
            bill.fundEscrowFromPermit2.selector,
            "twin selector"
        );

        token.mint(owner, 123);
        _bundleApprove(owner, address(fbill), 123, 0);
        vm.prank(owner);
        fbill.fundEscrowFromPermit2(123);
        assertEq(fbill.escrowBalance(), 123, "twin funding works");

        vm.expectRevert(abi.encodeWithSelector(FastTandaBillV2.Permit2AmountTooLarge.selector));
        vm.prank(owner);
        fbill.fundEscrowFromPermit2(uint256(type(uint160).max) + 1);
    }
}
