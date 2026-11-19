# ADR-0010: Permit2 single-tap escrow funding (`fundEscrowFromPermit2`)

- **Status:** Proposed → Implemented on branch `w2.5/permit2-funding` (PR for Closes #22)
- **Date:** 2026-11-19
- **Authors:** Nimbus (recon + draft), direction: Flux wave-2.5 rank-2 brief + owner World Chain brief (card `t_fb1c0ea8`)
- **Scope:** testnet-only contract addition; **no mainnet deploy in this wave**; fully reversible (new implementation + new factory; old clones keep old rules)

## Context

Tanda escrow funding today is `token.approve(bill, x)` **then** `bill.fundEscrow(x)`. In World App
(Safe smart-account + paymaster-sponsored `userOp`s) each user-signed call is its own confirmation
popup, so funding costs **two taps** — the top churn source on the deposit step.

The wave brief asked for a Permit2 path keyed on `PERMIT2_SIGNATURE_PLACEHOLDER_0`
(canonical `0x000000000022D473030F116dDEE9F6B43aC78BA3`). Recon against the **live host-app
reality** refined the mechanism; this ADR records both the finding and the chosen design.

## Research findings (all fetched/verified 2026-11-19)

**E1 — MiniKit v2 deprecated the SignatureTransfer placeholder flow.**
Official docs (https://docs.world.org/mini-apps/commands/send-transaction, retrieved 2026-11-19):
> "Breaking Changes in MiniKit v2: **SignatureTransfer is no longer supported. Please use
> Allowance Transfers documented below.** Standard ERC-20 `approve()` calls now work in mini apps.
> Approval will be automatically revoked after the transaction."

The migration guide (https://docs.world.org/mini-apps/migration/minikit-v2) adds: `sendTransaction`
now takes pre-encoded calldata and returns a `userOpHash`; "Permit2 switched from SignatureTransfer
to AllowanceTransfer". `PERMIT2_SIGNATURE_PLACEHOLDER_0` was the **v1** backend-injection mechanism
for a one-shot `ISignatureTransfer` EIP-712 message (per the archived v1 doc
`worldcoin/world-id-docs@ d770a94 …/send-transaction.mdx`). It is history, not the current wire.

**E2 — The app pins minikit-js 2.0.3; the vendored SDK has zero placeholder machinery.**
`FluxNimbusAi/tanda-miniapp` `package.json`: `"@worldcoin/minikit-js": "2.0.3"`,
`"@worldcoin/minikit-react": "2.0.3"`. Grep of `node_modules/@worldcoin/minikit-js/build/` and
`minikit-react/`: **no `PERMIT2` string at all** — client-side placeholder substitution is gone;
allowance injection is host-backend-side within the bundled `userOp`. This is the decisive
SDK-before-docs check (host-app capability questions settle from the vendored SDK).

**E3 — The v2 single-tap bundle shape.** Per the docs example, one `MiniKit.sendTransaction`
carries a transaction **array**; World App auto-approves the token to Permit2 and revokes after the
transaction. Bundle for a Tanda deposit:

1. `token.approve(Permit2, x)` — injected by World App (invisible to the mini app). This is
   required because Permit2's internal pull calls `token.transferFrom(owner, to, x)` **as Permit2
   itself** (spender of the token-layer allowance = Permit2).
2. `permit2.approve(token, bill, x, expiration=0)` — Permit2-layer allowance, owner-signed by the
   user's account, spender = the bill clone.
3. `bill.fundEscrowFromPermit2(x)` — our new call; internally
   `permit2.transferFrom(payer, bill, uint160(x), token)`.

One userOp → **one popup**, paymaster-covered gas → zero user ETH. Contract-side, the signature
argument disappears: the allowance model is what the host bundles.

**E4 — `expiration = 0` is a same-block fuse (replay-safety).**
Permit2 `src/libraries/Allowance.sol` (`updateAmountAndExpiration`):
`allowed.expiration = expiration == 0 ? uint48(block.timestamp) : expiration;`
and `_transfer` reverts `AllowanceExpired` when `block.timestamp > expiration`. A docs-example
bundle with `expiration = 0` therefore only ever works **inside the same block** — a captured or
replayed stale bundle can never drain the user. This is a property of the design, so the golden
suite pins it as a test.

**E5 — uint160 amount domain.** `IAllowanceTransfer.transferFrom(address,address,uint160,address)`
takes `uint160`; a Solidity explicit downcast **truncates silently** (`uint160(2**160)` → 0). The
new entrypoint must guard `amount > type(uint160).max` with its own revert, else an astronomically
large "dust-proof" input would fund 0 escrow while passing every balance check.

**E6 — Canonical Permit2 is live on World Chain Sepolia.**
`eth_getCode 0x000000000022D473030F116dDEE9F6B43aC78BA3 @ latest` → runtime **9152 B**
(RPC `https://worldchain-sepolia.g.alchemy.com/public`, chainId `0x12c1` = 4801, 2026-11-19).
Behavior-verified (not source-verified) — see Verification.

**E7 — Token surface.** Bill token: USDC `0x66145f38cBAC35Ca6F1Dfb4914dF98F1614aeA88` (1852 B
proxy → impl `0x46100463…51f8`). `DOMAIN_SEPARATOR()` answers; EIP-2612 `nonces(address)` reverts,
so the token-level `permit()` signature route is **not relied on anywhere** in this design — the
AllowanceTransfer path only needs plain `approve` + `transferFrom`, which Circle FiatToken always
provides.

**E8 — Identity physics under the factory forwarder.** MiniKit entrypoint = the static factory;
`callBill(bill, data)` appends the caller tail and the clone recovers the payer via `_caller()`.
The Permit2 pull must use `payer = _caller()` (the human wallet), never `msg.sender` (the factory).
PackedAllowance is keyed `[payer][token][bill]`, so the user's `permit2.approve` must name the
**clone address** as spender — escrow isolation per bill is preserved (no cross-clone spend).

## Decision

Add to `TandaBillV2` (purely additive):

```solidity
address public constant PERMIT2 = 0x000000000022D473030F116dDEE9F6B43aC78BA3;

interface IPermit2Transfer {
    function transferFrom(address from, address to, uint160 amount, address token) external;
}

error Permit2AmountTooLarge();

/// Single-tap escrow funding via Permit2 AllowanceTransfer (MiniKit v2 bundle step 3).
function fundEscrowFromPermit2(uint256 amount) external {
    address payer = _caller();
    if (amount > type(uint160).max) revert Permit2AmountTooLarge();
    IPermit2Transfer(PERMIT2).transferFrom(payer, address(this), uint160(amount), address(token));
    escrowBalance += amount;
    emit EscrowFunded(payer, amount);
}
```

- **`fundEscrow()` untouched** — the approve+pull legacy path stays byte-intact (direct EOAs,
  non-World wallets, existing tests). The brief requires both paths coexist.
- **Event reuse `EscrowFunded(funder, amount)`** → the `:8096` indexer (SR-003 parity) and the
  mini-app wire format need **zero changes**; `funder` = payer identity, matching `fundEscrow`.
- **No owner-gate** — mirrors `fundEscrow` open-funder semantics (anyone may top up escrow from
  their own funds; the pull can only ever move `payer`'s own approved money).
- **No signature parameter** — E1–E3: the v2 host bundles approvals; the bill only pulls. A
  v1-style `bytes signature` entrypoint would be dead surface for this app's SDK.
- **Storage layout unchanged** (constant + function only) → clone-compatible; existing bill slots
  keep their meaning; no migration.
- **Deployment physics:** `implementation` is immutable per factory (kill-pass), so this ships as
  a **new implementation + new factory instance**. Old bills delegate to old impls and simply lack
  the new selector; new bills get both paths. Reversal = app pins the old factory again.

## Rejected alternatives

1. **v1 `PERMIT2_SIGNATURE_PLACEHOLDER_0` / `ISignatureTransfer` entrypoint** (the brief's literal
   mechanism). Rejected by E1–E2: unsupported in the pinned MiniKit 2.x; would be unverifiable
   end-to-end and dead code. The brief's *goal* (one-tap, zero-gas Permit2 funding) is fully met by
   the AllowanceTransfer bundle.
2. **EIP-3009 / `token.permit` direct signature into `fundEscrow`.** Rejected: Sepolia USDC lacks
   the EIP-2612 surface (E7); Safe (1271) signing adds a second verification path the bill would
   have to trust; and it reintroduces signature-replay concerns Permit2's nonce/expiration model
   handles centrally.
3. **Client-side "bundle" = still two popups with a paymaster doing the middle.** Rejected: that is
   the status-quo churn this ADR removes.
4. **Upgradeable bills.** Rejected by invariant 1 (no key custody; settled-escrow safety > feature
   velocity).

## Consequences

- Funding is one tap on World Chain with zero ETH cost; the same call works from any EOA/wallet
  that can set a Permit2 allowance (no host lock-in at the contract layer).
- Replay window for a captured bundle: **0 blocks** when the app uses `expiration = 0` (E4) —
  golden-tested. If the app opts for a future expiration (e.g. offline-signed flows), the bill can
  only pull up to the approved amount for the approved spender, and `permit2.lockdown` remains a
  user-side kill switch.
- Dust/exactness table for the pre-merge dust proof (Xixi gate):
  - pull amount must equal the intended funding amount; `PackedAllowance` decrements exactly (no
    silent over-pull) — golden-tested;
  - funding **over** `_unsettledTotal()` is legal (escrow top-up; surplus stays `escrowBalance` and
    is reusable/refundable through the existing legs);
  - 1-wei funding with 2-seat split pays `[1, 0]` — payout legs already proven in P0.1a pull model;
  - `amount = 0` funds 0 and emits `EscrowFunded(0)` — parity with `fundEscrow(0)`;
  - `amount > type(uint160).max` reverts `Permit2AmountTooLarge` with token state untouched (E5).
- Indexer/mini-app: **no ABI re-pin required for `EscrowFunded`**; the new selector
  `fundEscrowFromPermit2(uint256)` must be added to the frontend ABI surface + Developer-Portal
  entrypoint allowlist when the app switches to the new factory (frontend lane, follow-up card).
- Mainnet: out of scope; re-verify E2/E4/E6 against whatever MiniKit the mainnet app ships before
  any mainnet gate.

## Verification plan (executed on this branch)

1. **Golden forge suite** `test/Permit2Funding.t.sol` — uses the **production Permit2 runtime
   bytes etched at the canonical address** (`test/lib/permit2-4801.hex`, sha256-pinned), factory +
   clone lineage per the canonical test scheme: same-block happy path, next-block
   `AllowanceExpired`, exact consumption, `type(uint160).max` unlimited pull,
   `Permit2AmountTooLarge` bound, forwarder (`callBill`) payer identity, 1-wei dust split,
   zero-amount parity, legacy `fundEscrow` coexistence, full lifecycle on a Permit2-funded escrow.
2. **CI** foundry+python lanes green at exact head.
3. **Sepolia live gate** (World Chain Sepolia 4801, pair: Alchemy public + `4801.rpc.thirdweb.com`
   second provider — see receipt): fresh impl+factory deploy, clone create, **real Permit2 +
   real USDC** two-tx pull (future-expiration form), same-block-fuse negative (expiration=0 then
   next-block → AllowanceExpired), exact-consumption negative, escrow accounting parity,
   lifecycle-open proof. Receipt JSON on the PR per the gate-receipt format.
4. **Xixi dust proof** (pre-merge gate) — dust table above is the test surface.
