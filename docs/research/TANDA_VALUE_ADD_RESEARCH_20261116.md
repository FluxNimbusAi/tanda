# TandaBill — Value-Add Research Digest (2026-11-16)

> Produced by Nimbus via 3-lane fan-out research (delegate_task), requested by d3b0m3n in Flux-Nimbus Bridge.
> Inputs: World MiniApp docs (quick-start + guidelines + policy), web2 incumbent user-sentiment research,
> crypto-native group-settlement landscape, World App mini-app ecosystem scan.
> NOTE: `reported`/`UNVERIFIED` items are subagent claims not independently byte-checked; URLs given for spot-audit.

---

## Lane 1: Web2 bill-splitting incumbents (Splitwise, Settle Up, Tricount, Splid, Venmo Groups, Google Pay groups, Kittysplit, PayPal ecosystem)

### Findings

**1. Splitwise**  `[verified]`
- Pain point / observation: Core-loop monetization squeeze: ~3-4 expenses/day cap on free tier plus forced 10s ads after each expense; long-time users report the app 'feels dead to use as a free user' and churn over it
- Lesson for Tanda: Never meter the core loop. Tanda's free seat-log + settle path IS the moat — every incumbent that paywalled basic expense entry created a switching cohort; Tanda's zero-fee model should be advertised as 'never a cap on entries'
- Evidence: https://www.reddit.com/r/androidapps/comments/1mynv2j/splitwise_feels_dead_to_use_as_a_free_user_i_cant/

**2. Splitwise**  `[verified]`
- Pain point / observation: Daily expense limit (2023 onward) triggered explicit comparisons to Settle Up, Tricount, Sesterce and Splid — users tried alternatives but left because Splitwise UI/UX and per-expense share handling were still best-in-class
- Lesson for Tanda: Paywall churn only converts if your UX matches the incumbent; Tanda must beat Splitwise on entry speed (MiniKit quick-add) or free-ness alone won't retain refugees
- Evidence: https://www.reddit.com/r/androidapps/comments/17prad3/splitwise_is_now_useless_without_pro/

**3. Splitwise**  `[verified]`
- Pain point / observation: Splitwise Pay is the #1 complaint: physical-mail identity verification, 2-5 day processing + 2-3 day deposits, no undo for sender and no reject for receiver, funds 'hostage' in Splitwise's bank, payments marked settled while money never arrived
- Lesson for Tanda: This is Tanda's clearest structural win: escrowed USDC settles in one on-chain step with instant finality and no custodial hostage state — and World ID replaces their archaic mail verification. Market settlement speed, not 'crypto'
- Evidence: https://www.reddit.com/r/ynab/comments/125rbny/does_anyone_else_hate_splitwise/

**4. Splitwise**  `[verified]`
- Pain point / observation: The human coordination problem is unsolved: payers forget/delay logging, creators become debt collectors ('reminded my roommates three times', '$350 electricity bill took two weeks'), managing who-owes-what 'feels like a part-time job'
- Lesson for Tanda: Tanda's escrow-at-approval removes the trust delay entirely (funder pays once, seats confirm once); also consider per-seat spending pre-authorization so forgotten logs can't create unilateral debt
- Evidence: https://www.reddit.com/r/Renters/comments/1lnsowx/splitwise_is_driving_me_insane_anyone_else/

**5. Splitwise**  `[verified]`
- Pain point / observation: Retention hook: automatic monthly summary email sent to every user on the 1st of the month at noon, plus manual 'Send reminder' per debtor and per-bill advance reminder emails on recurring expenses; activity feed + push notifications for all group changes
- Lesson for Tanda: The calendar-cadence nudge is the single most effective retention mechanic in this category — replicate via World App notifications on a monthly/rent-cycle cadence; Tanda's SETTLEMENT_WINDOW deadline gives a harder, more meaningful nudge than 'you owe money'
- Evidence: https://feedback.splitwise.com/forums/162446-general/suggestions/3976335-monthly-email-reminders

**6. Splitwise**  `[verified]`
- Pain point / observation: Users repeatedly requested a 'forgive debt' button (stray $0.01 balances, gifts, unrecoverable IOUs: 'no way for me to delete the balance or forgive his debt to me'); Splitwise officially declined, workaround is fake cash payment
- Lesson for Tanda: Rounding-dust forgiveness matters psychologically; on-chain splits will produce wei-level dust too — give creator a signed 'forgive/adjust payout' path in the Bill contract so ghosts' cents don't block the final payout
- Evidence: https://feedback.splitwise.com/forums/162446-general/suggestions/17887495-add-an-option-to-forgive-all-or-a-specific-amount

**7. Splitwise**  `[reported]`
- Pain point / observation: Monetization: freemium — ads + expense caps on free tier, Pro at ~$4.99/mo or ~$39.99/yr (receipt OCR, itemization, currency conversion, search, transaction import, ad-free); ~$30.2M raised, revenue unconfirmed (estimates range $6.6M–$25M ARR); growth flywheel is group invites at $0 CAC
- Lesson for Tanda: A decade of freemium produced no sustainable revenue even for the category leader — validates Tanda's zero-protocol-fee stance and suggests distribution inside World App (owned audience) is the real cost advantage to protect
- Evidence: https://yespress.io/splitwise-inc

**8. Splitwise**  `[reported]`
- Pain point / observation: Even the pitch deck's flywheel relies on interpersonal debt as the retention glue: more users → more groups → more invites; users describe the app as 'the agreed memory of a group' — the ledger itself is what keeps friends coming back, not payments
- Lesson for Tanda: Ledger-of-record > payment rail for retention: keep Tanda's Bill history viewable/exportable per group even after settlement so it becomes the trip's 'agreed memory', not a one-shot transaction
- Evidence: https://startupfundraising.com/library/articles/splitwise-pitch-deck-teardown

**9. Settle Up**  `[verified]`
- Pain point / observation: Praised hook: weighted shares (couple=2, singles=1) auto-apply across all expenses, multi-country currency consolidation, and group-level premium that persists because 'groups can be reset after a trip is complete' — pay once, reuse forever
- Lesson for Tanda: Default per-seat weights (e.g., couple seats count double) set at Bill creation is a loved, rarely-perfected feature; Tanda's seat roster maps 1:1 to weights and the per-seat payout schema already supports it
- Evidence: https://apps.apple.com/us/app/settle-up-group-expenses/id737534985?see-all=reviews

**10. Settle Up**  `[verified]`
- Pain point / observation: Complaints: 'way too invasive' ads on free tier, debt-settlement 'algorithm can get weird' requiring friends to be convinced to trust suggested transfers, server/login lockouts after updates, and a customer-service refusal to cancel a paid premium for 30 days; lifetime-premium buyers found features still gated behind subscription ('Abzocke')
- Lesson for Tanda: Minimized-transfer suggestions must be explainable — show the exact per-seat payout vector and why, since black-box optimization erodes consent; and never let paid tiers silently downgrade (upgrade-path contract review lesson)
- Evidence: https://play.google.com/store/apps/details?id=cz.destil.settleup&hl=en_US

