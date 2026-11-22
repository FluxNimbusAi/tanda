"""Gate negative-test per skill law: feed the gate's DECLARED input shape, not a proxy.

Covers the InputTypeError contract of w10_userop_map.extract_user_op_hash (t_w10fix):
- proof-field-only dict must raise InputTypeError naming the defect;
- valid shapes pass: data.userOpHash dict, bare-string tap arg;
- wrong-type input raises before any network call.
"""
import unittest, sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))
import w10_userop_map as mod

GOOD = "0x" + "ab12" * 10  # 40 hex — within contract cap {40,64}

class TestGateContract(unittest.TestCase):
    def test_proof_dict_raises_named_defect(self):
        with self.assertRaises(mod.InputTypeError) as cm:
            mod.extract_user_op_hash({"nullifier": "abc", "nonce": "xyz"})
        self.assertIn("proof field", str(cm.exception))

    def test_data_shape_passes(self):
        self.assertEqual(mod.extract_user_op_hash({"data": {"userOpHash": GOOD}}), GOOD)

    def test_bare_string_tap_arg_passes(self):
        self.assertEqual(mod.extract_user_op_hash(GOOD), GOOD)

    def test_wrong_type_raises_before_network(self):
        for bad in ([], 42, None, ""):
            with self.assertRaises(mod.InputTypeError):
                mod.extract_user_op_hash(bad)

if __name__ == "__main__":
    unittest.main()
