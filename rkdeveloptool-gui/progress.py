"""
Progress of a write measured in bytes: overall percent, recent speed and an
estimate of the time left.

Speed comes from the last few seconds only, so a write that slows down (a
busy eMMC, a flaky cable) shows it instead of averaging it away, and no
estimate is offered until there's enough to base one on.
"""
import time

WINDOW_S = 10.0         # speed is measured over this much recent time
MIN_ELAPSED_S = 3.0     # no estimate before this much time has passed


class ProgressTracker:
    def __init__(self, total_bytes, clock=time.monotonic):
        self.total = max(int(total_bytes), 0)
        self._clock = clock
        self._start = clock()
        self._samples = [(self._start, 0)]
        self.done = 0

    def update(self, done_bytes):
        now = self._clock()
        self.done = min(max(int(done_bytes), self.done), self.total)
        self._samples.append((now, self.done))
        # Keep one sample at or before the window's start as the baseline.
        while len(self._samples) > 2 and self._samples[1][0] <= now - WINDOW_S:
            self._samples.pop(0)

    def percent(self):
        return int(self.done * 100 // self.total) if self.total else 0

    def speed(self):
        """Bytes per second over the recent window, or None."""
        (t0, b0), (t1, b1) = self._samples[0], self._samples[-1]
        if t1 - t0 <= 0 or b1 <= b0:
            return None
        return (b1 - b0) / (t1 - t0)

    def eta(self):
        """Seconds left at the recent speed, or None when there isn't
        enough to go on yet."""
        if self._clock() - self._start < MIN_ELAPSED_S or self.done <= 0:
            return None
        speed = self.speed()
        if not speed:
            return None
        return max(self.total - self.done, 0) / speed


def format_speed(bytes_per_s):
    if bytes_per_s >= 1024 ** 2:
        return f"{bytes_per_s / 1024 ** 2:.1f} MB/s"
    return f"{bytes_per_s / 1024:.0f} KB/s"


def format_eta(tr, seconds):
    """'about 2 min 10 s left' in the UI language."""
    seconds = int(round(seconds))
    if seconds >= 60:
        minutes, rest = divmod(seconds, 60)
        return tr("eta_min_s").format(minutes, rest)
    return tr("eta_s").format(max(seconds, 1))