**11. Settle Up**  `[verified]`
- Pain point / observation: Monetization menu: $3.99/mo / $19.99/yr individual premium, time-boxed 'Group Premium' passes ($5.99/week → $39.99/yr) and $149.99 lifetime group premium — group-scoped, trip-length pricing tiers
- Lesson for Tanda: Group-scoped, duration-scoped pricing is how this market tolerates money; if Tanda ever monetizes convenience (OCR, exports), price per-Bill not per-user — per-user subs in a 2-person bill double the perceived cost and are actively resented (Splitwise Brazil complaints)
- Evidence: https://apps.apple.com/cr/app/settle-up-group-expenses/id737534985?l=en-GB

**12. Tricount**  `[verified]`
- Pain point / observation: Praise: fully free, no ads, no expense limits, up to 50 people, friends join with NO account — headline positioning 'Free. No ads. No limits.' is aimed directly at Splitwise's paywall; 17M+ users claimed
- Lesson for Tanda: Anti-Splitwise positioning ('no caps, no ads') converts defectors fast — Tanda's zero-fee + World-ID-native angle should explicitly contrast against caps/subs, but note frless accountless join is a friction bar Tanda cannot match (World ID seat = one-time cost of trust)
- Evidence: https://tricount.com/

**13. Tricount**  `[reported]`
- Pain point / observation: bunq's July 2024 full rebuild silently dropped CSV/PDF export, personal mode (see only your share), recurring expenses and the web version; UK App Store written-review average fell to ~3.2/5 post-rebuild; one traveler lost ALL data of an in-progress week-long trip on forced update, with only email support and a trainee handling it for weeks
- Lesson for Tanda: Feature/data regressions burn decade-old goodwill overnight; Tanda V1→V2 (hold anchored on last-confirm) must carry an explicit migration story and never force-app-update mid-bill — a settlement in flight is sacred state
- Evidence: https://www.bananasplitapp.com/blog/tricount-review/

**14. Tricount**  `[verified]`
- Pain point / observation: Limits users hit: only ONE payer per expense (two friends paying with two cards must be entered as two expenses), no recurring bills ('add each bill manually'), 50-participant cap, 'sometimes it doesn't refresh — not everyone knows who owes what', 'friends forget to pay' with no enforcement, and Trustpilot reports of balances that didn't match a spreadsheet check
- Lesson for Tanda: Multiple payers per expense and reconciliation visibility are table stakes Tanda's model already handles (payer = seat, escrow = truth source); the ghost-payer problem Tricount has no answer for is exactly what MAX_HOLD + auto-refund escape solves
- Evidence: https://www.g2.com/products/tricount/reviews

**15. Splid**  `[verified]`
- Pain point / observation: Adopted specifically as Splitwise's paywall refuge ('Moved over from splitwise after they added the daily expense limit'); praised for no-sign-up, fully-offline entry (works where travel has no cell service), 150+ currencies with one settle-up transaction at trip end, and free PDF summary (Excel export is a one-time in-app purchase, no subscription)
- Lesson for Tanda: Offline capture + one-settlement-at-end-of-trip is the travel-group ideal; Tanda's sendTransaction flow assumes connectivity per step — queue expense logs locally and batch to chain, or paymasters/World App sessions will fail on exactly the trips users buy the app for
- Evidence: https://apps.apple.com/nz/app/splid-split-group-bills/id991473495?see-all=reviews

**16. Splid**  `[verified]`
- Pain point / observation: Smaller but telling complaints: settle-up figures off by 'a few dollars' due to multi-currency rounding, can't edit time-of-entry so backdated expenses sort wrong, users 'can only have debts with 1 person/group at a time' (they'd use it more otherwise), one user hit an unexplained expense ceiling mid-trip 1.5 years ago, and ad hatred persists even in travel apps
- Lesson for Tanda: Cross-currency rounding must be pinned at escrow time (USDC-denominated payouts with fixed FX at conversion, show both amounts); and single-context limits cut usage — support concurrent Bills per user from day one
- Evidence: https://apps.apple.com/gb/app/splid-split-group-bills/id991473495?see-all=reviews&platform=undefined

**17. Venmo Groups**  `[verified]`
- Pain point / observation: Group-expense math is an un-auditable black box: ~$800 owed to a creator blocked because a member who joined→left→rejoined via his partner's account 'owes' him per the engine; no visibility into how costs divide among payers; support admitted Venmo 'cannot view who made these edits or updates' — CFPB and BBB complaints filed after 3 weeks unresolved
- Lesson for Tanda: On-chain edit history + per-seat ledger makes Venmo's opacity unsolvable-problem trivially solvable for Tanda; member-identity churn (leave/rejoin/guest accounts) is precisely the ghost-seat attack that World ID nullifier binding is designed to prevent — showcase an 'why you owe this' drill-down per seat
- Evidence: https://www.reddit.com/r/venmo/comments/1wiziej/venmo_group_expense_feature_is_hell_woat_customer/

**18. Venmo Groups**  `[verified]`
- Pain point / observation: Retention-by-hostage mechanics: you cannot leave or hide a group until fully settled up, removal of members only when 'all paid up', ownership transfer required to exit as manager, deletion only for the last member — users report the netting ('someone who owes me money covers my share instead') makes household bills impossible to track
- Lesson for Tanda: Locking membership behind debt reads as punishment; Tanda's MAX_HOLD 72h refund escape is the humane opposite — copy the exit-rigor (seat roster is contractual) but beat the exit-experience (ghosts can't trap the group's funds)
- Evidence: https://help.venmo.com/cs/articles/venmo-and-imessage-vhel212

**19. Venmo**  `[verified]`
- Pain point / observation: Monetization: P2P sends via balance/bank are $0; revenue comes from 1.75% instant-transfer fee ($0.25 min/$25 max), 3% credit-card send fee, and merchant processing; Groups itself is free — the float and transfer fees are the business; Venmo also shipped receipt-scanning bill-split by item
- Lesson for Tanda: Incumbents monetize money MOVEMENT speed/float, never the split itself; Tanda (gasless via paymaster, USDC native) has no float to harvest — confirms the brief's 'zero protocol fee' is competitive-parity, and any future revenue must come outside the settlement path
- Evidence: https://venmo.com/legal/fees

**20. Venmo Groups**  `[verified]`
- Pain point / observation: Reliability wall: Android Groups tab crashes on 'Add Expenses' with zero support channels ('no support available'), pushing users to reconstruct the trip in a web calculator and email the spreadsheet; iOS members unaffected
- Lesson for Tanda: MiniKit's cross-platform parity (iOS/Android inside World App) is a risk surface — an expense-entry crash with no support path converts a whole friend group against the app at once; instrument seat-logging and test both OSes before launch review
- Evidence: https://www.reddit.com/r/venmo/comments/1xgykfa/groups_not_letting_me_add_expenses/

