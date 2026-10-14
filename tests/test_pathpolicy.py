"""Tests for the write-sandbox policy.

These are the security boundary, so they are adversarial rather than happy-path:
a test that only proves "the allowed path worked" cannot catch a containment
regression. Every case below is an attempt to write outside the root.
"""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from rig_gateway.pathpolicy import (  # noqa: E402
    PathDenied,
    describe_policy,
    is_contained,
    resolve_read_path,
    resolve_write_path,
)

ROOT = r"C:\approved\root"


class ContainmentTests(unittest.TestCase):
    def test_prefix_is_not_containment(self):
        """The bug this whole module exists to prevent."""
        self.assertFalse(is_contained(r"C:\approved\rootX", ROOT))
        self.assertFalse(is_contained(r"C:\approved\root2\sub", ROOT))
        self.assertTrue(is_contained(r"C:\approved\root\sub\file.txt", ROOT))

    def test_root_itself_is_contained(self):
        self.assertTrue(is_contained(ROOT, ROOT))

    def test_normalisation(self):
        self.assertTrue(is_contained(r"C:\approved\root\sub\..\ok.txt", ROOT))
        self.assertFalse(is_contained(r"C:\approved\root\..\escape.txt", ROOT))

    def test_other_drive_rejected(self):
        self.assertFalse(is_contained(r"D:\approved\root\a.txt", ROOT))

    def test_empty_inputs_rejected(self):
        self.assertFalse(is_contained("", ROOT))
        self.assertFalse(is_contained(ROOT, ""))


class WritePathTests(unittest.TestCase):
    def assert_allowed(self, path: str) -> None:
        resolve_write_path(path, ROOT)  # must not raise

    def assert_denied(self, path: str) -> None:
        with self.assertRaises(PathDenied, msg=f"should have denied {path!r}"):
            resolve_write_path(path, ROOT)

    def test_allows_paths_inside_root(self):
        for path in (ROOT, ROOT + r"\a.txt", ROOT + r"\sub\dir\deep\file.bin"):
            with self.subTest(path=path):
                self.assert_allowed(path)

    def test_denies_sibling_prefix(self):
        for path in (r"C:\approved\rootX\a.txt", r"C:\approved\root2", r"C:\approved\root-2\x"):
            with self.subTest(path=path):
                self.assert_denied(path)

    def test_denies_escape_attempts(self):
        for path in (r"C:\approved\root\..\..\Windows\Temp\x",
                     r"C:\Windows\System32\drivers\etc\hosts",
                     r"..\..\sneaky.txt"):
            with self.subTest(path=path):
                self.assert_denied(path)

    def test_denies_ambiguous_forms(self):
        for path in (r"\\server\share\x", r"//server/share/x", r"C:relative.txt"):
            with self.subTest(path=path):
                self.assert_denied(path)

    def test_fails_closed_without_configured_root(self):
        """Unconfigured sandbox must refuse writes, not allow them."""
        for path in (ROOT + r"\a.txt", r"C:\Windows\x"):
            with self.subTest(path=path):
                with self.assertRaises(PathDenied):
                    resolve_write_path(path, "")

    def test_error_message_names_the_boundary(self):
        """The message must let the operator see which root was enforced.

        The path is repr'd, so backslashes appear doubled -- compare against the
        repr of the root, not the raw string, or the assertion fails on escaping
        rather than on the actual behaviour.
        """
        with self.assertRaises(PathDenied) as ctx:
            resolve_write_path(r"C:\Windows\x", ROOT)
        message = str(ctx.exception)
        self.assertIn(repr(ROOT).strip("'"), message)
        self.assertIn("sandbox root", message)


class ReadPathTests(unittest.TestCase):
    def test_reads_are_not_sandboxed(self):
        self.assertEqual(resolve_read_path(r"C:\Windows\System32"), r"C:\Windows\System32")

    def test_reads_still_reject_ambiguous_forms(self):
        with self.assertRaises(PathDenied):
            resolve_read_path(r"C:file.txt")


class PolicyReportTests(unittest.TestCase):
    def test_report_states_the_boundary(self):
        report = describe_policy(ROOT)
        self.assertTrue(report["writes_confined_to_root"])
        self.assertEqual(report["sandbox_root"], ROOT)

    def test_report_is_honest_when_unconfigured(self):
        report = describe_policy("")
        self.assertFalse(report["writes_confined_to_root"])
        self.assertIn("unset", report["sandbox_root"])


if __name__ == "__main__":
    unittest.main(verbosity=2)