# Tanda

On-chain split-bill settlement circles for verified humans. One World ID = one seat. Members record shared expenses; the contract settles equal shares on settlement — short hold, no custody of keys, no pots.

**Why:** split-bills are a recurring, non-terminal ritual (the daily hook). Personhood-as-seat is the moat: identity is the collateral that off-chain trust circles lack. ROSCA pots are deferred until collateral + compliance mechanics are designed — see `docs/killpass-adjudication.md`.

## Architecture
- `contracts/TandaLedger.sol` — expense ledger + equal-share settlement escrow (short hold, non-custodial copy must match code).
- MiniKit app shell — seat registration via World ID integration, bill creation, share settlement.
- Fee model deferred: fee-free MVP; priced from real ticket data, not before it exists.

## W1 scope (this week)
- `forge init` contract + tests skeleton (Foundry 1.9.0, sigstore-verified on laptop node).
- MiniKit UI shell directory layout.
- README + docs mirror of the adjudication and dev plan.
- Gates before budgeting: world.org/rfp dev-rewards continuation read-back; current review rules (no "World" in app name — this name complies; live World ID integration required at review).

## Weekly targets
W2 split-bill core → W3 settlement UX + World ID soft gate → W4 testnet deploy + dogfood with 5 real circles. See worldapp-recon/docs/06-name-and-dev-plan.md.

Provenance: repo opened by Flux (PC node, verified gh credential) 2026-11-12; laptop lane (Harley/Xixi) executes W1 scaffold on push once token transport lands.
