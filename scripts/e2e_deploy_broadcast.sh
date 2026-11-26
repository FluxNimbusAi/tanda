#!/usr/bin/env bash
# ENGINE 31 (t_3dae49ae): E2E harness hardening - anvil-local broadcast leg for
# both production deploy scripts. On a REAL node the script caller IS the
# broadcast deployer, so the verify requires
#   script/TandaDeploy.s.sol   L45 token / L46 owner / L47 zero-seats
#   script/TandaDeployV2.s.sol L28 impl-match
# take their TRUE-success arms - the legs pinned as harness-unreachable under
# `forge test` in test/DeployScriptGolden11255.t.sol (prank x startBroadcast is
# hard-incompatible; delegatecall collapses msg.sender only to the test contract).
#
# After the broadcasts the harness verifies EXTERNALLY with plain JSON-RPC,
# outside the script's own EVM execution context:
#   eth_getTransactionReceipt status==0x1 + from==deployer for every tx,
#   eth_getCode non-empty + runtime sha256 for every deployment,
#   eth_call token()/owner()/activeSeatCount() on the V1 bill and
#   implementation() on the V2 factory. All results land in the proof JSON.
#
# Usage: bash scripts/e2e_deploy_broadcast.sh   (run from anywhere; cds to root)
# Env:   FORGE_BIN ANVIL_BIN CAST_BIN PYTHON_BIN ANVIL_PORT DEPLOY_KEY
#        USDC_STANDBY PROOF_OUT KEEP_TMP=1 (retain .engine31_out for forensics)
# Exit 0 only if BOTH scripts broadcast AND every external check passes.
set -euo pipefail
cd "$(git rev-parse --show-toplevel)"

FORGE="${FORGE_BIN:-forge}"
ANVIL="${ANVIL_BIN:-anvil}"
CAST="${CAST_BIN:-cast}"
PY="${PYTHON_BIN:-python3}"
# Kanban/cron shells ship no foundry on PATH - resolve the standard install dir.
command -v "$FORGE" >/dev/null 2>&1 || export PATH="$PATH:$HOME/.foundry/bin"
for b in "$FORGE" "$ANVIL" "$CAST" "$PY"; do
  command -v "$b" >/dev/null 2>&1 || { echo "FATAL: required binary not on PATH: $b" >&2; exit 1; }
done
# MSYS lesson (measured 2026-11-26 re-run): the embedded NATIVE python cannot
# CreateProcess binaries resolved to /c/... paths, and cron PATHs hide foundry
# from native tools entirely. On MSYS hosts resolve every foundry binary to a
# native Windows path and export it, so the python block's `forge --version`
# metadata leg works from a bare shell.
if command -v cygpath >/dev/null 2>&1; then
  FORGE="$(cygpath -w "$(command -v "$FORGE")")"
  ANVIL="$(cygpath -w "$(command -v "$ANVIL")")"
  CAST="$(cygpath -w "$(command -v "$CAST")")"
fi
export FORGE_BIN="$FORGE" ANVIL_BIN="$ANVIL" CAST_BIN="$CAST"

PORT="${ANVIL_PORT:-8545}"
# Anvil genesis account #0 (public, deterministic, dev-only key).
KEY="${DEPLOY_KEY:-0xac0974bec39a17e36ba4a6b4d238ff944bacb478cbed5efcae784d7bf4f2ff80}"
# USDC stand-in: the constructors store the token address with no code check
# (contracts/TandaBill.sol `constructor(IERC20 _token) { token = _token; ... }`),
# so any well-formed address deploys. Anvil account #1 keeps this receipt honest
# as an anvil-ecosystem proof - NOT a 4801 mainnet deploy.
USDC="${USDC_STANDBY:-0x70997970C51812dc3A010C7d01b50e0d17dc79C8}"
RPC="http://127.0.0.1:${PORT}"
PROOF="${PROOF_OUT:-proofs/ENGINE31_ANVIL_BROADCAST_$(date -u +%Y%m%d).json}"
DEPLOYER="$("$CAST" wallet address --private-key "$KEY")"
case "$DEPLOYER" in 0x[0-9a-fA-F][0-9a-fA-F]*) ;; *) echo "FATAL: bad derived deployer: $DEPLOYER" >&2; exit 1 ;; esac

# Repo-local scratch: MSYS /tmp is invisible to native binaries (forge/anvil and
# the Hermes-bundled python.exe are all native on this host) - keep paths relative.
OUT=".engine31_out"
rm -rf "$OUT"; mkdir -p "$OUT"

