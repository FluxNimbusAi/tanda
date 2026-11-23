# Deploy hardened TandaBillV2 impl + factory to World Chain Sepolia 4801.
# Signer derived from mnemonic file via eth_account (never printed); assert vs known SIGNER_ADDR first.
# forge build artifacts supply bytecode. Receipt JSON (addresses + tx hashes only) written to proofs/.
import json, os, sys, time, urllib.request
from pathlib import Path

SECRETS = Path.home() / ".hermes-secrets"
MNEMONIC_FILE = SECRETS / "metamask-cli-wallet.txt"
SIGNER_PATH = "m/44'/60'/0'/0/0"
SIGNER_ADDR = "0x98D2389C44438DA07D603a148239E706892497D7"
RPC = "https://worldchain-sepolia.g.alchemy.com/public"
USDC = "0x66145f38cBAC35Ca6F1Dfb4914dF98F1614aeA88"
REPO = Path("C:/Users/dbvis/agent-bench/tanda-sync")

from eth_account import Account
from eth_account.signers.local import LocalAccount
import rlp

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


words = _vault_resolve(MNEMONIC_FILE).split()
assert len(words) >= 12, "mnemonic file format unexpected"
Account.enable_unaudited_hdwallet_features()
acct: LocalAccount = Account.from_mnemonic(" ".join(words), account_path=SIGNER_PATH)
assert acct.address.lower() == SIGNER_ADDR.lower(), f"signer mismatch: {acct.address}"

_id = [0]
def rpc(method, params):
    _id[0] += 1
    body = json.dumps({"jsonrpc": "2.0", "id": _id[0], "method": method, "params": params}).encode()
    req = urllib.request.Request(RPC, data=body, headers={"content-type": "application/json"})
    for attempt in range(3):
        try:
            with urllib.request.urlopen(req, timeout=30) as r:
                j = json.loads(r.read())
            if "error" in j: raise RuntimeError(j["error"])
            return j["result"]
        except Exception:
            if attempt == 2: raise
            time.sleep(3)

cid = int(rpc("eth_chainId", []), 16)
assert cid == 4801, f"wrong chain {cid}"
bal = int(rpc("eth_getBalance", [acct.address, "latest"]), 16)
print("chain 4801 OK | signer balance(eth):", bal / 1e18)
assert bal > 10**15, "insufficient testnet ETH"

def load_artifact(name):
    d = json.loads((REPO / "out" / (name + ".sol") / (name + ".json")).read_text(encoding="utf-8"))
    bc = d["bytecode"]["object"]
    return ("0x" * 0 + bc if bc.startswith("0x") else "0x" + bc), d["abi"]

impl_code, impl_abi = load_artifact("TandaBillV2")
fac_code, fac_abi = load_artifact("TandaBillFactory")

nonce = int(rpc("eth_getTransactionCount", [acct.address, "latest"]), 16)
gp = rpc("eth_feeHistory", ["0x5", "latest", [50]])
base = int(rpc("eth_getBlockByNumber", ["latest", False])["baseFeePerGas"], 16)
prio = max(int(gp["baseFeePerGas"][-1], 16) // 10, 10**6)

def send(to, data):
    global nonce
    tx = {
        "chainId": 4801, "nonce": nonce,
        "maxPriorityFeePerGas": prio, "maxFeePerGas": base * 2 + prio,
        "gas": int(rpc("eth_estimateGas", [{"from": acct.address, "to": to, "data": data} if to else {"from": acct.address, "data": data}]), 16) * 13 // 10 + 20000,
        "value": 0, "data": data, "type": "0x02", "accessList": [],
        "to": to,
    }
    signed = acct.sign_transaction(tx)
    raw = signed.raw_transaction
    h = rpc("eth_sendRawTransaction", ["0x" + raw.hex()])
    nonce += 1
    for _ in range(60):
        r = rpc("eth_getTransactionReceipt", [h])
        if r: break
        time.sleep(2)
    assert r and int(r["status"], 16) == 1, f"tx reverted {h}"
    return h, r

from eth_abi.abi import encode as abi_encode
from eth_hash.auto import keccak
def ctor(code, args_types=(), args=()):
    data = code + (abi_encode(args_types, args).hex() if args_types else "")
    return send(None, data)

h1, r1 = ctor(impl_code)
impl = r1["contractAddress"]
h2, r2 = ctor(fac_code, ("address",), (impl,))
factory = r2["contractAddress"]

# verify lineage: factory.implementation() == impl
sel = keccak(b"implementation()")[:4].hex()
raw_res = rpc("eth_call", [{"to": factory, "data": "0x" + sel}, "latest"])
got = "0x" + raw_res[2:].zfill(64)[24:]  # last 20 bytes of the 32-byte word
assert got.lower() == impl.lower(), f"lineage mismatch {got} != {impl}"

receipt = {"deployed_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
           "chain_id": 4801, "impl": impl, "factory": factory,
           "tx_impl": r1["transactionHash"], "tx_factory": r2["transactionHash"],
           "source_main_sha": os.popen("git -C C:/Users/dbvis/agent-bench/tanda-sync rev-parse HEAD").read().strip(),
           "contract_blob": "SafeERC20Minimal-hardened (51de25aee + 0e3966dc9 era main)",
           "usdc": USDC, "signer_verified": SIGNER_ADDR}
out = REPO / "proofs" / f"DEPLOY_RECEIPT_V3_HARDENED_{time.strftime('%Y%m%d')}.json"
out.write_text(json.dumps(receipt, indent=2), encoding="utf-8")
print(json.dumps(receipt, indent=1))
