[![CI](https://github.com/FluxNimbusAi/tanda/actions/workflows/ci.yml/badge.svg)](https://github.com/FluxNimbusAi/tanda/actions/workflows/ci.yml)

# Tanda

On-chain split-bill settlement circles for verified humans. One World ID = one seat. Members record shared expenses; the contract settles equal shares on settlement — short hold, no custody of keys, no pots.

**Why:** split-bills are a recurring, non-terminal ritual (the daily hook). Personhood-as-seat is the moat: identity is the collateral that off-chain trust circles lack. ROSCA pots are deferred until collateral + compliance mechanics are designed — see `docs/killpass-adjudication.md`.

## Architecture
- `contracts/TandaBill.sol` — expense ledger + equal-share settlement escrow (short hold, non-custodial copy must match code).
- MiniKit app shell — seat registration via World ID integration, bill creation, share settlement.
- `services/nudge_engine.py` — P1.1 MiniKit cadence nudge (six settlement triggers, hard frequency caps, default-off). Guide: `docs/MINIKIT_CADENCE_NUDGE.md`; release entry: `CHANGELOG.md`.
- Fee model deferred: fee-free MVP; priced from real ticket data, not before it exists.

## W1 scope (this week)
- `forge init` contract + tests skeleton (Foundry 1.9.0, sigstore-verified on laptop node).
- MiniKit UI shell directory layout.
- README + docs mirror of the adjudication and dev plan.
- Gates before budgeting: world.org/rfp dev-rewards continuation read-back; current review rules (no "World" in app name — this name complies; live World ID integration required at review).

## Weekly targets
W2 split-bill core → W3 settlement UX + World ID soft gate → W4 testnet deploy + dogfood with 5 real circles. See worldapp-recon/docs/06-name-and-dev-plan.md.

Provenance: repo opened by Flux (PC node, verified gh credential) 2026-11-12; laptop lane (Harley/Xixi) executes W1 scaffold on push once token transport lands.

Build from a fresh clone: `forge install foundry-rs/forge-std` (canonical). A vendored `lib/forge-std/src/Test.sol` is committed for CI-from-clone; submodule conversion at W2.


## W7 source-reproducibility — verified cross-reference (bus ruling 2026-11-15, Flux)

Sign-off (`W7_SOURCE_REPRODUCIBILITY_SIGNOFF_20261115.md`) independently recomputed on the PC node against this repo's `artifacts/verification-standard-json.json`, pinned solc 0.8.38, stored settings:
1. Init code sha256 (bytes): `3946e26302bfc782ecbafa578fe9cf1bf56f9945cf11e4f2866479fc25881afc` — verified, 4,671 B.
2. Runtime with zeroed immutables: `dcde760ef2478a761528dac6eccdfecebda9d4a47d8a759b9c04681be741039d` — verified, 4,508 B.
3. USDC bake at slots 752/1568/3657 → live runtime `6aa4c60ef2d13d6fe18113aaebcb169e70c6b9f691bc4f249488d22107d21188` — verified.

Mispost on Strata #5959 adjudicated: content archived verbatim, correction comment posted (comment 6905096420), duplicate pair collapsed per bus ruling. Nothing deleted upstream.
