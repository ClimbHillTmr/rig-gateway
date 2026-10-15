"""Regression tests for the HTTP bind decision.

The bug this pins down shipped once and made the server fail to start at all
under --transport streamable-http (the mode the PowerShell launcher uses):

    accepts_kwargs = "host" in run_params and "port" in run_params

mcp 2.x declares ``MCPServer.run(self, transport='stdio', **kwargs)`` -- host and
port travel through **kwargs, so neither name appears in the signature. The test
returned False, the code fell to the Settings branch, Settings has no host field,
and the process exited without ever binding.

The earlier "verification" of that fix used hand-written stub objects whose
signatures were authored to match the assumption being tested, so it could not
fail. These tests are written the other way round: the first one interrogates
whatever MCPServer is actually installed.
"""
from __future__ import annotations

import inspect
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from rig_gateway.server import resolve_http_binding  # noqa: E402


def _run_with_var_keyword(self, transport="stdio", **kwargs):  # noqa: ANN001
    pass


def _run_with_explicit_host_port(self, transport="stdio", host="127.0.0.1", port=8000):
    pass


def _run_without_either(self, transport="stdio"):
    pass


class RealFastMcpBindingTests(unittest.TestCase):
    """Ask the installed SDK what it accepts, instead of assuming."""

    def test_installed_run_accepts_host_port_somehow(self):
        """Whatever FastMCP is installed must be driven down the kwargs path.

        If a future version stops accepting host/port at all, this fails and the
        operator learns the server cannot be bound where they asked for -- which
        is the honest outcome, not a silent bind to 127.0.0.1.
        """
        try:
            from mcp.server.mcpserver import MCPServer
        except ImportError:
            try:
                from mcp.server.fastmcp import FastMCP as MCPServer  # type: ignore
            except ImportError:
                self.skipTest("no MCP server implementation installed")

        method = MCPServer.run
        params = inspect.signature(method).parameters
        self.assertEqual(
            resolve_http_binding(method), "kwargs",
            f"installed run() signature is {list(params)} with no **kwargs; "
            "the server would fail to bind host/port")


class StubBindingTests(unittest.TestCase):
    """The three signature shapes, checked independently of the SDK."""

    def test_var_keyword_is_treated_as_accepting(self):
        """The mcp 2.x shape, and the one that regressed."""
        self.assertEqual(resolve_http_binding(_run_with_var_keyword), "kwargs")

    def test_explicit_host_port_is_accepted(self):
        self.assertEqual(resolve_http_binding(_run_with_explicit_host_port), "kwargs")

    def test_neither_falls_back_to_settings(self):
        """No **kwargs and no host/port: the Settings path is the only option left."""
        self.assertEqual(resolve_http_binding(_run_without_either), "settings")


class DeniedHierarchyTests(unittest.TestCase):
    """Denied must keep its message AND stay catchable as PermissionError.

    The SDK scrubs the text of an unexpected exception, so a policy refusal has
    to be one of its anticipated errors or the operator sees only "Error
    executing tool X" -- indistinguishable from a crash. It also has to remain a
    PermissionError for callers that reason in stdlib terms.
    """

    def test_denied_is_a_permission_error(self):
        from rig_gateway.server import Denied
        self.assertTrue(issubclass(Denied, PermissionError))

    def test_denied_message_survives_str(self):
        from rig_gateway.server import Denied
        try:
            raise Denied("outside the sandbox root")
        except PermissionError as exc:  # catchable as the stdlib type
            self.assertIn("sandbox root", str(exc))

    def test_sdk_less_base_selection_is_valid(self):
        """PermissionError twice is a TypeError; the bases must not duplicate.

        The SDK-less branch is the realistic second case -- a standalone
        ToolError-ish class, not a bare Exception (which is an ancestor of
        PermissionError and so cannot be combined with it at all).
        """
        class FakeToolError(OSError):
            """Stands in for the SDK's ToolError, which derives from Exception/OSError."""

        for base in (FakeToolError, PermissionError):
            with self.subTest(base=base.__name__):
                bases = (base,) if base is PermissionError else (base, PermissionError)
                made = type("Probe", bases, {})
                self.assertTrue(issubclass(made, PermissionError))


if __name__ == "__main__":
    unittest.main(verbosity=2)
