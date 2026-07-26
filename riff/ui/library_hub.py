"""Library hub — Riff Mobile's Songs/Albums/Artists/more, nested for desktop."""

from __future__ import annotations

from gi.repository import Gtk

from . import iconutil


# (stack_name, title, subtitle, icon)
_LIBRARY_DESTINATIONS = (
    ("explore", "Explore & Discover", "Charts, moods, and personal picks",
     "web-browser-symbolic"),
    ("history", "History", "Recently played",
     "document-open-recent-symbolic"),
    ("local", "Local Files", "Music on this computer",
     "folder-music-symbolic"),
    ("downloads", "Downloads", "Offline songs",
     "folder-download-symbolic"),
    ("stats", "Stats", "Listening insights",
     "riff-stats-symbolic"),
    ("dislikes", "Never Play This", "Banned from radio & mixes",
     "action-unavailable-symbolic"),
)


class LibraryHub(Gtk.Box):
    """Single Library destination that fans out to the rest of the catalog."""

    def __init__(self, window):
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        self.window = window
        self.set_vexpand(True)

        scroll = Gtk.ScrolledWindow()
        scroll.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        scroll.set_vexpand(True)
        self.append(scroll)

        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        box.set_margin_top(20)
        box.set_margin_bottom(100)
        box.set_margin_start(20)
        box.set_margin_end(20)
        scroll.set_child(box)

        title = Gtk.Label(label="Library")
        title.add_css_class("title-1")
        title.set_xalign(0.0)
        box.append(title)

        sub = Gtk.Label(
            label="Everything else from Riff Mobile — history, local, "
                  "downloads, and discovery.")
        sub.add_css_class("dim-label")
        sub.set_wrap(True)
        sub.set_xalign(0.0)
        sub.set_margin_bottom(12)
        box.append(sub)

        listbox = Gtk.ListBox()
        listbox.add_css_class("boxed-list")
        listbox.set_selection_mode(Gtk.SelectionMode.NONE)
        listbox.connect("row-activated", self._on_row)
        box.append(listbox)

        for name, label, subtitle, icon in _LIBRARY_DESTINATIONS:
            row = Gtk.ListBoxRow()
            row.dest_name = name
            row.set_activatable(True)
            inner = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=14)
            inner.set_margin_top(12)
            inner.set_margin_bottom(12)
            inner.set_margin_start(12)
            inner.set_margin_end(12)
            inner.append(iconutil.image(icon))
            text = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
            text.set_hexpand(True)
            t = Gtk.Label(label=label)
            t.add_css_class("heading")
            t.set_xalign(0.0)
            s = Gtk.Label(label=subtitle)
            s.add_css_class("caption")
            s.add_css_class("dim-label")
            s.set_xalign(0.0)
            text.append(t)
            text.append(s)
            inner.append(text)
            chev = Gtk.Label(label="›")
            chev.add_css_class("dim-label")
            chev.add_css_class("title-3")
            inner.append(chev)
            row.set_child(inner)
            listbox.append(row)

    def _on_row(self, _lb, row) -> None:
        name = getattr(row, "dest_name", None)
        if name:
            self.window.goto(name)

    def refresh(self) -> None:
        return