**21. Google Pay**  `[verified]`
- Pain point / observation: Distribution play, not feature play: bill-split embedded directly in group chats (India, Singapore, US 2025) — split from past transactions, per-person paid/unpaid tracking, one-tap settle from the chat message; structural limitation: only the bill creator can receive money (single-payer design, same flaw as Tricount)
- Lesson for Tanda: Chat-embedded splitting is where the market is heading — Google/PayPal bundle it free with payments, so standalone ledger apps are being commoditized; Tanda's chat deep-links + in-conversation Bill creation is the right wedge, and per-seat escrow payouts beat Google's creator-only receive constraint
- Evidence: https://support.google.com/pay/india/answer/11420982?hl=EN

**22. Kittysplit**  `[verified]`
- Pain point / observation: Anti-subscription monetization praised by users: basic event free forever (unlimited expenses, no sign-up, join via web link on any device 'maybe even your fridge'), Super Kitty = one-time ~€3/$2.99 per group for 100-person cap, multi-currency, receipts, default shares, read-only links — 'Monetisation is really fair and not predatory... one time payment of a few bucks for the entire group'
- Lesson for Tanda: Per-group one-time pricing for optional convenience features is the model this market actually rewards; also note their most-requested missing feature is recurring payments — the household/roommate cohort is underserved even by the darling app
- Evidence: https://play.google.com/store/apps/details?id=com.kittysplit&hl=en

**23. Kittysplit**  `[reported]`
- Pain point / observation: Growth mechanics from the builders: zero-friction entry ('start splitting within seconds'), account optional, friends need no app; roadmap explicitly adds push notifications, receipts and RevenueCat-based monetization after 6 free years; free tier capped at 9 people
- Lesson for Tanda: Every incumbent that wins invites flows on 'recipient needs no app' — Tanda's opposite bet (each seat MUST hold World ID) needs a first-run path where verification happens once, during a natural invite via World App chat, not as a wall at expense-entry time
- Evidence: https://www.itechguides.com/best/personal-finance-software/kittysplit/

**24. PayPal (Venmo) ecosystem**  `[UNVERIFIED]`
- Pain point / observation: PayPal's dedicated group-fund product (PayPal Together) is gone from its newsroom record while Venmo Groups shipped group expenses, receipt scanning and social-split messaging ('splitting the bill holds friend groups together'); the majors fold splitting into their payment super-apps rather than maintaining a standalone splitter
- Lesson for Tanda: Confirms the mini-app thesis: standalone splitters get crushed by payment-native bundling — Tanda living INSIDE World App with USDC rails is structurally on the winning side of this consolidation; UNVERIFIED: no primary PayPal source dated for the Together shutdown (noted from absence in PayPal newsroom listings)
- Evidence: https://newsroom.paypal-corp.com/

### Lane top insights
1. Paywalling the core loop is the category's one proven self-inflicted wound: Splitwise's 3-4 expenses/day cap + forced ads created a documented refugee stream (posts literally 'Moved over from splitwise after they added the daily expense limit') to Splid/Tricount/Kittysplit/Chipp — Tanda's permanently-free, zero-fee seat logging and settlement is not a nicety, it is the acquisition weapon, and per-GROUP one-time pricing (Kittysplit €3, Settle Up group passes) is the only monetization users in this market praise rather than punish.
2. The #1 unsolved pain is human, not math: forgetful payers, silent ghosting, creator-becomes-collector ('reminded my roommates three times... two weeks to receive $350'), and awkward-reminder mechanics (Splitwise's monthly-1st summary email is its stickiest retention hook). No incumbent can enforce anything — they can only nudge. Tanda's escrow + all-seats-confirm + settlement-window + 72h auto-refund is the first STRUCTURAL answer: sell it as 'the money is already there, nobody has to chase anybody', and replicate their cadence-nudges via World App notifications.
3. Opaque settlement math destroys ledger trust: Venmo Groups' netting is un-auditable (support admits it can't even see who edited an expense) and a join/leave/rejoin ghost blocked an $800 payout; Settle Up's suggested transfers 'get weird'; Tricount users cross-checked balances against spreadsheets and found errors; Splid multi-currency rounding drifts by dollars. Tanda's public per-seat payout vector + World-ID-bound roster + on-chain edit history directly beats all of these — but only if the UI ships a plain-English 'why you owe/paid what' drill-down, and USDC-pinned conversion to kill FX rounding drift.

---

## Lane 2: Crypto-native bill-split / payment-request / group-settlement projects (requests.cash & Request Network, Spliit, Beervote, Tally/Collctiv, SplitSats/Sattle/Bolt.fun/Zebedee Lightning group settles, SplitRent/SplitMyRent-style dapps, escrow+dispute patterns: Kleros Escrow, Argus)

### Findings

**1. Request Network (requests.cash is its consumer request app)**  `[verified]`
- Mechanism: Payment-request protocol: a request is a stored record (IPFS + indexed smart objects) that the payer settles by executing their own on-chain transaction linked via payment reference; states Created/Accepted/Cancelled; partially_paid tracking with overpayment capping; optional fees routed atomically via ERC20FeeProxy (fee set by integrator, protocol itself is open-source contracts on 15+ chains incl. Base/Optimism/Polygon).
- Deadbeat handling: None at protocol level — pure pull-based request. If the payer never pays, nothing happens; accept/reject is bookkeeping, not enforcement. Requester bears 100% of counterparty risk; the protocol only guarantees reconciliation, not settlement.
- Adoption evidence: Most-infrastructure of the lane: contract addresses published for Ethereum, Polygon, Base, Optimism, Arbitrum, zkSync, Gnosis, BNB, Avalanche, Celo, Fuse, Moonbeam, Sonic, Boba, NEAR, TRON (disclaimer page); API + MCP integration for AI agents; no public user/TVL numbers found. UNVERIFIED: any usage metric.
- Lesson for Tanda: The request/confirm/reconcile state machine (payment reference → webhook → partially_paid capping) is worth mirroring for the seat-confirm leg, but Tanda's escrow-first design is exactly the guarantee Request Network lacks — don't let the settlement UX degrade into 'send a request and hope'.
- Evidence: https://docs.request.network/api-features/create-requests ; https://request.network/disclaimer/ ; https://github.com/RequestNetwork/documentation

