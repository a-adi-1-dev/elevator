import io
import os
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout

from elevator_sim.__main__ import main


class CliTest(unittest.TestCase):
    def run_cli(self, csv_text, *args):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "requests.csv")
            with open(path, "w") as f:
                f.write(csv_text)
            out, err = io.StringIO(), io.StringIO()
            with redirect_stdout(out), redirect_stderr(err):
                code = main([path, "--positions-log", os.path.join(tmp, "pos.csv"), *args])
            return code, out.getvalue(), err.getvalue()

    def test_complete_run_exits_0(self):
        code, out, _ = self.run_cli("time,id,source,dest\n0,a,1,5\n")
        self.assertEqual(code, 0)
        self.assertIn("completed       : 1", out)

    def test_timeout_exits_1_and_says_so(self):
        code, out, err = self.run_cli("time,id,source,dest\n0,a,1,9\n", "--max-ticks", "3")
        self.assertEqual(code, 1)
        self.assertIn("hit max_ticks", out)
        self.assertIn("1 passenger(s) not delivered", err)

    def test_bad_floor_exits_2_without_a_traceback(self):
        code, _, err = self.run_cli("time,id,source,dest\n0,a,0,5\n")
        self.assertEqual(code, 2)
        self.assertIn("below 1", err)


if __name__ == "__main__":
    unittest.main()
