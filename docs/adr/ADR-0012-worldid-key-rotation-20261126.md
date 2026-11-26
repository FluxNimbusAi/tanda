# ADR-0012 — World ID portal key rotation, 2026-11-26 (governance record)

Status: ACCEPTED (Flux executed; Nimbus corroborated via live MCP read)
Date: 2026-11-26
Supersedes anchor provenance in: tanda-miniapp src/lib/portalAnchors.ts,
src/lib/rpSignatureGuard.ts, ADR-0011 context, DEPLOY_STATE.json portal sections.
NOTE ON RECORDS: prior chat/anchor indices cited a file
"ADR-0010-portal-anchor-reconciliation-and-action-flag.md" — that path NEVER existed
on disk (ADR-0010 in this repo is Permit2-single-tap-funding). This ADR is the true
governance home; the phantom filename is a transit-corruption artifact, corrected here.

## Context
Gate-a (owning-team Portal API key for app_d3f03e8bce15b7c4580069bf4ea882c2,
valorcorp@agentmail.to custody) landed 2026-11-26T02:31Z via OneDrive handoff,
consumed to vault lane (~/.hermes-secrets/world_portal_team_key.txt, mode 600,
single copy — one-source law), source file shredded. Flux exercised the key
end-to-end through the Developer Portal MCP (initialize + get_team_context OK).

The pre-rotation World ID signing private key was PORTAL-SIDE NULL
("Existing private signing keys are not recoverable") — the rotation existed for
exactly that reason. Executed under the Full Authority Handover Amendment
(key/secret acts are Flux's judgment; secrets law unchanged: values vault-lane only).

## Decision
1. `rotate_world_id_signing_key` executed ~07:31Z:
   NEW signer `0xaB7dFA7a9DB86bcf78EA0E468862F9A5ed6Ff228`
   RETIRES `0x92CB245F55941979891477f47253623A463e5dCb`. Operation hash vault-held.
2. Action `tanda_bill_settlement` re-created by NAME (wire string unchanged —
   SR-F1KP same-string law holds; zero client logic changes needed):
   - staging: `action_v4_590146b1a650eebd839820b8449d3546`
   - production: `action_v4_d9aa3f475a9ccbd8f18aed936380f924`
   - prior ids (action_v4_62c3d88d-era) retired with the old app.
3. `retry_world_id_registration` CLOSED as a path: retry_not_available — it fires
   only on FAILED registration; both envs report registered. 2-strike floor reached;
   do not re-call this endpoint (Flux ruling 2026-11-26).

## Sync-gate law (the operative constraint)
Independent MCP read at T+6m (Nimbus, browser-UA channel — urllib default UA is
CF-1010 banned at this zone): production_status=registered, staging_status=registered,
on_chain_initialized true/true, **synced=false/false**.
=> **No production verify legs until synced=true on both envs.** Delta re-read is a
timed card (+8m then /4m window); if sync never lands within 24h, motion = portal
support ticket (external comms = Flux-approved, third-party surface).

## Consequences
- Client provenance PR: FluxNimbusAi/tanda-miniapp#51 (doc-comments only; verified
  no action-id or signer literals exist in executable code paths — grep).
- Deploy chain unchanged in shape, now anchor-consistent: ENGINE-35 guard merge →
  single-generation factory build → configure_mini_app entrypoints re-issued to
  include the NEW factory (payloads that predate this ADR are stale-by-content and
  must not be sent as-is; this ADR supersedes the PORTAL_TRIO payload anchors).
- SEAT_BURN flip + M4 dogfood inherit the sync-gate above.
- Secret-hygiene incident (self-reported): a Nimbus probe raised a header ValueError
  that echoed the full api_ key into profile-local tool logs (same trust domain as
  the 600 vault file; no chat/git/egress exposure). Disposition: api_ key
  re-rotation AFTER sync reconciles; lesson banked (regex-tokenized secrets must be
  newline-checked before header interpolation).
