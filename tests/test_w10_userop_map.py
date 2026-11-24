"""t_w10fix unit tests — proof-identifier vs numeric userOpHash mapping.

Run: python -m unittest discover -s tests  (CI lane) or python -m unittest tests.w10_userop_map_test.
Fixtures are golden response shapes captured from the W10 lanes; the UUID-rejection
case reproduces the exact 2026-11-20 defect (proofs/W10_APP_PATH_RECEIPT_20261122.json
detail: 'Cannot convert 3abb1670-5ff7-485b-8204-77c2130a262e to a BigInt').
"""
import sys, unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
from w10_userop_map import extract_user_op_hash, InputTypeError

H64 = "0x" + "ab" * 32            # 64-hex userOpHash (MiniKit receipt class)
UUID = "3abb1670-5ff7-485b-8204-77c2130a262e"  # verbatim defect value


class TestMapping(unittest.TestCase):
    def test_minikit_data_shape(self):
        self.assertEqual(extract_user_op_hash({"data": {"userOpHash": H64.upper().replace("0X", "0x")}}),
                         H64.lower())

    def test_flat_shape(self):
        self.assertEqual(extract_user_op_hash({"userOpHash": H64}), H64)

    def test_nested_worldcoin_shape(self):
        self.assertEqual(extract_user_op_hash({"transaction": {"userOpHash": H64}}), H64)

    def test_priority_data_over_flat(self):
        r = extract_user_op_hash({"data": {"userOpHash": H64}, "userOpHash": "0x" + "cd" * 20})
        self.assertEqual(r, H64)  # data leg wins (verified receipt is authoritative)

    def test_uuid_proof_nonce_rejected(self):
        """THE standing defect: proof envelope forwarded where a receipt is required."""
        resp = {"protocol_version": "4.0", "nonce": UUID, "action": "grant_bill",
                "environment": "production",
                "responses": [{"identifier": "proof_of_human", "nullifier": "0c5c46" + "0" * 58}]}
        with self.assertRaises(InputTypeError) as cm:
            extract_user_op_hash(resp)
        self.assertIn("nonce", str(cm.exception))       # names the near-miss field
        self.assertIn("t_w10fix", str(cm.exception))    # routes the operator to the card

    def test_identifier_rejected_not_hashed_quietly(self):
        with self.assertRaises(InputTypeError):
            extract_user_op_hash({"identifier": "proof_of_human"})

    def test_short_and_long_rejects(self):
        for bad in ("0x1234", H64 + "ff", "plain-string", None):
            with self.assertRaises(InputTypeError):
                extract_user_op_hash({"userOpHash": bad} if bad else {})

    def test_40hex_tx_variant_accepted(self):
        h = "0x" + "ef" * 20  # some lanes carry 40-hex tx hashes (HEX64 allows 40..64)
        self.assertEqual(extract_user_op_hash({"userOpHash": h}), h)


    def test_bare_string_hash_accepted(self):
        self.assertEqual(extract_user_op_hash("0x" + "ab" * 32), "0x" + "ab" * 32)

    def test_bare_string_uuid_rejected(self):
        with self.assertRaises(InputTypeError):
            extract_user_op_hash("3abb1670-5ff7-485b-8204-77c2130a262e")

    def test_wrong_type_fails_loud_not_attributeerror(self):
        # Flux A7 reproduction: str was the crash class; None/int must share the gate.
        for bad in (None, 42, ["0x" + "ab" * 32]):
            with self.assertRaises(InputTypeError):
                extract_user_op_hash(bad)


if __name__ == "__main__":
    unittest.main()
