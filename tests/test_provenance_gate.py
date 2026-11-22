"""Python-leg runner for the provenance CI gate golden matrix.

The gate itself (tools/ci_provenance_gate.py) ships its own --self-test
so the provenance job is self-verifying without depending on this leg;
this wrapper additionally folds the goldens into `unittest discover`
per the repo's honest-green convention (see test_nudge_engine.py shape).
Requires `git` on PATH (always present on runners).
"""

import pathlib
import shutil
import subprocess
import sys
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
GATE = ROOT / "tools" / "ci_provenance_gate.py"


class ProvenanceGateTests(unittest.TestCase):
    @unittest.skipIf(shutil.which("git") is None, "git not available")
    def test_self_test_golden_matrix(self):
        proc = subprocess.run(
            [sys.executable, str(GATE), "--self-test"],
            capture_output=True,
            text=True,
        )
        self.assertEqual(
            proc.returncode, 0, msg=f"stdout:\n{proc.stdout}\nstderr:\n{proc.stderr}"
        )
        self.assertIn("SELF-TEST OK", proc.stdout)

    def test_gate_scans_real_repo_clean(self):
        # Dogfood: the gate must pass against this very checkout's full
        # history (proves zero live violations of the new law at landing).
        if shutil.which("git") is None:
            self.skipTest("git not available")
        proc = subprocess.run(
            [sys.executable, str(GATE), "--repo", str(ROOT), "--revs", "HEAD"],
            capture_output=True,
            text=True,
        )
        self.assertEqual(
            proc.returncode, 0, msg=f"stdout:\n{proc.stdout}\nstderr:\n{proc.stderr}"
        )


if __name__ == "__main__":
    unittest.main()
