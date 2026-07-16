"""Play queue with shuffle and repeat, independent of any backend."""

from __future__ import annotations

import random

from .models import Track

REPEAT_OFF = "off"
REPEAT_ALL = "all"
REPEAT_ONE = "one"


class PlayQueue:
    def __init__(self) -> None:
        self._tracks: list[Track] = []
        self._order: list[int] = []  # play order as indices into _tracks
        self._pos = -1  # position within _order
        self.shuffle = False
        self.repeat = REPEAT_OFF
        self.on_changed = None  # callback()

    # -- inspection ----------------------------------------------------------

    @property
    def tracks(self) -> list[Track]:
        """Tracks in play order."""
        return [self._tracks[i] for i in self._order]

    @property
    def current_index(self) -> int:
        """Index of the current track within play order (-1 if none)."""
        return self._pos

    @property
    def current(self) -> Track | None:
        if 0 <= self._pos < len(self._order):
            return self._tracks[self._order[self._pos]]
        return None

    def __len__(self) -> int:
        return len(self._tracks)

    def peek_next(self) -> Track | None:
        """The track that next() would move to, without moving."""
        nxt = self._next_pos()
        if nxt is None:
            return None
        return self._tracks[self._order[nxt]]

    # -- mutation ------------------------------------------------------------

    def set_tracks(self, tracks: list[Track], start: int = 0) -> None:
        """Replace the queue. `start` is the index (into `tracks`) to play first.

        With shuffle on, the start track is anchored at the head of the
        shuffled order; otherwise the position simply points at it.
        """
        self._tracks = list(tracks)
        self._rebuild_order(anchor=start if 0 <= start < len(tracks) else None)
        self._notify()

    def clear(self) -> None:
        self._tracks = []
        self._order = []
        self._pos = -1
        self._notify()

    def add_next(self, tracks: list[Track]) -> None:
        """Insert tracks right after the current one, in play order."""
        if not tracks:
            return
        base = len(self._tracks)
        self._tracks.extend(tracks)
        # Play order (self._order) is authoritative everywhere; storage order
        # only serves as backing store, so inserting into _order is enough.
        self._order[self._pos + 1 : self._pos + 1] = range(base, base + len(tracks))
        self._notify()

    def add_end(self, tracks: list[Track]) -> None:
        if not tracks:
            return
        base = len(self._tracks)
        self._tracks.extend(tracks)
        self._order.extend(range(base, base + len(tracks)))
        self._notify()

    def remove_at(self, order_index: int) -> None:
        """Remove the track at the given play-order position."""
        if not (0 <= order_index < len(self._order)):
            return
        track_idx = self._order.pop(order_index)
        del self._tracks[track_idx]
        self._order = [i - 1 if i > track_idx else i for i in self._order]
        if order_index < self._pos:
            self._pos -= 1
        elif order_index == self._pos:
            self._pos = min(self._pos, len(self._order) - 1)
        self._notify()

    def move(self, src: int, dst: int) -> None:
        """Move the track at play-order position `src` to position `dst`."""
        n = len(self._order)
        if src == dst or not (0 <= src < n) or not (0 <= dst < n):
            return
        item = self._order.pop(src)
        self._order.insert(dst, item)
        if src == self._pos:
            self._pos = dst
        elif src < self._pos <= dst:
            self._pos -= 1
        elif dst <= self._pos < src:
            self._pos += 1
        self._notify()

    def jump_to(self, order_index: int) -> Track | None:
        if 0 <= order_index < len(self._order):
            self._pos = order_index
            self._notify()
            return self.current
        return None

    # -- traversal -----------------------------------------------------------

    def _next_pos(self) -> int | None:
        if not self._order:
            return None
        if self.repeat == REPEAT_ONE:
            return self._pos
        if self._pos + 1 < len(self._order):
            return self._pos + 1
        if self.repeat == REPEAT_ALL:
            return 0
        return None

    def next(self, manual: bool = False) -> Track | None:
        """Advance and return the new current track (None at queue end).

        With repeat-one, a *manual* skip still moves to the following track;
        only natural track end repeats.
        """
        if not self._order:
            return None
        if self.repeat == REPEAT_ONE and manual:
            if self._pos + 1 < len(self._order):
                self._pos += 1
            self._notify()
            return self.current
        nxt = self._next_pos()
        if nxt is None:
            return None
        self._pos = nxt
        self._notify()
        return self.current

    def previous(self) -> Track | None:
        if not self._order:
            return None
        if self._pos > 0:
            self._pos -= 1
        elif self.repeat == REPEAT_ALL:
            self._pos = len(self._order) - 1
        self._notify()
        return self.current

    def has_next(self) -> bool:
        return self._next_pos() is not None

    # -- modes ---------------------------------------------------------------

    def set_shuffle(self, enabled: bool) -> None:
        if enabled == self.shuffle:
            return
        self.shuffle = enabled
        current_track_idx = self._order[self._pos] if self._pos >= 0 else None
        self._rebuild_order(anchor_track_idx=current_track_idx)
        self._notify()

    def cycle_repeat(self) -> str:
        order = [REPEAT_OFF, REPEAT_ALL, REPEAT_ONE]
        self.repeat = order[(order.index(self.repeat) + 1) % len(order)]
        self._notify()
        return self.repeat

    # -- internals -------------------------------------------------------------

    def _rebuild_order(self, anchor: int | None = None, anchor_track_idx: int | None = None) -> None:
        n = len(self._tracks)
        if anchor_track_idx is None and anchor is not None:
            anchor_track_idx = anchor
        if self.shuffle:
            rest = [i for i in range(n) if i != anchor_track_idx]
            random.shuffle(rest)
            self._order = ([anchor_track_idx] if anchor_track_idx is not None else []) + rest
        else:
            self._order = list(range(n))
        if anchor_track_idx is not None and anchor_track_idx in self._order:
            self._pos = self._order.index(anchor_track_idx)
        elif self._order:
            self._pos = 0
        else:
            self._pos = -1

    def _notify(self) -> None:
        if self.on_changed:
            self.on_changed()
