"""Fail-closed credential narrowing — the merged auth path must never mint a session
from malformed input. Earned test case (Flux, default-action card ENG-20261122-A1).
Mirrors src/auth/index.ts narrowing in Python as an executable contract check."""
import re, unittest

KEYS = ["world_id", "nullifier", "app_id"]

def narrow(creds):
    # contract: Partial<Record<key, unknown>> -> only strings pass; anything else -> None
    if not isinstance(creds, dict):
        return None
    out = {}
    for k in KEYS:
        v = creds.get(k)
        if not isinstance(v, str):
            return None
        out[k] = v
    return out

class TestFailClosed(unittest.TestCase):
    def test_valid(self):
        self.assertEqual(narrow({"world_id": "u_1", "nullifier": "n_1", "app_id": "a_1"}),
                         {"world_id": "u_1", "nullifier": "n_1", "app_id": "a_1"})
    def test_partial_missing_field_closes(self):
        self.assertIsNone(narrow({"world_id": "u_1"}))
    def test_non_string_values_close(self):
        self.assertIsNone(narrow({"world_id": 42, "nullifier": None, "app_id": "a"}))
    def test_non_dict_closes(self):
        for bad in ([], "", None, "string"):
            self.assertIsNone(narrow(bad))

if __name__ == "__main__":
    unittest.main()
