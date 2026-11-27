# Security Policy — tanda

This is the money layer of TandaBill: the USDC bill-escrow contracts
(`contracts/`), the bill indexer (`bill_index.py`), the nudge engine, and
the deploy/verification lane. The user-facing app lives in
[`FluxNimbusAi/tanda-miniapp`](https://github.com/FluxNimbusAi/tanda-miniapp).

One law governs every claim below: **the contract state is the only source
of truth about money — any off-chain surface that disagrees with it is a
bug.**

## Reporting a vulnerability

Email **tandabill-support@agentmail.to** with:

- the surface (contract function, indexer path, engine routine) and how to
  reach it — deployed addresses are pinned in `DEPLOY_RECEIPT*.json`
- a minimal reproduction — testnet steps only; never exploit live users
- what you believe the impact is

We acknowledge within 72 hours. Triage is by funds-at-risk, not by label:
anything that can move or strand escrow without a seat-owner's action is
critical and outranks all feature work.

## Scope

In scope:

- `contracts/` — `TandaBillV2.sol` (canonical deployment),
  `TandaBill.sol` (legacy), `TandaBillFactory.sol`, `SafeERC20Minimal.sol`
- the bill indexer and its write path (`bill_index.py`)
- notification nudge engine and its template substitution
- deploy scripts and the on-chain artifact verification lane

Out of scope (by design, not dismissal):

- the USDC token contract itself and World Chain sequencer/infra
- World ID / Orb attestation infrastructure
- testnet-only value: World Chain 4801 carries no real funds today;
  mainnet GA re-scopes this document
- `TandaBill.sol` V1 — superseded lineage (see
  `docs/SUPERSEDED_LINEAGE_README.md`); V2 is the deployed source of truth

## Known issues (live honesty section)

- **Coverage is published, not promised.** The forge test-matrix census and
  the named coverage-gap landscape live at `gaps_full.json` /
  `gaps_after.json` (repo root) with per-card evidence in `proofs/`.
  Some state transitions are still exercised only at unit depth; the gap
  files are the honest index of which.
- **No pre-flight token-reality probe.** The escrow trusts its pinned USDC
  address; fee-on-transfer/rebase/blocklist behavior of arbitrary ERC-20s
  is untested because non-pinned tokens cannot enter a bill. If custom
  tokens are ever enabled, this becomes a required gate first.
- **Indexer is eventually consistent by design.** After a restart it
  rebuilds state from chain events; read surfaces may lag the chain briefly
  mid-resync. Settlement itself never depends on the indexer — claims are
  enforced on-chain.
- **No external third-party audit yet.** See `audits/README.md`.

## Hardening already in place (so reports land faster)

- Every PR runs `forge build` + the full forge suite (29 test files) and
  the Python regression suite in CI.
- `proofs/` (100+ artifacts) binds test claims to machine-checkable
  receipts, including dedicated security sweeps
  (`proofs/SECURITY_SWEEP_20261124.json`, `...20261125.json`).
- Deployed bytecode is anchor-verified against build artifacts
  (`DEPLOY_RECEIPT*.json`, source-reproducibility signoff in
  `W7_SOURCE_REPRODUCIBILITY_SIGNOFF_20261115.md`).
- Key/portal rotation is handled as a recorded ADR process
  (`docs/adr/`), not an ad-hoc swap.
- Every commit carries provenance trailers
  ([`FluxNimbusAi/provenance-gate`](https://github.com/FluxNimbusAi/provenance-gate)
  `TRAILER_SCHEMA.md`) and a nightly sweep re-validates the public record.
