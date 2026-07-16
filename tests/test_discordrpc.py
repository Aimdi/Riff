"""Discord RPC wire protocol against a fake local IPC socket."""

import json
import os
import socket
import struct
import threading

from riff.core.discordrpc import DiscordRPC


class FakeDiscord:
    """Accepts one client, answers every frame, records what it got."""

    def __init__(self, path: str):
        self.path = path
        self.frames: list[tuple[int, dict]] = []
        self._srv = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self._srv.bind(path)
        self._srv.listen(1)
        self._thread = threading.Thread(target=self._serve, daemon=True)
        self._thread.start()

    def _serve(self) -> None:
        conn, _ = self._srv.accept()
        try:
            while True:
                header = b""
                while len(header) < 8:
                    chunk = conn.recv(8 - len(header))
                    if not chunk:
                        return
                    header += chunk
                op, length = struct.unpack("<II", header)
                body = b""
                while len(body) < length:
                    body += conn.recv(length - len(body))
                self.frames.append((op, json.loads(body.decode())))
                reply = json.dumps({"evt": "READY" if op == 0 else None,
                                    "data": {}}).encode()
                conn.sendall(struct.pack("<II", 1, len(reply)) + reply)
        except OSError:
            pass

    def close(self) -> None:
        self._srv.close()


def test_handshake_and_activity(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_RUNTIME_DIR", str(tmp_path))
    fake = FakeDiscord(os.path.join(str(tmp_path), "discord-ipc-0"))
    try:
        rpc = DiscordRPC("12345")
        assert rpc.connect()
        rpc.set_activity(details="Song Title", state="Artist",
                         large_image="https://img", duration=200, position=10)
        rpc.clear()

        ops = [f[0] for f in fake.frames]
        assert ops[0] == 0  # handshake first
        handshake = fake.frames[0][1]
        assert handshake == {"v": 1, "client_id": "12345"}

        act = fake.frames[1][1]
        assert act["cmd"] == "SET_ACTIVITY"
        activity = act["args"]["activity"]
        assert activity["details"] == "Song Title"
        assert activity["state"] == "Artist"
        assert activity["type"] == 2  # Listening
        assert activity["assets"]["large_image"] == "https://img"
        ts = activity["timestamps"]
        assert ts["end"] - ts["start"] == 200

        cleared = fake.frames[2][1]
        assert cleared["args"]["activity"] is None
    finally:
        fake.close()


def test_connect_without_socket_fails_quietly(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_RUNTIME_DIR", str(tmp_path))
    rpc = DiscordRPC("12345")
    assert rpc.connect() is False
    assert rpc.connected is False


def test_empty_client_id_never_connects(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_RUNTIME_DIR", str(tmp_path))
    assert DiscordRPC("").connect() is False
