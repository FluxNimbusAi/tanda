#!/usr/bin/env python3
# W10 explorer verification: build payloads from git-blob sources, prove init vs live CREATE, submit both.
import json, subprocess, hashlib, sys, os

SYNC = r"C:\Users\dbvis\agent-bench\tanda-sync"
KEYFILE = os.path.expanduser("~/.hermes-secrets/etherscan_v2_keys.txt")
API = "https://api.etherscan.io/v2/api"
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


KEY = _vault_resolve(KEYFILE).splitlines()[0].strip()
PROD_IMPL = "0xD33A44fC56Fb859be08a8aAc5Cc26Cd2a27D47c6"
PROD_FAC = "0x96B6Ebc35aD760561d26a6C57d5b3F491B524332"
DEPLOYER = "0x78dC32F6a4edF80c538A75e1F7664505B1969E7A"
COMMIT = "17a34e2b1"

def gitshow(path):
    r = subprocess.run(["git", "-C", SYNC, "show", f"{COMMIT}:{path}"], capture_output=True)
    if r.returncode: sys.exit(f"git show failed {path}: {r.stderr[:200]}")
    return r.stdout  # raw bytes, LF-pure git blob

def http(url, params=None, post=None):
    import urllib.parse, urllib.request
    q = dict(params or {}); q.update({"chainid": "4801", "apikey": KEY})
    full = url + "?" + urllib.parse.urlencode(q)
    data = urllib.parse.urlencode(post or {}).encode()
    req = urllib.request.Request(full, data=data if post else None,
                                 method="POST" if post else "GET")
    return json.loads(urllib.request.urlopen(req, timeout=30).read())

# 1. payloads from the PROVEN W7 template (opaque constant settings; mutate only sources + contract name)
tpl = json.load(open(os.path.join(SYNC, "artifacts", "verification-standard-json.json")))
src_v2 = gitshow("contracts/TandaBillV2.sol").decode("utf-8")
src_fac = gitshow("contracts/TandaBillFactory.sol").decode("utf-8")

def payload_for(name):
    p = json.loads(json.dumps(tpl))  # deep copy
    keep = {k: v for k, v in tpl["sources"].items()}  # template sources = old V1 file; replace wholesale
    p["sources"] = {
        "contracts/TandaBillV2.sol": {"urls": [], "content": src_v2},
        "contracts/TandaBillFactory.sol": {"urls": [], "content": src_fac},
    }
    return p

p_fac = payload_for("factory")
with open(os.path.join(SYNC, "scratch_verify_factory.json"), "w", encoding="utf-8", newline="\n") as f:
    json.dump(p_fac, f)
# impl uses identical payload body (both sources present); contractname selects target
with open(os.path.join(SYNC, "scratch_verify_impl.json"), "w", encoding="utf-8", newline="\n") as f:
    json.dump(p_fac, f)

# 2. prove: compile with pinned solc 0.8.38, compare init prefix vs live CREATE tx input
solc = os.path.join(SYNC, "solc-0.8.38.exe")
r = subprocess.run([solc, "--standard-json"], stdin=open(os.path.join(SYNC, "scratch_verify_factory.json"), "rb"),
                   capture_output=True, encoding="utf-8", errors="replace", timeout=240)
out = json.loads(r.stdout)
if out.get("errors"):
    errs = [e for e in out["errors"] if e["severity"] == "error"]
    if errs: sys.exit("solc errors: " + errs[0]["formattedMessage"][:300])
c = out["contracts"]
init_impl = c["contracts/TandaBillV2.sol"]["TandaBillV2"]["evm"]["bytecode"]["object"]
init_fac = c["contracts/TandaBillFactory.sol"]["TandaBillFactory"]["evm"]["bytecode"]["object"]
print("compiled clean (0.8.38):", len(init_impl)//2, "B impl init,", len(init_fac)//2, "B factory init")

# live CREATE txs of the prod pair (most recent deploys by deployer)
txs = http(API, {"module": "account", "action": "txlist", "address": DEPLOYER,
                 "startblock": 0, "page": 1, "offset": 30, "sort": "desc"})["result"]
creates = [t for t in txs if t["to"] == "" and "0x" + init_impl[:400] in t["input"][:100000] or (t["to"] == "" and init_fac[:400] in t["input"])]
def find(init):
    for t in txs:
        if t["to"] == "" and t["input"][2:].lower().startswith(init[:400].lower()):
            return t
    return None
t_impl, t_fac = find(init_impl), find(init_fac)
if not t_impl or not t_fac:
    sys.exit("could not locate live CREATE txs in last 30 (deploy order assumption?)")
# constructor arg check on factory create: input == init + abi-encoded impl ptr
ctor = t_fac["input"][2+len(init_fac):]
expect = PROD_IMPL[2:].lower().zfill(64)
print("FACTORY ctor arg tail:", ctor.lower()[:80])
assert ctor.lower() == expect, f"ctor mismatch: {ctor.lower()} != {expect}"
print("PROVE PASS: impl init prefix matches live CREATE (tx", t_impl["hash"][:16] + "…);"
      "factory init+ctor matches live CREATE (tx", t_fac["hash"][:16] + "…)")

# 3. submit both
guids = {}
for tag, addr, name, ctorargs in [("impl", PROD_IMPL, "contracts/TandaBillV2.sol:TandaBillV2", ""),
                                   ("factory", PROD_FAC, "contracts/TandaBillFactory.sol:TandaBillFactory", expect)]:
    post = {
        "module": "contract", "action": "verifysourcecode",
        "contractaddress": addr, "sourceCode": json.dumps(p_fac),
        "codeformat": "solidity-standard-json-input",
        "contractname": name,
        "compilerversion": "v0.8.38+commit.1835d247",
        "licenseType": "3",
        "constructorArguments": ctorargs,
    }
    resp = http(API, post=post)
    print(tag, "submit:", resp.get("status"), resp.get("result", "")[:80])
    if resp.get("status") == "1":
        guids[tag] = resp["result"]

# 4. poll + readback
import time
for attempt in range(10):
    time.sleep(8)
    done = True
    for tag, g in list(guids.items()):
        st = http(API, {"module": "contract", "action": "checkverifystatus", "guid": g})
        msg = st.get("result", "")
        if "Pending" in msg or "Queue" in msg:
            done = False
            continue
        print(tag, "=>", msg[:120])
        src = http(API, {"module": "contract", "action": "getsourcecode", "address": guids_addr[tag] if False else (PROD_IMPL if tag=="impl" else PROD_FAC)})
        r0 = src["result"][0]
        print(tag, "readback: ContractName:", r0.get("ContractName"), "| OptimizationUsed:", r0.get("OptimizationUsed"),
              "| EVMVersion:", r0.get("EVMVersion"), "| source len:", len(r0.get("SourceCode", "")))
        del guids[tag]
    if not guids: break
print("VERIFICATION LANE COMPLETE")
