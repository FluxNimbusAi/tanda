"""Tie-in law: the on-chain SafeERC20Minimal at settlement sites must match the goldens class.

Enforces that the contract guard is strict-bool ONLY — the lenient OZ branch
(data.length == 0 accepted as success) must NOT appear, because the adjudicated
law (XIXI-CARD-4 shape_b, tests/test_goldens_shape_b.py) treats empty returndata
as a stranding failure condition at claimSettlement/refundSettlement.

Source-shape assertion, stdlib only — CI python leg. If the contract adopts the
lenient branch, this test fails: divergence is caught at CI, not in prose.
"""
import re, unittest
from pathlib import Path

SRC = Path(__file__).resolve().parents[1] / "contracts" / "FastTandaBillV2.sol"

class TestGuardShapeMatch(unittest.TestCase):
    def setUp(self):
        self.src = SRC.read_text(encoding="utf-8")

    def test_strict_bool_guard_present(self):
        m = re.search(r"data\.length == 32 && abi\.decode\(data, \(bool\)\)", self.src)
        self.assertIsNotNone(m, "strict-bool guard missing from SafeERC20Minimal")

    def test_lenient_branch_absent(self):
        # The OZ lenient acceptance of empty returndata must not appear in the library.
        lib = self.src[self.src.index("library SafeERC20Minimal"):self.src.index("contract FastTandaBillV2")]
        self.assertNotIn("data.length == 0 ||", lib, "lenient branch contradicts goldens law")

    def test_settlement_sites_use_guard(self):
        self.assertEqual(self.src.count("require(token.transfer("), 0)
        self.assertGreaterEqual(self.src.count("SafeERC20Minimal.safeTransfer(token,"), 2)

if __name__ == "__main__":
    unittest.main()
