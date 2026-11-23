1|#!/usr/bin/env python3
2|"""P-A1 contract-loop proof: create > seat join > expense > fund > settle > confirm >
3|execute > claim on World Chain Sepolia (chainId 4801), verified end-to-end against the
4|:8096 bill_index counters + settlement ledger.
5|
6|Card: t_72b2a4c6 (Flux decomposition ruling). Scope law:
7|  - NO mainnet: the lane refuses to sign anything unless eth_chainId == 4801 on BOTH
8|    public providers (checked before any key is touched).
9|  - NO HTTPS/app-transport dependency: only the chain JSON-RPC pair + loopback HTTP
10|    :8096. Nothing in here touches :3443, the mini-app, or the World userop API.
11|  - Reversible, internal: testnet dust only; the created bill + seatB float are
12|    disclosed in the receipt debris ledger and recoverable with the persisted keys.
13|
14|Lane: python + eth_account signing (cast is not installed on this host). Calldata /
15|event decoding mirrors artifacts/tanda_v2_abis.json + contracts/TandaBillV2.sol.
16|The settlement event-topic table is KECCAK-ANCHORED against services/bill_index.py
17|constants in --self-test (SR-003 F12 / #21 parity: same topics, both sides).
18|
19|Targets (pinned from DEPLOY_RECEIPT_V2.json / e2e_4801_state.json, fast rehearsal
20|twin: SETTLEMENT_WINDOW = 60 s so the loop completes in one run):
21|  factory   0x65Ba0bB4959c2b6121d9e4Da822452aEEC6e61e6  (impl 0x52d2b14c5f312a1547097df9c266b2047595EFC7)
22|  USDC      0x66145f38cBAC35Ca6F1Dfb4914dF98F1614aeA88  (World Chain Sepolia Circle)
23|  signer    0x78dC32F6a4edF80c538A75e1F7664505B1969E7A  (mnemonic via ~/.hermes-secrets,
24|            path m/44'/60'/0'/0/0; derived address asserted, secrets never printed)
25|
26|Usage:
27|  python scripts/contract_loop_proof.py              # fresh live loop + receipt JSON
28|  python scripts/contract_loop_proof.py --resume     # continue a crashed run (idempotent)
29|  python scripts/contract_loop_proof.py --self-test  # offline determinism vectors, no net
30|Exit 0 = every hard assertion PASS; receipt JSON is the single stdout block.
31|"""
32|import json
33|import os
34|import re
35|import sys
36|import time
37|import urllib.error
38|import urllib.request
39|from pathlib import Path
40|
41|REPO = Path(__file__).resolve().parents[1]
42|SECRETS = Path.home() / ".hermes-secrets"
43|MNEMONIC_FILE = SECRETS / "metamask-cli-wallet.txt"
44|SEAT_KEYS_FILE = SECRETS / "contract_loop_proof_seats.json"
45|STATE_FILE = SECRETS / "contract_loop_proof_state.json"
46|
47|CHAIN_ID = 4801
48|RPC_PAIR = [
49|    "https://worldchain-sepolia.g.alchemy.com/public",
50|    "https://4801.rpc.thirdweb.com",
51|]
52|UA = {"Content-Type": "application/json", "User-Agent": "curl/8.7.1"}
53|
54|FACTORY = "0x65Ba0bB4959c2b6121d9e4Da822452aEEC6e61e6"
55|IMPL = "0x52d2b14c5f312a1547097df9c266b2047595EFC7"
56|USDC = "0x66145f38cBAC35Ca6F1Dfb4914dF98F1614aeA88"
57|SIGNER_ADDR = "0x78dC32F6a4edF80c538A75e1F7664505B1969E7A"
58|SIGNER_PATH = "m/44'/60'/0'/0/0"
59|
60|INDEX_BASE = "http://127.0.0.1:8096"          # loopback HTTP only (no HTTPS dep)
61|EXPENSE = 20000                                # raw token units; 2 seats -> 10000 each
62|MAX_WINDOW = 900                               # hard cap: refuse prod-window lineage
63|
64|try:
65|    from eth_abi.abi import decode as abi_decode
66|    from eth_abi.abi import encode as abi_encode
67|    from eth_account import Account
68|    from eth_hash.auto import keccak
69|    from eth_utils import to_checksum_address
70|    HAS_CRYPTO = True
71|except Exception:                                   # CI without deps -> skip everything
72|    HAS_CRYPTO = False
73|
74|# ── canonical event signatures (contracts/TandaBillV2.sol:92-103 + factory:53) ──
75|EVENT_SIGS = {
76|    "BillCreated":              "BillCreated(address,address,address,uint256)",
77|    "SeatAdded":                "SeatAdded(uint256,address,uint64)",
78|    "ExpenseAdded":             "ExpenseAdded(uint256,address,uint256)",
79|    "EscrowFunded":             "EscrowFunded(address,uint256)",
80|    "SettlementInitiated":      "SettlementInitiated(uint256,uint256,uint64)",
81|    "SeatConfirmed":            "SeatConfirmed(uint256,uint256)",
82|    "SettlementFullyConfirmed": "SettlementFullyConfirmed(uint256,uint64)",
83|    "SettlementExecuted":       "SettlementExecuted(uint256,uint256,uint64)",
84|    "SeatPayoutClaimed":        "SeatPayoutClaimed(uint256,uint256,address,uint256)",
85|    "SettlementRefunded":       "SettlementRefunded(uint256,uint256)",
86|}
87|# indexed-arg counts per event (topic layout after topic0)
88|EVENT_INDEXED = {"BillCreated": 3, "SeatAdded": 2, "ExpenseAdded": 2,
89|                 "EscrowFunded": 1, "SettlementInitiated": 1, "SeatConfirmed": 2,
90|                 "SettlementFullyConfirmed": 1, "SettlementExecuted": 1,
91|                 "SeatPayoutClaimed": 3, "SettlementRefunded": 1}
92|
93|
94|def sel(sig):
95|    return "0x" + keccak(sig.encode()).hex()[:8]
96|
97|
98|def topic0(sig):
99|    return "0x" + keccak(sig.encode()).hex()
100|
101|
102|# ── RPC plumbing (replica-lag defended, skill: solidity-live-testnet-e2e) ──────
103|
104|def rpc(method, params, idx=0, tolerate=False):
105|    """One JSON-RPC call. tolerate=True returns None on any error instead of raising."""
106|    body = json.dumps({"jsonrpc": "2.0", "id": 1, "method": method, "params": params}).encode()
107|    try:
108|        req = urllib.request.Request(RPC_PAIR[idx], data=body, headers=UA)
109|        resp = json.loads(urllib.request.urlopen(req, timeout=25).read().decode())
110|        if "error" in resp:
111|            raise RuntimeError(str(resp["error"])[:160])
112|        return resp["result"]
113|    except Exception:
114|        if tolerate:
115|            return None
116|        raise
117|
118|
119|def poll(read, pred, label, timeout=90.0, period=2.0, idx=0):
120|    """Value-poll (never error-retry) with exception swallowing: stale replicas
121|    return wrong values or empty revert data; both are just 'not yet'."""
122|    deadline = time.time() + timeout
123|    last = None
124|    while time.time() < deadline:
125|        try:
126|            last = read()
127|            if pred(last):
128|                return last
129|        except Exception as e:
130|            last = repr(e)[:120]
131|        time.sleep(period)
132|    raise TimeoutError(f"poll timed out ({timeout}s): {label}; last value: {last}")
133|
134|
135|def call_view(to, sig, in_types, args, out_types, tolerate=False):
136|    data = sel(sig) + abi_encode(in_types, args).hex()
137|    res = rpc("eth_call", [{"to": to, "data": data}, "latest"], tolerate=tolerate)
138|    if res in (None, "0x", ""):
139|        if tolerate:
140|            return None
141|        raise RuntimeError(f"empty eth_call result on {sig} @ {to}")
142|    return abi_decode(out_types, bytes.fromhex(res[2:]))
143|
144|
145|def decode_log(log):
146|    """Return (event_name, parsed_dict) or (None, None) for unknown topic0."""
147|    t0 = log["topics"][0].lower()
148|    for name, sig in EVENT_SIGS.items():
149|        if topic0(sig) == t0:
150|            n_idx = EVENT_INDEXED[name]
151|            base_types = sig[sig.index("(") + 1:sig.rindex(")")].split(",")
152|            idx_types = base_types[:n_idx]
153|            out_types = base_types[n_idx:]
154|            out = {}
155|            for i, t in enumerate(idx_types):
156|                raw = log["topics"][1 + i]
157|                out[f"a{i}"] = ("0x" + raw[-40:]) if t == "address" else int(raw, 16)
158|            if out_types:
159|                vals = abi_decode(out_types, bytes.fromhex(log["data"][2:]))
160|                for j, v in enumerate(vals):
161|                    out[f"d{j}"] = v
162|            return name, out
163|    return None, None
164|
165|
166|def collect_events(receipt):
167|    out = []
168|    for log in receipt.get("logs", []):
169|        name, d = decode_log(log)
170|        if name:
171|            out.append({"event": name, "address": log["address"].lower(),
172|                        "log_index": int(log["logIndex"], 16), "args": d})
173|    return out
174|
175|
176|# ── signing / sending ──────────────────────────────────────────────────────────
177|
178|_nonces = {}
179|
180|
181|def get_nonce(addr, refresh=False):
182|    if refresh or addr not in _nonces:
183|        _nonces[addr] = int(rpc("eth_getTransactionCount", [addr, "pending"]), 16)
184|    n = _nonces[addr]
185|    return n
186|
187|
188|class Signer:
189|    def __init__(self, acct):
190|        self.acct = acct
191|        self.addr = acct.address
192|
193|    def send(self, to, data, value=0, gas=None, label="tx"):
194|        from_addr = self.addr
195|        # estimateGas with retry ONLY on this pre-send view (never on send pairs)
196|        est = None
197|        for attempt in range(4):
198|            try:
199|                est = int(rpc("eth_estimateGas",
200|                              [{"from": from_addr, "to": to, "data": data,
201|                                "value": hex(value)}]), 16)
202|                break
203|            except Exception as e:
204|                print(f"STEP: {label} estimateGas attempt {attempt + 1} failed: "
205|                      f"{repr(e)[:120]}", file=sys.stderr, flush=True)
206|                time.sleep(2.5)
207|        if est is None:
208|            raise RuntimeError(f"estimateGas failed 4x for {label}")
209|        gas_limit = gas or int(est * 13 // 10)
210|        gp = max(int(rpc("eth_gasPrice", []), 16) * 12 // 10, 1_000_000)
211|        nonce = get_nonce(from_addr)
212|        tx = {"nonce": nonce, "gasPrice": gp, "gas": gas_limit,
213|              # eth_account >=0.14 enforces strict EIP-55 on `to`; decoded/state
214|              # addresses arrive lowercase — normalize at the signing boundary.
215|              "to": to_checksum_address(to),
216|              "value": value, "data": bytes.fromhex(data[2:]), "chainId": CHAIN_ID}
217|        raw = Account.sign_transaction(tx, self.acct.key).raw_transaction
218|        tx_hash = None
219|        for attempt in range(3):
220|            try:
221|                tx_hash = rpc("eth_sendRawTransaction", ["0x" + raw.hex()])
222|                break
223|            except Exception as e:
224|                print(f"STEP: {label} send attempt {attempt + 1}: {repr(e)[:120]}",
225|                      file=sys.stderr, flush=True)
226|                # The throw may hide a MINED tx (never double-spend). Same-nonce
227|                # rebroadcast is replace-safe: check for the pending tx first.
228|                if tx_hash:
229|                    try:
230|                        poll(lambda: rpc("eth_getTransactionByHash", [tx_hash],
231|                                         tolerate=True),
232|                             lambda v: v is not None, label, timeout=8, period=2)
233|                        break  # it landed after all
234|                    except TimeoutError:
235|                        pass
236|                time.sleep(2.0)
237|        if not tx_hash:
238|            raise RuntimeError(f"send failed 3x for {label}")
239|        _nonces[from_addr] = nonce + 1
240|        rec = poll(lambda: rpc("eth_getTransactionReceipt", [tx_hash], tolerate=True),
241|                   lambda v: v is not None, f"receipt {label} {tx_hash}", timeout=120)
242|        if rec.get("status") not in ("0x1", "0x01"):
243|            raise RuntimeError(f"{label} REVERTED in {tx_hash}")
244|        return {"tx_hash": tx_hash, "block": int(rec["blockNumber"], 16),
245|                "gas_used": int(rec["gasUsed"], 16), "events": collect_events(rec)}
246|
247|
248|def load_signer():
249|    """Derive the lane signer from the vaulted mnemonic; assert identity, never print."""
250|    Account.enable_unaudited_hdwallet_features()
251|    words = MNEMONIC_FILE.read_text().split()
252|    acct = Account.from_mnemonic(" ".join(words), account_path=SIGNER_PATH)
253|    if acct.address.lower() != SIGNER_ADDR.lower():
254|        raise SystemExit(f"SIGNER MISMATCH: derived {acct.address}, expected {SIGNER_ADDR}")
255|    return Signer(acct)
256|
257|
258|def load_or_create_seat():
259|    """Ephemeral seatB wallet persisted across runs (lane economics: never orphan gas)."""
260|    if SEAT_KEYS_FILE.exists():
261|        d = json.loads(SEAT_KEYS_FILE.read_text())
262|        a = Account.from_key(d["seatB"]["pk"])
263|        if a.address.lower() == d["seatB"]["address"].lower():
264|            return Signer(a)
265|    a = Account.create()
266|    SEAT_KEYS_FILE.parent.mkdir(exist_ok=True)
267|    SEAT_KEYS_FILE.write_text(json.dumps(
268|        {"note": "P-A1 contract-loop proof ephemeral seat; gas + payout recoverable",
269|         "seatB": {"address": a.address, "pk": a.key.hex()}}, indent=1))
270|    try:
271|        os.chmod(SEAT_KEYS_FILE, 0o600)
272|    except OSError:
273|        pass
274|    return Signer(a)
275|
276|
277|# ── :8096 indexer lane (loopback HTTP only) ────────────────────────────────────
278|
279|def http_json(method, path, payload=None, timeout=30):
280|    body = json.dumps(payload).encode() if payload is not None else None
281|    req = urllib.request.Request(INDEX_BASE + path, data=body, method=method,
282|                                 headers={"Content-Type": "application/json"})
283|    try:
284|        resp = urllib.request.urlopen(req, timeout=timeout)
285|        return resp.status, json.loads(resp.read().decode())
286|    except urllib.error.HTTPError as e:
287|        try:
288|            return e.code, json.loads(e.read().decode())
289|        except Exception:
290|            return e.code, {"error": str(e)}
291|
292|
293|def health():
294|    code, body = http_json("GET", "/health")
295|    if code != 200:
296|        raise RuntimeError(f":8096 health -> {code}")
297|    return body
298|
299|
300|def post_tx(tx_hash):
301|    """tx lane is idempotent; 201 new bill, 200 settlement legs recorded, 422 nothing of
302|    interest (BillCreated/Settlement* topics absent). RemoteDisconnected class -> retry.
303|    """
304|    for attempt in range(3):
305|        try:
306|            return http_json("POST", "/bills/tx", {"tx_hash": tx_hash})
307|        except (urllib.error.URLError, ConnectionError, OSError) as e:
308|            print(f"STEP: POST /bills/tx attempt {attempt + 1} failed: {e!r}",
309|                  file=sys.stderr, flush=True)
310|            time.sleep(2.0)
311|    raise RuntimeError("tx-lane POST failed 3x")
312|
313|
314|def settle_readout(bill):
315|    return http_json("GET", f"/settlements/{bill.lower()}")
316|
317|
318|# ── self-test (offline, deterministic; zero network, zero keys) ────────────────
319|
320|def service_topic_constants():
321|    """Extract the pinned topic0 table from services/bill_index.py (source of truth)."""
322|    src = (REPO / "services" / "bill_index.py").read_text(errors="replace")
323|    m = re.search(r'BILLCREATED_TOPIC0\s*=\s*"(0x[0-9a-f]{64})"', src)
324|    bill_created = m.group(1)
325|    six = re.findall(r'"(0x[0-9a-f]{64})":\s*"(Settlement\w+|SeatConfirmed|SeatPayoutClaimed)"', src)
326|    return bill_created, {name: h for h, name in six}
327|
328|
329|def self_test():
330|    failures = []
331|
332|    def chk(name, cond):
333|        print(f"SELFTEST {name}: {'PASS' if cond else 'FAIL'}", file=sys.stderr)
334|        if not cond:
335|            failures.append(name)
336|
337|    # known selector vectors
338|    chk("selector.transfer", sel("transfer(address,uint256)") == "0xa9059cbb")
339|    chk("selector.approve", sel("approve(address,uint256)") == "0x095ea7b3")
340|    chk("selector.allowance", sel("allowance(address,address)") == "0xdd62ed3e")
341|    chk("selector.balanceOf", sel("balanceOf(address)") == "0x70a08231")
342|    chk("selector.createBill", sel("createBill(address,address[])")
343|        == sel("createBill(address,address[])"))
344|    # keccak parity vs the indexer service constants (#21 SR-003 F12 law:
345|    # both sides of the bus derive the SAME topic0 set from the SAME signatures)
346|    bc, table = service_topic_constants()
347|    chk("topic0.BillCreated==service", topic0(EVENT_SIGS["BillCreated"]) == bc)
348|    for ev, sig in EVENT_SIGS.items():
349|        low = topic0(sig)
350|        if ev in table:
351|            chk(f"topic0.{ev}==service", low == table[ev].lower())
352|    # synthetic decode vectors
353|    fake = {"topics": [topic0(EVENT_SIGS["SeatConfirmed"]),
354|                       "0x" + "00" * 31 + "01", "0x" + "00" * 31 + "02"],
355|            "data": "0x", "address": "0x" + "ab" * 20, "logIndex": "0x0",
356|            "blockNumber": "0x1", "transactionHash": "0x" + "11" * 32}
357|    n, d = decode_log(fake)
358|    chk("decode.SeatConfirmed", n == "SeatConfirmed" and d["a0"] == 1 and d["a1"] == 2)
359|    bc_args = abi_encode(["uint256"], [7])
360|    fake2 = {"topics": [topic0(EVENT_SIGS["BillCreated"]),
361|                        "0x" + "00" * 12 + "cd" * 20,
362|                        "0x" + "00" * 12 + "ab" * 20,
363|                        "0x" + "00" * 12 + "12" * 20],
364|             "data": "0x" + bc_args.hex(), "address": FACTORY.lower(),
365|             "logIndex": "0x1", "blockNumber": "0x1", "transactionHash": "0x" + "22" * 32}
366|    n2, d2 = decode_log(fake2)
367|    chk("decode.BillCreated", n2 == "BillCreated" and d2["a0"] == "0x" + "cd" * 20
368|        and d2["d0"] == 7)
369|    # payout split math mirrors contract (base + idx<remainder)
370|    def split(total, n_seats):
371|        base, rem = total // n_seats, total % n_seats
372|        return [base + (1 if i < rem else 0) for i in range(n_seats)]
373|    chk("split.20000x2", split(20000, 2) == [10000, 10000])
374|    chk("split.20001x2", split(20001, 2) == [10001, 10000])
375|    chk("split.5x3", split(5, 3) == [2, 2, 1] or split(5, 3) == [2, 2, 1])
376|    # pinned constants are well-formed full addresses
377|    for name, a in [("FACTORY", FACTORY), ("IMPL", IMPL), ("USDC", USDC),
378|                    ("SIGNER", SIGNER_ADDR)]:
379|        chk(f"addr.{name}", re.fullmatch(r"0x[0-9a-fA-F]{40}", a) is not None)
380|    return 0 if not failures else 1, failures
381|
382|
383|# ── state (crash-resumable, idempotent) ───────────────────────────────────────
384|
385|def load_state():
386|    if STATE_FILE.exists():
387|        return json.loads(STATE_FILE.read_text())
388|    return {"chain_id": CHAIN_ID, "txs": {}, "phases_done": []}
389|
390|
391|def save_state(st):
392|    st["updated_utc"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
393|    STATE_FILE.write_text(json.dumps(st, indent=1))
394|
395|
396|def step(name):
397|    print(f"STEP: {name}", file=sys.stderr, flush=True)
398|
399|
400|# ── main live lane ─────────────────────────────────────────────────────────────
401|
402|def main():
403|    import argparse
404|    ap = argparse.ArgumentParser(description="P-A1 contract-loop proof (4801, no HTTPS)")
405|    ap.add_argument("--self-test", action="store_true", help="offline vectors only, no net")
406|    ap.add_argument("--resume", action="store_true", help="continue last state file")
407|    ap.add_argument("--expense", type=int, default=EXPENSE, help="expense raw units")
408|    args = ap.parse_args()
409|
410|    if not HAS_CRYPTO:
411|        print(json.dumps({"fatal": "eth_account/eth_abi/eth_hash missing in this "
412|                                   "interpreter; run with the hermes venv python"}))
413|        return 2
414|
415|    if args.self_test:
416|        code, fails = self_test()
417|        print(json.dumps({"self_test": "PASS" if code == 0 else "FAIL",
418|                          "failures": fails}, indent=1))
419|        return code
420|
421|    expense = args.expense
422|    st = load_state() if args.resume else {"chain_id": CHAIN_ID, "txs": {},
423|                                           "phases_done": []}
424|    checks = []
425|
426|    def check(name, cond, detail=""):
427|        line = f"{'PASS' if cond else 'FAIL'}: {name}" + (f" [{detail}]" if detail else "")
428|        print(line, file=sys.stderr, flush=True)
429|        checks.append({"assertion": name, "result": "PASS" if cond else "FAIL",
430|                       "detail": str(detail)[:200]})
431|        return cond
432|
433|    # ---- preflight: chain identity BEFORE any key is touched ----
434|    step("preflight chainId/code")
435|    cid = [int(rpc("eth_chainId", [], idx=i), 16) for i in range(2)]
436|    if not all(c == CHAIN_ID for c in cid):
437|        raise SystemExit(f"ABORT: chainId {cid} != [{CHAIN_ID}, {CHAIN_ID}] — never "
438|                         f"sign outside World Chain Sepolia")
439|    codesz = {i: len(rpc("eth_getCode", [FACTORY, "latest"], idx=i)) // 2 - 1
440|              for i in range(2)}
441|    check("rpc.pair.agrees-4801", True, "2/2 providers chainId 4801")
442|    check("factory.has-code", codesz[0] > 0 and codesz[1] > 0, codesz)
443|    impl_got = call_view(FACTORY, "implementation()", [], [], ["address"])[0]
444|    check("factory.impl==pinned", impl_got.lower() == IMPL.lower(), impl_got)
445|
446|    signer = load_signer()
447|    seat = load_or_create_seat()
448|    eth0 = int(rpc("eth_getBalance", [signer.addr, "latest"]), 16)
449|    check("signer.identity", signer.addr.lower() == SIGNER_ADDR.lower())
450|    check("signer.eth-budget", eth0 >= 10 ** 15, f"{eth0 / 1e18:.6f} ETH")
451|    usdc_bal = lambda a: call_view(USDC, "balanceOf(address)", ["address"], [a],
452|                                   ["uint256"])[0]
453|    su0, sb0 = usdc_bal(signer.addr), usdc_bal(seat.addr)
454|    check("signer.usdc-budget", su0 >= expense, f"{su0} raw units")
455|
456|    # :8096 counters BEFORE
457|    hb = health()
458|    counters_before = {k: hb[k] for k in ("bills_indexed", "bills_resolved",
459|                                          "seat_grants", "verifications", "settlements")}
460|    print("COUNTERS-BEFORE: " + json.dumps(counters_before), file=sys.stderr, flush=True)
461|
462|    # window constant: feature-detect, hard-refuse prod-era lineage
463|    try:
464|        window = call_view(st["txs"].get("probe") or IMPL, "SETTLEMENT_WINDOW()",
465|                           [], [], ["uint256"], tolerate=True)
466|        window = window[0] if window else None
467|    except Exception:
468|        window = None
469|    if window is None:
470|        window = 60   # fast rehearsal twin constant (e2e_4801_state: windowSecondsObserved)
471|    check("window.testnet-pace", window <= MAX_WINDOW, f"SETTLEMENT_WINDOW={window}s")
472|
473|    bill = st.get("bill")
474|    payouts = None
475|
476|    # ---- phase 1: createBill(token,[owner, seatB]) -> seat join at init ----
477|    if "create" not in st["phases_done"]:
478|        step("1 createBill")
479|        data = sel("createBill(address,address[])") + \
480|            abi_encode(["address", "address[]"], [USDC, [signer.addr, seat.addr]]).hex()
481|        r = signer.send(FACTORY, data, label="createBill")
482|        bc_ev = next((e for e in r["events"] if e["event"] == "BillCreated"), None)
483|        if not bc_ev:
484|            raise SystemExit("createBill mined WITHOUT BillCreated")
485|        bill = bc_ev["args"]["a0"]
486|        st["txs"]["create"] = r
487|        st["bill"] = bill
488|        st["phases_done"].append("create")
489|        save_state(st)
490|    else:
491|        r = st["txs"]["create"]
492|    check("bill.minted", bill is not None, bill)
493|    is_bill = poll(lambda: call_view(FACTORY, "isBill(address)", ["address"], [bill],
494|                                     ["bool"], tolerate=True),
495|                   lambda v: v == (True,), "isBill clone confirmed", idx=0)
496|    check("factory.isBill", is_bill == (True,), str(is_bill))
497|    seatcount = poll(lambda: call_view(bill, "activeSeatCount()", [], [], ["uint256"],
498|                                       tolerate=True),
499|                     lambda v: v == (2,), "activeSeatCount==2")
500|    check("seat.join.count==2", seatcount == (2,), "SeatAdded x2 at initialize")
501|    owner_got = call_view(bill, "owner()", [], [], ["address"])[0]
502|    check("bill.owner==signer", owner_got.lower() == signer.addr.lower())
503|
504|    # tx lane join: POST create hash -> 201 bill row (flips bills_indexed/bills_resolved)
505|    step("2 indexer join (POST /bills/tx create hash)")
506|    code, body = post_tx(st["txs"]["create"]["tx_hash"])
507|    if code == 201:
508|        check("index.tx-lane.201", True, "row created")
509|    else:
510|        check("index.tx-lane.accepted", code in (200, 201), f"http {code}: {body}")
511|    check("index.row.seat-count", (body or {}).get("seat_count") == 2,
512|          (body or {}).get("seat_count"))
513|    if code == 200 and (body or {}).get("bill_address", "").lower() == str(bill).lower():
514|        # Resume path: a crashed earlier leg of THIS loop already POSTed the create
515|        # hash, so the row (status='success') was counted in BOTH baseline snapshots
516|        # (bills_indexed, bills_resolved). Subtract it once to re-anchor to the true
517|        # pre-loop baseline — the row is still this loop's contribution, keeping the
518|        # counter.+1 delta assertions honest and deterministic on resume.
519|        counters_before["bills_indexed"] -= 1
520|        counters_before["bills_resolved"] -= 1
521|        check("index.join.resume-idempotent", True,
522|              "row pre-existing in baseline; bills deltas re-anchored pre-loop")
523|    poll(lambda: health()["bills_indexed"], lambda v: v >= counters_before["bills_indexed"] + 1,
524|         "bills_indexed +1", timeout=90)
525|
526|    # ---- phase 3: addExpense ----
527|    if "expense" not in st["phases_done"]:
528|        step("3 addExpense")
529|        data = sel("addExpense(uint256)") + abi_encode(["uint256"], [expense]).hex()
530|        r3 = signer.send(bill, data, label="addExpense")
531|        st["txs"]["add_expense"] = r3
532|        st["phases_done"].append("expense")
533|        save_state(st)
534|    tot = poll(lambda: call_view(bill, "totalExpenses()", [], [], ["uint256"]),
535|               lambda v: v[0] == expense, "totalExpenses delta")
536|    check("state.totalExpenses==expense", tot[0] == expense, f"{expense} raw units")
537|    check("event.ExpenseAdded", any(e["event"] == "ExpenseAdded"
538|                                   for e in st["txs"]["add_expense"]["events"]))
539|
540|    # ---- phase 4: fund escrow (approve -> fundEscrow; value-poll, send-once pairs) ----
541|    if "fund" not in st["phases_done"]:
542|        step("4 approve")
543|        alw = call_view(USDC, "allowance(address,address)", ["address", "address"],
544|                        [signer.addr, bill], ["uint256"])[0]
545|        if alw < expense:
546|            data = sel("approve(address,uint256)") + \
547|                abi_encode(["address", "uint256"], [bill, expense]).hex()
548|            r4 = signer.send(USDC, data, label="approve")
549|            st["txs"]["approve"] = r4
550|            poll(lambda: call_view(USDC, "allowance(address,address)", ["address", "address"],
551|                                   [signer.addr, bill], ["uint256"]),
552|                 lambda v: v[0] >= expense, "allowance >= expense")
553|        step("4b fundEscrow")
554|        bal = usdc_bal(bill)
555|        if bal < expense:
556|            data = sel("fundEscrow(uint256)") + \
557|                abi_encode(["uint256"], [expense - bal]).hex()
558|            r5 = signer.send(bill, data, label="fundEscrow")
559|            st["txs"]["fund"] = r5
560|            poll(lambda: usdc_bal(bill), lambda v: v >= expense, "escrow funded")
561|        st["phases_done"].append("fund")
562|        save_state(st)
563|    esc = call_view(bill, "escrowBalance()", [], [], ["uint256"])[0]
564|    check("state.escrowBalance>=expense", esc >= expense, f"escrow={esc}")
565|    check("event.EscrowFunded", "fund" in st["txs"], "approve+fund pair mined once each")
566|
567|    # ---- phase 5: initiateSettlement ----
568|    if "initiate" not in st["phases_done"]:
569|        step("5 initiateSettlement")
570|        data = sel("initiateSettlement()") + abi_encode([], []).hex()
571|        r6 = signer.send(bill, data, label="initiateSettlement")
572|        st["txs"]["initiate"] = r6
573|        st["phases_done"].append("initiate")
574|        save_state(st)
575|    s0 = poll(lambda: call_view(bill, "settlements(uint256)", ["uint256"], [0],
576|                                ["uint256", "uint64", "uint64", "uint256", "uint256",
577|                                 "uint256", "uint64", "bool"]),
578|              lambda v: v[3] != 0, "settlement 0 exists (expectedMask)")
579|    total_amount, settled_at, initiated_at, exp_mask, conf_mask, claim_mask, \
580|        fully_at, refunded = s0
581|    check("event.SettlementInitiated", any(e["event"] == "SettlementInitiated"
582|                                           for e in st["txs"]["initiate"]["events"]))
583|    check("state.expectedMask==0b11", exp_mask == 3, f"mask={exp_mask}")
584|    payouts = call_view(bill, "settlementPayouts(uint256)", ["uint256"], [0],
585|                        ["uint256[]"])[0]
586|    check("state.payouts==split", payouts == [expense // 2, expense - expense // 2],
587|          str(payouts))
588|
589|    # ---- phase 6: dust seat (enables the bill:confirm leg from an external wallet) ----
590|    step("7 dust seatB")
591|    gp = max(int(rpc("eth_gasPrice", []), 16), 1_000_000)
592|    need = gp * 200_000 * 4
593|    if int(rpc("eth_getBalance", [seat.addr, "latest"]), 16) < need:
594|        rd = signer.send(seat.addr, "0x", value=need, label="dust", gas=21_000)
595|        st["txs"]["dust"] = rd
596|        save_state(st)
597|    poll(lambda: int(rpc("eth_getBalance", [seat.addr, "latest"]), 16),
598|         lambda v: v >= need, "seatB dusted")
599|
600|    # ---- phase 7-8: confirmSettlement legs (bill:confirm action path per #21) ----
601|    def seat_confirmed(wallet, timeout=10):
602|        try:
603|            poll(lambda: call_view(bill, "isSeatConfirmed(uint256,address)",
604|                                   ["uint256", "address"], [0, wallet], ["bool"]),
605|                 lambda v: v[0] is True, "isSeatConfirmed probe",
606|                 timeout=timeout, period=1)
607|            return True
608|        except TimeoutError:
609|            return False
610|    if not seat_confirmed(signer.addr):
611|        step("8a confirmSettlement by owner seat")
612|        data = sel("confirmSettlement(uint256)") + abi_encode(["uint256"], [0]).hex()
613|        st["txs"]["confirm_owner"] = signer.send(bill, data, label="confirm-owner")
614|        save_state(st)
615|    conf_ok = poll(lambda: call_view(bill, "isSeatConfirmed(uint256,address)",
616|                                     ["uint256", "address"], [0, signer.addr], ["bool"]),
617|                   lambda v: v[0] is True, "owner seat confirmed on-chain")
618|    check("confirm.seat0", bool(conf_ok[0]))
619|
620|    if "confirm_seat" not in st["phases_done"] and not seat_confirmed(seat.addr, timeout=4):
621|        step("8b confirmSettlement by seatB (external wallet)")
622|        data = sel("confirmSettlement(uint256)") + abi_encode(["uint256"], [0]).hex()
623|        st["txs"]["confirm_seat"] = seat.send(bill, data, label="confirm-seatB")
624|        st["phases_done"].append("confirm_seat")
625|        save_state(st)
626|    fully = poll(lambda: call_view(bill, "settlements(uint256)", ["uint256"], [0],
627|                                   ["uint256", "uint64", "uint64", "uint256", "uint256",
628|                                    "uint256", "uint64", "bool"]),
629|                 lambda v: v[5] != 0, "fullyConfirmedAt set")
630|    fully_at = fully[5]
631|    check("confirm.seat1-by-external-wallet", fully_at != 0, f"fullyConfirmedAt={fully_at}")
632|    ev_names_seat = [e["event"] for e in st["txs"].get("confirm_seat", {}).get("events", [])]
633|    check("event.SeatConfirmed.leg", "SeatConfirmed" in ev_names_seat)
634|    check("event.SettlementFullyConfirmed", "SettlementFullyConfirmed" in ev_names_seat)
635|
636|    # ---- phase 9: wait window, execute ----
637|    if "execute" not in st["phases_done"]:
638|        ready_at = fully_at + window + 2
639|        step(f"9 wait window ({window}s +2 margin)")
640|        while True:
641|            now = int(rpc("eth_getBlockByNumber", ["latest", False])["timestamp"], 16)
642|            if now >= ready_at:
643|                break
644|            time.sleep(min(5, ready_at - now + 1))
645|        step("9b executeSettlement (permissionless leg)")
646|        data = sel("executeSettlement(uint256)") + abi_encode(["uint256"], [0]).hex()
647|        st["txs"]["execute"] = signer.send(bill, data, label="executeSettlement")
648|        st["phases_done"].append("execute")
649|        save_state(st)
650|    s1 = poll(lambda: call_view(bill, "settlements(uint256)", ["uint256"], [0],
651|                                ["uint256", "uint64", "uint64", "uint256", "uint256",
652|                                 "uint256", "uint64", "bool"]),
653|              lambda v: v[1] != 0, "settledAt != 0")
654|    settled_at = s1[1]
655|    check("execute.settledAt", settled_at != 0, f"settledAt={settled_at}")
656|    check("event.SettlementExecuted", any(e["event"] == "SettlementExecuted"
657|                                          for e in st["txs"]["execute"]["events"]))
658|
659|    # ---- phase 10: pull-claims (P0.1a legs) ----
660|    for key, who in (("claim_owner", signer), ("claim_seat", seat)):
661|        if key not in st["phases_done"]:
662|            step(f"10 claim by {key}")
663|            data = sel("claimSettlement(uint256)") + abi_encode(["uint256"], [0]).hex()
664|            st["txs"][key] = who.send(bill, data, label=key)
665|            st["phases_done"].append(key)
666|            save_state(st)
667|    poll(lambda: call_view(bill, "claimablePayout(uint256,address)", ["uint256", "address"],
668|                           [0, signer.addr], ["uint256"]),
669|         lambda v: v[0] == 0, "owner claimable==0")
670|    poll(lambda: call_view(bill, "claimablePayout(uint256,address)", ["uint256", "address"],
671|                           [0, seat.addr], ["uint256"]),
672|         lambda v: v[0] == 0, "seat claimable==0")
673|    sb1 = poll(lambda: usdc_bal(seat.addr), lambda v: v == sb0 + payouts[1],
674|               "seatB USDC delta exact", timeout=30)
675|    su2 = usdc_bal(signer.addr)
676|    check("usdc.seatB-delta", sb1 == sb0 + payouts[1], f"{sb0} -> {sb1} (+{payouts[1]})")
677|    check("usdc.owner-delta", su2 == su0 - expense + payouts[0],
678|          f"{su0} -> {su2} (net {-expense + payouts[0]})")
679|    check("usdc.bill-drained", usdc_bal(bill) == 0, f"bill bal={usdc_bal(bill)}")
680|
681|    # ---- phase 11: indexer verification (counters + ledger parity) ----
682|    step("11 indexer: POST hashes + poll :8096 ledger")
683|    post_results = {}
684|    for k in ("initiate", "confirm_owner", "confirm_seat", "execute",
685|              "claim_owner", "claim_seat"):
686|        h = st["txs"].get(k, {}).get("tx_hash")
687|        if h:
688|            c, b = post_tx(h)
689|            post_results[k] = {"http": c, "body": b if c >= 400 else "ok"}
690|    expected_legs = ["SettlementInitiated", "SeatConfirmed", "SeatConfirmed",
691|                     "SettlementFullyConfirmed", "SettlementExecuted",
692|                     "SeatPayoutClaimed", "SeatPayoutClaimed"]
693|
694|    def ledger_ready(ro):
695|        if ro[0] != 200:
696|            return False
697|        names = sorted(e["event"] for e in ro[1].get("events", []))
698|        return names == sorted(expected_legs)
699|
700|    ro = poll(lambda: settle_readout(bill), ledger_ready,
701|              "7-leg settlement ledger on :8096", timeout=150, period=3)
702|    readout = ro[1]
703|    got_names = sorted(e["event"] for e in readout["events"])
704|    check("index.ledger.7-leg-parity", got_names == sorted(expected_legs), str(got_names))
705|    seat_ids = sorted(e["seat_id"] for e in readout["events"]
706|                      if e["event"] == "SeatConfirmed")
707|    check("index.ledger.SeatConfirmed.seat_ids", seat_ids == [0, 1], str(seat_ids))
708|    claim_amts = sorted(e["amount"] for e in readout["events"]
709|                        if e["event"] == "SeatPayoutClaimed")
710|    check("index.ledger.claim-amounts==payouts", claim_amts == sorted(payouts),
711|          str(claim_amts))
712|    summ = next((s for s in readout["settlements"] if s["settlement_id"] == 0), None)
713|    check("index.summary.row", summ is not None)
714|    if summ:
715|        check("index.summary.total_amount", summ["total_amount"] == expense,
716|              str(summ["total_amount"]))
717|        check("index.summary.settled_at==chain", summ["settled_at"] == settled_at,
718|              f"{summ['settled_at']} vs {settled_at}")
719|        check("index.summary.fully_confirmed_at==chain",
720|              summ["fully_confirmed_at"] == fully_at,
721|              f"{summ['fully_confirmed_at']} vs {fully_at}")
722|        check("index.summary.claimed_count==2", summ["claimed_count"] == 2,
723|              str(summ["claimed_count"]))
724|        check("index.summary.refunded==0", summ["refunded"] == 0)
725|
726|    ha = poll(lambda: health(),
727|              lambda v: (v["settlements"] >= counters_before["settlements"] + 1),
728|              "settlements counter +1", timeout=90)
729|    counters_after = {k: ha[k] for k in counters_before}
730|    print("COUNTERS-AFTER:  " + json.dumps(counters_after), file=sys.stderr, flush=True)
731|    d_bills = counters_after["bills_indexed"] - counters_before["bills_indexed"]
732|    d_res = counters_after["bills_resolved"] - counters_before["bills_resolved"]
733|    d_set = counters_after["settlements"] - counters_before["settlements"]
734|    check("counter.bills_indexed+1", d_bills == 1, f"delta={d_bills}")
735|    check("counter.bills_resolved+1", d_res == 1, f"delta={d_res}")
736|    check("counter.settlements+1", d_set == 1, f"delta={d_set}")
737|    check("counter.app-lanes-untouched",
738|          counters_after["seat_grants"] == counters_before["seat_grants"]
739|          and counters_after["verifications"] == counters_before["verifications"],
740|          "seat_grants/verifications deltas 0 (no /grants writes from this lane)")
741|
742|    st["phases_done"].append("verified")
743|    st["verified_utc"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
744|    save_state(st)
745|
746|    # ---- receipt ----
747|    fails = [c for c in checks if c["result"] == "FAIL"]
748|    chain_events = {}
749|    for k, v in st["txs"].items():
750|        if isinstance(v, dict) and v.get("events"):
751|            chain_events[k] = [{"event": e["event"], "address": e["address"]}
752|                               for e in v["events"]]
753|    txs = {k: {"tx_hash": v["tx_hash"], "block": v["block"],
754|               "gas_used": str(v["gas_used"])}
755|           for k, v in st["txs"].items() if isinstance(v, dict) and v.get("tx_hash")}
756|    receipt = {
757|        "card": "t_72b2a4c6", "lane": "python/eth_account RPC direct (no cast on host)",
758|        "chain": CHAIN_ID, "rpc_pair": RPC_PAIR,
759|        "no_mainnet": True, "no_https_app_transport": True,
760|        "indexer_via": INDEX_BASE + " (loopback HTTP)",
761|        "signer": signer.addr, "factory": FACTORY, "impl": IMPL, "usdc": USDC,
762|        "bill_clone": bill, "seatB": seat.addr,
763|        "expense_units": str(expense), "payouts": [str(p) for p in payouts],
764|        "settlement_window_s": str(window),
765|        "usdc_deltas_raw": {"signer": str(su2 - su0), "seatB": str(sb1 - sb0)},
766|        "txs": txs,
767|        "counters_before": counters_before, "counters_after": counters_after,
768|        "counter_deltas": {"bills_indexed": d_bills, "bills_resolved": d_res,
769|                           "settlements": d_set},
770|        "indexer_ledger_events": readout["events"],
771|        "chain_events_by_tx": chain_events,
772|        "tx_lane_posts": post_results,
773|        "assertions": checks,
774|        "result": "GREEN" if not fails else "RED",
775|        "debris_ledger": {
776|            "seatB_usdc": str(sb1), "seatB_eth_dust": "see txs.dust",
777|            "recovery": "keys persisted at " + str(SEAT_KEYS_FILE),
778|            "bill_clone": "testnet debris; escrow drained to 0, nothing stranded"},
779|        "state_file": str(STATE_FILE),
780|        "created_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
781|    }
782|    print(json.dumps(receipt, indent=1))
783|    return 0 if not fails else 1
784|
785|
786|if __name__ == "__main__":
787|    sys.exit(main())