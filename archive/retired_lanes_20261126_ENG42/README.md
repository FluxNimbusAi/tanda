# Retired lanes — ENG-42 (card t_d3b102d3), 2026-11-26

Disposition per ENGINE-41 sweep receipt (`proofs/SEC_SWEEP_41_20261126.json`,
defect D1): `contract_loop_proof_CLEAN_recovered.py` archived out of `scripts/`
instead of re-pinned.

Why archived, not re-pinned:
- The lane is a double zombie. Its `SIGNER_ADDR` pinned the pre-11-21-rotation
  (burned-lineage) signer `0x78dC32`, while `load_signer()` derives the key from
  `~/.hermes-secrets/metamask-cli-wallet.txt` — post-rotation that vault resolves
  to the `0x98D238` lineage (independently re-derived during ENG-42: match True).
  The equality assert therefore hard-failed every run, and a vault regression to
  the old mnemonic would have silently signed with the burned key.
- Re-pinning the signer would still leave the lane targeting the retired pre-V3
  factory pair (`0x65Ba0bB` / impl `0x52d2b14c`). The canonical lane is
  `scripts/contract_loop_proof_V3.py`, pinned to the V3 hardened pair
  (`0x010872d47b` / `0xd0cc3595`, proofs/DEPLOY_RECEIPT_V3_HARDENED_20261121.json),
  with signer `0x98D238` in code.
- Nothing in CI, tests, or docs referenced the recovered script.

The file is preserved byte-unmodified for audit. Use V3 for all live loop proofs.
