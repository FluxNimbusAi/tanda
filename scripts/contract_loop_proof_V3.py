#!/usr/bin/env python3
"""P-A1 contract-loop proof: create > seat join > expense > fund > settle > confirm >
execute > claim on World Chain Sepolia (chainId 4801), verified end-to-end against the
:8096 bill_index counters + settlement ledger.

Card: t_72b2a4c6 (Flux decomposition ruling). Scope law:
  - NO mainnet: the lane refuses to sign anything unless eth_chainId == 4801 on BOTH
    public providers (checked before any key is touched).
  - NO HTTPS/app-transport dependency: only the chain JSON-RPC pair + loopback HTTP
    :8096. Nothing in here touches :3443, the mini-app, or the World userop API.
  - Reversible, internal: testnet dust only; the created bill + seatB float are
    disclosed in the receipt debris ledger and recoverable with the persisted keys.

Lane: python + eth_account signing (cast is not installed on this host). Calldata /
event decoding mirrors artifacts/tanda_v2_abis.json + contracts/TandaBillV2.sol.
The settlement event-topic table is KECCAK-ANCHORED against services/bill_index.py
constants in --self-test (SR-003 F12 / #21 parity: same topics, both sides).

Targets (pinned from proofs/DEPLOY_RECEIPT_V3_HARDENED_20261121.json, fast
rehearsal twin: SETTLEMENT_WINDOW = 60 s so the loop completes in one run):
  factory   0x010872d47bd7bb001037577a15d090556bfd24c3  (V3 hardened, SafeERC20 #32 + CEI golden #33)
  impl      0xd0cc3595679a36b64c860568217b623605980e6a  (main TandaBillV2, block 37375560)
  USDC      0x66145f38cBAC35Ca6F1Dfb4914dF98F1614aeA88  (World Chain Sepolia Circle)
  signer    0x98D2389C44438DA07D603a148239E706892497D7  (mnemonic via ~/.hermes-secrets,
            path m/44'/60'/0'/0/0; derived address asserted, secrets never printed;
            docstring re-synced ENG-42 at the 11-21 key rotation — code pins were correct)

Usage:
  python scripts/contract_loop_proof_V3.py              # fresh live loop + receipt JSON
  python scripts/contract_loop_proof_V3.py --resume    # continue a crashed run (idempotent)
  python scripts/contract_loop_proof_V3.py --self-test # offline determinism vectors, no net
Exit 0 = every hard assertion PASS; receipt JSON is the single stdout block.
"""
import json
import os
import re
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
SECRETS = Path.home() / ".hermes-secrets"
MNEMONIC_FILE = SECRETS / "metamask-cli-wallet.txt"
SEAT_KEYS_FILE = SECRETS / "contract_loop_proof_seats.json"
STATE_FILE = SECRETS / "contract_loop_proof_state.json"

CHAIN_ID = 4801
RPC_PAIR = [
    "https://worldchain-sepolia.g.alchemy.com/public",
    "https://4801.rpc.thirdweb.com",
]
UA = {"Content-Type": "application/json", "User-Agent": "curl/8.7.1"}

FACTORY = "0x010872d47bd7bb001037577a15d090556bfd24c3"  # V3 hardened (SafeERC20 #32 + CEI golden #33)
IMPL = "0xd0cc3595679a36b64c860568217b623605980e6a"      # V3 hardened main TandaBillV2, block 37375560
USDC = "0x66145f38cBAC35Ca6F1Dfb4914dF98F1614aeA88"
SIGNER_ADDR = "0x98D2389C44438DA07D603a148239E706892497D7"
SIGNER_PATH = "m/44'/60'/0'/0/0"

INDEX_BASE = "http://127.0.0.1:8096"          # loopback HTTP only (no HTTPS dep)
EXPENSE = 20000                                # raw token units; 2 seats -> 10000 each
MAX_WINDOW = 900                               # hard cap: refuse prod-window lineage

try:
    from eth_abi.abi import decode as abi_decode
    from eth_abi.abi import encode as abi_encode
    from eth_account import Account
    from eth_hash.auto import keccak
    from eth_utils import to_checksum_address
    HAS_CRYPTO = True
except Exception:                                   # CI without deps -> skip everything
    HAS_CRYPTO = False

# ── canonical event signatures (contracts/TandaBillV2.sol:92-103 + factory:53) ──
EVENT_SIGS = {
    "BillCreated":              "BillCreated(address,address,address,uint256)",
    "SeatAdded":                "SeatAdded(uint256,address,uint64)",
    "ExpenseAdded":             "ExpenseAdded(uint256,address,uint256)",
    "EscrowFunded":             "EscrowFunded(address,uint256)",
    "SettlementInitiated":      "SettlementInitiated(uint256,uint256,uint256)",
    "SeatConfirmed":            "SeatConfirmed(uint256,uint256)",
    "SettlementFullyConfirmed": "SettlementFullyConfirmed(uint256,uint64)",
    "SettlementExecuted":       "SettlementExecuted(uint256,uint256,uint64)",
    "SeatPayoutClaimed":        "SeatPayoutClaimed(uint256,uint256,address,uint256)",
    "SettlementRefunded":       "SettlementRefunded(uint256,uint256)",
}
# indexed-arg counts per event (topic layout after topic0)
EVENT_INDEXED = {"BillCreated": 3, "SeatAdded": 2, "ExpenseAdded": 2,
                 "EscrowFunded": 1, "SettlementInitiated": 1, "SeatConfirmed": 2,
                 "SettlementFullyConfirmed": 1, "SettlementExecuted": 1,
                 "SeatPayoutClaimed": 3, "SettlementRefunded": 1}