"$ANVIL" --port "$PORT" --chain-id 31337 >"$OUT/anvil.log" 2>&1 &
ANVIL_PID=$!
cleanup() {
  kill "$ANVIL_PID" 2>/dev/null || true
  [ "${KEEP_TMP:-0}" = 1 ] || rm -rf "$OUT"
}
trap cleanup EXIT

# Node readiness: poll eth_chainId for 0x7a69 (31337), max ~10s.
READY=0
for _ in $(seq 1 20); do
  if curl -s -m 2 -X POST -H 'content-type: application/json' \
      --data '{"jsonrpc":"2.0","id":1,"method":"eth_chainId","params":[]}' "$RPC" \
      2>/dev/null | grep -q 0x7a69; then READY=1; break; fi
  sleep 0.5
done
if [ "$READY" != 1 ]; then
  echo "FATAL: anvil never answered eth_chainId on $RPC" >&2
  tail -n 5 "$OUT/anvil.log" >&2 || true
  exit 1
fi

export USDC_ADDRESS="$USDC"
echo "== TandaDeploy.s.sol (V1 mainline) =="
if ! "$FORGE" script script/TandaDeploy.s.sol --rpc-url "$RPC" --private-key "$KEY" \
    --broadcast --slow --json >"$OUT/v1.json" 2>"$OUT/v1.err"; then
  echo "FATAL: V1 broadcast failed" >&2; tail -n 25 "$OUT/v1.err" >&2; exit 1
fi
echo "== TandaDeployV2.s.sol (factory lineage) =="
if ! "$FORGE" script script/TandaDeployV2.s.sol --rpc-url "$RPC" --private-key "$KEY" \
    --broadcast --slow --json >"$OUT/v2.json" 2>"$OUT/v2.err"; then
  echo "FATAL: V2 broadcast failed" >&2; tail -n 25 "$OUT/v2.err" >&2; exit 1
fi

# forge 1.9.0 --json over a live broadcast is streaming event-lines (shape
# measured this tick by throwaway probe: [execution-result, estimate, one row
# per broadcast tx carrying contract_name/tx_hash/status, final summary
# carrying transactions+status]). Parse it, then verify everything externally.
"$PY" - "$OUT" "$RPC" "$PROOF" "$DEPLOYER" "$USDC" <<'PY'
import datetime, hashlib, json, os, pathlib, subprocess, sys, urllib.request

out, rpc, proof_path, deployer, usdc = map(str, sys.argv[1:6])
low = lambda a: str(a).lower()


def rpc_call(method, params):
    body = json.dumps({"jsonrpc": "2.0", "id": 1, "method": method,
                       "params": params}).encode()
    req = urllib.request.Request(rpc, data=body,
                                 headers={"content-type": "application/json"})
    with urllib.request.urlopen(req, timeout=10) as r:
        resp = json.loads(r.read())
    assert "result" in resp, f"{method} -> {resp}"
    return resp["result"]


def parse(name):
    txs, summary = [], None
    for line in pathlib.Path(out, f"{name}.json").read_text().splitlines():
        s = line.strip()
        if not s.startswith("{"):
            continue
        o = json.loads(s)
        if "contract_name" in o and "tx_hash" in o:
            txs.append(o)
        if "transactions" in o and "status" in o:
            summary = o
    assert summary and summary["status"] == "success", f"{name}: no success summary"
    assert txs, f"{name}: no per-tx broadcast rows"
    deps = {}
    for t in txs:
        assert t["status"] == "success", f"{name}: failed tx {t['tx_hash']} ({t['contract_name']})"
        # The node's own receipt must agree with the forge event row.
        rec = rpc_call("eth_getTransactionReceipt", [t["tx_hash"]])
        assert rec and rec["status"] == "0x1", f"{name}: receipt not 0x1 for {t['tx_hash']}"
        assert low(rec["contractAddress"]) == low(t["contract_address"]), \
            f"{name}: receipt/row address split {rec['contractAddress']} vs {t['contract_address']}"
        assert low(rec["from"]) == low(deployer), f"{name}: tx {t['tx_hash']} not sent by deployer"
        code = rpc_call("eth_getCode", [t["contract_address"], "latest"])
        assert code and code != "0x", f"{name}: no runtime code at {t['contract_address']}"
        deps[t["contract_name"]] = {
            "tx_hash": t["tx_hash"],
            "contract_address": t["contract_address"],
            "block_number": t["block_number"],
            "gas_used": t.get("gas_used"),
            "receipt_status": rec["status"],
            "receipt_from": rec["from"],
            "receipt_gas_used": rec["gasUsed"],
            "runtime_sha256": hashlib.sha256(bytes.fromhex(code[2:])).hexdigest(),
            "runtime_bytes": (len(code) - 2) // 2,
        }
        print(f"  {t['contract_name']}: addr={t['contract_address']} tx={t['tx_hash']} "
              f"block={t['block_number']} code={deps[t['contract_name']]['runtime_bytes']}B")
    return deps


