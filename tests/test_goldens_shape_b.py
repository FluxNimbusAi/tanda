"""Goldens class: ERC20 return-value semantics per XIXI-CARD-4 adjudication (shape_b).

Ruling (Flux, 2026-11-22): accepting empty returndata is documented intent, but CEI
flag-before-call + accepted-empty opens the silent-stranding window at
claimSettlement/refundSettlement. Goldens must prove the guard NEVER flips on an
ambiguous result — stranding is a failure condition, not accepted state.

Executable contract mirror of SafeERC20Minimal posture (no network, no forge):
- strict bool True required for success; False or empty/None returndata -> revert class.
"""
import unittest

class AmbiguousTransfer(Exception):
    pass

def safe_transfer_result(call_result):
    if call_result is None or call_result == b"":
        raise AmbiguousTransfer("empty returndata — must not be treated as success")
    if call_result is not True:
        raise AmbiguousTransfer("non-true return — revert class")
    return True

class TestShapeB(unittest.TestCase):
    def test_strict_true_advances(self):
        self.assertTrue(safe_transfer_result(True))

    def test_empty_returndata_reverts(self):
        for bad in (b"", None):
            with self.assertRaises(AmbiguousTransfer):
                safe_transfer_result(bad)

    def test_false_reverts(self):
        with self.assertRaises(AmbiguousTransfer):
            safe_transfer_result(False)

if __name__ == "__main__":
    unittest.main()
