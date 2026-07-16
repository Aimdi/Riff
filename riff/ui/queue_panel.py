"""Sidebar showing the current play queue."""

from __future__ import annotations

from gi.repository import Gdk, GObject, Gtk, Pango

from .widgets import CoverArt, build_track_menu, menu_dots_button


class QueuePanel(Gtk.Box):
    def __init__(self, window):
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        self.window = window
        self.service = window.service

        header = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        header.set_margin_top(12)
        header.set_margin_start(12)
        header.set_margin_end(12)
        title = Gtk.Label(label="Queue")
        title.add_css_class("title-3")
        title.set_hexpand(True)
        title.set_xalign(0.0)
        header.append(title)
        clear = Gtk.Button.new_from_icon_name("user-trash-symbolic")
        clear.add_css_class("flat")
        clear.set_tooltip_text("Clear queue")
        clear.connect("clicked", self._on_clear)
        header.append(clear)
        self.append(header)

        self.listbox = Gtk.ListBox()
        self.listbox.set_selection_mode(Gtk.SelectionMode.NONE)
        self.listbox.add_css_class("navigation-sidebar")
        self.listbox.connect("row-activated", self._on_activated)

        scroller = Gtk.ScrolledWindow()
        scroller.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        scroller.set_vexpand(True)
        scroller.set_child(self.listbox)
        self.append(scroller)

        self.service.queue_listeners.append(self.refresh)
        self.service.track_listeners.append(lambda _t: self.refresh())
        self.refresh()

    def refresh(self) -> None:
        self.listbox.remove_all()
        queue = self.service.queue
        current = queue.current_index
        for i, track in enumerate(queue.tracks):
            row = Gtk.ListBoxRow()
            box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
            box.set_margin_top(4)
            box.set_margin_bottom(4)
            box.set_margin_start(6)
            box.set_margin_end(6)

            if i == current:
                icon = Gtk.Image.new_from_icon_name(
                    "media-playback-start-symbolic")
                icon.add_css_class("accent")
                box.append(icon)
            else:
                num = Gtk.Label(label=str(i + 1))
                num.add_css_class("dim-label")
                num.add_css_class("caption")
                num.set_width_chars(2)
                box.append(num)

            art = CoverArt(36)
            art.set_url(track.thumbnail)
            box.append(art)

            text = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
            text.set_valign(Gtk.Align.CENTER)
            text.set_hexpand(True)
            t = Gtk.Label(label=track.title)
            t.set_ellipsize(Pango.EllipsizeMode.END)
            t.set_xalign(0.0)
            if i == current:
                t.add_css_class("heading")
            a = Gtk.Label(label=track.artist)
            a.set_ellipsize(Pango.EllipsizeMode.END)
            a.set_xalign(0.0)
            a.add_css_class("dim-label")
            a.add_css_class("caption")
            text.append(t)
            text.append(a)
            box.append(text)

            menu_btn = menu_dots_button()
            menu, group = build_track_menu(self.window, track)
            menu_btn.set_menu_model(menu)
            row.insert_action_group("trk", group)
            box.append(menu_btn)

            remove = Gtk.Button.new_from_icon_name("window-close-symbolic")
            remove.add_css_class("flat")
            remove.set_valign(Gtk.Align.CENTER)
            remove.set_tooltip_text("Remove from queue")
            remove.connect("clicked", self._on_remove, i)
            box.append(remove)

            row.set_child(box)
            self._make_draggable(row, i)
            self.listbox.append(row)

    def _make_draggable(self, row: Gtk.ListBoxRow, index: int) -> None:
        """Drag a row onto another row to reorder the queue."""
        source = Gtk.DragSource()
        source.set_actions(Gdk.DragAction.MOVE)
        source.connect(
            "prepare",
            lambda _s, _x, _y, i=index:
                Gdk.ContentProvider.new_for_value(str(i)))
        row.add_controller(source)

        target = Gtk.DropTarget.new(GObject.TYPE_STRING, Gdk.DragAction.MOVE)
        target.connect("drop", self._on_drop, index)
        row.add_controller(target)

    def _on_drop(self, _target, value, _x, _y, dest_index: int) -> bool:
        try:
            src_index = int(value)
        except (TypeError, ValueError):
            return False
        self.service.queue.move(src_index, dest_index)
        return True

    def _on_activated(self, _lb, row: Gtk.ListBoxRow) -> None:
        self.service.play_from_queue(row.get_index())

    def _on_remove(self, _btn, index: int) -> None:
        self.service.queue.remove_at(index)

    def _on_clear(self, _btn) -> None:
        self.service.stop()
        self.service.queue.clear()
