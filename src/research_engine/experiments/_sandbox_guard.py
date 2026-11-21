"""Audit-hook guard for experiment child processes.

The root and network policy are captured in a closure created before user code
runs. Paths are resolved (including existing symlink parents) before checks.
This is defence in depth, not a replacement for an OS-level sandbox: Python
audit hooks do not make hostile in-process code a security boundary.
"""
from __future__ import annotations

import os as _os
from pathlib import Path as _Path


def build_guard(root: str, deny_net: bool = True):
    """Create a guard whose trusted values are closure cells, not env lookups."""
    # Capture helpers and flags before task code can mutate imported modules.
    path_type = _Path
    path_resolve = path_type.resolve
    path_is_relative_to = path_type.is_relative_to
    path_like_type = _os.PathLike
    fsdecode = _os.fsdecode
    permission_error = PermissionError
    writable_flags = (_os.O_WRONLY | _os.O_RDWR | _os.O_CREAT |
                      _os.O_APPEND | _os.O_TRUNC)
    root_path = path_resolve(path_type(root), strict=True)
    mutation_paths = {
        "os.mkdir": ((0,), (2,)),
        "os.remove": ((0,), (1,)),
        "os.rmdir": ((0,), (1,)),
        "os.chmod": ((0,), (2,)),
        "os.chown": ((0,), (3,)),
        "os.truncate": ((0,), ()),
        "os.utime": ((0,), (3,)),
        "os.symlink": ((1,), (2,)),
        "os.link": ((0, 1), (2, 3)),
        "os.rename": ((0, 1), (2, 3)),
        "os.replace": ((0, 1), (2, 3)),
    }

    def require_inside(path) -> None:
        if not isinstance(path, (str, bytes, path_like_type)):
            raise permission_error("sandbox cannot validate non-path filesystem operation")
        try:
            candidate = path_resolve(path_type(fsdecode(path)), strict=False)
        except (OSError, RuntimeError, ValueError) as exc:
            raise permission_error("sandbox cannot resolve filesystem path") from exc
        if candidate != root_path and not path_is_relative_to(candidate, root_path):
            raise permission_error(
                f"filesystem operation outside experiment sandbox denied: {candidate}"
            )

    def guard(event, args):
        if deny_net and event in ("socket.connect", "socket.getaddrinfo",
                                  "socket.bind"):
            raise PermissionError("network access denied by experiment sandbox")
        if event == "subprocess.Popen":
            raise PermissionError("process spawning denied by experiment sandbox")
        if event == "open" and len(args) >= 3:
            path, mode, flags = args[0], args[1], args[2]
            try:
                is_write = bool(flags & writable_flags) or any(
                    c in str(mode) for c in ("w", "a", "+", "x"))
            except TypeError:
                is_write = False
            if is_write:
                require_inside(path)
            return

        paths = mutation_paths.get(event)
        if paths is None:
            return
        path_indexes, dir_fd_indexes = paths
        # dir_fd makes a string path relative to an arbitrary open directory;
        # Python uses -1/None for the default "no dir_fd" value. Refuse only
        # active descriptors so ordinary in-workdir operations still work.
        if any(index < len(args) and args[index] not in (None, -1)
               for index in dir_fd_indexes):
            raise PermissionError("dir_fd filesystem operations are denied by sandbox")
        for index in path_indexes:
            if index < len(args):
                require_inside(args[index])

    return guard
