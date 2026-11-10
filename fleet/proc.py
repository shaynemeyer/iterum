"""Process checks shared by run.py and the queue."""

import os
import signal


def group_alive(pgid):
    """True if any process is left in this process group. EPERM means it exists but is not ours."""
    try:
        os.killpg(pgid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def stop_on_sigterm():
    """Make SIGTERM raise KeyboardInterrupt, so a polite stop kills the running command's group as Ctrl-C does.

    Call from the main thread; Python runs signal handlers there.
    """
    signal.signal(signal.SIGTERM, signal.default_int_handler)
