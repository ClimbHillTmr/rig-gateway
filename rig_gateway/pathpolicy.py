"""Shared path policy for the rig gateway.

The rule: **any** path that can cause a write, delete, or move must resolve
inside the approved sandbox root. Read-only paths are unrestricted by default,
because a diagnostic channel that cannot read the thing it is diagnosing is
useless.

Two things this module is careful about, both learned the hard way:

1. ``startswith`` is not containment. ``C:\\rootX`` starts with ``C:\\root``.
   Every check resolves the path and compares *path components*.

2. Canonicalisation is best-effort. The remote filesystem may contain junctions
   we cannot resolve from this machine, so a resolved-inside result is
   necessary but not sufficient. It is still far better than a prefix test, and
   it fails closed for the realistic mistake (a typo landing outside the root).
"""
from __future__ import annotations

import ntpath
import os
import re

ENV_VAR = "RIG_SANDBOX_ROOT"


def active_root() -> str:
    """The sandbox root in force *now*.

    Read from the environment on every call rather than cached at import. A
    cached copy is a second source of truth: the module that enforces the bound
    and the tool that reports it could then disagree, and `host_status` would be
    describing a policy that is not the one being applied. Resolution is
    cheap (a dict lookup) and the alternative is a silent divergence.
    """
    return os.environ.get(ENV_VAR, "").strip()


# Kept for callers that imported the old constant. Do not use in new code;
# prefer active_root(), which cannot go stale.
DEFAULT_ROOT = active_root()

# Drive-relative and UNC forms bypass naive prefix checks; reject them outright.
# Match a bare drive letter with nothing after it (C:, C:file.txt) but NOT a
# proper absolute path (C:\dir\file) -- the backslash after the colon is fine.
_SUSPECT = re.compile(r"^(\\\\|//|[\w]:($|[^\\/]))", re.IGNORECASE)


def _is_ambiguous(raw: str) -> bool:
    """True for UNC, drive-relative and device-prefixed paths.

    Checks the raw input before normalisation, because ``ntpath.abspath``
    silently rewrites ``C:file.txt`` to ``C:\\file.txt`` -- resolving a
    drive-relative path against the wrong root instead of refusing it.
    """
    text = (raw or "").strip().replace("/", "\\")
    if text.startswith("\\\\"):
        return True
    return bool(_SUSPECT.match(text))


class PathDenied(ValueError):
    """Raised when a path falls outside the write sandbox."""


def _norm(path: str) -> str:
    return ntpath.normpath((path or "").replace("/", "\\")).rstrip("\\") or "\\"


def is_contained(candidate: str, root: str) -> bool:
    """True iff *candidate* is *root* or lies beneath it, component-wise."""
    if not candidate or not root:
        return False
    cand, base = _norm(candidate), _norm(root)
    if _is_ambiguous(cand):
        return False
    try:
        rel = ntpath.relpath(cand, base)
    except ValueError:  # different drives
        return False
    if rel == os.curdir:
        return True
    return not rel.startswith("..") and not ntpath.isabs(rel)


def resolve_write_path(path: str, root: str | None = None, *, must_exist: bool = False) -> str:
    """Return the absolute path for a write, or raise PathDenied.

    Call this immediately before *every* mutating operation. Do not cache the
    result across calls -- that is how TOCTOU bugs get in. ``root`` defaults to
    the live environment value; pass it explicitly only in tests.
    """
    root = active_root() if root is None else root
    if not root:
        raise PathDenied(
            "No sandbox root configured. Set RIG_SANDBOX_ROOT to the single "
            "directory this gateway is allowed to modify.")
    if _is_ambiguous(path):
        raise PathDenied(f"Path {path!r} uses a drive-relative or UNC form; use an absolute path.")
    absolute = _norm(ntpath.abspath(_norm(path)))
    if not is_contained(absolute, root):
        raise PathDenied(
            f"Path {path!r} normalises to {absolute!r}, which is outside the sandbox "
            f"root {_norm(root)!r}. Writes are confined to that root by policy.")
    if must_exist and not os.path.exists(absolute):
        raise PathDenied(f"Path {absolute!r} does not exist.")
    return absolute


def resolve_read_path(path: str) -> str:
    """Normalise a read path. Unrestricted, but still absolute and explicit."""
    if _is_ambiguous(path):
        raise PathDenied(f"Path {path!r} uses a drive-relative or UNC form; use an absolute path.")
    return _norm(ntpath.abspath(_norm(path)))


def describe_policy(root: str | None = None) -> dict:
    """Report the live policy. Callers show this instead of asserting safety."""
    root = active_root() if root is None else root
    return {
        "sandbox_root": root or "(unset -- all writes will be refused)",
        "writes_confined_to_root": bool(root),
        "reads_unrestricted": True,
        "rule": "component-wise containment; a prefix match is not containment",
    }