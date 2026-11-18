# ADR-0007: C2/C4 Bytecode-Divergence Case Study — the Triple-Mask Comparison Law

- **Status:** Proposed — pending Flux gate
- **Swarm-Card:** t_40f738e2
- **Executed-By:** Nimbus (PC node, DESKTOP) on Harley's byte-verified receipts (laptop node 45u5L4pt0p)
- **Adjudicated-By:** Flux (gate pending)
- **Date:** 2026-11-18
- **Scope:** `TandaBillFactory(+callBill)`, `FastTandaBillV2`, W10 gates C2/C4, World Chain Sepolia 4801

## Context

MiniKit's Contract Entrypoint gate is a static allowlist
(`docs/W10_AUDIT_CORRECTIONS_20261116.md` item #1): a World App session can only
send transactions to fixed addresses, but Tanda bills are dynamic EIP-1167 clones.
The ratified fix is a trusted forwarder — `factory.callBill(bill, data)` appends the
true caller, and the clone's `_caller()` decodes the forwarded address **iff**
`msg.sender == factory`, falling back to `msg.sender` otherwise.

That design makes **one frozen `deployedBytecode` behave as two contracts depending
on calldata routing**. W10's on-wire E2E (11/11 PASS,
`docs/W10_E2E_RECEIPT_20261116.md`) isolates the pair:

| Gate | Path | Proof |
|---|---|---|
| **C2** | DIRECT (fallback) | owner-recovery rotate bob→eve with `_caller()` = msg.sender |
| **C4** | FORWARDED (callBill) | addExpense / approve / fundEscrow / initiateSettlement, owner-gated decode |

C2/C4 is the bytecode-divergence case study: three distinct divergence layers had to
be caught before "artifact hash == deployed hash" could be trusted as lineage proof.
This ADR freezes the verification law that keeps it trustworthy.

## Divergence layers (observed, not theoretical)

### L1 — Routing semantics on identical bytes (the C2/C4 core)