v1, v2 = parse("v1"), parse("v2")
assert "TandaBill" in v1, "v1: TandaBill deployment missing"
assert {"TandaBillV2", "TandaBillFactory"} <= set(v2), "v2: factory-lineage pair missing"

# Selector literals measured this tick with `cast keccak` (forge 1.9.0):
SEL = {"token()": "0xfc0c546a", "owner()": "0x8da5cb5b",
       "activeSeatCount()": "0x0d9461ba", "implementation()": "0x5c60da1b"}
bill, fac, impl = v1["TandaBill"], v2["TandaBillFactory"], v2["TandaBillV2"]


def addr_of(word):
    assert len(word) == 66, f"unexpected 32-byte word from eth_call: {word}"
    return "0x" + word[-40:]


checks = []


def require_external(leg, target, fn, expected, actual):
    ok = low(expected) == low(actual)
    checks.append({"leg": leg, "target_contract": target, "call": fn,
                   "selector": SEL[fn], "expected": str(expected),
                   "actual": str(actual), "pass": ok})
    assert ok, f"EXTERNAL VERIFY FAILED {leg} {fn} at {target}: want {expected}, got {actual}"
    print(f"  OK {leg} {fn} -> {actual}")


# The four verify-requires, read off the node OUTSIDE the script's context.
require_external("v1_token", bill["contract_address"], "token()", usdc,
                 addr_of(rpc_call("eth_call", [{"to": bill["contract_address"],
                                                "data": SEL["token()"]}, "latest"])))
require_external("v1_owner", bill["contract_address"], "owner()", deployer,
                 addr_of(rpc_call("eth_call", [{"to": bill["contract_address"],
                                                "data": SEL["owner()"]}, "latest"])))
require_external("v1_zero_seats", bill["contract_address"], "activeSeatCount()", "0",
                 str(int(rpc_call("eth_call", [{"to": bill["contract_address"],
                                                "data": SEL["activeSeatCount()"]}, "latest"]), 16)))
require_external("v2_impl_match", fac["contract_address"], "implementation()",
                 impl["contract_address"],
                 addr_of(rpc_call("eth_call", [{"to": fac["contract_address"],
                                                "data": SEL["implementation()"]}, "latest"])))

fv = subprocess.run([os.environ.get("FORGE_BIN", "forge"), "--version"],
                    capture_output=True, text=True)
meta = {
    "card": "t_3dae49ae",
    "engine": "TICK-1125-14 ENGINE 31 anvil broadcast leg",
    "generated_utc": datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds"),
    "git_rev": subprocess.run(["git", "rev-parse", "HEAD"], capture_output=True, text=True).stdout.strip(),
    "forge_version": (fv.stdout or "").splitlines()[0] if fv.returncode == 0 else "forge --version failed",
    "anvil_chain_id": 31337,
    "rpc": rpc,
    "deployer": f"{deployer} (anvil genesis acct #0, dev-only key)",
    "usdc_standby": (f"{usdc} (anvil acct #1; constructors store the token address "
                     "without a code check, so this receipt is an anvil-ecosystem "
                     "proof, NOT a 4801 mainnet deploy)"),
    "claims": [
        "V1 run(): L45 token-match, L46 owner==msg.sender (caller==deployer TRUE arm, "
        "harness-unreachable under forge test per DeployScriptGolden11255.t.sol), L47 "
        "zero-seats - green in-script AND re-verified by external eth_call on the live node",
        "V2 run(): L28 factory.implementation()==impl golden green in-script AND "
        "re-verified by external eth_call on the live node",
        "every broadcast tx independently confirmed via eth_getTransactionReceipt "
        "status=0x1 + from==deployer; every deployment via non-empty eth_getCode runtime sha256",
    ],
    "deployments": {"v1": v1, "v2": v2},
    "external_verify": checks,
    "all_green": True,
}
proof = pathlib.Path(proof_path)
proof.parent.mkdir(parents=True, exist_ok=True)
blob = (json.dumps(meta, indent=2, sort_keys=True) + "\n").encode().replace(b"\r\n", b"\n")
proof.write_bytes(blob)
print("proof written:", proof, "sha256:", hashlib.sha256(blob).hexdigest(), "bytes:", len(blob))
PY
echo "harness OK (exit 0)"