**2. Spliit (spliit.app)**  `[verified]`
- Mechanism: Open-source (MIT) Splitwise alternative: link-shared groups, expense ledger with uneven/percentage/share splits, balances view, reimbursements + 'suggested settlements' (fewest-transfer optimization), receipt AI scan. No money movement at all — settlement happens off-app, IOU-style.
- Deadbeat handling: Pure social ledger: no escrow, no payment rails, no enforcement; 'who owes what' is authoritative, paying it is honor-system. Debt-graph simplification minimizes the number of IOUs that must be chased.
- Adoption evidence: 3,061 GitHub stars / 538 forks (repo page, Nov 2026 crawl); hosted instance at spliit.app; funded via Open Collective with public ledger; community fork (spliit-cloud) exists — evidence of distribution demand.
- Lesson for Tanda: This is the UX bar, not a payment competitor: users expect link-share groups, uneven splits, and an optimized settlement graph. Tanda's per-seat net-share math should present a minimal-transfer plan the way Spliit's 'suggested settlements' do — and its donation/Open Collective funding model is the honest template for sustaining a zero-fee claim.
- Evidence: https://github.com/spliit-app/spliit ; https://opencollective.com/spliit ; https://spliit.app/

**3. Beervote**  `[UNVERIFIED]`
- Mechanism: Not found. Multiple targeted searches (project name + ETHBerlin/devpost/GitHub/ethereum/bill-split terms, Nov 2026) surfaced no public repo, devpost, dapp, or article for a crypto bill-split project named Beervote; results were all unrelated (Minnesota beer takeout legislation, restaurant listings).
- Deadbeat handling: Unknown — no source exists to characterize it.
- Adoption evidence: None found. UNVERIFIED: the project's existence as described in the brief.
- Lesson for Tanda: Treat the brief's Beervote mention as unconfirmed. Its absence across hackathon archives is itself a datapoint: crypto bill-split projects born at hackathons overwhelmingly die without a distribution channel — the survivors (Request Network, Kleros, Bolt.fun) attached to rails or infra, not to the splitter itself.
- Evidence: https://projects.ethberlin.org/submissions/ (searched, no Beervote entry surfaced)

**4. Tally (split-bill receipt app) and Collctiv (collctiv.com)**  `[verified]`
- Mechanism: Neither is on-chain despite the brief's framing ('Tally/collct-type on-chain efforts' — no crypto-native project of these names found). Collctiv (UK fintech): organizer creates a collection pot, sends payment links/QR; payers pay upfront by card/Apple/Google Pay; only the collector needs an account. Tally (iOS, Lei lab): scan receipt → per-person share card carrying your own bank's receive-QR (DuitNow/PayPay); 'money never touches the app'; paid status is tapped by the payer.
- Deadbeat handling: Collctiv: collect-before-spend — the organizer never fronts money, a non-payer simply has no seat in the pot (closest web2 analogue to Tanda's escrow-before-settlement). Tally: honor-system confirmation ('they tap paid shows up on your screen') with zero verification.
- Adoption evidence: Collctiv: FCA-regulated processors (Nuvei, PayPoint, Persona ID checks), launched ~2020 per Reddit launch thread; no user/TPV numbers public. Tally: App Store listing only. UNVERIFIED: both volumes.
- Lesson for Tanda: Collctiv's positioning line — 'collect money upfront so you don't pay out for people and cross your fingers' — is precisely Tanda's funder-escrow pitch and proves demand for collect-first over settle-later. Fee model to copy for zero-fee optics: pots free to create, with a voluntary opt-in (Collctiv's 2% at withdrawal). Tally shows the opposite failure mode: unconfirmable 'paid' taps — Tanda's on-chain seat confirmation is the hard-evidence differentiator.
- Evidence: https://www.collctiv.com/ ; https://apps.apple.com/us/app/tally-split-bill-from-receipt/id6829149573 ; https://www.reddit.com/r/SideProject/comments/erf66d/any_thoughts_or_comments_about_this_group_payment/

**5. SplitMate (hackathon dApp)**  `[verified]`
- Mechanism: EVM escrow splitter (Sepolia testnet, Web3.js): creator defines bill + participants via createBill; each participant's exact share is paid into the contract (payShare); when fully funded, one atomic transaction pays the merchant and clears all debts simultaneously; planned NFT receipts as proof-of-payment reputation records.
- Deadbeat handling: All-or-nothing funding: no settlement occurs until every share is escrowed — a deadbeat freezes the whole bill rather than hurting the merchant. Their own noted design bug was the who-fronts-the-money question, solved by forcing the creator to pay their share at creation.
- Adoption evidence: Hackathon prototype on testnet only; no users, no mainnet deployment. Team-documented challenge (creator-share forcing) is the only engineering signal.
- Lesson for Tanda: The pure pre-escrow model deadlocks on one non-payer — that is Tanda's key advantage: funder escrows up front so settlement never waits on stragglers, with the 72h refund escape as the deadlock-breaker. SplitMate's creator-forcing fix foreshadows the real UX question Tanda must answer: does the funder's advance become a claim against late seats, and is it enforceable in-contract?
- Evidence: https://devpost.com/software/splitmate-x309oe

**6. SplitRent / Rent-Payment-Splitter (Stellar Soroban — SplitMyRent-style dapp)**  `[verified]`
- Mechanism: Multi-participant rent escrow: create escrow (participants, amounts, deadline) → all deposit proportional shares → contract auto-splits and landlord calls release; if deadline passes under-funded, per-participant refund path; built-in arbitration hooks; 28 passing contract tests; deployed on Stellar testnet with published contract address.
- Deadbeat handling: Time-boxed funding deadline + automatic refund (pull-based, callable by each participant) + dispute/arbitration mechanism; deadbeat means partial refund flow, not frozen funds — the structurally closest known pattern to Tanda's settlement window + 72h escape.
- Adoption evidence: Testnet-only student/side project (live demo on splitrent.vercel.app with test XLM); no production users.
- Lesson for Tanda: The escrow lifecycle every group-settlement contract converges on — create → fund → release-or-timeout-refund — validates Tanda's window/escape design; copy its two details: individual pull-refunds (any participant can exit after deadline without funder cooperation) and deadline-anchored state transitions, both of which remove the funder as a liveness dependency.
- Evidence: https://github.com/x0lg0n/Rent-Payment-Splitter

**7. Kleros Escrow V2 (Arbitrum)**  `[verified]`
- Mechanism: Production two-party smart-contract escrow (ETH + ERC20 incl. USDC/USDT, Arbitrum One mainnet; EscrowUniversal.sol) with decentralized court arbitration: buyer partial releases, seller partial refunds, alternating settlement proposals (prevents rush-to-arbitration), automatic execution after deadline, appealable juror rulings with evidence submission, governance-set per-token amount caps.
- Deadbeat handling: Collateralized dispute path: stalled/unfair settlement escalates to Kleros Court where randomized jurors rule on a finalized dispute policy stored on IPFS; silence-at-deadline auto-releases (optimistic finality).
- Adoption evidence: V2 'in production' per official docs with published mainnet contract addresses; Kleros court handles real disputes historically — no escrow-specific volume published. UNVERIFIED: escrow TVL/case counts.
- Lesson for Tanda: This is the strongest precedent for Tanda's settlement-window hold: optimistic finality with auto-execution-on-timeout plus an appeal path only when someone objects. If seats can ever dispute a logged expense (wrong share, phantom expense), the borrowable stack is evidence → juror ruling → appeal, and the risk-capping idea (governance-set per-token caps on escrow size) maps to a per-bill USDC cap.
- Evidence: https://kleros.mintlify.app/developers/products/escrow/overview