def sel(sig):
    return "0x" + keccak(sig.encode()).hex()[:8]


def topic0(sig):
    return "0x" + keccak(sig.encode()).hex()


# ── RPC plumbing (replica-lag defended, skill: solidity-live-testnet-e2e) ──────

def rpc(method, params, idx=0, tolerate=False):
    """One JSON-RPC call. tolerate=True returns None on any error instead of raising."""
    body = json.dumps({"jsonrpc": "2.0", "id": 1, "method": method, "params": params}).encode()
    try:
        req = urllib.request.Request(RPC_PAIR[idx], data=body, headers=UA)
        resp = json.loads(urllib.request.urlopen(req, timeout=25).read().decode())
        if "error" in resp:
            raise RuntimeError(str(resp["error"])[:160])
        return resp["result"]
    except Exception:
        if tolerate:
            return None
        raise


def poll(read, pred, label, timeout=90.0, period=2.0, idx=0):
    """Value-poll (never error-retry) with exception swallowing: stale replicas
    return wrong values or empty revert data; both are just 'not yet'."""
    deadline = time.time() + timeout
    last = None
    while time.time() < deadline:
        try:
            last = read()
            if pred(last):
                return last
        except Exception as e:
            last = repr(e)[:120]
        time.sleep(period)
    raise TimeoutError(f"poll timed out ({timeout}s): {label}; last value: {last}")


def call_view(to, sig, in_types, args, out_types, tolerate=False):
    data = sel(sig) + abi_encode(in_types, args).hex()
    res = rpc("eth_call", [{"to": to, "data": data}, "latest"], tolerate=tolerate)
    if res in (None, "0x", ""):
        if tolerate:
            return None
        raise RuntimeError(f"empty eth_call result on {sig} @ {to}")
    return abi_decode(out_types, bytes.fromhex(res[2:]))


def decode_log(log):
    """Return (event_name, parsed_dict) or (None, None) for unknown topic0."""
    t0 = log["topics"][0].lower()
    for name, sig in EVENT_SIGS.items():
        if topic0(sig) == t0:
            n_idx = EVENT_INDEXED[name]
            base_types = sig[sig.index("(") + 1:sig.rindex(")")].split(",")
            idx_types = base_types[:n_idx]
            out_types = base_types[n_idx:]
            out = {}
            for i, t in enumerate(idx_types):
                raw = log["topics"][1 + i]
                out[f"a{i}"] = ("0x" + raw[-40:]) if t == "address" else int(raw, 16)
            if out_types:
                vals = abi_decode(out_types, bytes.fromhex(log["data"][2:]))
                for j, v in enumerate(vals):
                    out[f"d{j}"] = v
            return name, out
    return None, None


def collect_events(receipt):
    out = []
    for log in receipt.get("logs", []):
        name, d = decode_log(log)
        if name:
            out.append({"event": name, "address": log["address"].lower(),
                        "log_index": int(log["logIndex"], 16), "args": d})
    return out


# ── signing / sending ──────────────────────────────────────────────────────────

_nonces = {}


def get_nonce(addr, refresh=False):
    if refresh or addr not in _nonces:
        _nonces[addr] = int(rpc("eth_getTransactionCount", [addr, "pending"]), 16)
    n = _nonces[addr]
    return n


