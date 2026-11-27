# ENGINE-61 — bill_index :8096 freshness reload (G2G-6 endpoints live)

Card: t_1a322004 | Date: 2026-11-27 11:39-11:45 EST | Actor: Nimbus (continuity tick)

## Delta found
- Live worker PID 20204 ran since 2026-11-24 16:44:53 EST — pre-G2G-6.
- `GET /api/funnel` returned 404 while main carried the endpoint since
  squash `987b49c78` (PR #217, merged 2026-11-27 09:01 EST).
- Runtime source = `services/bill_index.py` (recorded cmdline of PID 20204);
  root `bill_index.py` (16,814 B, Nov 22) remains decoy per R-44a census.
  DB stays repo-root `bill_index.db` via `DB_PATH = parents[1]` (L26-27) —
  cwd-independent.

## Action taken
1. `taskkill /PID 20204 /F` — old worker terminated; :8096 freed.
2. Supervisor chain (19980 -> 5816, launched Nov 24) auto-respawned the
   canonical worker pair 24960 -> 30652 at 11:42:30 EST from the post-#217
   working tree (file mtime 11:41).
3. A manual `Start-Process` launch (tree 25064 -> 28744, 11:42:26) briefly
   created a second Windows duplicate-bind listener; tree-killed
   `/PID 25064 /T`. Canonical supervised worker 30652 retained.

## Post-reload verification (live probes, same tick)
- `GET /health` -> 200; `GET /api/funnel` -> 200 (was 404).
- `/api/funnel` body = pure aggregate: per-source {sent, opens, open_rate},
  organic_opens, share_opens, badge_bar_15pct_any; zero 0x-address
  occurrences (wallet-escape assert holds live, SR-RV-A1 posture).
- `POST /api/track` (no auth) -> 401 — keyed lane fail-closed confirmed.
- `_write_key()` resolves per-request (env -> vault fallback, L145+), so the
  respawned worker needs no env refresh; supervisor staleness ruled out.
- `netstat`: exactly one LISTENING PID on 127.0.0.1:8096 = 30652.

## Anchors (recomputed from disk bytes this tick, 0 CRLF)
- main HEAD squash: 987b49c78; blob services/bill_index.py @ main:
  3eed8acb0ac74d6c45503e6ebded77e07f9a5bc6 (== working tree).
- services/bill_index.py: 72,861 B;
  sha256_LF 818e9e0a19bea2f1f2fb9ec8d25731ccc18827ff415fe6878fabe76a40f5df7b
  — MATCHES commit fd5b4a447 Receipt-SHA256 trailer (graded).
- tests/test_funnel_track.py: 3,629 B;
  sha256_LF e8c0a34961d03947dd1864e83ecbe0a09067a51396d11d51d5811b0ad81d5763
  — MATCHES secondary anchor in fd5b4a447 body (graded).
- Board: t_a83e4336 done (G2G-6), t_1a322004 = this card, t_9d3c71e2 park
  check 25 valid (awaiting_review, 11:08 EST readback; next wake ~12:08 EST).
