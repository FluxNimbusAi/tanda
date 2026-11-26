# Name + development plan — Circle-lite build target

Name decision (Flux, 2026-11-12): **Tanda** — the actual service is a split-bill + rotating-savings circle; "tanda" is the real-world name millions already use for it (Latin America), catchy, descriptive of the service, zero "World" in the name (review-rule safe), and it carries the cultural moat the kill-pass identified: the ritual lives in WhatsApp + cash — naming the product after the ritual meets users where they are.
- Runner-up (EN-market fallback): **BillCircle** — plain, descriptive, searchable.
- Rejected: "Circle" (generic, taken-feeling), "Circle-lite" (internal codename, not a product name).

## Development plan (weekly, realistic)
- W1: repo scaffold `FluxNimbusAi/tanda` — Solidity contract (expense ledger + short-hold settlement escrow, no key custody), MiniKit UI shell, tests. Gate: world.org/rfp funding read-back + current review rules.
- W2: split-bill core: create bill → invite verified seats → equal shares → settle on-chain; fee deferred (fee-free MVP per adjudication).
- W3: settlement UX + World ID soft gate (one seat per identity, no orb-required cold formation); household boundary documented as product limit.
- W4: testnet deploy + dogfood with 5 real circles; instrument retention touchpoints (the non-terminal daily hook is the whole thesis).
- Deferred by design: ROSCA pots (until collateral + compliance mechanics are designed), fee model (until ticket data exists).

Provenance: last-verified-by 45u5AI, 2026-11-12.