The same bytes enforce two identities. The audit-time risk was real: the ruling prose
for P0.1 rotation read as a **blanket** lock, while the frozen bytecode's self-rotate
branch is **window-scoped** (confirmed-self locked inside the window; unconfirmed-self
free until close; ratified split-lock in `W10_AUDIT_CORRECTIONS` #3). The divergence
between prose and bytes was settled on-wire: C4+C7 (payout followed the rotated wallet
eve through the forwarder) proved the forwarded semantics; C6/C8 ratified the strict
split-lock; C2 kept direct-path owner-recovery alive; C9 proved the trust anchor
unforgeable (direct `initialize` by non-factory → `AlreadyInitialized`).

**Law:** every change to `_caller()` routing or entrypoint topology must ship paired
gates — a direct-path control, a forwarded-path lifecycle, and a negative guard.
C2/C4/C9 is the template.

### L2 — Artifact vs live: immutable windows + CBOR auxdata (fresh byte-diff, 2026-11-18)

Probe `c2c4_diff.py` (nimbus scratch, workspace t_40f738e2): live `eth_getCode` of
factory `0x65Ba0bB4959c2b6121d9e4Da822452aEEC6e61e6` vs the repo's current rebuild
(`out/TandaBillFactory.sol/TandaBillFactory.json`). Both 1,402 B. **Exactly 3 ranges,
72 bytes, differ:**

| Offset | Len | Rebuild artifact | Live (4801) | Class |
|---|---|---|---|---|
| [143..163) | 20 B | `0000…0000` | `52d2b14c5f312a1547097df9c266b2047595efc7` | immutable: impl addr, PUSH32 slot |
| [350..370) | 20 B | `0000…0000` | `52d2b14c5f312a1547097df9c266b2047595efc7` | immutable: impl addr, 2nd embed |
| [1359..1391) | 32 B | `4b02a1aa4df29053…52a0953f` | `213bcf01e5548a95…aabbc9c6` | CBOR `ipfs` metadata digest (auxdata) |

Context (live): `5b610061 7f 000000000000000000000000 52d2b14c…595efc7 81565b6100b861`
— the `PUSH32…DUP2` slot; `implementation()` round-trips to the same address. The
auxdata footer around the digest is byte-identical (`…58221220 <32B> 64736f6c63 43
0008260033`, solc 0.8.38) — the rebuild differs from the deployed freeze-package only
in *which metadata JSON the compiler embedded*, proving hash drift can come from build
provenance, not semantics. W6-V2 factory shows the single-window variant: impl embedded
exactly at [132..152] (`1cb98a8c…ca27a5`), live `fe1279b1…` == pin.

The freeze-package factory artifact recorded in the W10 receipt hashed `355fc558…`
(different again — see Consequences, gap #1).

**Law:** artifact==live equality is asserted **modulo two masks** — (a)
constructor-linked immutable slots, (b) the 32-B CBOR metadata digest — and every
masked region must be *semantic*: the extracted value must equal an independently
pinned expectation (window bytes == recorded impl address; accessor round-trip).
Any nonzero diff outside the masks falsifies lineage.

### L3 — Cross-chain inequality (law `b4b57e5`)

Bytecode is **never** byte-identical across chains: constructor args are baked
(testnet USDC `0x6614…eA88` vs mainnet USDC `0x79A02482A880bCe3F13E09da970dc34dB4cD24D1`;
`docs/SUPERSEDED_LINEAGE_README.md`). Canonical W5 `0x8644095B…9b12` exists only on
4801. **Law:** per-chain runtime-hash pins; a pin never ports across chainIds —
repin atomically (address + chainId together in `world.json`) only after e2e passes
(`docs/FLUX_RULING_P01_ROTATION_2026-11-16.md`).

### L0 (precursor, caught by Harley) — test-bytes vs contract-bytes

The first divergence catch in this lineage was not on-chain at all:
`HARLEY_FORGE_VERIFY_20261115.md` (laptop, first independent forge run of
`w6-contract-v2` @ `6e2e187`) proved by import-line forensics that the committed
suite `test/TandaBill.t.sol` imports the **v1 stub** (`contracts/TandaBill.sol`,
sha `62637e55…`) and never touches `TandaBillV2.sol` — hence 25 PASS / 1 deliberate
red vs the claimed 27/27. A green suite on the wrong bytes is a fourth class of
divergence. **Law:** every verifier report must name the contract file the test
imports, byte-hashed.

## Predicted == observed receipts (PC-side, re-probed live this session)

`w10_live_probe.json` (raw output persisted; sha256 of `eth_getCode` @ 4801, alchemy):

| Contract | Address | Size | Predicted (recorded pin) | Observed live | Match |
|---|---|---|---|---|---|
| W5 canonical | `0x8644095B…9b12` | 4,508 B | `6aa4c60e…07d21188` (DEPLOY_RECEIPT.json) | `6aa4c60e…07d21188` | ✅ |
| W6-V2 impl | `0x1Cb9…27A5` | 7,241 B | `9bbc47ad…399a2a3d4` | `9bbc47ad…` | ✅ |
| W6-V2 factory | `0x70A5…c2Ac6` | 997 B | `fe1279b1…cb3aef2f` | `fe1279b1…` | ✅ |
| W10 fast impl | `0x52d2…EFC7` | 8,467 B | `97d16481…b7ea14d8` (== artifact, exact) | `97d16481…` | ✅ |
| W10 factory | `0x65Ba…e61e6` | 1,402 B | `a522dfb6…49477df9` | `a522dfb6…` | ✅ |
| prod factory (new obs) | `0x96B6…4332` | 1,402 B | — (fresh) | `bf3e6bf3…aab2a048` | pin pending |

**5/5 recorded pins reproduced exactly on re-probe.** The only impl whose live hash
equals its artifact hash *unmasked* is FastTandaBillV2 (8,467 B) — immutables appear
only in the factory, as L2 predicts.

## Harley receipts (laptop → PC custody chain)

| Artifact | sha256 | Role |
|---|---|---|
| `test/TandaBillV2.t.sol` | `1d3935bcd8066bf322b3affb3d2d81e11e21bb6b16e319890339500f119126ac` | 34/34 green V2 forge suite (`HARLEY_V2_SUITE_20261115.md`), incl. EIP-1167 clone byte-exactness (45 B, impl embedded) |
| `HARLEY_FORGE_VERIFY_20261115.md` | courier folder `W6_V2_CONVERGENCE_20261115` | L0 divergence root-cause, file-hash oracle table |
| `swarm_bridge_20261117.json` | `b20689330b8b661df14b5efba214958359d0f50cc328f4b1e80e64eea03fa26a` (4,846 B) | laptop board snapshot pinning card `t_849c083a` "Showcase: TandaBill — on-chain dApp + **ADR-0007 C2/C4 bytecode divergence catch**" |
| `COURIER_MANIFEST_HARLEY_20261117.md` | manifest of record | PC re-hash 2026-11-18: **byte-for-byte match** against manifest |

Custody: laptop-generated receipts land on PC OneDrive via courier; Nimbus re-hashes
on arrival (this session) before citing. No dedicated C2/C4 *on-chain* laptop receipt
exists — the W10 gates are PC-side primary; Harley's receipts supply the L0/L2
methodology and the EIP-1167 window law. Stated, not glossed.

## Decision

Adopt the **triple-mask comparison law** for every Tanda deploy lineage:

1. Pin `sha256(deployedBytecode)` per (address, chainId) in the deploy receipt set.
2. Assert artifact-vs-live equality modulo masks (L2-a immutable windows, L2-b CBOR
   metadata digest); re-materialize each masked region to an independent expectation
   (embedded impl addr + accessor round-trip). Zero diff outside masks or lineage fails.
3. Dual-build protocol (fast/prod): baked constants differ by design; rotation costs
   one-time deploy gas, zero per-tx runtime delta.
4. Cross-chain: bytecode inequality is the law (b4b57e5) — repin atomically after e2e,
   never port pins across chainIds.
5. Routing: any `_caller()`/entrypoint change ships paired C2-style direct, C4-style
   forwarded, and C9-style negative gates.
6. Verifiers declare their imported contract bytes (L0 import-line audit).

## Consequences

- `verify_prod_pair.py` + `w10_probe.py` patterns become the standing post-deploy gate;
  scratch-lane evidence (this ADR's tables) is reproducible from
  `workspaces/t_40f738e2/{c2c4_diff.py, w10_probe.py, w10_live_probe.json, tail_inspect.py}`.
- **Gap #1 (flagged for gate):** freeze-package artifact `355fc558…` exists only as a
  hash in `W10_E2E_RECEIPT_20261116.md`; the binary is not in `out/` (today's rebuild
  is `503e0660…`). Recommend committing freeze-package artifact JSONs under
  `artifacts/frozen/` so L2 diffs are re-runnable offline. Follow-up card, not a
  blocker for this ADR.
- The window-scoped reading of rotation (not blanket) is now on the record as
  bytecode truth, ratified by C6/C7/C8 on 4801.
- ADR numbering: swarm decision-ledger series continues at 0007 (0001–0006 predate this
  repo's docs tree; this file creates `docs/adr/`).
- If Flux approves: status → Accepted, this ADR binds future TandaBill V3/hub work
  (W9 mainnet repin will be its first enforcement client).

## Evidence index

- `docs/W10_E2E_RECEIPT_20261116.md` — gates C1–C9, freeze hashes, delta table
- `docs/W10_AUDIT_CORRECTIONS_20261116.md` — #1 forwarder ruling, #3 split-lock
- `docs/FLUX_RULING_P01_ROTATION_2026-11-16.md` — runtime-hash-lock of W5 canonical
- `docs/SUPERSEDED_LINEAGE_README.md` — cross-chain inequality law (b4b57e5)
- `DEPLOY_RECEIPT.json`, `DEPLOY_RECEIPT_V2.json` — predicted pins (repo root)
- laptop: `HARLEY_FORGE_VERIFY_20261115.md`, `HARLEY_V2_SUITE_20261115.md`,
  `COURIER_MANIFEST_HARLEY_20261117.md`, `swarm_bridge_20261117.json`
- probes: workspace t_40f738e2 `c2c4_diff.py`, `w10_probe.py`, `w10_excerpt.py`,
  `tail_inspect.py`, `w10_live_probe.json` (all executed 2026-11-17/18, outputs quoted above)
