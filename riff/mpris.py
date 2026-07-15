"""MPRIS2 (org.mpris.MediaPlayer2) integration via Gio D-Bus.

Lets media keys, GNOME/KDE media widgets, playerctl etc. control Riff.
"""

from __future__ import annotations

import logging

from gi.repository import Gio, GLib

from . import APP_ID
from .core.models import Track
from .core.player import STATE_PAUSED, STATE_PLAYING

log = logging.getLogger("riff.mpris")

BUS_NAME = "org.mpris.MediaPlayer2.riff"
OBJECT_PATH = "/org/mpris/MediaPlayer2"

MPRIS_XML = """
<node>
  <interface name="org.mpris.MediaPlayer2">
    <method name="Raise"/>
    <method name="Quit"/>
    <property name="CanQuit" type="b" access="read"/>
    <property name="CanRaise" type="b" access="read"/>
    <property name="HasTrackList" type="b" access="read"/>
    <property name="Identity" type="s" access="read"/>
    <property name="DesktopEntry" type="s" access="read"/>
    <property name="SupportedUriSchemes" type="as" access="read"/>
    <property name="SupportedMimeTypes" type="as" access="read"/>
  </interface>
  <interface name="org.mpris.MediaPlayer2.Player">
    <method name="Next"/>
    <method name="Previous"/>
    <method name="Pause"/>
    <method name="PlayPause"/>
    <method name="Stop"/>
    <method name="Play"/>
    <method name="Seek"><arg direction="in" name="Offset" type="x"/></method>
    <method name="SetPosition">
      <arg direction="in" name="TrackId" type="o"/>
      <arg direction="in" name="Position" type="x"/>
    </method>
    <method name="OpenUri"><arg direction="in" name="Uri" type="s"/></method>
    <signal name="Seeked"><arg name="Position" type="x"/></signal>
    <property name="PlaybackStatus" type="s" access="read"/>
    <property name="Rate" type="d" access="readwrite"/>
    <property name="Metadata" type="a{sv}" access="read"/>
    <property name="Volume" type="d" access="readwrite"/>
    <property name="Position" type="x" access="read"/>
    <property name="MinimumRate" type="d" access="read"/>
    <property name="MaximumRate" type="d" access="read"/>
    <property name="CanGoNext" type="b" access="read"/>
    <property name="CanGoPrevious" type="b" access="read"/>
    <property name="CanPlay" type="b" access="read"/>
    <property name="CanPause" type="b" access="read"/>
    <property name="CanSeek" type="b" access="read"/>
    <property name="CanControl" type="b" access="read"/>
  </interface>
</node>
"""


_PROPERTY_NAMES = {
    "org.mpris.MediaPlayer2": [
        "CanQuit", "CanRaise", "HasTrackList", "Identity", "DesktopEntry",
        "SupportedUriSchemes", "SupportedMimeTypes",
    ],
    "org.mpris.MediaPlayer2.Player": [
        "PlaybackStatus", "Rate", "Metadata", "Volume", "Position",
        "MinimumRate", "MaximumRate", "CanGoNext", "CanGoPrevious",
        "CanPlay", "CanPause", "CanSeek", "CanControl",
    ],
}


