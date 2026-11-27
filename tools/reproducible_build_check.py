#!/usr/bin/env python3
"""KAIZEN-4 (H7): reproducible-build gate — forge bytecode-hash vs on-chain.

Proves, from a clean checkout, that the TandaBillV2 pair deployed on
World Chain Sepolia (4801) is byte-reproducible from the pinned source
commit using the pinned toolchain (forge v1.9.0 / solc 0.8.38 / optimizer
runs=200 per the pinned commit's foundry.toml):

  1. rpc.agrees            — 2 independent public providers return identical
                             runtime code for impl + factory (cross-attestation).
  2. impl.zero-diff        — `git archive <source_main_sha> | forge build`
                             deployedBytecode == live runtime, byte-exact,
                             and == DEPLOY_STATE lineage keccak/size pins.
  3. factory.masked-match  — artifact vs live differs ONLY inside the ADR-0007
                             masks: constructor-linked immutable windows (20-B
                             impl-address bakes; artifact side all zeros, live
                             side must re-materialize to the pinned impl addr)
                             and/or the 32-B CBOR metadata digest in the tail.
                             Any unclassified diff range falsifies lineage.
  4. create.initcode       — the recorded factory CREATE tx input starts with
                             the rebuilt factory creationCode and its tail is
                             abi(impl address) — deploy-time init == build init.
  5. accessor.roundtrip    — eth_call factory.implementation() == pinned impl.
  6. receipt.anchor        — CREATE tx receipt.contractAddress == pinned factory.

Stdlib-only. Zero secrets, zero keys. Exit 0 = all gates PASS.

Usage:
  python tools/reproducible_build_check.py [--out proof.json]
                                           [--solc 0.8.38] [--forge forge]
                                           [--repo .] [--no-tx]

CI: .github/workflows/reproducible-build.yml runs this on every contracts/
push + weekly schedule; README badge reflects the latest main-branch run.
"""
import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
import urllib.request
from pathlib import Path

# --------------------------------------------------------------------------
# Pure-Python keccak-256 (Ethereum's Keccak, pad 0x01 — NOT SHA3's 0x06).
# Self-tested below before use; no third-party dependency.
# --------------------------------------------------------------------------
_RC = [0x0000000000000001, 0x0000000000008082, 0x800000000000808A, 0x8000000080008000,
       0x000000000000808B, 0x0000000080000001, 0x8000000080008081, 0x8000000000008009,
       0x000000000000008A, 0x0000000000000088, 0x0000000080008009, 0x000000008000000A,
       0x000000008000808B, 0x800000000000008B, 0x8000000000008089, 0x8000000000008003,
       0x8000000000008002, 0x8000000000000080, 0x000000000000800A, 0x800000008000000A,
       0x8000000080008081, 0x8000000000008080, 0x0000000080000001, 0x8000000080008008]
_ROT = [[0, 36, 3, 41, 18], [1, 44, 10, 45, 2], [62, 6, 43, 15, 61],
        [28, 55, 25, 21, 56], [27, 20, 39, 8, 14]]
_M64 = (1 << 64) - 1


def _rol(x, n):
    n %= 64
    return ((x << n) | (x >> (64 - n))) & _M64 if n else x


def _keccak_f(a):
    for rnd in range(24):
        c = [a[x][0] ^ a[x][1] ^ a[x][2] ^ a[x][3] ^ a[x][4] for x in range(5)]
        d = [c[(x - 1) % 5] ^ _rol(c[(x + 1) % 5], 1) for x in range(5)]
        for x in range(5):
            for y in range(5):
                a[x][y] ^= d[x]
        b = [[0] * 5 for _ in range(5)]
        for x in range(5):
            for y in range(5):
                b[y][(2 * x + 3 * y) % 5] = _rol(a[x][y], _ROT[x][y])
        for x in range(5):
            for y in range(5):
                a[x][y] = b[x][y] ^ ((~b[(x + 1) % 5][y] & _M64) & b[(x + 2) % 5][y])
        a[0][0] ^= _RC[rnd]
    return a


