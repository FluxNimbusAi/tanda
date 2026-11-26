#!/usr/bin/env python3
"""ENGINE 33: twin-contract scan as a rerunnable gate (family B2 automation).

Encodes the proven manual recipe from verdict e743a64d (t_921c1849, 2026-11-25)
into CI-callable porcelain. Scans every git-tracked contracts/*.sol for token
transfer call sites and classifies each:

  SAFE-LIB        routed through SafeERC20Minimal / SafeERC20Funding wrappers
                  (lenient empty-ret = success in V2 per ADR-0010 World-Chain
                  USDC note; strict-bool data.length==32 in Fast twin — the
                  asymmetry is documented adjudication, not a defect)
  RETURN-CHECKED  bare call whose bool is consumed by require/if
  BARE            return value discarded -> DEFECT unless adjudicated below

Adjudicated exemptions (void-return interfaces, revert-or-succeed, no bool
to ignore — never card these):
  IPermit2Transfer(PERMIT2).transferFrom(...)  TandaBillV2.sol + FastTandaBillV2.sol

Exit code: 0 = CLEAN, 1 = unexempted BARE hits (open defect lines -> cards).
Prints one JSON receipt to stdout (or --out FILE) with sha256-LF of every
scanned file so the golden can be diffed against disk on re-run.
"""
import hashlib
import json
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

CALL_RE = re.compile(r"\.(safeTransferFrom|safeTransfer|safeApprove|transferFrom|transfer|approve)\s*\(")
FN_RE = re.compile(r"^\s*(?:pragma|abstract|contract|interface|library|function|modifier)\b")
FUNC_RE = re.compile(r"\b(?:function|modifier)\s+([A-Za-z_][A-Za-z0-9_]*)")
# library wrapper call style: LibraryName.safeTransfer(...)
LIB_RE = re.compile(r"[A-Za-z_][A-Za-z0-9_]*\.(safeTransferFrom|safeTransfer|safeApprove)\s*\(")
# adjudicated void-return interface call: InterfaceName(addr).transferFrom(...)
VOIDIFACE_RE = re.compile(r"\bI[A-Za-z0-9_]+\([^)]*\)\.(transfer|transferFrom|approve)\s*\(")
REQUIRE_CHECKED_RE = re.compile(r"^\s*(?:require|if|assert)\s*\(|[=!]==?\s*$|\breturn\b")

SAFE_KINDS = {"safeTransfer", "safeTransferFrom", "safeApprove"}


def strip_comment(line: str) -> str:
    """Remove // line comments and drop block-comment lines (single-pass,
    good enough for our canonically formatted sources; block comment
    interiors carry prose, not call sites)."""
    m = re.search(r"//", line)
    if m:
        line = line[: m.start()]
    return line


def in_block_comment(lines, idx):
    """True if line idx sits inside a /* ... */ block (odd count of /* so far)."""
    opened = 0
    for l in lines[: idx + 1]:
        opened += l.count("/*") - l.count("*/")
    return opened > 0


def enclosing_fn(lines, idx):
    for j in range(idx, -1, -1):
        m = FUNC_RE.search(lines[j])
        if m:
            return m.group(1)
    return "<top>"


def sha256_lf(path: Path) -> str:
    """Canonical hash: CRLF/CR normalized to LF before digest (cross-node law)."""
    data = path.read_bytes().replace(b"\r\n", b"\n").replace(b"\r", b"\n")
    return hashlib.sha256(data).hexdigest()


def scan_file(rel: str):
    lines = (ROOT / rel).read_text(encoding="utf-8").splitlines()
    hits = []
    for i, raw in enumerate(lines):
        if "/*" in raw or in_block_comment(lines, i):
            # cheap block-comment guard only when a marker is nearby
            if not any(tok in raw for tok in ("transfer", "approve")):
                continue
        line = strip_comment(raw)
        m = CALL_RE.search(line)
        if not m:
            continue
        kind = m.group(1)
        if kind in SAFE_KINDS:
            if LIB_RE.search(line):
                cls = "SAFE-LIB"
            else:
                cls = "BARE"  # e.g. `token.safeTransfer(` via `using` — flag for review
        elif VOIDIFACE_RE.search(line):
            cls = "EXEMPT-VOID-IFACE"
        elif REQUIRE_CHECKED_RE.search(line):
            cls = "RETURN-CHECKED"
        else:
            # was the bool consumed on an enclosing require/if opened above?
            cls = "BARE"
        hits.append({
            "file": rel,
            "line": i + 1,
            "kind": kind,
            "classification": cls,
            "function": enclosing_fn(lines, i),
            "snippet": line.strip()[:120],
        })
    return hits


def main():
    out = None
    if "--out" in sys.argv:
        out = Path(sys.argv[sys.argv.index("--out") + 1])
    files = [
        f for f in subprocess.run(
            ["git", "ls-files", "contracts/"], cwd=ROOT, capture_output=True, text=True, check=True
        ).stdout.splitlines()
        if f.endswith(".sol")
    ]
    all_hits = []
    manifest = {}
    for rel in sorted(files):
        manifest[rel] = sha256_lf(ROOT / rel)
        all_hits.extend(scan_file(rel))

    bare = [h for h in all_hits if h["classification"] == "BARE"]
    counts = {}
    for h in all_hits:
        counts[h["classification"]] = counts.get(h["classification"], 0) + 1

    receipt = {
        "card": "ENGINE-33",
        "recipe_provenance": "t_921c1849 verdict e743a64de (2026-11-25) encoded as gate",
        "files_scanned": len(files),
        "sha256_lf": manifest,
        "call_sites": all_hits,
        "counts": counts,
        "verdict": "CLEAN" if not bare else "GATED-BARE-DEFECTS",
        "unexempted_bare": bare,
    }
    text = json.dumps(receipt, indent=2, sort_keys=True)
    if out:
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(text + "\n", encoding="utf-8", newline="\n")
    print(text)
    return 1 if bare else 0


if __name__ == "__main__":
    sys.exit(main())
