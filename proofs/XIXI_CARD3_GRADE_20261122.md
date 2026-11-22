# XIXI_CARD3 GRADE — REBASE-REQUIRED (Flux ruling 2026-11-22)

Verdict: NOT pass/fail. The golden spec's loci and repo_anchor cite the 17,127 B laptop copy
(git-blob fb846d5381e5a7553852f2c066e9870d2b3a6829), which is a pre-#32 revision.

Canonical at main befa86bf0494d07a864717483c580c36dc272b5e:
- contracts/TandaBillV2.sol git-blob 2eb989d669fd7a0c0469ec410f65bec2ff798660, 26,490 B LF (recomputed on my disk: git blob = 26,490 B LF; worktree CRLF copy = 26,969 raw — packet anchor confirmed exact), sha256-LF 6ea3a1dc430848b524fe6ac0e9706ed44589b531083bfd45fedfe26303db6e0a — matches packet anchor exactly.

Consequence: every L-locus in per_test/cei_assertions/hook_token_matrix must be re-derived against
the canonical blob before the suite can be graded executable. Semantic intent (CEI reorder + strict-bool
SafeERC20 guard) IS satisfied on canonical by 595bf5abb + 7c632761f — shape_b law enforcement is live;
the spec's line numbers are stale, not its law.

Action: rebase the golden suite onto canonical loci (Flux lane), then grade executable coverage.
