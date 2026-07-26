"""Sleep timer state machine (Riff Mobile PlayerController port).

Pure helpers + a small runner used by PlaybackService. No ``gi``.
"""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass
from typing import Callable


PRESETS_MINUTES = (5, 10, 15, 30, 45, 60)


@dataclass
class SleepTimerState:
    active: bool = False
    end_of_song: bool = False
    ends_at: float = 0.0  # monotonic deadline when timed
    label: str = ""


class SleepTimer:
    def __init__(self, on_fire: Callable[[], None]):
        self._on_fire = on_fire
        self._lock = threading.Lock()
        self._state = SleepTimerState()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    @property
    def state(self) -> SleepTimerState:
        with self._lock:
            return SleepTimerState(
                active=self._state.active,
                end_of_song=self._state.end_of_song,
                ends_at=self._state.ends_at,
                label=self._state.label,
            )

    def start_minutes(self, minutes: int) -> None:
        minutes = max(1, int(minutes))
        with self._lock:
            self._state = SleepTimerState(
                active=True,
                end_of_song=False,
                ends_at=time.monotonic() + minutes * 60,
                label=f"{minutes} min",
            )
        self._ensure_thread()

    def start_end_of_song(self) -> None:
        with self._lock:
            self._state = SleepTimerState(
                active=True,
                end_of_song=True,
                ends_at=0.0,
                label="End of song",
            )
        self._ensure_thread()

    def add_five_minutes(self) -> None:
        with self._lock:
            if not self._state.active or self._state.end_of_song:
                return
            self._state.ends_at += 300
            left = max(0, int(self._state.ends_at - time.monotonic()))
            self._state.label = f"{left // 60} min"

    def cancel(self) -> None:
        with self._lock:
            self._state = SleepTimerState()

    def remaining_seconds(self) -> float | None:
        with self._lock:
            if not self._state.active or self._state.end_of_song:
                return None
            return max(0.0, self._state.ends_at - time.monotonic())

    def on_track_ending(self) -> bool:
        """Call when current track ends. Returns True if timer consumed pause."""
        with self._lock:
            if self._state.active and self._state.end_of_song:
                self._state = SleepTimerState()
                return True
        return False

    def _ensure_thread(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(
            target=self._loop, name="riff-sleep-timer", daemon=True)
        self._thread.start()

    def _loop(self) -> None:
        while not self._stop.wait(1.0):
            fire = False
            with self._lock:
                if not self._state.active:
                    return
                if not self._state.end_of_song and (
                        time.monotonic() >= self._state.ends_at):
                    self._state = SleepTimerState()
                    fire = True
            if fire:
                try:
                    self._on_fire()
                except Exception:  # noqa: BLE001
                    pass
                return
