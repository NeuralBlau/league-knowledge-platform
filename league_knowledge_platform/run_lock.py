"""A local nonblocking OS guard; no lease, heartbeat, PID file, or SQL transaction."""

from contextlib import contextmanager
import errno
import os
from pathlib import Path

from .run_models import RunStateError


class RunBusyError(RunStateError):
    """Another local invocation owns the database execution guard."""


@contextmanager
def execution_guard(database_path: Path):
    lock_path = database_path.with_name(database_path.name + ".lock")
    try:
        lock_path.parent.mkdir(parents=True, exist_ok=True)
        handle = open(lock_path, "a+b")
    except OSError as error:
        raise RunStateError("Cannot open the local run execution guard") from error
    locked = False
    try:
        try:
            if os.name == "nt":
                import msvcrt
                handle.seek(0)
                msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            locked = True
        except OSError as error:
            if error.errno in (errno.EACCES, errno.EAGAIN, errno.EDEADLK):
                raise RunBusyError("Another local run invocation is active") from None
            raise RunStateError("Cannot acquire the local run execution guard") from error
        yield
    finally:
        try:
            if locked:
                if os.name == "nt":
                    import msvcrt
                    handle.seek(0)
                    msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
                else:
                    import fcntl
                    fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
        finally:
            # Keep the inode/path stable; unlinking a lock file permits split ownership.
            handle.close()
