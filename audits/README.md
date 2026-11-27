# audits/ — canonical evidence index for the TandaBill product family

**Status (2026-11-27): no external third-party audit yet.** TandaBill runs
on World Chain testnet 4801 where escrow carries no real value. A
third-party contract audit is planned as a mainnet-GA precondition; when
reports land, they go here with their sha256 receipts stated in the
commit that adds them.

What exists today is a published internal-verification record — every
artifact below is machine-checkable against the repo it came from.

## Internal audit artifacts (this repo)

| Artifact | What it proves |
|---|---|
| `proofs/SECURITY_SWEEP_20261124.json`, `proofs/SECURITY_SWEEP_20261125.json` | Dedicated security sweeps: stale-anchor scans, voided-portal containment checks |
| `gaps_full.json`, `gaps_after.json` (repo root) | Forge test-matrix census + named coverage-gap landscape |
| `proofs/` (100+ files) | Per-card graded receipts: E2E route matrices, broadcast proofs, deploy-receipt grades, bounds guards |
| `DEPLOY_RECEIPT.json`, `DEPLOY_RECEIPT_V2.json` | Deployed-address ↔ build-artifact anchors (bytecode equality on-chain) |
| `W7_SOURCE_REPRODUCIBILITY_SIGNOFF_20261115.md` | Source-reproducibility signoff lane |
| `.github/workflows/ci.yml` | Every PR: `forge build`, full forge suite, Python regression suite |

## Sibling surfaces

- **Mini-app** (`FluxNimbusAi/tanda-miniapp`): signing-oracle fail-closed,
  anchor coercion, notification idempotency — pinned by compliance golden
  tests in its CI; its `audits/` dir carries the client-surface lane.
- **Website** (`FluxNimbusAi/tandabill-website`): static marketing plus one
  signature-verified serverless webhook receiver.

## Naming law for external reports

`YYYY-MM-DD_<auditor>_<scope>.pdf` plus a sibling `.md` summary stating:
scope, environment, findings by severity, remediation status, and the
sha256 of the report bytes — so the file itself is verifiable, not just
linked. Findings never get quietly dropped: each gets a disposition in
`proofs/` or a named issue.
