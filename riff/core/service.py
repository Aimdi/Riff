"""PlaybackService — the heart of the app.

Owns the queue, the mpv engine, the stream resolver and radio autoplay.
The UI (and MPRIS) observe it through simple callback lists.
"""

from __future__ import annotations

import logging

from .. import config
from ..util import _dispatch, run_async
from . import scrobble
from .api import MusicApi
from .library import Library
from .models import Track
from .player import (
    STATE_LOADING,
    STATE_PAUSED,
    STATE_PLAYING,
    STATE_STOPPED,
    PlayerEngine,
)
from .queue import PlayQueue
from .stream import StreamResolver
from .video_gst import GstVideoPlayer, gst_video_available

log = logging.getLogger("riff.service")


class PlaybackService:
    def __init__(
        self,
        api: MusicApi,
        library: Library,
        engine: PlayerEngine,
        resolver: StreamResolver | None = None,
    ):
        self.api = api
        self.library = library
        self.engine = engine
        self.resolver = resolver or StreamResolver(
            quality=config.settings.get("audio_quality", "high")
        )
        self.queue = PlayQueue()

        # observers: lists of callables
        self.track_listeners: list = []      # fn(track | None)
        self.state_listeners: list = []      # fn(state: str)
        self.position_listeners: list = []   # fn(pos: float)
        self.duration_listeners: list = []   # fn(dur: float)
        self.queue_listeners: list = []      # fn()
        self.error_listeners: list = []      # fn(message: str)
        self.video_listeners: list = []      # fn(enabled: bool)
        self.video_paintable_listeners: list = []  # fn(paintable|None)

        self._play_token = 0  # invalidates in-flight resolutions
        self._radio_pending = False
        self._scrobbled_current = False
        self.video_mode = False
        self._video: GstVideoPlayer | None = None
        self._using_gst_video = False
        self._video_state = STATE_STOPPED
        self._video_pos_id = None

        self.queue.on_changed = self._emit_queue_changed
        engine.on_state = self._on_engine_state
        engine.on_position = self._on_engine_position
        engine.on_duration = lambda d: self._emit(self.duration_listeners, d)
        engine.on_track_ended = self._on_track_ended
        engine.on_error = self._on_engine_error

        self.engine.set_volume(int(config.settings.get("volume", 100)))

    # -- public control ------------------------------------------------------

    @property
    def current_track(self) -> Track | None:
        return self.queue.current

    @property
    def state(self) -> str:
        if self._using_gst_video:
            return self._video_state
        return self.engine.state

    def play_tracks(self, tracks: list[Track], start: int = 0) -> None:
        """Replace the queue and start playing."""
        playable = [t for t in tracks if t.video_id or t.local_path]
        if not playable:
            return
        self._maybe_scrobble()
        self.queue.set_tracks(playable, start=start)
        self._start_current()

    def play_track_with_radio(self, track: Track) -> None:
        """Play one track and asynchronously extend the queue with its radio."""
        self.play_tracks([track])
        if config.settings.get("autoplay_radio", True):
            self._extend_with_radio(track)

    def play_from_queue(self, order_index: int) -> None:
        self._maybe_scrobble()
        if self.queue.jump_to(order_index):
            self._start_current()

    def _maybe_scrobble(self) -> None:
        """Submit the current track to ListenBrainz if it played enough."""
        if self._scrobbled_current:
            return
        token = str(config.settings.get("listenbrainz_token", "") or "")
        track = self.queue.current
        if not token or track is None:
            return
        duration = float(track.duration or self.engine.duration or 0)
        if scrobble.should_scrobble(self.engine.position, duration):
            self._scrobbled_current = True
            run_async(lambda: scrobble.submit(token, track),
                      name="riff-scrobble")

    def next(self) -> None:
        self._maybe_scrobble()
        if self.queue.next(manual=True):
            self._start_current()
        else:
            self.engine.stop()
            self._emit(self.track_listeners, None)

    def previous(self) -> None:
        # Standard behaviour: restart the track unless we're near its start.
        if self.engine.position > 5:
            self.engine.seek(0)
            return
        self._maybe_scrobble()
        if self.queue.previous():
            self._start_current()

    def toggle_pause(self) -> None:
        if self._using_gst_video and self._video is not None:
            if self._video_state == STATE_PAUSED:
                self._video.set_paused(False)
                self._video_state = STATE_PLAYING
                self._emit(self.state_listeners, STATE_PLAYING)
            else:
                self._video.set_paused(True)
                self._video_state = STATE_PAUSED
                self._emit(self.state_listeners, STATE_PAUSED)
            return
        if self.engine.state in (STATE_PLAYING, STATE_PAUSED):
            self.engine.toggle_pause()
        elif self.queue.current:
            self._start_current()

    def stop(self) -> None:
        self._play_token += 1
        self._stop_video_backend()
        self.engine.stop()

    def seek(self, seconds: float) -> None:
        if self._using_gst_video and self._video is not None:
            self._video.seek(seconds)
            return
        self.engine.seek(seconds)

    def set_volume(self, volume: int) -> None:
        self.engine.set_volume(volume)
        config.settings.set("volume", int(volume))

    def set_video_mode(self, enabled: bool) -> None:
        """Toggle in-app video for the current (and following) tracks."""
        enabled = bool(enabled)
        if enabled == self.video_mode:
            self._emit(self.video_listeners, self.video_mode)
            return
        if enabled and not gst_video_available():
            self._emit(
                self.error_listeners,
                "In-app video needs gst-plugin-gtk4 — "
                "run: sudo pacman -S gst-plugin-gtk4",
            )
            self.video_mode = False
            self._emit(self.video_listeners, False)
            return
        self.video_mode = enabled
        self._emit(self.video_listeners, enabled)
        # Re-resolve current track in the new mode (keeps place in queue).
        if self.queue.current:
            pos = self.engine.position
            self._start_current()
            # Best-effort seek after a short delay is handled by the UI if needed.
            if pos > 2 and not enabled:
                self.engine.seek(pos)

    def add_next(self, tracks: list[Track]) -> None:
        self.queue.add_next(tracks)

    def add_to_queue(self, tracks: list[Track]) -> None:
        self.queue.add_end(tracks)

    def shutdown(self) -> None:
        self._play_token += 1
        self._stop_video_backend()
        self.engine.shutdown()

    # -- internals -------------------------------------------------------------

    def _stop_video_backend(self) -> None:
        self._using_gst_video = False
        self._video_state = STATE_STOPPED
        if self._video_pos_id is not None:
            try:
                from gi.repository import GLib
                GLib.source_remove(self._video_pos_id)
            except Exception:  # noqa: BLE001
                pass
            self._video_pos_id = None
        if self._video is not None:
            self._video.stop()
        self._emit(self.video_paintable_listeners, None)

    def _on_engine_position(self, pos: float) -> None:
        if self._using_gst_video:
            return  # GStreamer poll owns the scrubber while video is on
        self._emit(self.position_listeners, pos)

    def _ensure_video_player(self) -> GstVideoPlayer:
        if self._video is None:
            self._video = GstVideoPlayer(dispatcher=_dispatch)
            self._video.on_eos = self._on_track_ended
            self._video.on_error = lambda msg: self._emit(
                self.error_listeners, f"Video: {msg}")
        return self._video

    def _start_current(self) -> None:
        track = self.queue.current
        if track is None:
            return
        self._play_token += 1
        self._scrobbled_current = False
        token = self._play_token
        self._stop_video_backend()
        self._emit(self.track_listeners, track)

        local = track.local_path or self.library.download_path(track.video_id)
        if local:
            import os

            if os.path.exists(local):
                self.engine.play_uri(local)
                self._after_start(track)
                return

        want_video = self.video_mode and bool(track.video_id)

        # Resolve the stream URL off the main loop, then start playback.
        def resolve() -> tuple[str, bool]:
            if want_video:
                try:
                    return self.resolver.resolve(track.video_id, video=True), True
                except Exception:  # noqa: BLE001 — fall back to audio
                    log.warning("video stream failed; using audio", exc_info=True)
            return self.resolver.resolve(track.video_id, video=False), False

        def done(result) -> None:
            if token != self._play_token:
                return  # user already skipped elsewhere
            url, is_video = result
            if is_video and self.video_mode and gst_video_available():
                try:
                    self.engine.stop()  # audio from GStreamer instead
                    player = self._ensure_video_player()
                    player.play_uri(url)
                    self._using_gst_video = True
                    self._video_state = STATE_PLAYING
                    self._emit(self.video_paintable_listeners, player.paintable)
                    self._emit(self.state_listeners, STATE_PLAYING)
                    self._start_video_position_poll()
                    self._after_start(track)
                    return
                except Exception as exc:  # noqa: BLE001
                    log.warning("GStreamer video failed: %s", exc)
                    self._stop_video_backend()
                    self._emit(
                        self.error_listeners,
                        f"Couldn't show video — playing audio only ({exc})",
                    )
            self.engine.play_uri(url)
            self._after_start(track)

        def error(exc: Exception) -> None:
            if token != self._play_token:
                return
            log.warning("failed to resolve %s: %s", track.video_id, exc)
            self._emit(self.error_listeners, f"Couldn't play “{track.title}”: {exc}")
            # Skip to the next track instead of going silent.
            if self.queue.has_next():
                self.next()

        self._emit(self.state_listeners, STATE_LOADING)
        run_async(resolve, done, error, name="riff-resolve")

    def _start_video_position_poll(self) -> None:
        if self._video_pos_id is not None:
            return
        try:
            from gi.repository import GLib
        except ImportError:
            return

        def tick() -> bool:
            if not self._using_gst_video or self._video is None:
                self._video_pos_id = None
                return False
            pos = self._video.position()
            dur = self._video.duration()
            self._emit(self.position_listeners, pos)
            if dur > 0:
                self._emit(self.duration_listeners, dur)
            return True

        self._video_pos_id = GLib.timeout_add(250, tick)

    def _after_start(self, track: Track) -> None:
        run_async(lambda: self.library.record_play(track), name="riff-history")
        self._prefetch_next()

    def _prefetch_next(self) -> None:
        nxt = self.queue.peek_next()
        if not nxt or nxt.local_path or not nxt.video_id:
            return
        if self.resolver.cached(nxt.video_id):
            return
        run_async(
            lambda: self.resolver.resolve(nxt.video_id),
            name="riff-prefetch",
        )

    def _extend_with_radio(self, seed: Track) -> None:
        if self._radio_pending or not seed.video_id:
            return
        self._radio_pending = True

        def fetch() -> list[Track]:
            return self.api.radio(seed.video_id)

        def done(tracks: list[Track]) -> None:
            self._radio_pending = False
            tracks = self._without_dislikes(tracks)
            # Only extend if the seed is still what's playing.
            cur = self.queue.current
            if cur and cur.video_id == seed.video_id and tracks:
                self.queue.add_end(tracks)
                self._prefetch_next()
            elif not tracks:
                log.warning("radio for %s returned no tracks", seed.video_id)

        def error(exc: Exception) -> None:
            self._radio_pending = False
            log.warning("radio fetch failed for %s: %s", seed.video_id, exc)
            self._emit(self.error_listeners,
                       "Radio unavailable — playing this song only")

        run_async(fetch, done, error, name="riff-radio")

    def _on_track_ended(self) -> None:
        self._maybe_scrobble()
        nxt = self.queue.next(manual=False)
        if nxt is not None:
            self._start_current()
            return
        # Queue exhausted: optionally keep going with radio.
        cur = self.queue.current
        if cur and config.settings.get("autoplay_radio", True):
            self._continue_radio_after(cur)
        else:
            self._emit(self.state_listeners, STATE_STOPPED)

    def _continue_radio_after(self, last: Track) -> None:
        def fetch() -> list[Track]:
            return self.api.radio(last.video_id)

        def done(tracks: list[Track]) -> None:
            known = {t.video_id for t in self.queue.tracks}
            fresh = [t for t in self._without_dislikes(tracks)
                     if t.video_id not in known]
            if not fresh:
                self._emit(self.state_listeners, STATE_STOPPED)
                return
            self.queue.add_end(fresh)
            if self.queue.next(manual=False):
                self._start_current()

        def error(exc: Exception) -> None:
            log.warning("radio continuation failed: %s", exc)
            self._emit(self.error_listeners,
                       "Couldn't continue with radio — queue ended")
            self._emit(self.state_listeners, STATE_STOPPED)

        run_async(fetch, done, error, name="riff-radio-continue")

    def _without_dislikes(self, tracks: list[Track]) -> list[Track]:
        try:
            banned = self.library.disliked_ids()
        except Exception:  # noqa: BLE001
            return tracks
        return [t for t in tracks if t.video_id not in banned]

    def _on_engine_state(self, state: str) -> None:
        self._emit(self.state_listeners, state)

    def _on_engine_error(self, message: str) -> None:
        self._emit(self.error_listeners, message)
        if self.queue.has_next():
            self.next()

    @staticmethod
    def _safe_call(fn, *args) -> None:
        try:
            fn(*args)
        except Exception:  # noqa: BLE001 — one bad listener must not break others
            log.exception("listener failed")

    def _emit(self, listeners: list, *args) -> None:
        for fn in list(listeners):
            self._safe_call(fn, *args)

    def _emit_queue_changed(self) -> None:
        self._emit(self.queue_listeners)
