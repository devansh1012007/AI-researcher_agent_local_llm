"""Sandbox audit-hook guard for experiment execution.

Security fix (W4 / P0-5): the write root and deny-net flag are bound as
default argument values of ``_guard`` at function definition time (module
import in the child process), capturing ``GAR_EXPERIMENT_WORKDIR`` /
``GAR_EXPERIMENT_NETWORK`` once. User code executed via ``exec()`` in the
same child process can rebind module globals (e.g.
``globals()["_ALLOWED_WRITE_ROOT"] = "/tmp"``) but cannot rebind default
argument values, so the sandbox root cannot be escaped that way.

The guard is installed with ``sys.addaudithook(_guard)`` inside the
experiment child process (see ``experiments/runner.py``).
"""
from __future__ import annotations

import os as _os

_ROOT = _os.environ.get("GAR_EXPERIMENT_WORKDIR", "")
_DENY_NET = _os.environ.get("GAR_EXPERIMENT_NETWORK", "") != "1"


def _guard(event, args, _root=_ROOT, _deny_net=_DENY_NET):
    """Audit-hook callback: deny network/subprocess, contain file writes.

    ``_root`` and ``_deny_net`` are default arguments bound at definition
    time from the env vars read above. They are not module globals read at
    call time, so user code cannot rebind them to escape the sandbox.
    """
    if _deny_net and event in ("socket.connect", "socket.getaddrinfo",
                               "socket.bind"):
        raise PermissionError(
            "network access denied by experiment sandbox")
    if event == "subprocess.Popen":
        raise PermissionError(
            "process spawning denied by experiment sandbox")
    if event == "open" and len(args) >= 3:
        path, mode, flags = args[0], args[1], args[2]
        if not isinstance(path, (str, bytes, _os.PathLike)):
            return
        writable_flags = (_os.O_WRONLY | _os.O_RDWR | _os.O_CREAT |
                          _os.O_APPEND | _os.O_TRUNC)
        try:
            is_write = bool(flags & writable_flags) or any(
                c in str(mode) for c in ("w", "a", "+", "x"))
        except TypeError:
            is_write = False
        if is_write and _root:
            p = _os.path.abspath(
                path.decode() if isinstance(path, bytes) else str(path))
            root = _os.path.abspath(_root)
            if not p.startswith(root + _os.sep) and p != root:
                raise PermissionError(
                    f"write outside experiment sandbox denied: {p}")