**8. Argus (identity check requested by brief)**  `[reported]`
- Mechanism: The brief's note ('dispute-resolution protocol on Arbitrum') matches no project I could find. Two real Arguses: (a) academic Argus (Microsoft/CMU, arXiv 2107.06049) — anti-piracy bounty system on Ethereum where accused licensees get a bounded appeal window and auto-guilty on timeout, with O(1) on-chain appeals; (b) Argus oracle (Circle Alliance, on Arc/Arbitrum/Base) — three agents stake real USDC on security verdicts; dissenters pay winners; on-chain ELO makes reputation into slashable collateral.
- Deadbeat handling: (a) time-boxed appeal-or-lose; (b) skin-in-the-game consensus: every challenge costs a bond, wrong answers pay the correct ones.
- Adoption evidence: (b) claims 363+ users, 1,727 scans, $0.01/scan fee, Circle Alliance directory listing (self-reported repo numbers). (a) is a research prototype. Neither is used for group bill settlement.
- Lesson for Tanda: If Tanda ever lets a seat contest settlement within the window, the Argus-oracle idea is directly transferable: require a small USDC bond to challenge, slash frivolous challengers to the settlement, so one bad actor cannot stall the window — plus the academic Argus pattern of auto-confirm-on-silence, which is exactly what a settlement-window hold should do.
- Evidence: https://arxiv.org/html/2107.06049v1 ; https://github.com/Gideon145/argus ; https://partners.circle.com/partner/argus

**9. Bolt.fun (Lightning group tips)**  `[reported]`
- Mechanism: Lightning-based social tipping: sender pre-funds tips/tip-cards (bulk funding, expiry dates, personalized messages); receivers claim via web app (phone or email auth, or anonymized LNURL-withdraw); platform tracks Seen/Claimed/Withdrawn/Refunded states; unclaimed tips auto-return to sender at expiry. Group use = event/community distribution (hackathons, hubs), not bill math.
- Deadbeat handling: Structurally immune: funds are escrowed/owned before the recipient acts, so no IOUs exist; the failure mode becomes non-claim, which the time-boxed auto-refund handles — a consumer-proven mirror of Tanda's 72h refund escape.
- Adoption evidence: Active platform (GitHub peakshift/bolt.fun, stories on bolt.fun, Legends of Lightning tournaments it runs); no user/volume numbers published. UNVERIFIED: any adoption metric.
- Lesson for Tanda: Bolt.fun's explicit state machine (funded → claimed → withdrawn → refunded-on-expiry) with per-state UI is the clearest public UX precedent for Tanda's seat-confirm + refund-escape leg; label the 72h window with the same visible countdown/reclaim affordance.
- Evidence: https://bolt.fun/story/bitcoin-tip-cards-by-lightsats--561/ ; https://github.com/peakshift/bolt.fun

**10. SplitSats (Nostr + Lightning group bill splitter)**  `[verified]`
- Mechanism: Chat-first bill splitting: groups built from Nostr follows (contacts), expenses itemized (incl. receipt scan) and published as end-to-end-encrypted Nostr events readable only by group members; no server; settlement via Lightning zaps through NWC (Nostr Wallet Connect) directly from the user's wallet.
- Deadbeat handling: None enforced — an encrypted IOU ledger; settlement is instant when people choose to zap, but a non-payer just sits in the ledger. Serverless/relays mean no operator can pressure anyone.
- Adoption evidence: Proof of concept; won the P2P award at BOLT.fun Legends of Lightning vol. 2 and got a nobsbitcoin special-mention writeup — community recognition, not users. No TVL/DAU published.
- Lesson for Tanda: SplitSats proves the social-graph-first framing ('financial coordination between friends' is how the team pitched it on the award stream) — same wedge Tanda bets on — but its anonymous relay identities are exactly the Sybil weakness World ID nullifier seats eliminate. The transferable piece: E2E-encrypt the expense log while keeping settlement on-chain-verifiable.
- Evidence: https://github.com/SplitSats/SplitSats ; https://www.nobsbitcoin.com/legends-of-lightning-vol-2-winners/ ; http://www.youtube.com/watch?v=w-xQCKiOZAs

**11. Sattle (sattle.tech, Lightning/UPI)**  `[verified]`
- Mechanism: 'Split expenses and settle up over Bitcoin Lightning — only one person needs the app': organizer tracks the group; payers settle from a plain browser via Lightning invoices/Lightning Address (or UPI in India); optional debt simplification (fewest-transfers graph toggle); every expense/edition/confirmed settlement also published as Nostr events so the ledger survives server disappearance.
- Deadbeat handling: Pull-based settlement at settle-time only (invoices the debtor must pay) + reminders; no escrow. Architectural answer to the operator-trust problem: Nostr-backed ledger so a dead backend can't erase history.
- Adoption evidence: Public repo + Android releases + 1:43 demo video; no usage numbers. UNVERIFIED: traction.
- Lesson for Tanda: 'One installs, everyone else just pays a link' is the friction benchmark for group payments — Tanda's in-answer is stronger (every seat is already inside World App) and should market that asymmetry. Its Nostr ledger backup shows the non-custodial-data instinct that Tanda gets for free from chain; use that in the trust story.
- Evidence: https://github.com/gandhiyaash/sattle

**12. Zebedee / ZBD (Lightning infra + consumer app; Status 'Satoshi' app pay flows)**  `[reported]`
- Mechanism: Zebedee: custodial Lightning API — charges (single-use fixed-amount payment requests), keysend, gamertag identity (Lightning Address abstraction), Discord/Telegram bots for group tips and 'rain' to any Lightning Address; consumer ZBD app sends/receives sats, cash-out to Cash App; ZBD terms: $0 sending/receiving between ZBD users. Status satoshi-app (satoshi.app): one-tap send/request between friends on Lightning (App Store); group escrow not found; their status-im/satoshi-app GitHub repo now 404s.
- Deadbeat handling: Nonexistent by design — both are person-to-person push/pull payment rails; a request that isn't answered just stays unanswered. Group features (rain/bots) pre-send money, sidestepping debt entirely.
- Adoption evidence: Zebedee is a funded API company powering game rewards (gamertag economy, ZBD Social); specific volumes unpublished. UNVERIFIED: the brief's 'Zebedee groups' bill-split feature — no such group-settlement feature found in docs, SDKs, or site.
- Lesson for Tanda: Two rails lessons: (1) invoice/charge UX ('payer opens link, pays fixed amount, webhook fires') is the settled mental model for seat-payment legs — Tanda's escrow deposit should look exactly like this inside World App; (2) the fee-schedule framing in ZBD's terms ('$0 between users; fees only at conversion/cash-out') is how a zero-fee product credibly documents where money actually is — Tanda should publish an equivalent fee truth-table, naming sponsored gas as its subsidy.
- Evidence: https://cdn.zebedee.io/legal-docs/terms-of-service/v1.1.0.pdf ; https://github.com/zebedeeio/nodejs-sdk ; https://stacker.news/items/63017 ; https://apps.apple.com/hu/app/satoshi-the-bitcoin-app/id6463799763