def keccak256(data: bytes) -> bytes:
    rate = 136  # 1088 bits
    st = [[0] * 5 for _ in range(5)]
    padded = bytearray(data)
    padded.append(0x01)                      # Keccak (Ethereum), not SHA3
    while len(padded) % rate != 0:
        padded.append(0x00)
    padded[-1] |= 0x80
    for off in range(0, len(padded), rate):
        blk = padded[off:off + rate]
        for i in range(rate // 8):
            lane = int.from_bytes(blk[i * 8:(i + 1) * 8], "little")
            st[i % 5][i // 5] ^= lane
        _keccak_f(st)
    out = bytearray()
    while len(out) < 32:
        for i in range(rate // 8):
            out += st[i % 5][i // 5].to_bytes(8, "little")
            if len(out) >= 32:
                break
    return bytes(out[:32])


def _selftest_keccak():
    assert keccak256(b"").hex() == \
        "c5d2460186f7233c927e7db2dcc703c0e500b653ca82273b7bfad8045d85a470", "keccak empty"
    assert keccak256(b"abc").hex() == \
        "4e03657aea45a94fc7d47ba826c8d667c0d1e6e33a64a036ec44f58fa12d6c45", "keccak abc"
    assert keccak256(b"implementation()").hex()[:8] == "5c60da1b", "keccak selector"


# --------------------------------------------------------------------------
# RPC (public endpoints; browser UA — thirdweb 403s the default urllib UA)
# --------------------------------------------------------------------------
_UA = {"Content-Type": "application/json",
       "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                     "(KHTML, like Gecko) Chrome/131.0 Safari/537.36"}
PROVIDERS = [
    ("alchemy", "https://worldchain-sepolia.g.alchemy.com/public"),  # official docs.world.org
    ("thirdweb", "https://4801.rpc.thirdweb.com"),
]


def rpc(url, method, params):
    req = urllib.request.Request(url, data=json.dumps(
        {"jsonrpc": "2.0", "id": 1, "method": method, "params": params}).encode(),
        headers=_UA)
    r = json.loads(urllib.request.urlopen(req, timeout=30).read())
    if "error" in r:
        raise RuntimeError(f"{method} @ {url}: {r['error']}")
    return r["result"]


def hx(b: bytes) -> str:
    return b.hex()


def diff_ranges(a: bytes, b: bytes):
    """Maximal contiguous ranges where a != b (both must be same length)."""
    out, i, n = [], 0, len(a)
    while i < n:
        if a[i] != b[i]:
            j = i
            while j < n and not (a[j] == b[j]):
                j += 1
            out.append((i, j))
            i = j
        else:
            i += 1
    return out


def main():
    _selftest_keccak()
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--repo", default=str(Path(__file__).resolve().parent.parent))
    ap.add_argument("--out", default=None, help="write proof JSON here")
    ap.add_argument("--solc", default="0.8.38")
    ap.add_argument("--forge", default=None, help="forge binary (default: PATH / FORGE env)")
    ap.add_argument("--no-tx", action="store_true", help="skip CREATE-tx initcode leg")
    args = ap.parse_args()

    repo = Path(args.repo).resolve()
    state = json.loads((repo / "docs" / "DEPLOY_STATE.json").read_text(encoding="utf-8"))
    impl_addr = state["impl"].lower()
    fac_addr = state["factory"].lower()
    sha = state["source_main_sha"]
    pin_k = state["lineage"]["impl_runtime_keccak"][2:].lower()
    pin_n = int(state["lineage"]["impl_runtime_bytes"])
    chain_id = int(state["chain_id"])
    # V3-pair CREATE tx of record (proofs/DEPLOY_RECEIPT_V3_HARDENED_20261121.json)
    fac_tx = json.loads((repo / state["receipt_path"]).read_text(encoding="utf-8"))["tx_factory"]

    checks, fails = [], []

    def check(name, ok, detail=""):
        checks.append({"name": name, "pass": bool(ok), "detail": detail})
        if not ok:
            fails.append(name)
        print(("PASS " if ok else "FAIL ") + name + ("  " + detail if detail else ""))

    # 0. forge binary + toolchain version (recorded, informational gate)
    forge = args.forge or os.environ.get("FORGE") or shutil.which("forge")
    if not forge:
        check("toolchain.forge", False, "forge not found on PATH (CI installs v1.9.0)")
        return finish(args, checks, {"error": "forge not found"}, fails)
    fver = (subprocess.run([forge, "--version"], capture_output=True, text=True,
                           encoding="utf-8", errors="replace").stdout or "").splitlines()[0]
    check("toolchain.forge", True, fver)

    # 1. cross-provider runtime attestation
    codes = {}   # provider -> {"impl": bytes, "factory": bytes}
    for pname, purl in PROVIDERS:
        try:
            cid = int(rpc(purl, "eth_chainId", []), 16)
            if cid != chain_id:
                raise RuntimeError(f"chainId {cid} != {chain_id}")
            codes[pname] = {
                "impl": bytes.fromhex(rpc(purl, "eth_getCode", [impl_addr, "latest"])[2:]),
                "factory": bytes.fromhex(rpc(purl, "eth_getCode", [fac_addr, "latest"])[2:]),
            }
        except Exception as e:
            check("rpc.agrees", False, f"{pname}: {type(e).__name__} {str(e)[:120]}")
            return finish(args, checks, {"error": str(e)}, fails)
    agree = all(codes[p]["impl"] == codes[PROVIDERS[0][0]]["impl"]
                and codes[p]["factory"] == codes[PROVIDERS[0][0]]["factory"]
                for p in codes)
    check("rpc.agrees", agree, f"{len(PROVIDERS)} providers 2/2 identical runtime "
          f"(impl {len(codes[PROVIDERS[0][0]]['impl'])} B, factory "
          f"{len(codes[PROVIDERS[0][0]]['factory'])} B)")
    if not agree:
        return finish(args, checks, {}, fails)
    live_impl = codes[PROVIDERS[0][0]]["impl"]
    live_fac = codes[PROVIDERS[0][0]]["factory"]

    # 2. rebuild from the pinned source commit in a throwaway tree
    with tempfile.TemporaryDirectory(prefix="repro_") as td:
        tree = Path(td) / "pin"
        tree.mkdir()
        p = subprocess.run(["git", "-C", str(repo), "archive", "--format=tar", sha],
                           capture_output=True)
        if p.returncode:
            check("build.archive", False, p.stderr[:200].decode(errors="replace"))
            return finish(args, checks, {}, fails)
        import io
        import tarfile
        with tarfile.open(fileobj=io.BytesIO(p.stdout)) as tf:
            tf.extractall(tree, filter="data")  # deterministic + path-safe extraction
        check("build.archive", True, f"git archive {sha[:10]} -> {len(p.stdout)} B tar, "
              f"extracted via stdlib tarfile")
        env = dict(os.environ, FOUNDRY_DISABLE_NIGHTLY_WARNING="1")
        b = subprocess.run([forge, "build", "--contracts", "contracts", "--use", args.solc],
                           cwd=tree, capture_output=True, text=True, env=env,
                           encoding="utf-8", errors="replace", timeout=900)
        if b.returncode:
            check("build.forge", False, (b.stdout + b.stderr)[-400:])
            return finish(args, checks, {}, fails)
        check("build.forge", True, f"solc {args.solc} @ {sha[:10]}")

        def artifact(file, name):
            d = json.loads((tree / "out" / file / f"{name}.json").read_text(encoding="utf-8"))
            return (bytes.fromhex(d["bytecode"]["object"][2:]),        # creationCode
                    bytes.fromhex(d["deployedBytecode"]["object"][2:]))  # runtime shape

        impl_init, impl_rt = artifact("TandaBillV2.sol", "TandaBillV2")
        fac_init, fac_rt = artifact("TandaBillFactory.sol", "TandaBillFactory")

        # 3. impl: byte-exact zero-diff vs live, and vs repo pins
        z = impl_rt == live_impl
        k, s = keccak256(live_impl).hex(), hashlib.sha256(live_impl).hexdigest()
        check("impl.zero-diff", z,
              f"built runtime == live @4801 byte-exact ({len(live_impl)} B)" if z else
              f"DIFF ranges {diff_ranges(impl_rt, live_impl)[:5]}")
        check("impl.pin-keccak", k == pin_k and len(live_impl) == pin_n,
              f"keccak {k[:16]}… == DEPLOY_STATE pin, size {len(live_impl)} == {pin_n}")

        # 4. factory: masked comparison (ADR-0007 L2)
        m_ok, m_note = True, []
        if len(fac_rt) != len(live_fac):
            m_ok, m_note = False, [f"size drift artifact {len(fac_rt)} vs live {len(live_fac)}"]
        else:
            for (i, j) in diff_ranges(fac_rt, live_fac):
                art, liv = fac_rt[i:j], live_fac[i:j]
                if len(liv) == 20 and art == b"\x00" * 20 and hx(liv) == impl_addr[2:]:
                    m_note.append(f"[{i}..{j}) immutable bake -> impl addr")
                elif len(liv) == 32 and j + 16 >= len(live_fac):
                    m_note.append(f"[{i}..{j}) CBOR metadata digest (tail)")
                else:
                    m_ok = False
                    m_note.append(f"[{i}..{j}) UNMASKED DIFF -> lineage FALSIFIED")
        check("factory.masked-match", m_ok,
              f"len(live)=={len(live_fac)} B; diff ranges: " + ("; ".join(m_note) or "none (exact)"))

        # 5. CREATE tx initcode proof (deploy-time init == build init)
        tx_info = {"skipped": args.no_tx}
        if not args.no_tx:
            r = rpc(PROVIDERS[0][1], "eth_getTransactionReceipt", [fac_tx])
            check("receipt.anchor", r and r.get("contractAddress", "").lower() == fac_addr,
                  f"tx {fac_tx[:14]}… contractAddress == {fac_addr}")
            t = rpc(PROVIDERS[0][1], "eth_getTransactionByHash", [fac_tx])
            inp = bytes.fromhex(t["input"][2:]) if t and t.get("input") else b""
            ok = inp.startswith(fac_init) and inp[len(fac_init):].hex().endswith(impl_addr[2:])
            check("create.initcode", bool(ok),
                  f"live CREATE input ({len(inp)} B) starts with rebuilt factory initcode "
                  f"({len(fac_init)} B) + abi(impl) tail")
            tx_info = {"tx": fac_tx, "input_bytes": len(inp), "init_bytes": len(fac_init)}

        # 6. accessor round-trip
        call = rpc(PROVIDERS[0][1], "eth_call",
                   [{"to": fac_addr, "data": "0x5c60da1b"}, "latest"])
        got = call[2:].lower()[-40:]          # last 20 bytes of the 32-byte return word
        check("accessor.roundtrip", got == impl_addr[2:], f"implementation() -> 0x{got}")

    result = {
        "gate": "KAIZEN-4 reproducible-build (H7)",
        "chain_id": chain_id, "source_main_sha": sha, "forge": fver, "solc": args.solc,
        "impl": {"address": impl_addr, "bytes": len(live_impl),
                 "sha256": hashlib.sha256(live_impl).hexdigest(),
                 "keccak256": keccak256(live_impl).hex()},
        "factory": {"address": fac_addr, "bytes": len(live_fac),
                    "sha256": hashlib.sha256(live_fac).hexdigest(),
                    "keccak256": keccak256(live_fac).hex()},
        "built": {"impl_deployed_sha256": hashlib.sha256(impl_rt).hexdigest(),
                  "impl_init_sha256": hashlib.sha256(impl_init).hexdigest(),
                  "factory_deployed_sha256": hashlib.sha256(fac_rt).hexdigest(),
                  "factory_init_sha256": hashlib.sha256(fac_init).hexdigest()},
        "providers": [p for p, _ in PROVIDERS], "create_tx": tx_info,
        "checks": checks, "verdict": "PASS" if not fails else "FAIL",
    }
    return finish(args, checks, result, fails)


def finish(args, checks, result, fails):
    if "checks" not in result:
        result["checks"] = checks
        result["verdict"] = "FAIL" if fails else "PASS"
    print("\n" + ("=" * 66))
    print(f"VERDICT: {'PASS' if not fails else 'FAIL ' + ','.join(fails)}")
    out = json.dumps(result, indent=2, sort_keys=True)
    if args.out:
        Path(args.out).write_text(out + "\n", encoding="utf-8", newline="\n")
        print(f"proof written: {args.out}  sha256_LF {hashlib.sha256((out + chr(10)).encode()).hexdigest()}")
    return 0 if not fails else 1


if __name__ == "__main__":
    sys.exit(main())
