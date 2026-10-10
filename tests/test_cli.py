import contextlib
import io
import unittest

from spory.cli import build_parser


class ArgumentTests(unittest.TestCase):
    def rejects(self, argv):
        with contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
            build_parser().parse_args(argv)

    def test_margin_must_be_zero_or_more(self):
        self.rejects(["cap", "60", "--margin", "-5"])
        self.rejects(["cap", "--margin", "inf"])
        self.assertEqual(build_parser().parse_args(["cap", "--margin", "0"]).margin, 0)

    def test_durations_and_intervals_must_be_positive(self):
        self.rejects(["charge-now", "--hours", "0"])
        self.rejects(["run", "--interval", "-1"])
        self.rejects(["log", "--interval", "nan"])


if __name__ == "__main__":
    unittest.main()
