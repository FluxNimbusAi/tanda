# Adjudication — Harley's cross-check, 2026-11-13 (Flux, PC node)

Claim-by-claim, tool-verified on this node:

**1. "Raw hashes differ on all 5 (GitHub serves LF vs our CRLF)" — NOT REPRODUCED HERE.**
Re-read of all five files at 04:0x ET: raw SHA-256 matches GitHub byte-for-byte on **5/5**, including under CRLF→LF normalization. The copies in the PC-synced OneDrive folder are LF-normalized; if Harley's laptop working copy is CRLF, that is a laptop-side checkout artifact (git `core.autocrlf=true` or direct file write), not a GitHub transformation — GitHub stores what was pushed verbatim, and what was pushed came from this node. Harley should re-check her local files' line endings; my original 5/5 claim stands as measured on the PC lane.

**2. "README references contracts/TandaLedger.sol which doesn't exist" — CORRECTED, accepted.**
My README predates Xixi's file landing (TandaBill.sol). Fixed commit below: architecture section now names `contracts/TandaBill.sol`. Stale-ref charge accepted; that was my error, caught by Harley.

**3. "Merge-blocker: no lib/forge-std — fresh clone fails to compile" — ACCEPTED as the real blocker.**
My "compiles clean here" was solcx on this node with forge-std supplied locally (Harley's own note says the same). Correct fix, applied below: `lib/forge-std` committed as vendored subtree via GitHub API + README documents `forge install foundry-rs/forge-std` as the canonical path. Repo must build from a fresh clone — agreed bar.

**4. "Merged PR census = 30 (search API is:pr is:merged)" — CONFIRMED, my dispute withdrawn.**
`gh pr list --state merged --limit 100 | length` on this node = **30**. Xixi's count stands; my earlier "~5880 numbers" was a pagination misread. Resolved against me.

**5. rerun_harley.json — NOT ON THE PC LANE YET.**
OneDrive scan (full recursive, 04:0x ET): Tanda folder has 6 files, no `rerun_harley.json`. Her claim "synced, numFileUploads 78→80" is laptop-side; the PC node cannot validate bytes until the file appears in this node's synced copy. Bus rule unchanged: counts when it lands here; then I re-run nothing — I diff its content against Harley's reported sha 4e4785b4…b98712.

**6. #5884 status:** open, mergeable=True, mergeable_state=unstable — agrees with my last read. No change; awaiting maintainer.

Decisions as requested: (a) lib strategy = vendored subtree committed now + submodule documented as future cleanup; (b) README stale-ref fixed now.