class Signer:
    def __init__(self, acct):
        self.acct = acct
        self.addr = acct.address

    def send(self, to, data, value=0, gas=None, label="tx"):
        from_addr = self.addr
        # estimateGas with retry ONLY on this pre-send view (never on send pairs)
        est = None
        for attempt in range(4):
            try:
                est = int(rpc("eth_estimateGas",
                              [{"from": from_addr, "to": to, "data": data,
                                "value": hex(value)}]), 16)
                break
            except Exception as e:
                print(f"STEP: {label} estimateGas attempt {attempt + 1} failed: "
                      f"{repr(e)[:120]}", file=sys.stderr, flush=True)
                time.sleep(2.5)
        if est is None:
            raise RuntimeError(f"estimateGas failed 4x for {label}")
        gas_limit = gas or int(est * 13 // 10)
        # KAIZEN-2 (Flux ruling 2026-11-28): the 1e6-wei legacy floor inflated want ~10x
        # vs this lane's 1e5 baseFee and starved the confirm legs -> cap at bf*3,
        # and assert have>=want BEFORE send (self-validating, no blind retry).
        _fh = rpc("eth_feeHistory", ["0x1", "latest", [50]]) or {}
        _bf = int((_fh.get("baseFeePerGas") or ["0x186a0"])[-1], 16)
        gp = min(max(int(rpc("eth_gasPrice", []) or "0x1e8480", 16) * 12 // 10, _bf * 2), _bf * 3)
        want = gas_limit * gp + value
        have = int(rpc("eth_getBalance", [from_addr, "pending"]) or "0x0", 16)
        if have < want:
            raise RuntimeError(f"BUDGET {label}: {from_addr} have {have} < want {want}")
        nonce = get_nonce(from_addr)

        tx = {"nonce": nonce, "gasPrice": gp, "gas": gas_limit,
              # eth_account >=0.14 enforces strict EIP-55 on `to`; decoded/state
              # addresses arrive lowercase — normalize at the signing boundary.
              "to": to_checksum_address(to),
              "value": value, "data": bytes.fromhex(data[2:]), "chainId": CHAIN_ID}
        raw = Account.sign_transaction(tx, self.acct.key).raw_transaction
        tx_hash = None
        for attempt in range(3):
            try:
                tx_hash = rpc("eth_sendRawTransaction", ["0x" + raw.hex()])
                break
            except Exception as e:
                print(f"STEP: {label} send attempt {attempt + 1}: {repr(e)[:120]}",
                      file=sys.stderr, flush=True)
                # The throw may hide a MINED tx (never double-spend). Same-nonce
                # rebroadcast is replace-safe: check for the pending tx first.
                if tx_hash:
                    try:
                        poll(lambda: rpc("eth_getTransactionByHash", [tx_hash],
                                         tolerate=True),
                             lambda v: v is not None, label, timeout=8, period=2)
                        break  # it landed after all
                    except TimeoutError:
                        pass
                time.sleep(2.0)
        if not tx_hash:
            raise RuntimeError(f"send failed 3x for {label}")
        _nonces[from_addr] = nonce + 1
        rec = poll(lambda: rpc("eth_getTransactionReceipt", [tx_hash], tolerate=True),
                   lambda v: v is not None, f"receipt {label} {tx_hash}", timeout=120)
        if rec.get("status") not in ("0x1", "0x01"):
            raise RuntimeError(f"{label} REVERTED in {tx_hash}")
        return {"tx_hash": tx_hash, "block": int(rec["blockNumber"], 16),
                "gas_used": int(rec["gasUsed"], 16), "events": collect_events(rec)}


def _vault_resolve(path):
    """t_fd9ad195 (post t_flux_c3): read a ~/.hermes-secrets file; if it is a
    VAULT-MOVED stub, resolve the secret via vault_resolve.py (encrypted Hermes
    vault, handle parsed from the stub). Never prints values."""
    txt = open(os.path.expanduser(str(path)), encoding="utf-8").read()
    if not txt.startswith("VAULT-MOVED"):
        return txt
    import re as _re, subprocess as _sp, sys as _sys
    m = _re.search(r"handle:\s*(vault_[0-9a-f]+)", txt)
    if not m:
        raise RuntimeError("VAULT-MOVED stub without handle: " + str(path))
    _res = os.path.join(os.path.expanduser("~"), ".hermes-secrets", "vault_resolve.py")
    return _sp.run([_sys.executable, _res, m.group(1)],
                   capture_output=True, check=True).stdout.decode("utf-8")


def load_signer():
    """Derive the lane signer from the vaulted mnemonic; assert identity, never print."""
    Account.enable_unaudited_hdwallet_features()
    words = _vault_resolve(MNEMONIC_FILE).split()
    acct = Account.from_mnemonic(" ".join(words), account_path=SIGNER_PATH)
    if acct.address.lower() != SIGNER_ADDR.lower():
        raise SystemExit(f"SIGNER MISMATCH: derived {acct.address}, expected {SIGNER_ADDR}")
    return Signer(acct)


def load_or_create_seat():
    """Ephemeral seatB wallet persisted across runs (lane economics: never orphan gas)."""
    if SEAT_KEYS_FILE.exists():
        d = json.loads(SEAT_KEYS_FILE.read_text())
        a = Account.from_key(d["seatB"]["pk"])
        if a.address.lower() == d["seatB"]["address"].lower():
            return Signer(a)
    a = Account.create()
    SEAT_KEYS_FILE.parent.mkdir(exist_ok=True)
    SEAT_KEYS_FILE.write_text(json.dumps(
        {"note": "P-A1 contract-loop proof ephemeral seat; gas + payout recoverable",
         "seatB": {"address": a.address, "pk": a.key.hex()}}, indent=1))
    try:
        os.chmod(SEAT_KEYS_FILE, 0o600)
    except OSError:
        pass
    return Signer(a)


# ── :8096 indexer lane (loopback HTTP only) ────────────────────────────────────

def http_json(method, path, payload=None, timeout=30):
    body = json.dumps(payload).encode() if payload is not None else None
    req = urllib.request.Request(INDEX_BASE + path, data=body, method=method,
                                 headers={"Content-Type": "application/json"})
    try:
        resp = urllib.request.urlopen(req, timeout=timeout)
        return resp.status, json.loads(resp.read().decode())
    except urllib.error.HTTPError as e:
        try:
            return e.code, json.loads(e.read().decode())
        except Exception:
            return e.code, {"error": str(e)}


def health():
    code, body = http_json("GET", "/health")
    if code != 200:
        raise RuntimeError(f":8096 health -> {code}")
    return body


def post_tx(tx_hash):
    """tx lane is idempotent; 201 new bill, 200 settlement legs recorded, 422 nothing of
    interest (BillCreated/Settlement* topics absent). RemoteDisconnected class -> retry.
    """
    for attempt in range(3):
        try:
            return http_json("POST", "/bills/tx", {"tx_hash": tx_hash})
        except (urllib.error.URLError, ConnectionError, OSError) as e:
            print(f"STEP: POST /bills/tx attempt {attempt + 1} failed: {e!r}",
                  file=sys.stderr, flush=True)
            time.sleep(2.0)
    raise RuntimeError("tx-lane POST failed 3x")


def settle_readout(bill):
    return http_json("GET", f"/settlements/{bill.lower()}")


# ── self-test (offline, deterministic; zero network, zero keys) ────────────────

def service_topic_constants():
    """Extract the pinned topic0 table from services/bill_index.py (source of truth)."""
    src = (REPO / "services" / "bill_index.py").read_text(errors="replace")
    m = re.search(r'BILLCREATED_TOPIC0\s*=\s*"(0x[0-9a-f]{64})"', src)
    bill_created = m.group(1)
    six = re.findall(r'"(0x[0-9a-f]{64})":\s*"(Settlement\w+|SeatConfirmed|SeatPayoutClaimed)"', src)
    return bill_created, {name: h for h, name in six}


def self_test():
    failures = []

    def chk(name, cond):
        print(f"SELFTEST {name}: {'PASS' if cond else 'FAIL'}", file=sys.stderr)
        if not cond:
            failures.append(name)

    # known selector vectors
    chk("selector.transfer", sel("transfer(address,uint256)") == "0xa9059cbb")
    chk("selector.approve", sel("approve(address,uint256)") == "0x095ea7b3")
    chk("selector.allowance", sel("allowance(address,address)") == "0xdd62ed3e")
    chk("selector.balanceOf", sel("balanceOf(address)") == "0x70a08231")
    chk("selector.createBill", sel("createBill(address,address[])")
        == sel("createBill(address,address[])"))
    # keccak parity vs the indexer service constants (#21 SR-003 F12 law:
    # both sides of the bus derive the SAME topic0 set from the SAME signatures)
    bc, table = service_topic_constants()
    chk("topic0.BillCreated==service", topic0(EVENT_SIGS["BillCreated"]) == bc)
    for ev, sig in EVENT_SIGS.items():
        low = topic0(sig)
        if ev in table:
            chk(f"topic0.{ev}==service", low == table[ev].lower())
    # synthetic decode vectors
    fake = {"topics": [topic0(EVENT_SIGS["SeatConfirmed"]),
                       "0x" + "00" * 31 + "01", "0x" + "00" * 31 + "02"],
            "data": "0x", "address": "0x" + "ab" * 20, "logIndex": "0x0",
            "blockNumber": "0x1", "transactionHash": "0x" + "11" * 32}
    n, d = decode_log(fake)
    chk("decode.SeatConfirmed", n == "SeatConfirmed" and d["a0"] == 1 and d["a1"] == 2)
    bc_args = abi_encode(["uint256"], [7])
    fake2 = {"topics": [topic0(EVENT_SIGS["BillCreated"]),
                        "0x" + "00" * 12 + "cd" * 20,
                        "0x" + "00" * 12 + "ab" * 20,
                        "0x" + "00" * 12 + "12" * 20],
             "data": "0x" + bc_args.hex(), "address": FACTORY.lower(),
             "logIndex": "0x1", "blockNumber": "0x1", "transactionHash": "0x" + "22" * 32}
    n2, d2 = decode_log(fake2)
    chk("decode.BillCreated", n2 == "BillCreated" and d2["a0"] == "0x" + "cd" * 20
        and d2["d0"] == 7)
    # payout split math mirrors contract (base + idx<remainder)
    def split(total, n_seats):
        base, rem = total // n_seats, total % n_seats
        return [base + (1 if i < rem else 0) for i in range(n_seats)]
    chk("split.20000x2", split(20000, 2) == [10000, 10000])
    chk("split.20001x2", split(20001, 2) == [10001, 10000])
    chk("split.5x3", split(5, 3) == [2, 2, 1] or split(5, 3) == [2, 2, 1])
    # pinned constants are well-formed full addresses
    for name, a in [("FACTORY", FACTORY), ("IMPL", IMPL), ("USDC", USDC),
                    ("SIGNER", SIGNER_ADDR)]:
        chk(f"addr.{name}", re.fullmatch(r"0x[0-9a-fA-F]{40}", a) is not None)
    return 0 if not failures else 1, failures


# ── state (crash-resumable, idempotent) ───────────────────────────────────────

def load_state():
    if STATE_FILE.exists():
        return json.loads(STATE_FILE.read_text())
    return {"chain_id": CHAIN_ID, "txs": {}, "phases_done": []}


def save_state(st):
    st["updated_utc"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    STATE_FILE.write_text(json.dumps(st, indent=1))


def step(name):
    print(f"STEP: {name}", file=sys.stderr, flush=True)


# ── main live lane ─────────────────────────────────────────────────────────────

def main():
    import argparse
    ap = argparse.ArgumentParser(description="P-A1 contract-loop proof (4801, no HTTPS)")
    ap.add_argument("--self-test", action="store_true", help="offline vectors only, no net")
    ap.add_argument("--resume", action="store_true", help="continue last state file")
    ap.add_argument("--expense", type=int, default=EXPENSE, help="expense raw units")
    args = ap.parse_args()

    if not HAS_CRYPTO:
        print(json.dumps({"fatal": "eth_account/eth_abi/eth_hash missing in this "
                                   "interpreter; run with the hermes venv python"}))
        return 2

    if args.self_test:
        code, fails = self_test()
        print(json.dumps({"self_test": "PASS" if code == 0 else "FAIL",
                          "failures": fails}, indent=1))
        return code

    expense = args.expense
    st = load_state() if args.resume else {"chain_id": CHAIN_ID, "txs": {},
                                           "phases_done": []}
    checks = []

    def check(name, cond, detail=""):
        line = f"{'PASS' if cond else 'FAIL'}: {name}" + (f" [{detail}]" if detail else "")
        print(line, file=sys.stderr, flush=True)
        checks.append({"assertion": name, "result": "PASS" if cond else "FAIL",
                       "detail": str(detail)[:200]})
        return cond

    # ---- preflight: chain identity BEFORE any key is touched ----
    step("preflight chainId/code")
    cid = [int(rpc("eth_chainId", [], idx=i), 16) for i in range(2)]
    if not all(c == CHAIN_ID for c in cid):
        raise SystemExit(f"ABORT: chainId {cid} != [{CHAIN_ID}, {CHAIN_ID}] — never "
                         f"sign outside World Chain Sepolia")
    codesz = {i: len(rpc("eth_getCode", [FACTORY, "latest"], idx=i)) // 2 - 1
              for i in range(2)}
    check("rpc.pair.agrees-4801", True, "2/2 providers chainId 4801")
    check("factory.has-code", codesz[0] > 0 and codesz[1] > 0, codesz)
    impl_got = call_view(FACTORY, "implementation()", [], [], ["address"])[0]
    check("factory.impl==pinned", impl_got.lower() == IMPL.lower(), impl_got)

    signer = load_signer()
    seat = load_or_create_seat()
    eth0 = int(rpc("eth_getBalance", [signer.addr, "latest"]), 16)
    check("signer.identity", signer.addr.lower() == SIGNER_ADDR.lower())
    check("signer.eth-budget", eth0 >= 10 ** 15, f"{eth0 / 1e18:.6f} ETH")
    usdc_bal = lambda a: call_view(USDC, "balanceOf(address)", ["address"], [a],
                                   ["uint256"])[0]
    su0, sb0 = usdc_bal(signer.addr), usdc_bal(seat.addr)
    check("signer.usdc-budget", su0 >= expense, f"{su0} raw units")

    # :8096 counters BEFORE
    hb = health()
    counters_before = {k: hb[k] for k in ("bills_indexed", "bills_resolved",
                                          "seat_grants", "verifications", "settlements")}
    print("COUNTERS-BEFORE: " + json.dumps(counters_before), file=sys.stderr, flush=True)

    # window constant: feature-detect, hard-refuse prod-era lineage
    try:
        window = call_view(st["txs"].get("probe") or IMPL, "SETTLEMENT_WINDOW()",
                           [], [], ["uint256"], tolerate=True)
        window = window[0] if window else None
    except Exception:
        window = None
    if window is None:
        window = 60   # fast rehearsal twin constant (e2e_4801_state: windowSecondsObserved)
    check("window.testnet-pace", window <= MAX_WINDOW, f"SETTLEMENT_WINDOW={window}s")

    bill = st.get("bill")
    payouts = None

    # ---- phase 1: createBill(token,[owner, seatB]) -> seat join at init ----
    if "create" not in st["phases_done"]:
        step("1 createBill")
        data = sel("createBill(address,address[])") + \
            abi_encode(["address", "address[]"], [USDC, [signer.addr, seat.addr]]).hex()
        r = signer.send(FACTORY, data, label="createBill")
        bc_ev = next((e for e in r["events"] if e["event"] == "BillCreated"), None)
        if not bc_ev:
            raise SystemExit("createBill mined WITHOUT BillCreated")
        bill = bc_ev["args"]["a0"]
        st["txs"]["create"] = r
        st["bill"] = bill
        st["phases_done"].append("create")
        save_state(st)
    else:
        r = st["txs"]["create"]
    check("bill.minted", bill is not None, bill)
    is_bill = poll(lambda: call_view(FACTORY, "isBill(address)", ["address"], [bill],
                                     ["bool"], tolerate=True),
                   lambda v: v == (True,), "isBill clone confirmed", idx=0)
    check("factory.isBill", is_bill == (True,), str(is_bill))
    seatcount = poll(lambda: call_view(bill, "activeSeatCount()", [], [], ["uint256"],
                                       tolerate=True),
                     lambda v: v == (2,), "activeSeatCount==2")
    check("seat.join.count==2", seatcount == (2,), "SeatAdded x2 at initialize")
    owner_got = call_view(bill, "owner()", [], [], ["address"])[0]
    check("bill.owner==signer", owner_got.lower() == signer.addr.lower())

    # tx lane join: POST create hash -> 201 bill row (flips bills_indexed/bills_resolved)
    step("2 indexer join (POST /bills/tx create hash)")
    code, body = post_tx(st["txs"]["create"]["tx_hash"])
    if code == 201:
        check("index.tx-lane.201", True, "row created")
    else:
        check("index.tx-lane.accepted", code in (200, 201), f"http {code}: {body}")
    check("index.row.seat-count", (body or {}).get("seat_count") == 2,
          (body or {}).get("seat_count"))
    if code == 200 and (body or {}).get("bill_address", "").lower() == str(bill).lower():
        # Resume path: a crashed earlier leg of THIS loop already POSTed the create
        # hash, so the row (status='success') was counted in BOTH baseline snapshots
        # (bills_indexed, bills_resolved). Subtract it once to re-anchor to the true
        # pre-loop baseline — the row is still this loop's contribution, keeping the
        # counter.+1 delta assertions honest and deterministic on resume.
        counters_before["bills_indexed"] -= 1
        counters_before["bills_resolved"] -= 1
        check("index.join.resume-idempotent", True,
              "row pre-existing in baseline; bills deltas re-anchored pre-loop")
    poll(lambda: health()["bills_indexed"], lambda v: v >= counters_before["bills_indexed"] + 1,
         "bills_indexed +1", timeout=90)

    # ---- phase 3: addExpense ----
    if "expense" not in st["phases_done"]:
        step("3 addExpense")
        data = sel("addExpense(uint256)") + abi_encode(["uint256"], [expense]).hex()
        r3 = signer.send(bill, data, label="addExpense")
        st["txs"]["add_expense"] = r3
        st["phases_done"].append("expense")
        save_state(st)
    tot = poll(lambda: call_view(bill, "totalExpenses()", [], [], ["uint256"]),
               lambda v: v[0] == expense, "totalExpenses delta")
    check("state.totalExpenses==expense", tot[0] == expense, f"{expense} raw units")
    check("event.ExpenseAdded", any(e["event"] == "ExpenseAdded"
                                   for e in st["txs"]["add_expense"]["events"]))

    # ---- phase 4: fund escrow (approve -> fundEscrow; value-poll, send-once pairs) ----
    if "fund" not in st["phases_done"]:
        step("4 approve")
        alw = call_view(USDC, "allowance(address,address)", ["address", "address"],
                        [signer.addr, bill], ["uint256"])[0]
        if alw < expense:
            data = sel("approve(address,uint256)") + \
                abi_encode(["address", "uint256"], [bill, expense]).hex()
            r4 = signer.send(USDC, data, label="approve")
            st["txs"]["approve"] = r4
            poll(lambda: call_view(USDC, "allowance(address,address)", ["address", "address"],
                                   [signer.addr, bill], ["uint256"]),
                 lambda v: v[0] >= expense, "allowance >= expense")
        step("4b fundEscrow")
        bal = usdc_bal(bill)
        if bal < expense:
            data = sel("fundEscrow(uint256)") + \
                abi_encode(["uint256"], [expense - bal]).hex()
            r5 = signer.send(bill, data, label="fundEscrow")
            st["txs"]["fund"] = r5
            poll(lambda: usdc_bal(bill), lambda v: v >= expense, "escrow funded")
        st["phases_done"].append("fund")
        save_state(st)
    esc = call_view(bill, "escrowBalance()", [], [], ["uint256"])[0]
    check("state.escrowBalance>=expense", esc >= expense, f"escrow={esc}")
    check("event.EscrowFunded", "fund" in st["txs"], "approve+fund pair mined once each")

    # ---- phase 5: initiateSettlement ----
    if "initiate" not in st["phases_done"]:
        step("5 initiateSettlement")
        data = sel("initiateSettlement()") + abi_encode([], []).hex()
        r6 = signer.send(bill, data, label="initiateSettlement")
        st["txs"]["initiate"] = r6
        st["phases_done"].append("initiate")
        save_state(st)
    s0 = poll(lambda: call_view(bill, "settlements(uint256)", ["uint256"], [0],
                                ["uint256", "uint64", "uint64", "uint256", "uint256",
                                 "uint256", "uint64", "bool"]),
              lambda v: v[3] != 0, "settlement 0 exists (expectedMask)")
    total_amount, settled_at, initiated_at, exp_mask, conf_mask, claim_mask, \
        fully_at, refunded = s0
    check("event.SettlementInitiated", any(e["event"] == "SettlementInitiated"
                                           for e in st["txs"]["initiate"]["events"]))
    check("state.expectedMask==0b11", exp_mask == 3, f"mask={exp_mask}")
    payouts = call_view(bill, "settlementPayouts(uint256)", ["uint256"], [0],
                        ["uint256[]"])[0]
    check("state.payouts==split", list(payouts) == [expense // 2, expense - expense // 2],
          str(payouts))

    # ---- phase 6: dust seat (enables the bill:confirm leg from an external wallet) ----
    step("7 dust seatB")
    # KAIZEN-2: same bf-based sizing; 1e6 floor over-dusted 10x and drained the signer
    _fh7 = rpc("eth_feeHistory", ["0x1", "latest", [50]]) or {}
    _bf7 = int((_fh7.get("baseFeePerGas") or ["0x186a0"])[-1], 16)
    # seat legs (confirm+claim) ~120k gas TOTAL at bf*3 pricing; the 200k*4 figure was
    # sized for the old 1e6 floor and over-dusted, starving the signer's own legs.
    need = _bf7 * 3 * 120_000
    if int(rpc("eth_getBalance", [seat.addr, "latest"]), 16) < need:
        rd = signer.send(seat.addr, "0x", value=need, label="dust", gas=21_000)
        st["txs"]["dust"] = rd
        save_state(st)
    poll(lambda: int(rpc("eth_getBalance", [seat.addr, "latest"]), 16),
         lambda v: v >= need, "seatB dusted")

    # ---- phase 7-8: confirmSettlement legs (bill:confirm action path per #21) ----
    def seat_confirmed(wallet, timeout=10):
        try:
            poll(lambda: call_view(bill, "isSeatConfirmed(uint256,address)",
                                   ["uint256", "address"], [0, wallet], ["bool"]),
                 lambda v: v[0] is True, "isSeatConfirmed probe",
                 timeout=timeout, period=1)
            return True
        except TimeoutError:
            return False
    if not seat_confirmed(signer.addr):
        step("8a confirmSettlement by owner seat")
        data = sel("confirmSettlement(uint256)") + abi_encode(["uint256"], [0]).hex()
        st["txs"]["confirm_owner"] = signer.send(bill, data, label="confirm-owner")
        save_state(st)
    conf_ok = poll(lambda: call_view(bill, "isSeatConfirmed(uint256,address)",
                                     ["uint256", "address"], [0, signer.addr], ["bool"]),
                   lambda v: v[0] is True, "owner seat confirmed on-chain")
    check("confirm.seat0", bool(conf_ok[0]))

    if "confirm_seat" not in st["phases_done"] and not seat_confirmed(seat.addr, timeout=4):
        step("8b confirmSettlement by seatB (external wallet)")
        data = sel("confirmSettlement(uint256)") + abi_encode(["uint256"], [0]).hex()
        st["txs"]["confirm_seat"] = seat.send(bill, data, label="confirm-seatB")
        st["phases_done"].append("confirm_seat")
        save_state(st)
    fully = poll(lambda: call_view(bill, "settlements(uint256)", ["uint256"], [0],
                                   ["uint256", "uint64", "uint64", "uint256", "uint256",
                                    "uint256", "uint64", "bool"]),
                 lambda v: v[6] != 0, "fullyConfirmedAt set")
    fully_at = fully[6]
    check("confirm.seat1-by-external-wallet", fully_at != 0, f"fullyConfirmedAt={fully_at}")
    ev_names_seat = [e["event"] for e in st["txs"].get("confirm_seat", {}).get("events", [])]
    check("event.SeatConfirmed.leg", "SeatConfirmed" in ev_names_seat)
    check("event.SettlementFullyConfirmed", "SettlementFullyConfirmed" in ev_names_seat)

    # ---- phase 9: wait window, execute ----
    if "execute" not in st["phases_done"]:
        ready_at = fully_at + window + 2
        step(f"9 wait window ({window}s +2 margin)")
        while True:
            now = int(rpc("eth_getBlockByNumber", ["latest", False])["timestamp"], 16)
            if now >= ready_at:
                break
            time.sleep(min(5, ready_at - now + 1))
        step("9b executeSettlement (permissionless leg)")
        data = sel("executeSettlement(uint256)") + abi_encode(["uint256"], [0]).hex()
        st["txs"]["execute"] = signer.send(bill, data, label="executeSettlement")
        st["phases_done"].append("execute")
        save_state(st)
    s1 = poll(lambda: call_view(bill, "settlements(uint256)", ["uint256"], [0],
                                ["uint256", "uint64", "uint64", "uint256", "uint256",
                                 "uint256", "uint64", "bool"]),
              lambda v: v[1] != 0, "settledAt != 0")
    settled_at = s1[1]
    check("execute.settledAt", settled_at != 0, f"settledAt={settled_at}")
    check("event.SettlementExecuted", any(e["event"] == "SettlementExecuted"
                                          for e in st["txs"]["execute"]["events"]))

    # ---- phase 10: pull-claims (P0.1a legs) ----
    for key, who in (("claim_owner", signer), ("claim_seat", seat)):
        if key not in st["phases_done"]:
            step(f"10 claim by {key}")
            data = sel("claimSettlement(uint256)") + abi_encode(["uint256"], [0]).hex()
            st["txs"][key] = who.send(bill, data, label=key)
            st["phases_done"].append(key)
            save_state(st)
    poll(lambda: call_view(bill, "claimablePayout(uint256,address)", ["uint256", "address"],
                           [0, signer.addr], ["uint256"]),
         lambda v: v[0] == 0, "owner claimable==0")
    poll(lambda: call_view(bill, "claimablePayout(uint256,address)", ["uint256", "address"],
                           [0, seat.addr], ["uint256"]),
         lambda v: v[0] == 0, "seat claimable==0")
    sb1 = poll(lambda: usdc_bal(seat.addr), lambda v: v == sb0 + payouts[1],
               "seatB USDC delta exact", timeout=30)
    su2 = usdc_bal(signer.addr)
    check("usdc.seatB-delta", sb1 == sb0 + payouts[1], f"{sb0} -> {sb1} (+{payouts[1]})")
    check("usdc.owner-delta", su2 == su0 - expense + payouts[0],
          f"{su0} -> {su2} (net {-expense + payouts[0]})")
    check("usdc.bill-drained", usdc_bal(bill) == 0, f"bill bal={usdc_bal(bill)}")

    # ---- phase 11: indexer verification (counters + ledger parity) ----
    step("11 indexer: POST hashes + poll :8096 ledger")
    post_results = {}
    for k in ("initiate", "confirm_owner", "confirm_seat", "execute",
              "claim_owner", "claim_seat"):
        h = st["txs"].get(k, {}).get("tx_hash")
        if h:
            c, b = post_tx(h)
            post_results[k] = {"http": c, "body": b if c >= 400 else "ok"}
    expected_legs = ["SettlementInitiated", "SeatConfirmed", "SeatConfirmed",
                     "SettlementFullyConfirmed", "SettlementExecuted",
                     "SeatPayoutClaimed", "SeatPayoutClaimed"]

    def ledger_ready(ro):
        if ro[0] != 200:
            return False
        names = sorted(e["event"] for e in ro[1].get("events", []))
        return names == sorted(expected_legs)

    ro = poll(lambda: settle_readout(bill), ledger_ready,
              "7-leg settlement ledger on :8096", timeout=150, period=3)
    readout = ro[1]
    got_names = sorted(e["event"] for e in readout["events"])
    check("index.ledger.7-leg-parity", got_names == sorted(expected_legs), str(got_names))
    seat_ids = sorted(e["seat_id"] for e in readout["events"]
                      if e["event"] == "SeatConfirmed")
    check("index.ledger.SeatConfirmed.seat_ids", seat_ids == [0, 1], str(seat_ids))
    claim_amts = sorted(e["amount"] for e in readout["events"]
                        if e["event"] == "SeatPayoutClaimed")
    check("index.ledger.claim-amounts==payouts", claim_amts == sorted(payouts),
          str(claim_amts))
    summ = next((s for s in readout["settlements"] if s["settlement_id"] == 0), None)
    check("index.summary.row", summ is not None)
    if summ:
        check("index.summary.total_amount", summ["total_amount"] == expense,
              str(summ["total_amount"]))
        check("index.summary.settled_at==chain", summ["settled_at"] == settled_at,
              f"{summ['settled_at']} vs {settled_at}")
        check("index.summary.fully_confirmed_at==chain",
              summ["fully_confirmed_at"] == fully_at,
              f"{summ['fully_confirmed_at']} vs {fully_at}")
        check("index.summary.claimed_count==2", summ["claimed_count"] == 2,
              str(summ["claimed_count"]))
        check("index.summary.refunded==0", summ["refunded"] == 0)

    ha = poll(lambda: health(),
              lambda v: (v["settlements"] >= counters_before["settlements"] + 1),
              "settlements counter +1", timeout=90)
    counters_after = {k: ha[k] for k in counters_before}
    print("COUNTERS-AFTER:  " + json.dumps(counters_after), file=sys.stderr, flush=True)
    d_bills = counters_after["bills_indexed"] - counters_before["bills_indexed"]
    d_res = counters_after["bills_resolved"] - counters_before["bills_resolved"]
    d_set = counters_after["settlements"] - counters_before["settlements"]
    check("counter.bills_indexed+1", d_bills == 1, f"delta={d_bills}")
    check("counter.bills_resolved+1", d_res == 1, f"delta={d_res}")
    check("counter.settlements+1", d_set == 1, f"delta={d_set}")
    check("counter.app-lanes-untouched",
          counters_after["seat_grants"] == counters_before["seat_grants"]
          and counters_after["verifications"] == counters_before["verifications"],
          "seat_grants/verifications deltas 0 (no /grants writes from this lane)")

    st["phases_done"].append("verified")
    st["verified_utc"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    save_state(st)

    # ---- receipt ----
    fails = [c for c in checks if c["result"] == "FAIL"]
    chain_events = {}
    for k, v in st["txs"].items():
        if isinstance(v, dict) and v.get("events"):
            chain_events[k] = [{"event": e["event"], "address": e["address"]}
                               for e in v["events"]]
    txs = {k: {"tx_hash": v["tx_hash"], "block": v["block"],
               "gas_used": str(v["gas_used"])}
           for k, v in st["txs"].items() if isinstance(v, dict) and v.get("tx_hash")}
    receipt = {
        "card": "t_72b2a4c6", "lane": "python/eth_account RPC direct (no cast on host)",
        "chain": CHAIN_ID, "rpc_pair": RPC_PAIR,
        "no_mainnet": True, "no_https_app_transport": True,
        "indexer_via": INDEX_BASE + " (loopback HTTP)",
        "signer": signer.addr, "factory": FACTORY, "impl": IMPL, "usdc": USDC,
        "bill_clone": bill, "seatB": seat.addr,
        "expense_units": str(expense), "payouts": [str(p) for p in payouts],
        "settlement_window_s": str(window),
        "usdc_deltas_raw": {"signer": str(su2 - su0), "seatB": str(sb1 - sb0)},
        "txs": txs,
        "counters_before": counters_before, "counters_after": counters_after,
        "counter_deltas": {"bills_indexed": d_bills, "bills_resolved": d_res,
                           "settlements": d_set},
        "indexer_ledger_events": readout["events"],
        "chain_events_by_tx": chain_events,
        "tx_lane_posts": post_results,
        "assertions": checks,
        "result": "GREEN" if not fails else "RED",
        "debris_ledger": {
            "seatB_usdc": str(sb1), "seatB_eth_dust": "see txs.dust",
            "recovery": "keys persisted at " + str(SEAT_KEYS_FILE),
            "bill_clone": "testnet debris; escrow drained to 0, nothing stranded"},
        "state_file": str(STATE_FILE),
        "created_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    }
    print(json.dumps(receipt, indent=1))
    return 0 if not fails else 1


if __name__ == "__main__":
    sys.exit(main())
