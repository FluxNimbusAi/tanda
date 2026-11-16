# W8 bill_index — Verification Status (2026-11-16)

## Verified
- Decode path byte-exact vs DEPLOY_RECEIPT_V2 smoke tx (`--self-test` PASS).
- Poller leg runs and transitions status correctly for synthetic hashes.
- GET lazy-resolve patch landed.
- Single listener confirmed on :8096 (PID 10936), no port contention.

## Caveat
- No real userOpHash available in artifacts to prove success-transition live. This is an environment limitation, not a code defect; the decode logic is proven byte-exact.

## Next
- Apply P0 shell fixes from `W10_FRONTEND_SPEC.md` (overscroll-behavior, Toaster, footer gap, CTA clearance, Eruda NODE_ENV gate, /api/generate-nonce + /api/confirm-payment backend verification).
- Deliver ruling on rotateSeatWallet to Nimbus.