**13. peanutsplit (Peanut / Squirrel Labs) + OpenZeppelin PaymentSplitter pattern**  `[verified]`
- Mechanism: peanutsplit: accountless expense rooms — 'the room is a link', pick a name, add what you paid, get a payment plan; any currency, uneven splits, offline PWA, AGPL, one of its settlement options is 'Settle with Peanut' crypto payment links, never preselected. The underlying pattern for crypto payout legs is the classic (now-removed-from-OZ-v5) PaymentSplitter: pull-based claims against immutable shares, anyone may trigger release but funds only ever go to the payee, floors-only dust, no owner/pause/clawback.
- Deadbeat handling: peanutsplit: none (ledger + optional links). PaymentSplitter: converts deadbeat risk into accounting — owed = received × share − released, self-healing so partial funding just leaves an underpaid state, never a stuck batch.
- Adoption evidence: peanutsplit live at peanutsplit.com, 40★ (repo topic listing), company-funded (Squirrel Labs pays infra). PaymentSplitter pattern: inherited from OpenZeppelin's widely-used finance module.
- Lesson for Tanda: For the execute leg, implement per-seat pull-claims keyed to nullifier-hash (never a push loop at settlement): it's cheaper on gas, survives one seat's bad receivable, and mirrors the battle-tested release() accounting including floor-dust handling (define who sweeps rounding dust before launch — in a zero-fee product, dust left stranded is a visible trust bug).
- Evidence: https://github.com/peanutprotocol/peanutsplit ; https://github.com/dngr2/payment-splitter/blob/main/README.md

**14. CryptoSplitter / WeSplit (long-tail on-chain splitters)**  `[reported]`
- Mechanism: CryptoSplitter (cryptosplitter.app, LinkedIn corporate page): shared expenses invited and settled on-chain across EVM networks. WeSplit (Google Play): 'share expenses to split bills and pay via crypto.' Both are thin wrappers: expense ledger + wallet payments, no escrow contract depth, no dispute window.
- Deadbeat handling: Effectively none found on public pages; settlement is per-payment push, so a seat that won't send simply remains owed.
- Adoption evidence: Corporate LinkedIn page and a Play Store listing; no GitHub, no TVL, no users disclosed — presence is marketing-grade only. UNVERIFIED: any real usage.
- Lesson for Tanda: The graveyard of 'split bills in crypto' store listings shows the lane punishes wallets-with-ledgers that don't change settlement guarantees; Tanda's differentiator must always be told as escrow-window-refund mechanics (a settlement guarantee), not as 'crypto bill splitting' (which already exists and flopped).
- Evidence: https://www.linkedin.com/company/cryptosplitter ; https://play.google.com/store/apps/details?id=com.wesplit.app&hl=en

