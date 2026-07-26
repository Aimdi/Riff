"""Podcast transcript dialog — follow playback, tap to seek."""

from __future__ import annotations

import logging

from gi.repository import Adw, Gtk, Pango

from ..core.podcast_transcript import (
    TranscriptCue,
    active_cue_index,
    fetch_transcript,
)
from ..util import run_async
from .widgets import spinner_page, status_page

log = logging.getLogger("riff.transcript_ui")


def _fmt_sec(sec: float) -> str:
    if sec < 0:
        return ""
    total = int(sec)
    h, rem = divmod(total, 3600)
    m, s = divmod(rem, 60)
    if h:
        return f"{h}:{m:02d}:{s:02d}"
    return f"{m}:{s:02d}"


class TranscriptDialog(Adw.Dialog):
    def __init__(self, window, *, url: str, type_: str = "", title: str = ""):
        super().__init__()
        self.window = window
        self._url = url
        self._type = type_ or ""
        self._cues: list[TranscriptCue] = []
        self._rows: list[Gtk.ListBoxRow] = []
        self._active = -1
        self._pos_cb = None

        self.set_title("Transcript")
        self.set_content_width(480)
        self.set_content_height(560)

        toolbar = Adw.ToolbarView()
        header = Adw.HeaderBar()
        header.set_title_widget(Gtk.Label(label="Transcript"))
        toolbar.add_top_bar(header)

        self._body = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        self._body.set_margin_top(8)
        self._body.set_margin_bottom(12)
        self._body.set_margin_start(16)
        self._body.set_margin_end(16)
        if title:
            ep = Gtk.Label(label=title)
            ep.add_css_class("dim-label")
            ep.set_xalign(0.0)
            ep.set_ellipsize(Pango.EllipsizeMode.END)
            self._body.append(ep)
        self._host = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        self._host.set_vexpand(True)
        self._host.append(spinner_page())
        self._body.append(self._host)
        scrolled = Gtk.ScrolledWindow()
        scrolled.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        scrolled.set_child(self._body)
        scrolled.set_vexpand(True)
        toolbar.set_content(scrolled)
        self.set_child(toolbar)

        self.connect("closed", self._on_closed)
        self._load()

    def _clear_host(self) -> None:
        while child := self._host.get_first_child():
            self._host.remove(child)

    def _load(self) -> None:
        url, type_ = self._url, self._type

        def work():
            return fetch_transcript(url, type_=type_)

        def done(cues: list[TranscriptCue]) -> None:
            self._clear_host()
            self._cues = cues
            if not cues:
                self._host.append(status_page(
                    "text-x-generic-symbolic", "No transcript",
                    "This document was empty or unreadable."))
                return
            listbox = Gtk.ListBox()
            listbox.set_selection_mode(Gtk.SelectionMode.NONE)
            listbox.add_css_class("riff-discover-list")
            listbox.connect("row-activated", self._on_row)
            self._rows = []
            for i, cue in enumerate(cues):
                row = Gtk.ListBoxRow()
                row.cue_index = i
                row.set_activatable(cue.start_sec >= 0)
                box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
                box.set_margin_top(8)
                box.set_margin_bottom(8)
                head = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
                if cue.start_sec >= 0:
                    ts = Gtk.Label(label=_fmt_sec(cue.start_sec))
                    ts.add_css_class("caption")
                    ts.add_css_class("dim-label")
                    head.append(ts)
                if cue.speaker:
                    sp = Gtk.Label(label=cue.speaker)
                    sp.add_css_class("caption")
                    sp.add_css_class("heading")
                    sp.set_xalign(0.0)
                    head.append(sp)
                if head.get_first_child():
                    box.append(head)
                text = Gtk.Label(label=cue.text)
                text.set_wrap(True)
                text.set_xalign(0.0)
                text.add_css_class("riff-transcript-line")
                box.append(text)
                row.set_child(box)
                listbox.append(row)
                self._rows.append(row)
            self._host.append(listbox)
            self._pos_cb = self._on_position
            self.window.service.position_listeners.append(self._pos_cb)
            try:
                pos = float(self.window.service.engine.position or 0)
            except Exception:  # noqa: BLE001
                pos = 0.0
            self._on_position(pos)

        def fail(exc: Exception) -> None:
            self._clear_host()
            self._host.append(status_page(
                "network-error-symbolic", "Couldn't load transcript", str(exc)))

        run_async(work, done, fail, name="riff-transcript")

    def _on_row(self, _lb, row: Gtk.ListBoxRow) -> None:
        idx = getattr(row, "cue_index", -1)
        if idx < 0 or idx >= len(self._cues):
            return
        cue = self._cues[idx]
        if cue.start_sec < 0:
            return
        self.window.service.seek(cue.start_sec)

    def _on_position(self, pos: float) -> None:
        if not self._cues or not self._rows:
            return
        idx = active_cue_index(self._cues, float(pos or 0))
        if idx == self._active:
            return
        if 0 <= self._active < len(self._rows):
            self._rows[self._active].remove_css_class("accent")
        self._active = idx
        if 0 <= idx < len(self._rows):
            self._rows[idx].add_css_class("accent")

    def _on_closed(self, *_a) -> None:
        cb = getattr(self, "_pos_cb", None)
        if cb is not None:
            try:
                self.window.service.position_listeners.remove(cb)
            except ValueError:
                pass


def open_transcript(window, *, url: str, type_: str = "", title: str = "") -> None:
    if not url:
        window.toast("No transcript for this episode")
        return
    dialog = TranscriptDialog(
        window, url=url, type_=type_, title=title)
    dialog.present(window)
