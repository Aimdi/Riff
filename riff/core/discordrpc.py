"""Discord Rich Presence over Discord's local IPC socket.

No third-party dependency: the protocol is a unix socket carrying
little-endian (opcode, length) framed JSON. Everything here is
best-effort — Discord not running, no socket, protocol hiccups — none of
it may ever disturb playback.
"""

from __future__ import annotations

import json
import logging
import os
import socket
import struct
import time

log = logging.getLogger("riff.discord")

OP_HANDSHAKE = 0
OP_FRAME = 1

# Where Discord (native, flatpak, snap) puts its IPC sockets.
_SOCKET_SUBDIRS = ("", "app/com.discordapp.Discord", "snap.discord",
                   ".flatpak/com.discordapp.Discord/xdg-run")


def _candidate_sockets() -> list[str]:
    base = os.environ.get("XDG_RUNTIME_DIR") or "/tmp"
    paths = []
    for sub in _SOCKET_SUBDIRS:
        d = os.path.join(base, sub) if sub else base
        for i in range(10):
            paths.append(os.path.join(d, f"discord-ipc-{i}"))
    return paths


class DiscordRPC:
    """Minimal Rich Presence client for one Discord application id."""

    def __init__(self, client_id: str):
        self.client_id = str(client_id).strip()
        self._sock: socket.socket | None = None

    @property
    def connected(self) -> bool:
        return self._sock is not None

    def connect(self) -> bool:
        if not self.client_id:
            return False
        for path in _candidate_sockets():
            if not os.path.exists(path):
                continue
            try:
                s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
                s.settimeout(3)
                s.connect(path)
                self._sock = s
                self._send(OP_HANDSHAKE,
                           {"v": 1, "client_id": self.client_id})
                self._recv()  # READY (or an error frame we treat the same)
                log.info("Discord RPC connected via %s", path)
                return True
            except OSError as exc:
                log.debug("Discord socket %s: %s", path, exc)
                self._close()
        return False

    def set_activity(self, *, details: str, state: str = "",
                     large_image: str = "", large_text: str = "",
                     duration: float = 0, position: float = 0) -> None:
        """Show 'Listening to …' for the current song."""
        activity: dict = {
            "type": 2,  # Listening
            "details": details[:128] or "…",
        }
        if state:
            activity["state"] = state[:128]
        assets = {}
        if large_image:
            assets["large_image"] = large_image[:256]
        if large_text:
            assets["large_text"] = large_text[:128]
        if assets:
            activity["assets"] = assets
        if duration and duration > 0:
            now = time.time()
            activity["timestamps"] = {
                "start": int(now - max(0.0, position)),
                "end": int(now - max(0.0, position) + duration),
            }
        self._command("SET_ACTIVITY", {"pid": os.getpid(),
                                       "activity": activity})

    def clear(self) -> None:
        self._command("SET_ACTIVITY", {"pid": os.getpid(), "activity": None})

    def close(self) -> None:
        try:
            self.clear()
        except Exception:  # noqa: BLE001
            pass
        self._close()

    # -- wire ---------------------------------------------------------------

    def _command(self, cmd: str, args: dict) -> None:
        if self._sock is None:
            raise OSError("not connected")
        self._send(OP_FRAME, {
            "cmd": cmd,
            "args": args,
            "nonce": str(time.monotonic_ns()),
        })
        self._recv()

    def _send(self, op: int, payload: dict) -> None:
        data = json.dumps(payload).encode("utf-8")
        assert self._sock is not None
        self._sock.sendall(struct.pack("<II", op, len(data)) + data)

    def _recv(self) -> dict | None:
        assert self._sock is not None
        header = self._read_exact(8)
        if header is None:
            return None
        _op, length = struct.unpack("<II", header)
        body = self._read_exact(length)
        if body is None:
            return None
        try:
            return json.loads(body.decode("utf-8"))
        except ValueError:
            return None

    def _read_exact(self, n: int) -> bytes | None:
        assert self._sock is not None
        buf = b""
        while len(buf) < n:
            chunk = self._sock.recv(n - len(buf))
            if not chunk:
                return None
            buf += chunk
        return buf

    def _close(self) -> None:
        if self._sock is not None:
            try:
                self._sock.close()
            except OSError:
                pass
            self._sock = None


class PresenceManager:
    """Bridges the PlaybackService to Discord, if enabled in settings.

    Reads settings live so toggling in the Settings dialog takes effect on
    the next track without a restart. All socket work runs off the main
    loop via run_async.
    """

    def __init__(self, service, settings) -> None:
        self._service = service
        self._settings = settings
        self._rpc: DiscordRPC | None = None
        service.track_listeners.append(self._on_track)
        service.state_listeners.append(self._on_state)

    def _enabled(self) -> tuple[bool, str]:
        enabled = bool(self._settings.get("discord_rpc_enabled", False))
        client_id = str(
            self._settings.get("discord_client_id", "") or "").strip()
        return enabled and bool(client_id), client_id

    def _on_track(self, track) -> None:
        enabled, client_id = self._enabled()
        from ..util import run_async

        def work() -> None:
            if not enabled or track is None:
                if self._rpc is not None and self._rpc.connected:
                    try:
                        self._rpc.clear()
                    except OSError:
                        self._rpc = None
                return
            if (self._rpc is None or not self._rpc.connected
                    or self._rpc.client_id != client_id):
                rpc = DiscordRPC(client_id)
                if not rpc.connect():
                    self._rpc = None
                    return
                self._rpc = rpc
            try:
                self._rpc.set_activity(
                    details=track.title,
                    state=track.artist,
                    large_image=track.thumbnail,
                    large_text="Riff",
                    duration=float(track.duration or 0),
                )
            except OSError:
                self._rpc = None  # Discord went away; retry next track

        run_async(work, name="riff-discord")

    def _on_state(self, state: str) -> None:
        # Keep it simple: presence follows tracks; clear when stopped.
        if state == "stopped":
            self._on_track(None)

    def shutdown(self) -> None:
        rpc, self._rpc = self._rpc, None
        if rpc is not None and rpc.connected:
            try:
                rpc.close()
            except Exception:  # noqa: BLE001
                pass
