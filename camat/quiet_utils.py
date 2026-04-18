from __future__ import annotations

import os
import ctypes
import threading
from contextlib import contextmanager
from typing import Iterator


# File-descriptor redirection is process-global: if two threads enter
# `suppress_native_output` simultaneously, the saved fds clobber each other and
# stdout/stderr can end up pointing at /dev/null (or at a closed fd) after the
# inner context exits. Using an RLock lets us serialize the redirect window
# without breaking nested calls inside a single thread.
_NATIVE_FD_LOCK = threading.RLock()


def _flush_c_stdio() -> None:
    """
    Best-effort flush of C stdio buffers before fd redirection/restoration.
    """
    try:
        libc = ctypes.CDLL(None)
        fflush = getattr(libc, "fflush", None)
        if fflush is not None:
            fflush.argtypes = [ctypes.c_void_p]
            fflush.restype = ctypes.c_int
            fflush(None)
    except Exception:
        pass


@contextmanager
def suppress_native_output(
    *,
    enabled: bool = True,
    suppress_stdout: bool = True,
    suppress_stderr: bool = True,
) -> Iterator[None]:
    """
    Temporarily redirect process-level stdout/stderr to os.devnull.

    This is intended for noisy native libraries (e.g. Verovio / partitura backends)
    that write directly to file descriptors instead of Python's sys.stdout/sys.stderr.
    """
    if not enabled or (not suppress_stdout and not suppress_stderr):
        yield
        return

    targets = []
    if suppress_stdout:
        targets.append(1)
    if suppress_stderr:
        targets.append(2)

    saved: list[tuple[int, int]] = []
    null_fds: list[int] = []
    acquired = _NATIVE_FD_LOCK.acquire()
    try:
        _flush_c_stdio()
        for target in targets:
            try:
                saved_fd = os.dup(target)
            except OSError:
                continue
            null_fd = os.open(os.devnull, os.O_WRONLY)
            saved.append((target, saved_fd))
            null_fds.append(null_fd)
            os.dup2(null_fd, target)
        yield
    finally:
        _flush_c_stdio()
        for target, saved_fd in reversed(saved):
            try:
                os.dup2(saved_fd, target)
            except OSError:
                pass
            try:
                os.close(saved_fd)
            except OSError:
                pass
        for null_fd in null_fds:
            try:
                os.close(null_fd)
            except OSError:
                pass
        if acquired:
            _NATIVE_FD_LOCK.release()
