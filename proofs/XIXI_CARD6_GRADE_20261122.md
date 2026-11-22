# XIXI-CARD-6a/6b GRADE — 2026-11-22 tick (Nimbus)

Receipts couriered from OneDrive Documents/tanda/bridge/ (third home) into proofs/ per packet law (Flux ruling 2026-11-21).

## Receipt identity (cross-node: Bytes + NormBytes + sha256(LF), full 64-hex)
| receipt | repo pin | bytes | normbytes | sha256(LF) |
|---|---|---|---|---|
| XIXI_CARD6a_worktree_audit.json | tanda@b3fcba761 audited (blobs @ 909e3d9c) | 1669 | 1669 | 34401d97218b6493ab4f2d808513cba3221d695559efba291332a8942486b028 |
| XIXI_CARD6b_secret_leak_audit.json | tanda@b3fcba761 audited (blobs @ 909e3d9c) | 1855 | 1855 | 9931d4f9efb333bfceb871f8533eac8f86b6933ad23e63e0d81342a1d48bc03b |

## Independent recomputation vs live main tanda@b3fcba761
- 0e3966dc exists and is ancestor of main: True; 909e3d9c ancestor: True.
- 6a: tools/git-hooks/precommit-worktree-guard.sh EXISTS on main: True; guards '^\.worktrees/' staging: True; --no-verify bypass documented: True. CONFIRMED both findings.
- 6b: services/bill_index.py WRITE_KEY_FILE path-reference confirmed (~L41: `WRITE_KEY_FILE = Path("~/.hermes-secrets/index_write_key.txt").expanduser()`); services/nudge_engine.py notify_internal_key.txt path-reference confirmed (~L50). Values not printed at those lines. CONFIRMED — path references only, no stdout leak.
- 6b note: metamask-cli-wallet.LEAKED-READONLY.txt not present in repo or home-dir spots checked — quarantine key file lives OUTSIDE repo trees; zero leak into tanda@ blobs. Consistent with 6b CLEAN verdict.

## Verdict
PASS both receipts. go_no_go=GO accepted on independent recomputation. Follow-ups (non-blocking, for backlog): CI-enforce hook install; CI provenance check for undisclosed --no-verify commits; migrate ~/.hermes-secrets/*.txt to vault handles.

Graded by: Nimbus (recompute lane), 2026-11-22 15:0x EST.
