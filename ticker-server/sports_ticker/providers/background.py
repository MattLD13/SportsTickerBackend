"""Own one background task and defer cleanup until its request ends."""

from threading import Lock, Thread, current_thread


class BackgroundTask:
    def __init__(self, cleanup, *, wait_seconds=2.0, thread_factory=Thread):
        self._cleanup = cleanup
        self._wait = wait_seconds
        self._lock = Lock()
        self._thread = None
        self._closed = False
        self._cleaned = False
        self._thread_factory = thread_factory

    def start(self, target, *, name, args=()):
        with self._lock:
            if self._closed or self._thread is not None:
                return False
            thread = self._thread_factory(target=self._run, args=(target, args), name=name, daemon=True)
            self._thread = thread
        try:
            thread.start()
        except BaseException:
            with self._lock:
                self._thread = None
                cleanup = self._take_cleanup()
            if cleanup is not None:
                cleanup()
            raise
        return True

    def _run(self, target, args):
        try:
            with self._lock:
                allowed = not self._closed
            if allowed:
                target(*args)
        finally:
            with self._lock:
                self._thread = None
                cleanup = self._take_cleanup()
            if cleanup is not None:
                cleanup()

    def _take_cleanup(self):
        if self._closed and self._thread is None and not self._cleaned:
            self._cleaned = True
            return self._cleanup
        return None

    def close(self):
        with self._lock:
            self._closed = True
            thread = self._thread
            cleanup = self._take_cleanup()
        if thread is not None and thread is not current_thread() and getattr(thread, "is_alive", lambda: False)():
            thread.join(self._wait)
        if cleanup is not None:
            cleanup()
