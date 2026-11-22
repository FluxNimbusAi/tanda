"""w10_e2e_probe — one-shot E2E leg for the owner World App wallet tap (t_1392cfb5).

Usage (exactly one argument, straight from the MiniKit result of the tap):
    python scripts/w10_e2e_probe.py 0x<userOpHash-from-device>

Pipeline (all lanes already proven piecewise; this wires them):
  1. Map/gate: scripts/w10_userop_map.extract_user_op_hash — a UUID or proof field
     passed here FAILS LOUD (InputTypeError), by design.
  2. POST :8096/bills (userop lane, 202-pending semantics per W8).
  3. Poll GET :8096/bills/by-userop/<h> to terminal state
     (success | no_event | failed | error) with bound.
  4. Emit strict JSON: {user_op_hash, indexer_status, bill, tx, verdict}.

Verdict map:
  success   -> E2E GREEN: BillCreated resolved from userop; t_1392cfb5 +
               t_w10fix E2E leg close on this receipt.
  no_event  -> tap not mined yet or wrong chain (4801 expected); re-run after
               World App shows the tx confirmed. Honest terminal, not a failure.
  failed    -> userop rejected at source (check wallet/app error bubble).
Exit codes: 0 green, 1 no_event/failed, 2 mapping/input error.
"""
import json
import sys
import time
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from w10_userop_map import extract_user_op_hash, InputTypeError  # noqa: E402

INDEXER = "http://127.0.0.1:8096"


def _get(url, timeout=10.0):
    with urllib.request.urlopen(url, timeout=timeout) as r:
        return json.loads(r.read().decode())


def main(h: str, poll_s: float = 1.5, deadline: float = 120.0) -> int:
    try:
        canonical = extract_user_op_hash({"userOpHash": h})
    except InputTypeError as e:
        print(json.dumps({"verdict": "input_rejected", "detail": str(e)}))
        return 2

    # Step 2: userop lane join (202 semantics; duplicate-safe INSERT OR IGNORE).
    req = urllib.request.Request(
        INDEXER + "/bills",
        json.dumps({"user_op_hash": canonical, "chain_id": 4801}).encode(),
        {"Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=15) as r:
            joined = json.loads(r.read().decode())
    except Exception as e:  # 400 from indexer = mapper let something wrong through
        print(json.dumps({"verdict": "indexer_join_error", "detail": repr(e)[:200],
                          "user_op_hash": canonical}))
        return 2

    # Step 3: poll to terminal.
    terminal = {"success", "no_event", "failed", "error"}
    row, t0 = None, time.time()
    while time.time() - t0 < deadline:
        try:
            row = _get(f"{INDEXER}/bills/by-userop/{canonical}")
            if (row.get("status") or row.get("row", {}).get("status")) in terminal:
                break
        except Exception:
            pass
        time.sleep(poll_s)

    status = (row or {}).get("status") or (row or {}).get("row", {}).get("status") or "timeout"
    verdict = "GREEN" if status == "success" else status
    print(json.dumps({
        "user_op_hash": canonical,
        "join_response": joined,
        "indexer_status": status,
        "bill": (row or {}).get("bill_address") or (row or {}).get("row", {}).get("bill_address"),
        "tx": (row or {}).get("tx_hash") or (row or {}).get("row", {}).get("tx_hash"),
        "verdict": verdict,
        "elapsed_s": round(time.time() - t0, 1),
    }, indent=1))
    return 0 if verdict == "GREEN" else 1


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print(__doc__)
        sys.exit(2)
    sys.exit(main(sys.argv[1]))
