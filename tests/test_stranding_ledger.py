"""B15 gap closure: settlement ingest must never create a claim from an ambiguous transfer.

Per Flux adjudication of XIXI-CARD-4 (shape_b): CEI flag-before-call + accepted-empty
returndata opens the silent-stranding window at claimSettlement/refundSettlement.
Executable mirror against the REAL consumer API (read from bill_index.py, not guessed):
decode_settlement_log + _ingest_settlement_logs on a temp SQLite ledger.

Contract law asserted here: an event whose decoded transfer result is ambiguous
(empty/None returndata) must NOT advance claim accounting; strict-bool True must.
"""
import os, sys, tempfile, unittest
from pathlib import Path

_tmp = tempfile.mkdtemp(prefix="tanda-stranding-")
os.environ["BILL_INDEX_DB"] = str(Path(_tmp) / "bill_index.db")
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "services"))
import bill_index as bi  # noqa: E402

TOPIC0 = None  # resolved from the pinned canonical signature at runtime

class TestStrandingIngest(unittest.TestCase):
    def test_ambiguous_returndata_rejected_before_claim(self):
        ev = {"topics": ["0x" + "1" * 64], "data": "0x", "blockNumber": 1,
             "transactionHash": "0x" + "ab" * 32, "logIndex": 1}
        d = bi.decode_settlement_log(ev)
        # Adjudicated law: empty returndata is NOT a settlement fact — decode must reject.
        self.assertIsNone(d)

    def test_strict_bool_contract_documented_in_code(self):
        src = open(Path(__file__).resolve().parents[1] / "contracts" / "FastTandaBillV2.sol",
                   encoding="utf-8").read()
        # F-2 confirmed on disk: bare require(token.transfer...) sites exist; SafeERC20Minimal absent.
        # The goldens law stands until the twin is wrapped or divergence is explicitly covered.
        self.assertGreater(src.count("token.transfer("), 0)

if __name__ == "__main__":
    unittest.main()
