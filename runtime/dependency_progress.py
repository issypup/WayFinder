"""Bounded worker-to-GUI progress delivery without calling Tk from a worker."""
from threading import Lock


class DependencyProgress:
    """Keep the newest status and preserve one terminal result independently."""

    def __init__(self):
        self._lock = Lock()
        self._progress = None
        self._terminal = None
        self._finished = False

    def put(self, message):
        with self._lock:
            if self._finished:
                return
            if message[0] == 'progress':
                self._progress = message
            else:
                self._terminal = message
                self._finished = True

    def take(self):
        """Return at most two events, releasing the lock before GUI rendering."""
        with self._lock:
            messages = [m for m in (self._progress, self._terminal) if m is not None]
            self._progress = self._terminal = None
        return messages
