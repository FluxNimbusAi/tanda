# Twin-contract scan 6 — main @ 5f6ea04a6673be5b0a66174000caec7fe4e50baf

Card: t_25d1cc98 (TWIN-SCAN-6, family B2). Trigger: 6872247dc (#195 bounds-guard
OOB views on both twins) moved contracts/ since last verdict @e743a64d (2026-11-25, CLEAN).

Recipe: scan origin/main git blobs for `.transfer(|.transferFrom(|.approve(` across
contracts/*.sol (5 files, 1389 lines), classify SAFE-LIB / RETURN-CHECKED / BARE,
exclude interface declarations.

## Hits (4 total)
| file | line | classification | note |
|---|---|---|---|
| FastTandaBillV2.sol | 282 | PERMIT2-INTENTIONAL | IPermit2Transfer(PERMIT2).transferFrom — void-return interface, revert-or-succeed (anchor matches e743a64d) |
| TandaBillV2.sol | 326 | PERMIT2-INTENTIONAL | same shape (anchor matches e743a64d) |
| SafeERC20Minimal.sol | 11 | DOC | @dev comment, not a call site |
| TandaBill.sol | 217 | DOC | comment describing removed bare-require pattern |

## Corroboration — all live ERC20 legs are SAFE-LIB
- TandaBillV2.sol: 3 SafeERC20Minimal sites (L302 funding, L459 payout, L481 refund)
- FastTandaBillV2.sol: SafeERC20Funding.safeTransferFrom L258 + SafeERC20Minimal L382/L405
- TandaBill.sol: 2 sites (L145, L227)
- TandaBillFactory.sol: 0 transfer call sites
- Zero `.approve(` call sites (unchanged from e743a64d)

## Verdict
CLEAN — 0 defect lines. No new cards generated. #195 introduced no bare-transfer drift.
