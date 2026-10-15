"""The sandbox has to hold at the *tool* boundary, not just inside pathpolicy.

test_pathpolicy.py proves `resolve_write_path` is correct. That is necessary and
was not sufficient: `transfer_out` called it for neither endpoint's write side,
so a copy could be written anywhere on the host while every pathpolicy test
stayed green. These tests drive the real tools with a real sandbox root and
assert the escape attempts fail.

Confinement is checked by calling the tools, with RIG_SANDBOX_ROOT pointed at a
temporary directory, and asserting nothing lands outside it.
"""
from __future__ import annotations

import os
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

# Imported once, deliberately: the policy root is read from the environment at
# call time, so these tests need no module reload to change it. If someone
# re-introduces an import-time cache, the confinement tests below fail -- which
# is the point. A cached root is a policy that can disagree with the one
# host_status reports.
from rig_gateway import server  # noqa: E402


class _TempRootCase(unittest.TestCase):
    prefix = "rig_sandbox_"

    def setUp(self):
        self.sandbox = Path(tempfile.mkdtemp(prefix=self.prefix))
        self._env = dict(os.environ)
        os.environ["RIG_SANDBOX_ROOT"] = str(self.sandbox)
        os.environ.pop("RIG_ALLOW_OVERWRITE", None)
        os.environ.pop("RIG_ALLOW_TIER3", None)

    def tearDown(self):
        os.environ.clear()
        os.environ.update(self._env)
        shutil.rmtree(self.sandbox, ignore_errors=True)


class SandboxToolTests(_TempRootCase):
    def setUp(self):
        super().setUp()
        self.outside = Path(tempfile.mkdtemp(prefix="rig_outside_"))
        self.server = server

    def tearDown(self):
        shutil.rmtree(self.outside, ignore_errors=True)
        super().tearDown()

    def test_transfer_out_cannot_write_outside_sandbox(self):
        """The regression this file exists for: the copy target is a write too."""
        src = self.outside / "payload.txt"
        src.write_text("escape", encoding="utf-8")
        target = self.outside / "escaped.txt"
        with self.assertRaises(self.server.Denied):
            self.server.transfer_out(remote_path=str(src), local_path=str(target))
        self.assertFalse(target.exists(), "transfer_out wrote outside the sandbox root")

    def test_transfer_in_cannot_read_outside_sandbox(self):
        """The mirror hole: an unrestricted read is still only a read, but
        transfer_in's *source* used to reach any path on the host unchecked."""
        src = self.outside / "payload.txt"
        src.write_text("escape", encoding="utf-8")
        with self.assertRaises(self.server.Denied):
            self.server.transfer_in(local_path=str(src), remote_path=str(self.outside / "x"))

    def test_transfer_out_inside_sandbox_still_works(self):
        """A confinement fix that breaks the legitimate case is not a fix."""
        src = self.sandbox / "src.txt"
        src.write_text("data", encoding="utf-8")
        dst = self.sandbox / "copy.txt"
        result = self.server.transfer_out(remote_path=str(src), local_path=str(dst))
        self.assertTrue(dst.exists())
        self.assertEqual(result["to"], str(dst))

    def test_write_outside_sandbox_is_refused(self):
        with self.assertRaises(self.server.Denied):
            self.server.write_file(path=str(self.outside / "nope.txt"), content="x")
        self.assertFalse((self.outside / "nope.txt").exists())

    def test_delete_outside_sandbox_is_refused(self):
        victim = self.outside / "keep.txt"
        victim.write_text("keep", encoding="utf-8")
        with self.assertRaises(self.server.Denied):
            self.server.delete_path(path=str(victim))
        self.assertTrue(victim.exists(), "delete_path removed a file outside the sandbox")

    def test_move_outside_sandbox_is_refused_on_either_endpoint(self):
        src = self.sandbox / "a.txt"
        src.write_text("a", encoding="utf-8")
        with self.assertRaises(self.server.Denied):
            self.server.move_path(source=str(src), destination=str(self.outside / "b.txt"))
        self.assertFalse((self.outside / "b.txt").exists())


class OverwriteTests(_TempRootCase):
    """The two-key rule, and the documented parameter that used to not exist."""

    def setUp(self):
        super().setUp()
        self.server = server

    def test_overwrite_parameter_exists(self):
        """Callers must be able to pass the parameter the docstring names."""
        import inspect
        sig = inspect.signature(self.server.write_file)
        self.assertIn("overwrite", sig.parameters)

    def test_overwrite_refused_without_flag(self):
        target = self.sandbox / "f.txt"
        self.server.write_file(path=str(target), content="one")
        with self.assertRaises(self.server.Denied):
            self.server.write_file(path=str(target), content="two", overwrite=True)

    def test_overwrite_refused_without_operator_env(self):
        """Caller consent alone is not enough; the operator must opt in too."""
        target = self.sandbox / "f.txt"
        self.server.write_file(path=str(target), content="one")
        os.environ["RIG_ALLOW_OVERWRITE"] = "1"
        self.server.write_file(path=str(target), content="two", overwrite=True)
        self.assertEqual(target.read_text(encoding="utf-8"), "two")

    def test_overwrite_requires_both_keys(self):
        target = self.sandbox / "f.txt"
        self.server.write_file(path=str(target), content="one")
        os.environ["RIG_ALLOW_OVERWRITE"] = "1"
        with self.assertRaises(self.server.Denied):
            self.server.write_file(path=str(target), content="two", overwrite=False)
        self.assertEqual(target.read_text(encoding="utf-8"), "one")


class SelfCheckUrlTests(unittest.TestCase):
    """host_status must not crash on its own documented input."""

    def setUp(self):
        self._env = dict(os.environ)
        os.environ.pop("RIG_SELF_CHECK_URL", None)

    def tearDown(self):
        os.environ.clear()
        os.environ.update(self._env)

    def test_documented_mcp_endpoint_parses(self):
        """'http://host:8099/mcp' used to raise ValueError from int('8099/mcp')."""
        from rig_gateway import server
        os.environ["RIG_SELF_CHECK_URL"] = "http://127.0.0.1:1/mcp"
        result = server.host_status()  # port 1: connection refused, not a crash
        self.assertNotIn("parse_error", result)
        self.assertIn("tcp_open", result)

    def test_bare_host_port_parses(self):
        from rig_gateway import server
        os.environ["RIG_SELF_CHECK_URL"] = "127.0.0.1:1"
        result = server.host_status()
        self.assertNotIn("parse_error", result)

    def test_unparseable_url_is_reported_not_raised(self):
        from rig_gateway import server
        os.environ["RIG_SELF_CHECK_URL"] = "http://:notaport/mcp"
        result = server.host_status()
        self.assertIn("parse_error", result)

    def test_unset_url_reports_rather_than_probing(self):
        from rig_gateway import server
        result = server.host_status()
        self.assertIn("note", result)


if __name__ == "__main__":
    unittest.main(verbosity=2)
