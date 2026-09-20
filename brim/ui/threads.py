"""Shutting worker threads down without taking the process with them.

Two different crashes taught this file its shape, and both are easy to hit:

Close the window while a background resolve runs and Qt calls qFatal from
~QThread, because PySide destroys every QObject when QApplication goes away:

    QThread::~QThread() .cold
    PySide::destroyQCoreApplication()

The obvious fix, terminate the stragglers, is worse. Killing a QThread that is
executing Python bytecode leaves the interpreter holding a half released GIL
and the abort turns into a segfault. Killing one parked inside libdnf5 would
leave librpm and libsolv mid read.

So nothing is ever terminated. Workers are asked to stop, waited for, and the
process exits without running Qt teardown if any refuse. Settings are written
synchronously the moment they change, so there is nothing pending to lose.
"""

from __future__ import annotations

import os
import sys
import weakref

from PySide6.QtCore import QThread

# Long enough for a repo sack load or a COPR round trip to land on its own.
GRACE_MS = 6000

_live: weakref.WeakSet = weakref.WeakSet()


class Worker(QThread):
    """A background thread that shutdown can always find."""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        _live.add(self)


def stop_thread(thread: QThread | None, grace_ms: int = GRACE_MS) -> bool:
    """Ask a worker to finish and wait. True if it actually stopped."""
    if thread is None:
        return True
    try:
        if not thread.isRunning():
            return True
        thread.requestInterruption()
        return bool(thread.wait(grace_ms))
    except RuntimeError:
        # The C++ object is already gone, which is the state we wanted.
        return True


def stop_all(*threads: QThread | None) -> bool:
    return all([stop_thread(t) for t in threads])


def stop_registered(grace_ms: int = GRACE_MS) -> bool:
    """Last line of defence: catches workers owned by dialogs."""
    return all([stop_thread(t, grace_ms) for t in list(_live)])


def any_running() -> bool:
    for thread in list(_live):
        try:
            if thread.isRunning():
                return True
        except RuntimeError:
            continue
    return False


def exit_now(code: int = 0) -> None:
    """Leave without running Qt teardown.

    Only reached when a worker is still blocked in a C call that cannot be
    interrupted. Skipping finalisation is safe here and is the one option
    that neither aborts nor segfaults.
    """
    sys.stdout.flush()
    sys.stderr.flush()
    os._exit(code)
