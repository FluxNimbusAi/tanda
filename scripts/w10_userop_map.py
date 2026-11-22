"""W10 client-side mapping: proof response -> numeric userOpHash -> POST /bills.

Fix for the standing defect (card t_w10fix; anchor proofs/W10_APP_PATH_GRADE_20261122.md):
the 11-20 app-path probe forwarded a PROOF UUID (IDKit nonce/identifier) where the
indexer's POST /bills verifier expects a NUMERIC userOpHash matching
HEX64 = ^0x[0-9a-f]{40,64}$ -> 400 bad user_op_hash (IDX:UP).

Root cause class: client-side input-type defect; the proof envelope and the
transaction receipt are different objects and must never be conflated.

Priority chain (verified response shapes in the wild):
  1. resp["data"]["userOpHash"]        — MiniKit send_transaction command result
  2. resp["userOpHash"]                — flat variant
  3. resp["transaction"]["userOpHash"] — nested worldcoin.org status shape
                                        (same shape pair as /api/v2/minikit/transaction)

Anything else — nonce, identifier, nullifier, proof — is NOT a userOpHash and is
rejected with the defect-naming error so future probes fail LOUD, not 400-quiet.
"""
from __future__ import annotations

import json
import re
import urllib.request

USER_OP_RE = re.compile(r"^0x[0-9a-fA-F]{40,64}$")
# Fields that look hash-ish but are proof artifacts, never transaction receipts:
PROOF_FIELDS = ("nonce", "identifier", "nullifier", "proof", "merkle_root", "signal_hash")


class InputTypeError(ValueError):
    """Raised when no numeric userOpHash exists in the response (the 11-20 defect)."""


def extract_user_op_hash(resp) -> str:
    """Accepts MiniKit-style dicts OR a bare hash string (A7-class call shapes)."""
    """Map a verify/action response to its numeric userOpHash, or raise InputTypeError.

    Never falls back to proof-envelope fields — that conflation IS the defect.
    """
    if isinstance(resp, str):
        resp = {"userOpHash": resp}  # bare-hash convenience: the tap arg class
    elif not isinstance(resp, dict):
        raise InputTypeError(
            f"expected dict or str, got {type(resp).__name__} — no receipt shape "
            "to resolve (t_w10fix loud-fail contract)."
        )
    candidates = (
        ("data.userOpHash", resp.get("data", {}).get("userOpHash") if isinstance(resp.get("data"), dict) else None),
        ("userOpHash", resp.get("userOpHash")),
        ("transaction.userOpHash", resp.get("transaction", {}).get("userOpHash") if isinstance(resp.get("transaction"), dict) else None),
    )
    for source, val in candidates:
        if isinstance(val, str) and USER_OP_RE.match(val):
            return val.lower()
    # Refuse with a message that names the historical failure mode.
    near = next((f for f in PROOF_FIELDS if f in resp), None)
    hint = (
        f"response carries proof field '{near}' — that is IDKit/verify metadata, "
        if near else "response carries no userOpHash — "
    )
    raise InputTypeError(
        f"{hint}the indexer POST /bills verifier requires a numeric 0x[40,64]-hex "
        f"userOpHash (see t_w10fix / bad user_op_hash IDX:UP, 2026-11-20 anchor). "
        f"Resolved from shapes: {[s for s, _ in candidates]}."
    )


def post_bill(indexer_url: str, resp: dict, *, creator: str = "", token: str = "",
              chain_id: int = 4801, timeout: float = 10.0) -> dict:
    """Map-then-POST: /bills with the numeric userOpHash only. Returns indexer JSON."""
    h = extract_user_op_hash(resp)
    body = json.dumps({"user_op_hash": h, "creator": creator, "token": token,
                       "chain_id": chain_id}).encode()
    req = urllib.request.Request(indexer_url.rstrip("/") + "/bills", body,
                                 {"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        out = json.loads(r.read().decode())
    out["_mapped_user_op_hash"] = h
    return out
