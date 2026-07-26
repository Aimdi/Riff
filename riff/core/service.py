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
from .discovery import DiscoveryEngine
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
        self._engine = engine
        self.resolver = resolver or StreamResolver(
            quality=config.settings.get("audio_quality", "high")
        )
        self.queue = PlayQueue()
        self.discovery = DiscoveryEngine(library, api)

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
        # taste model: where each queued track came from + what's playing
        self._track_sources: dict[str, str] = {}
        self._playing_track = None
        self._last_completed: str | None = None
        self._scrobbled_current = False
        self._last_podcast_save_ts = 0.0
        self.video_mode = False
        self._video: GstVideoPlayer | None = None
        self._using_gst_video = False
        self._video_state = STATE_STOPPED
        self._video_pos_id = None

        # Crossfade: a second mpv deck fades in the next song while the
        # current one fades out (Spotify-style). Spare deck is created
        # lazily on the first fade and then reused forever.
        self._spare_engine: PlayerEngine | None = None
        self._fading = False
        self._fade_old = None

        self.queue.on_changed = self._emit_queue_changed
        self._attach_engine(engine)

        self.engine.set_volume(int(config.settings.get("volume", 100)))

    # -- public control ------------------------------------------------------

    @property
    def engine(self):
        """The active audio deck (swaps during a crossfade)."""
        return self._engine

    def _attach_engine(self, engine) -> None:
        engine.on_state = self._on_engine_state
        engine.on_position = self._on_engine_position
        engine.on_duration = lambda d: self._emit(self.duration_listeners, d)
        engine.on_track_ended = self._on_track_ended
        engine.on_error = self._on_engine_error

    @property
    def current_track(self) -> Track | None:
        return self.queue.current

    @property
    def state(self) -> str:
        # Audio (mpv) is the source of truth for transport state.
        return self.engine.state

    def play_tracks(self, tracks: list[Track], start: int = 0,
                    source: str = "user_click") -> None:
        """Replace the queue and start playing."""
        playable = [
            t for t in tracks
            if t.video_id or t.local_path or (t.stream_url or "").startswith(
                ("http://", "https://"))
        ]
        if not playable:
            return
        self._maybe_scrobble()
        self._tag_sources(playable, source)
        self.queue.set_tracks(playable, start=start)
        self._start_current()

    def _tag_sources(self, tracks, source: str) -> None:
        if len(self._track_sources) > 3000:
            self._track_sources.clear()
        for t in tracks:
            if t.video_id:
                self._track_sources.setdefault(t.video_id, source)

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
        if self.engine.state in (STATE_PLAYING, STATE_PAUSED):
            was_playing = self.engine.state == STATE_PLAYING
            self.engine.toggle_pause()
            # Keep cover video visually in sync with audio.
            if self._using_gst_video and self._video is not None:
                self._video.set_paused(was_playing)
                self._video_state = (
                    STATE_PAUSED if was_playing else STATE_PLAYING)
        elif self.queue.current:
            self._start_current()

    def stop(self) -> None:
        self._play_token += 1
        self._cancel_fade()
        self._stop_video_backend()
        self.engine.stop()

    def seek(self, seconds: float) -> None:
        self.engine.seek(seconds)
        if self._using_gst_video and self._video is not None:
            self._video.seek(seconds)

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

    def add_next(self, tracks: list[Track], source: str = "queue") -> None:
        self._tag_sources(tracks, source)
        self.queue.add_next(tracks)

    def add_to_queue(self, tracks: list[Track], source: str = "queue") -> None:
        self._tag_sources(tracks, source)
        self.queue.add_end(tracks)

    def shutdown(self) -> None:
        self._log_play_transition(natural=False)
        self._play_token += 1
        self._cancel_fade()
        self._stop_video_backend()
        if self._spare_engine is not None:
            try:
                self._spare_engine.shutdown()
            except Exception:  # noqa: BLE001
                pass
            self._spare_engine = None
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
        # Scrubber always follows mpv audio (video is visual-only).
        self._emit(self.position_listeners, pos)
        self._maybe_begin_crossfade(pos)
        self._maybe_save_podcast_progress(pos)

    # -- crossfade ------------------------------------------------------------

    def _crossfade_seconds(self) -> float:
        try:
            return max(0.0, min(12.0, float(
                config.settings.get("crossfade", 0) or 0)))
        except (TypeError, ValueError):
            return 0.0

    def _next_instant_uri(self) -> str | None:
        """URI for the next track only if playable *right now* (local file
        or prefetched stream) — a crossfade can't wait for the network."""
        nxt = self.queue.peek_next()
        if nxt is None:
            return None
        import os

        if nxt.local_path and os.path.exists(nxt.local_path):
            return nxt.local_path
        if nxt.video_id:
            local = self.library.download_path(nxt.video_id)
            if local and os.path.exists(local):
                return local
            return self.resolver.cached(nxt.video_id)
        return None

    def _maybe_begin_crossfade(self, pos: float) -> None:
        if self._fading:
            return
        fade = self._crossfade_seconds()
        if fade <= 0 or self.video_mode or self._using_gst_video:
            return
        duration = float(self.engine.duration or 0)
        # Overlapping most of a very short track sounds broken.
        if duration <= fade * 2.5 or pos < duration - fade:
            return
        uri = self._next_instant_uri()
        if not uri:
            return
        self._begin_crossfade(uri, fade)

    def _obtain_spare(self):
        if self._spare_engine is None:
            self._spare_engine = type(self._engine)(
                dispatcher=getattr(self._engine, "_dispatch", None),
                extra_options=getattr(self._engine, "_extra_options", None))
        spare, self._spare_engine = self._spare_engine, None
        return spare

    def _begin_crossfade(self, uri: str, fade: float) -> None:
        self._log_play_transition(natural=True)
        self._maybe_scrobble()
        old = self._engine
        target = int(config.settings.get("volume", 100))
        spare = self._obtain_spare()

        self._fading = True
        self._fade_old = old
        # New deck becomes the app's engine immediately: position, state
        # and MPRIS all follow the incoming song.
        self._attach_engine(spare)
        spare.set_volume(0)
        spare.play_uri(uri)
        self._engine = spare

        # Advance the queue and tell the UI — Spotify shows the next song
        # as soon as the blend starts.
        self._play_token += 1
        self._scrobbled_current = False
        if self.queue.next(manual=False) is None:
            pass  # repeat-off tail handled by normal end when fade finishes
        track = self.queue.current
        if track is not None:
            self._playing_track = track
            self._emit(self.track_listeners, track)
            self._after_start(track)

        start_pos = float(old.position or 0)

        def old_position(p: float) -> None:
            t = (float(p) - start_pos) / fade if fade else 1.0
            self._apply_fade(min(1.0, max(0.0, t)), target)

        # The outgoing deck only drives the blend now.
        old.on_state = None
        old.on_duration = None
        old.on_error = None
        old.on_position = old_position
        old.on_track_ended = lambda: self._finish_fade(target)

        # Timer smoothing (position events can be sparse). Best-effort:
        # without a main loop the position events alone still complete it.
        try:
            from gi.repository import GLib

            begun = None

            def tick() -> bool:
                nonlocal begun
                import time as _t

                if not self._fading or self._fade_old is not old:
                    return False
                begun = begun or _t.monotonic()
                self._apply_fade(
                    min(1.0, (_t.monotonic() - begun) / fade), target)
                return self._fading
            GLib.timeout_add(100, tick)
        except Exception:  # noqa: BLE001
            pass

    def _apply_fade(self, t: float, target: int) -> None:
        if not self._fading or self._fade_old is None:
            return
        # Equal-power curve: constant perceived loudness through the blend.
        import math

        fade_in = math.sin(t * math.pi / 2)
        fade_out = math.cos(t * math.pi / 2)
        self._fade_old.set_volume(int(round(target * fade_out)))
        self._engine.set_volume(int(round(target * fade_in)))
        if t >= 1.0:
            self._finish_fade(target)

    def _finish_fade(self, target: int) -> None:
        if not self._fading:
            return
        self._fading = False
        old, self._fade_old = self._fade_old, None
        if old is not None:
            old.on_position = None
            old.on_track_ended = None
            old.stop()
            old.set_volume(target)
            self._spare_engine = old  # reuse as the next spare deck
        self._engine.set_volume(target)

    def _cancel_fade(self) -> None:
        """Abort a blend instantly (user skipped or started something new)."""
        if self._fading:
            self._finish_fade(int(config.settings.get("volume", 100)))

    def _ensure_video_player(self) -> GstVideoPlayer:
        if self._video is None:
            self._video = GstVideoPlayer(dispatcher=_dispatch)
            self._video.on_eos = self._on_track_ended
            self._video.on_error = lambda msg: self._emit(
                self.error_listeners, f"Video: {msg}")
        return self._video

    def _log_play_transition(self, natural: bool = False) -> None:
        """Record how much of the outgoing track was heard (taste model)."""
        track, self._playing_track = self._playing_track, None
        if track is None or not track.video_id:
            return
        duration = float(self.engine.duration or track.duration or 0)
        position = float(self.engine.position or 0)
        if natural:
            fraction: float | None = 1.0
        elif duration > 0:
            fraction = max(0.0, min(1.0, position / duration))
        else:
            fraction = None
        source = self._track_sources.get(track.video_id, "queue")
        run_async(lambda: self.library.log_event(
            track, "play", source=source, listened_fraction=fraction),
            name="riff-taste")
        # same-session co-occurrence for meaningful listens
        if fraction is None or fraction >= 0.30:
            prev = self._last_completed
            if prev and prev != track.video_id:
                run_async(lambda: self.library.add_cooccurrence(
                    prev, track.video_id), name="riff-cooc")
            self._last_completed = track.video_id

    def _start_current(self) -> None:
        track = self.queue.current
        if track is None:
            return
        self._log_play_transition(natural=False)
        self._playing_track = track
        self._cancel_fade()
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

        # Podcasts / direct streams — no yt-dlp.
        stream = (track.stream_url or "").strip()
        if stream.startswith(("http://", "https://")):
            self.engine.play_uri(stream)
            self._after_start(track)
            return
        if (track.video_id or "").startswith("podcast_"):
            self._emit(
                self.error_listeners,
                f"Couldn't play “{track.title}”: missing stream URL")
            if self.queue.has_next():
                self.next()
            return

        want_video = self.video_mode and bool(track.video_id)

        # Resolve off the main loop. Video mode always resolves audio for mpv
        # and (when possible) a separate video URL for the cover-art surface.
        def resolve() -> tuple[str, str | None]:
            audio_url = self.resolver.resolve(track.video_id, video=False)
            video_url = None
            if want_video:
                try:
                    video_url = self.resolver.resolve(track.video_id, video=True)
                except Exception:  # noqa: BLE001
                    log.warning("video stream failed; audio only", exc_info=True)
            return audio_url, video_url

        def done(result) -> None:
            if token != self._play_token:
                return  # user already skipped elsewhere
            audio_url, video_url = result
            # Soundtrack always through mpv (reliable, volume/MPRIS/gapless).
            self.engine.play_uri(audio_url)
            if video_url and self.video_mode and gst_video_available():
                try:
                    player = self._ensure_video_player()
                    # Mute GStreamer: YouTube video tracks are often video-only;
                    # even when muxed, dual audio would double/desync.
                    player.play_uri(video_url, mute_audio=True)
                    self._using_gst_video = True
                    self._video_state = STATE_PLAYING
                    self._emit(self.video_paintable_listeners, player.paintable)
                    self._start_video_position_poll()
                except Exception as exc:  # noqa: BLE001
                    log.warning("GStreamer video failed: %s", exc)
                    self._stop_video_backend()
                    self._emit(
                        self.error_listeners,
                        f"Couldn't show video — audio only ({exc})",
                    )
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
        """Occasionally re-sync muted cover video to the mpv audio clock."""
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
            try:
                audio_pos = float(self.engine.position or 0)
                video_pos = float(self._video.position() or 0)
                if audio_pos > 0 and abs(audio_pos - video_pos) > 0.45:
                    self._video.seek(audio_pos)
            except Exception:  # noqa: BLE001
                pass
            return True

        self._video_pos_id = GLib.timeout_add(1000, tick)

    def _after_start(self, track: Track) -> None:
        run_async(lambda: self.library.record_play(track), name="riff-history")
        self._prefetch_next()
        self._maybe_resume_podcast(track)

    def _maybe_resume_podcast(self, track: Track) -> None:
        from . import podcast_progress as pp

        if not pp.is_podcast_track(track):
            return
        row = self.library.podcast_progress(track.video_id)
        if not row:
            return
        seek_to = pp.resume_seconds(
            int(row.get("position_ms") or 0),
            int(row.get("duration_ms") or 0),
        )
        if seek_to is None:
            return
        try:
            self.engine.seek(seek_to)
        except Exception:  # noqa: BLE001
            log.debug("podcast resume seek failed", exc_info=True)

    def _maybe_save_podcast_progress(self, pos: float) -> None:
        """Throttle-save podcast position (~every 5s), matching mobile."""
        import time

        from . import podcast_progress as pp

        track = self.queue.current
        if not pp.is_podcast_track(track):
            return
        dur = float(self.engine.duration or track.duration or 0)
        if dur <= 0:
            return
        pos_ms = int(max(0.0, pos) * 1000)
        dur_ms = int(dur * 1000)
        near_end = pp.is_finished(pos_ms, dur_ms)
        now = time.monotonic()
        if not near_end and now - self._last_podcast_save_ts < 5.0:
            return
        self._last_podcast_save_ts = now
        artists = track.artists or []
        self.library.save_podcast_progress(
            track.video_id,
            title=track.title or "",
            artist=artists[0] if artists else "",
            artwork=track.thumbnail or "",
            stream_url=track.stream_url or "",
            position_ms=pos_ms,
            duration_ms=dur_ms,
            transcript_url=getattr(track, "transcript_url", "") or "",
            transcript_type=getattr(track, "transcript_type", "") or "",
        )

    def _prefetch_next(self) -> None:
        nxt = self.queue.peek_next()
        if not nxt or nxt.local_path or not nxt.video_id:
            return
        # Direct streams / podcasts already have a URI.
        if (nxt.stream_url or "").startswith(("http://", "https://")):
            return
        if (nxt.video_id or "").startswith(
                ("podcast_", "librivox_", "abs_", "cloud_")):
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
        if (seed.video_id or "").startswith(
                ("podcast_", "librivox_", "abs_", "cloud_")) or (
                seed.stream_url or "").startswith(("http://", "https://")):
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
                tracks = self._smart_radio(seed, tracks)
                self._tag_sources(tracks, "radio")
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
        self._log_play_transition(natural=True)
        self._maybe_scrobble()
        ended = self.queue.current
        if ended and (ended.video_id or "").startswith("podcast_"):
            self.library.clear_podcast_progress(ended.video_id)
        nxt = self.queue.next(manual=False)
        if nxt is not None:
            self._start_current()
            return
        # Queue exhausted: optionally keep going with radio.
        cur = self.queue.current
        if cur and config.settings.get("autoplay_radio", True) and not (
                (cur.video_id or "").startswith(
                    ("podcast_", "librivox_", "abs_", "cloud_"))
                or (cur.stream_url or "").startswith(("http://", "https://"))):
            self._continue_radio_after(cur)
        else:
            self._emit(self.state_listeners, STATE_STOPPED)

    def _continue_radio_after(self, last: Track) -> None:
        if (last.video_id or "").startswith(
                ("podcast_", "librivox_", "abs_", "cloud_")):
            self._emit(self.state_listeners, STATE_STOPPED)
            return

        def fetch() -> list[Track]:
            return self.api.radio(last.video_id)

        def done(tracks: list[Track]) -> None:
            known = {t.video_id for t in self.queue.tracks}
            fresh = [t for t in self._smart_radio(last, tracks)
                     if t.video_id not in known]
            if not fresh:
                self._emit(self.state_listeners, STATE_STOPPED)
                return
            self._tag_sources(fresh, "radio")
            self.queue.add_end(fresh)
            if self.queue.next(manual=False):
                self._start_current()

        def error(exc: Exception) -> None:
            log.warning("radio continuation failed: %s", exc)
            self._emit(self.error_listeners,
                       "Couldn't continue with radio — queue ended")
            self._emit(self.state_listeners, STATE_STOPPED)

        run_async(fetch, done, error, name="riff-radio-continue")

    def _smart_radio(self, seed: Track, tracks: list[Track]) -> list[Track]:
        """Post-process raw radio through the discovery pipeline (dedupe
        vs session + last 7 days, artist caps, skip-rate penalties).
        Falls back to plain dislike-filtering if the engine chokes."""
        try:
            out = self.discovery.smart_radio_batch(
                seed, tracks, history_window=self.queue.tracks)
            return out if out else self._without_dislikes(tracks)
        except Exception:  # noqa: BLE001 — autoplay must never die
            log.exception("smart radio post-processing failed")
            return self._without_dislikes(tracks)

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
