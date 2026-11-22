# M4-1 Hosting Reconciliation Brief — Vercel vs ADR-0009 Plan B (Flux GO 2026-11-21)

**Author:** Nimbus (COO, PC node) · **Swarm-Card:** m4_hosting / t_3aed711f · **main_sha(tanda)=** 227f954741-era main
**Sources (all re-read on disk this turn, not from memory):**
- M4_HOSTING_PLAN_V2.md (canonical, sha256 d32bd7699791e6a4d4c03f385a94e8132b0d745a3ed868f24e5457e002e3fee1) + DNS_ENV_CHECKLIST_V2.md (ac3b08e0cb8f9a9943cac58c25ed7ed074d2dd140e92970928c741c1d9e0d09c)
- ADR-0009 (hosting-plan-b worktree, Proposed — pending Flux gate)
- Live probes: cloudflared 2026.11.1 at AppData/Local/hermes/tools/node-26.12.1-win32-x64/; npx vercel 66.6.0 cached; :8096 healthy 23,626 s; no ~/.vercel auth, no VERCEL_TOKEN env, no vercel_token.txt in vault.

## 1. Which plan — RECOMMENDATION: VERCEL (path a: device login)

Decisive asymmetry: World portal `configure_mini_app.integration_url` needs a **stable HTTPS origin** across the reviewer's acceptance window. Vercel's default `*.vercel.app` domain is stable, free, zero-DNS (checklist D1 ✅). ADR-0009 Plan B serves the app from this PC through a **trycloudflare quick tunnel = ephemeral URL that dies with the process** — a reviewer clicking a stale URL fails the acceptance test even when the app is healthy. The durable Plan-B variant (named tunnel) requires a **Cloudflare account + a domain** (registrar for FluxNimbusAi: unconfirmed on this PC, checklist D2/D3) = strictly MORE external-registration surface than the Vercel path.

Second asymmetry: ADR-0009 is a **pre-stage-only** ADR — it built the standalone build artifact (`output:'standalone'`, pinned tracing root) + 3-stage Dockerfile, and explicitly recorded: **no docker daemon on this PC**, no mkcert, and both cloudflared and ngrok account paths = boundary-3 items. It was never a hosting ruling; adopting "Plan B" now means either accepting ephemeral URLs (1) or provisioning Cloudflare+domain (2), neither of which its own text authorizes.

Vercel's residual dependency is the ONE thing already ruled in v2 (11-19): existing org project, free tier, sole hard gate = credential provisioning. Nothing in this brief re-opens that ruling; it confirms Plan B has no cheaper surviving path.

## 2. Blast radius per option
- **Vercel (recommended):** owner-side act = either `npx vercel login` device OAuth in external terminal (preferred; zero secrets transit) OR one API token from the EXISTING FluxNimbusAi Vercel org → `~/.hermes-secrets/vercel_token.txt`. No new account if org exists (v2 ruling says it does); if org does NOT exist, Hobby signup is a boundary-3 [HUMAN_GATE] act by owner, then identical flow. Deploy from CLEAN main checkout only (v2 pitfall: local clone had dirty-tree drift). Rollback = integration_url flip-back to get_app_config snapshot (R2: `vercel rm` FORBIDDEN — shared org project).
- **Quick tunnel (t_b3e207f9 precedent):** zero-account, already proven, but ephemeral — usable ONLY as the B2 indexer lane (BILL_INDEX_URL) under Vercel, matching v1 Option A rehearsal mode. Not a stable app origin.
- **Plan B durable:** Cloudflare named tunnel (account = [HUMAN_GATE] registration) + domain (unowned/purchase = paid) + PC-kept-up SLA + no docker daemon today (standalone `node server.js` possible, still PC-bound). Largest external surface, weakest uptime story.
- **Note both hybrid rows:** even Vercel + Option-A grants lane makes JOIN WRITE (verify-proof → POST /grants) depend on PC liveness during review; Option C (display-only, join unreleased) removes it entirely for the acceptance window, grants lane re-armed with durable tunnel in Phase 2.

## 3. Uptime dependency
- Vercel app lane: ZERO dependency on this PC (serverless; repo-CI proven `next build` with zero env).
- Grants lane (if Option A): PC must be up during actual user joins — for the REVIEW window Flux's own tie-breaker is satisfied either way IF reviewers only exercise display/auth lanes during acceptance (Option C posture).
- Plan B: PC must be up for EVERYTHING, continuously, including reviewer pokes at an unstable URL. Strictly dominated.

## 4. Exact card transitions
- Vercel ruling: `m4_hosting` → done (result = this brief + v2 docs as deliverables). `t_3aed711f` → stays blocked, blocked_reason narrowed to "awaiting owner device login/token ONLY"; on auth landing: unblock → runbook v2 steps 2-7 (link, env matrix E1-E8+ (sensitive via dashboard/`vercel env add`), preview, `deploy --prod` from clean checkout, snapshot-first integration_url flip via MCP `configure_mini_app`), receipts per step, Flux gates the portal write? No — dev-app config = Flux custody per v2 ruling #3, post-merge of CI + diff-review per charter.
- Plan B ruling (rejected): t_3aed711f → converts to [HUMAN_GATE] chain Cloudflare-account+domain first; ADR-0009 status Proposed→Accepted only after those exist. Not recommended.
- Either way: **no provisioning happens before Flux's ruling packet reply.**

## 5. One-line verdict
Vercel (device login) wins on stability, blast radius, and existing-ruling continuity; Plan B's only surviving role is exactly the role v1 already gave it — the B2 indexer quick-tunnel lane — with Option C display-only posture covering the acceptance window.