### Lane top insights
1. Deadbeat handling in this lane falls into two failing poles — pull-based IOUs/social ledgers (Request Network, Spliit, SplitSats, Sattle, peanutsplit: zero enforcement, non-payment costs the victim) and all-or-nothing pre-escrow (SplitMate: a single straggler freezes the bill). Nobody found combines collect-first certainty with deadlock-breaking except Tanda's design (funder escrows now, per-seat confirm, 72h auto-refund escape); Collctiv's web2 pots independently validate the 'collect upfront so nobody fingers-crosses-fronts-the-bill' positioning, and SplitRent/Stellar shows the correct mechanics: deadline-anchored, per-participant pull-refunds so even the funder isn't a liveness dependency.
2. Optimistic finality is the mature crypto precedent for Tanda's settlement window: Kleros Escrow V2 (production, Arbitrum) does auto-execute-at-deadline + alternating proposals + court-appealed disputes with governance-set per-token escrow caps; academic Argus does bounded-appeal-else-auto-confirm; oracle-Argus does bond-slashed dissent. Tanda's seat-confirm window is architecturally sound — the upgrades worth borrowing are a challenge bond (slash frivolous disputes so one bad seat can't stall), and a per-bill size cap for risk containment.
3. Adoption reality check: outside infrastructure players (Request Network's 15+ chain deployment, ZBD's funded API), every purpose-built crypto bill splitter is a hackathon PoC, testnet demo, or store listing with no published TVL/users — while the dominant UX mindshare is held by non-crypto open source (Spliit, 3k+ stars) and web2 collect-first pots (Collctiv). Zero-fee claims are funded by donations (Spliit), a parent company (peanutsplit/Squirrel Labs), or voluntary opt-in tips (Collctiv's 2%). Tanda's moat is distribution, not mechanism: World App-native seats, sponsored gas and World ID nullifiers solve the exact two failure causes — install friction (Sattle's 'only one needs the app' workaround) and Sybil identities (SplitSats' anonymous relays) — that killed the independent splitters; and the execute leg should use pull-claim payouts keyed to nullifier-hash (OZ PaymentSplitter accounting), never push loops.

---

## Lane 3: World App mini-app ecosystem scan (Tanda competitive study, lane 3): payments/group apps in the World ecosystem, success drivers of winning mini apps, and World-ID-native mechanics apps actually monetize

**Direct competitor scan:** No third-party Splitwise-style mini app found inside World App (UNVERIFIED absence — store not crawlable). The closest direct competitor is FIRST-PARTY: World Chat's native 'Split with friends' (group-chat bill split, tap-to-pay requests, paid-tracking, zero fees) launched Dec 11 2025 and live in 100+ countries, plus native fee-free P2P send/request by username in the World Money wallet. Adjacent finance mini apps (Credit microloans 70k users; Morpho lending; Kalshi/Polymarket prediction markets; Earn USDC yield; Holdstation; Top Ups/eSIM hundreds of thousands each) prove money-app demand but none do group expense escrow — a niche where only the platform itself currently competes.

### Findings

**1. World Chat native 'Split with friends' (first-party bill splitting)**  `[verified]`
- Pain point / observation: World App's World Chat (launched globally Dec 11-12, 2025, XMTP-secured E2E encryption) ships native group bill-splitting: 'Dinner, rent, a road trip. Split any amount across a group chat and everyone gets a tap-to-pay request', plus send/request money and gift animations in chat, all fee-free and borderless. This is a Tools for Humanity first-party feature, not a mini app.
- Lesson for Tanda: This is the closest thing to a Splitwise-in-World-App and it is owned by the platform itself. Tanda cannot compete on 'split a bill in a chat' alone; it must differentiate on what native split lacks — escrowed settlement, USDC-hold guarantees, receipts/history, defaulter accountability, cross-group ledgers — or integrate as a Mini App riding chat rails rather than fighting them.
- Evidence: https://world.org/worldchat

**2. World Chat launch mechanics (verified-human bubbles + mini apps inside threads)**  `[verified]`
- Pain point / observation: The Dec 2025 'new World App' positions chat bubbles blue/gray by World ID verification status, and third-party mini apps (Kalshi, Polymarket, games, savings tools) now run inside message threads. Payments in chat settle to wallet addresses resolvable to usernames; transaction data lands on a public ledger (World Chain).
- Lesson for Tanda: Tanda's distribution surface is literally group chats where every participant's human-status is already visible — 'no bots in your split' is one tap away from being a checked fact. Mini-in-chat support means a Tanda escrow flow can live inside the same thread where the dinner was booked.
- Evidence: https://world.org/blog/announcements/introducing-world-chat-connect-send-money-real-humans-world-network

**3. First-party wallet already does zero-fee USDC P2P by username**  `[verified]`
- Pain point / observation: World Money/World App sends stablecoins globally free ('send money to people around the world using only their World username'), holds USDC/EURC/wARS/wMXN etc., with Stripe/Bridge virtual accounts for USD payroll in 18 countries and no in-app conversion fees.
- Lesson for Tanda: Settlement rails are a solved first-party commodity — Tanda's value must sit above the rails (escrow logic, split state, reminders, accountability), not in moving USDC, and can market 'zero fees' as platform-consistent rather than novel.
- Evidence: https://world.org/blog/announcements/world-money

**4. Credit Mini App — proof-of-human as lending collateral**  `[verified]`
- Pain point / observation: Credit offers up to $1,000 unsecured microloans; its creator states: 'World's proof-of-human system gave us the confidence to offer microloans without requiring collateral... if someone fails to pay their loan, we can remove them—and they can't just come back with a new account' — cited as the reason Credit reached 70,000+ users.
- Lesson for Tanda: The single most transferable case study for Tanda: sybil-exclusion (one human = one identity, unbannable-rejoin) is a *payment-accountability primitive*. Tanda's 'verified defaulter can't ghost a split and reopen under a new wallet' claim is the same mechanic, applied to group settlement.
- Evidence: https://world.org/blog/announcements/world-launches-mini-apps-300k-dev-rewards-pilot-inspire-human-first-apps

**5. Earn — yield explicitly gated per verified human**  `[verified]`
- Pain point / observation: World's Earn product pays >15% APY on first $1,000 USDC and 18% on first 1,000 WLD, and the official blog states it 'uses proof of human to help limit multiple-account abuse, so each verified human can access the same reward opportunities.'
- Lesson for Tanda: Shows World itself monetizing one-human-one-share economics on USDC balances — the exact mental model Tanda needs for equal-share escrow pots ('one verified human per seat in the split').
- Evidence: https://world.org/blog/announcements/introducing-world-chat-connect-send-money-real-humans-world-network

**6. Morpho Mini App — extra rewards for verified humans on a USDC product**  `[verified]`
- Pain point / observation: Morpho (Apr 2025) brought DeFi lending/borrowing to 25M World App users with 'extra rewards for verified humans' (via Merkl), accessible to US individuals too.
- Lesson for Tanda: Precedent that US-facing World finance apps can be listed and rewarded, and that 'verified-human boost' is the accepted monetization layer on USDC flows — Tanda can mirror it (e.g., faster-settlement or fee-pool perks for Orb-verified members).
- Evidence: https://world.org/blog/announcements/morpho-mini-app-for-world-app

**7. Financial mini apps at scale: Kalshi, Polymarket, UNO Swap, zerohash funding rails**  `[reported]`
- Pain point / observation: zerohash's July 2025 PR names 'Kalshi, UNO Swap, and World Chat' as notable mini apps across 1M+ unique users and launched an Account Funding SDK so mini apps can take compliant USDC/WLD top-ups in-platform; official blog adds Top Ups and eSIM (Boxo) each serving 'hundreds of thousands' of users.
- Lesson for Tanda: Confirms there is a live money-movement mini-app lane with regulated funding rails available — Tanda does not need to solve deposits/off-ramps to operate, and its category (P2P group payments) is validated as usable in-app.
- Evidence: https://zerohash.com/press/zerohash-funding-infrastructure-helps-power-world-app-mini-app-ecosystem-launches-account-funding-sdk-for-mini-apps-in-world-app

**8. ORO (PartyDAO) — verified humanity as the consumable**  `[verified]`
- Pain point / observation: Official World blog: ORO, 'a daily token for unique humans,' averaged 1.4M World ID verifications weekly — one of the two most successful mini apps; PartyDAO's John Palmer: 'Distribution in crypto [is] kinda broken... with Mini Apps you can get a lot of distribution in a way that you probably haven't been able to before.'
- Lesson for Tanda: Winners build products whose core action IS a World ID verification. Tanda's equivalent reflex loop: every settle/confirm tap can double as a proof-of-human consumption — engagement and trust-building in one action.
- Evidence: https://world.org/blog/announcements/world-network-growth-helps-mini-apps-developers-reach-millions-daily

**9. Breakout non-finance growth stories: Meritt, Cudis, Holdstation, Argiefy**  `[verified]`
- Pain point / observation: Same official blog: Meritt (human-only social network) passed 30,000 World ID-verified users within weeks of launching; Cudis sold tens of thousands of dollars of smart rings through its mini app; Holdstation's Eggs Vault crossed 8.2M impressions in days; Argiefy credits World for easy human-validated onboarding in LATAM.
- Lesson for Tanda: 'Human-only' is itself a marketing wedge that drove real traction without paid distribution; Tanda's group economy should lean on human-only-room positioning (no bot ringers, no burner wallets) exactly as Meritt did.
- Evidence: https://world.org/blog/announcements/world-network-growth-helps-mini-apps-developers-reach-millions-daily

**10. Dev Rewards economics (Tanda's revenue floor)**  `[verified]`
- Pain point / observation: Developer Rewards paid in WLD on verified-human usage: $300K/3-month pilot from Apr 2025, raised to $100K/WEEK Sep 29–Dec 31 2025 as the ecosystem crossed 500 mini apps with 2M+ daily opens and 100M+ WLD transacted in mini apps; separate $1M retroactive WLD grant for pre-May-16 apps with 10,000+ verified users; World notes some mini-app devs raised capital off traction.
- Lesson for Tanda: Usage-tied WLD grants are a cold-start revenue stream independent of Tanda's zero-fee model — and the 10,000-verified-human threshold is a concrete, precedent-backed product target.
- Evidence: https://world.org/blog/announcements/dev-rewards-pilot-increases-to-100k-per-week-as-the-world-ecosystem-surpasses-500-mini-apps

**11. Official growth playbook: viral loops, gamification, notifications**  `[verified]`
- Pain point / observation: docs.world.org/mini-apps/growth prescribes four levers for mini apps — invites & viral loops, gamification (streaks), opt-in push notifications for retention, and analytics — citing PayPal referral (7-10% daily growth), Dropbox two-sided rewards, Duolingo streaks; MiniKit exposes Share, Contacts, Notifications and Quick-Action deep links to implement all four.
- Lesson for Tanda: Split-bill apps are inherently multi-player invite machines (every split enrolls 3-8 new users); the platform literally ships the referral primitives (share command, contacts command) and rewards exactly this loop.
- Evidence: https://docs.world.org/mini-apps/growth

**12. World Build incubator pipeline includes payments teams**  `[verified]`
- Pain point / observation: World+FWB incubator (with Alchemy, Bain Capital Crypto, Blockchain Capital, Variant): Feb-May 2025 cohort sent 12 hackathon teams to a Buenos Aires build retreat 'from payments and ticketing to wellness and AI'; World Build 2 (Sept 2025, 200+ applications) winners were Fram3s, Valor (hyperlocal data marketplace) and Whole World Catalog, with $15K hackathon pool, up to $200K grants, and a VC demo day finale.
- Lesson for Tanda: The fastest, evidenced route to breakout-mini-app status is the incubator/hackathon funnel — and payments is an explicitly recruited category; Tanda could enter World Build 3 or pitch the cohort for capital plus platform co-marketing.
- Evidence: https://world.org/blog/announcements/dev-rewards-pilot-increases-to-100k-per-week-as-the-world-ecosystem-surpasses-500-mini-apps

**13. ETHGlobal winners pattern: 'products that break without proof of human'**  `[verified]`
- Pain point / observation: World's ETHGlobal prize categories (2026) reward exactly: one-per-human access to scarce resources, sybil-resistant/quadratic voting, human-only marketplaces, personhood-gated reputation — validated by winning mini apps like Mini Vote (ETHGlobal Prague, ranked-choice voting with ZK nullifiers) and QuadWorldVote (scoped nullifier = one human per contest). IDKit 4.0 now offers Proof of Human, Passport, and Selfie Check with sybil_score.
- Lesson for Tanda: World's own judging criteria codify the differentiators Tanda should claim: one-verified-human-per-seat in a split, sybil-proof defaulters list, human-only group rooms. A hackathon-validated architecture (domain-scoped nullifiers per group/ledger) exists to copy.
- Evidence: https://ethglobal.com/events/newyork2026/prizes

**14. Social layer primitives: usernames, contacts, address book**  `[verified]`
- Pain point / observation: Jan 2025 rollout: Contacts tab with invites/favorites, usernames searchable for P2P transactions, a MiniKit Contacts Command letting any mini app read user-granted contacts, plus push notifications and Quick Actions deep links between apps.
- Lesson for Tanda: Group formation (who's in the trip/household) can borrow the platform's real-identity social graph instead of phone-number contacts — payer lookup by username plus contact-grant APIs is the cheapest way to seed a split group.
- Evidence: https://world.org/blog/announcements/world-mini-apps-milestones-new-features-incubator-announced

**15. 2026 platform restructure: World ID app + World Money split**  `[reported]`
- Pain point / observation: Sept 17, 2026: World divided into a separate World ID (identity) app and World Money (financial super-app, 150+ countries); support docs now say mini apps live in both 'World ID app and World Money app'; discovery is via Top Apps section, search/Spotlight, and in-chat threads.
- Lesson for Tanda: Tanda will be listed to a finance-first audience inside World Money with identity proofs served from the adjacent World ID app — a re-scoping of onboarding funnel assumptions vs. the old single World App.
- Evidence: https://ground.news/article/world-launches-world-money-super-app-for-global-payments-and-investing

**16. Enterprise anti-sybil finance push (human-vs-agent trust tailwind)**  `[verified]`
- Pain point / observation: Oct 18, 2026: 'World ID for banking and finance' launched at Money20/20 (Proof of Human / Presence / Attributes; design partners Bain Capital, Pantera, VanEck; Zoom integration for verified humans in meetings); Nov 12, 2026: Trusted Agent Delegation with Cloudflare; Nov 2, 2026 dating-trust survey tied to Tinder's verified-human badge. World Chain also cited (L2Beat) for the highest UOPS/TPS ratio of any Ethereum chain — 'mostly real humans, not bots'.
- Lesson for Tanda: The platform's entire 2026 narrative is 'trust is the scarcest resource'; Tanda's escrowed USDC splits are a consumer-scale demo of exactly that thesis (real humans, real money, provable participants) — good fit for World co-marketing and 'no bots' positioning.
- Evidence: https://world.org/blog/announcements/world-id-banking-finance-ai-safe

**17. No third-party split-expenses mini app found in the World ecosystem**  `[UNVERIFIED]`
- Pain point / observation: Across world.org blog/ecosystem pages, developer docs, ETHGlobal showcases, press (Blockworks, zerohash, crypto-news-flash, testingcatalog) and app-store-adjacent searches, no third-party World mini app for group expense splitting was found; all bill-split search hits were external web2 apps (Splitwise, Splid, Venmo, OweNo) outside the World App container. Caveat: the in-app Mini App store (500+ apps) is not crawlable from the public web, so absence of evidence is not proof of absence.
- Lesson for Tanda: The third-party slot for 'Splitwise inside World App' appears open — but the first-party World Chat splitter occupies the same job-to-be-done, so Tanda's wedge is escrow/guarantee features the native tool lacks, not basic splitting.
- Evidence: https://world.org/ecosystem

### Lane top insights
1. The enemy is native: World Chat already ships free, in-thread group bill-splitting with tap-to-pay requests. Tanda must either differentiate on what first-party splitting lacks — USDC escrow guarantees, settlement state, defaulter accountability, cross-group ledgers — or ship AS a mini app embedded inside those same group chats rather than competing with them.
2. Proven growth formula for World mini apps = zero-cost distribution to a verifiably-human audience + World ID as the product itself. Every cited winner (Credit 70k users via sybil-proof lending, ORO 1.4M weekly verifications, Meritt 30k humans on 'human-only' positioning, Earn's per-human APY) monetizes one-human-one-account mechanics; Dev Rewards (up to $100k/week in WLD keyed to verified-human usage), the World Build/FWB incubator (payments teams explicitly recruited), and the official invite-loop playbook provide the cold-start and revenue floor.
3. World's 2026 trajectory (World ID for banking, Trusted Agent Delegation, Tinder badges, 'no bots' chat bubbles) is a platform-wide bet on human-vs-agent trust — and 'every seat in your split is an Orb-verified human who cannot ghost and re-register' is the consumer-scale proof of that thesis, giving Tanda both a defensible anti-sybil feature set (scoped nullifiers per ledger, sybil_score, verified-defaulter lists per ETHGlobal-winning patterns) and a strong co-marketing story the platform itself is pushing.
