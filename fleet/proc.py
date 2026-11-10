"""Process checks shared by run.py and the queue."""

import os


def group_alive(pgid):
    """True if any process is left in this process group. EPERM means it exists but is not ours."""
    try:
        os.killpg(pgid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True