class MprisServer:
    def __init__(self, service, app=None):
        self.service = service
        self.app = app
        self._connection: Gio.DBusConnection | None = None
        self._registrations: list[int] = []
        self._owner_id = Gio.bus_own_name(
            Gio.BusType.SESSION,
            BUS_NAME,
            Gio.BusNameOwnerFlags.NONE,
            self._on_bus_acquired,
            None,
            None,
        )
        service.track_listeners.append(self._on_track_changed)
        service.state_listeners.append(self._on_state_changed)

    def shutdown(self) -> None:
        if self._connection:
            for reg in self._registrations:
                self._connection.unregister_object(reg)
            self._registrations = []
        if self._owner_id:
            Gio.bus_unown_name(self._owner_id)
            self._owner_id = 0

    # -- registration --------------------------------------------------------

    def _on_bus_acquired(self, connection: Gio.DBusConnection, _name: str) -> None:
        self._connection = connection
        node = Gio.DBusNodeInfo.new_for_xml(MPRIS_XML)
        for iface in node.interfaces:
            # Property closures are deliberately NOT passed: with a NULL
            # property vtable GDBus forwards org.freedesktop.DBus.Properties
            # Get/GetAll/Set to the method handler, which is far more
            # reliable across PyGObject versions.
            reg = connection.register_object(
                OBJECT_PATH,
                iface,
                self._on_method_call,
                None,
                None,
            )
            self._registrations.append(reg)

    # -- method calls ----------------------------------------------------------

    def _on_method_call(
        self, _conn, _sender, _path, iface, method, params, invocation
    ) -> None:
        try:
            if iface == "org.freedesktop.DBus.Properties":
                self._handle_properties(method, params, invocation)
                return
            self._dispatch(iface, method, params)
            invocation.return_value(None)
        except Exception as exc:  # noqa: BLE001
            log.warning("MPRIS %s.%s failed: %s", iface, method, exc)
            invocation.return_dbus_error(
                "org.mpris.MediaPlayer2.riff.Error", str(exc)
            )

    def _handle_properties(self, method: str, params, invocation) -> None:
        if method == "Get":
            iface_name, prop = params.unpack()
            value = self._on_get_property(
                None, None, None, iface_name, prop)
            if value is None:
                invocation.return_dbus_error(
                    "org.freedesktop.DBus.Error.InvalidArgs",
                    f"Unknown property {prop}")
                return
            invocation.return_value(GLib.Variant.new_tuple(
                GLib.Variant("v", value)))
        elif method == "GetAll":
            iface_name = params.unpack()[0]
            names = _PROPERTY_NAMES.get(iface_name, [])
            values = {
                name: self._on_get_property(None, None, None, iface_name, name)
                for name in names
            }
            values = {k: v for k, v in values.items() if v is not None}
            invocation.return_value(GLib.Variant("(a{sv})", (values,)))
        elif method == "Set":
            iface_name, prop, _ = params.unpack()
            # unpack() unwraps the inner variant; re-read it typed instead
            variant_value = params.get_child_value(2).get_variant()
            self._on_set_property(
                None, None, None, iface_name, prop, variant_value)
            invocation.return_value(None)
        else:
            invocation.return_dbus_error(
                "org.freedesktop.DBus.Error.UnknownMethod", method)

    def _dispatch(self, iface: str, method: str, params: GLib.Variant) -> None:
        svc = self.service
        if iface == "org.mpris.MediaPlayer2":
            if method == "Raise" and self.app:
                win = getattr(self.app, "window", None)
                if win:
                    win.present()
            elif method == "Quit" and self.app:
                self.app.quit()
            return
        if method == "Next":
            svc.next()
        elif method == "Previous":
            svc.previous()
        elif method in ("Pause",):
            svc.engine.set_paused(True)
        elif method == "PlayPause":
            svc.toggle_pause()
        elif method == "Stop":
            svc.stop()
        elif method == "Play":
            if svc.state == STATE_PAUSED:
                svc.engine.set_paused(False)
            else:
                svc.toggle_pause()
        elif method == "Seek":
            offset_us = params.unpack()[0]
            svc.seek(max(0.0, svc.engine.position + offset_us / 1_000_000))
            self._emit_seeked()
        elif method == "SetPosition":
            _track_id, pos_us = params.unpack()
            svc.seek(pos_us / 1_000_000)
            self._emit_seeked()
        # OpenUri: not supported (needs videoId resolution) — ignore.

    # -- properties --------------------------------------------------------------

    def _on_get_property(self, _conn, _sender, _path, iface, prop) -> GLib.Variant:
        svc = self.service
        root = {
            "CanQuit": GLib.Variant("b", True),
            "CanRaise": GLib.Variant("b", True),
            "HasTrackList": GLib.Variant("b", False),
            "Identity": GLib.Variant("s", "Riff"),
            "DesktopEntry": GLib.Variant("s", APP_ID),
            "SupportedUriSchemes": GLib.Variant("as", []),
            "SupportedMimeTypes": GLib.Variant("as", []),
        }
        if iface == "org.mpris.MediaPlayer2":
            return root.get(prop)
        player = {
            "PlaybackStatus": GLib.Variant("s", self._playback_status()),
            "Rate": GLib.Variant("d", 1.0),
            "MinimumRate": GLib.Variant("d", 1.0),
            "MaximumRate": GLib.Variant("d", 1.0),
            "Metadata": self._metadata_variant(),
            "Volume": GLib.Variant("d", 1.0),
            "Position": GLib.Variant("x", int(svc.engine.position * 1_000_000)),
            "CanGoNext": GLib.Variant("b", svc.queue.has_next()),
            "CanGoPrevious": GLib.Variant("b", len(svc.queue) > 0),
            "CanPlay": GLib.Variant("b", svc.queue.current is not None),
            "CanPause": GLib.Variant("b", True),
            "CanSeek": GLib.Variant("b", True),
            "CanControl": GLib.Variant("b", True),
        }
        return player.get(prop)

    def _on_set_property(self, _conn, _sender, _path, _iface, prop, value) -> bool:
        if prop == "Volume":
            self.service.set_volume(int(max(0.0, min(1.3, value.unpack())) * 100))
        return True

    # -- change notification -------------------------------------------------------

    def _playback_status(self) -> str:
        return {
            STATE_PLAYING: "Playing",
            STATE_PAUSED: "Paused",
        }.get(self.service.state, "Stopped")

    def _metadata_variant(self) -> GLib.Variant:
        track: Track | None = self.service.current_track
        builder: dict[str, GLib.Variant] = {}
        if track is None:
            builder["mpris:trackid"] = GLib.Variant(
                "o", "/org/mpris/MediaPlayer2/TrackList/NoTrack"
            )
        else:
            safe_id = "".join(c if c.isalnum() else "_" for c in track.video_id)
            builder["mpris:trackid"] = GLib.Variant(
                "o", f"/io/github/aimdi/Riff/Track/{safe_id or 'unknown'}"
            )
            builder["xesam:title"] = GLib.Variant("s", track.title)
            if track.artists:
                builder["xesam:artist"] = GLib.Variant("as", track.artists)
            if track.album:
                builder["xesam:album"] = GLib.Variant("s", track.album)
            if track.duration:
                builder["mpris:length"] = GLib.Variant(
                    "x", int(track.duration * 1_000_000)
                )
            if track.thumbnail:
                builder["mpris:artUrl"] = GLib.Variant("s", track.thumbnail)
        return GLib.Variant("a{sv}", builder)

    def _emit_properties_changed(self, changed: dict[str, GLib.Variant]) -> None:
        if not self._connection:
            return
        self._connection.emit_signal(
            None,
            OBJECT_PATH,
            "org.freedesktop.DBus.Properties",
            "PropertiesChanged",
            GLib.Variant(
                "(sa{sv}as)", ("org.mpris.MediaPlayer2.Player", changed, [])
            ),
        )

    def _emit_seeked(self) -> None:
        if not self._connection:
            return
        self._connection.emit_signal(
            None,
            OBJECT_PATH,
            "org.mpris.MediaPlayer2.Player",
            "Seeked",
            GLib.Variant("(x)", (int(self.service.engine.position * 1_000_000),)),
        )

    def _on_track_changed(self, _track) -> None:
        self._emit_properties_changed(
            {
                "Metadata": self._metadata_variant(),
                "CanGoNext": GLib.Variant("b", self.service.queue.has_next()),
            }
        )

    def _on_state_changed(self, _state: str) -> None:
        self._emit_properties_changed(
            {"PlaybackStatus": GLib.Variant("s", self._playback_status())}
        )
