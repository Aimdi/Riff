"""Local AI for AI Mix — Ollama + a model Riff chooses for you.

Design goals (from product intent):
- One good default, no model shopping
- Small enough for a laptop (~2 GB), not glacial on CPU
- One-button install from Settings
- Private: nothing leaves the machine once installed

We use Ollama because it is free, well-packaged on Arch/CachyOS, and speaks
the same OpenAI-compatible API AI Mix already uses.
"""

from __future__ import annotations

import json
import logging
import os
import platform
import shutil
import subprocess
import tarfile
import tempfile
import time
import urllib.error
import urllib.request
from dataclasses import dataclass

from .. import config

log = logging.getLogger("riff.local_ai")

# Riff's pick: strong instruction-following / JSON for the size, ~1.9 GB.
# Tag is stable on ollama.com/library/qwen2.5.
MODEL_ID = "qwen2.5:3b"
MODEL_LABEL = "Qwen 2.5 · 3B"
MODEL_SIZE_HINT = "~2 GB"
MODEL_WHY = (
    "Small enough for a laptop, fast enough for AI Mix, good at following "
    "JSON instructions. Riff picks this for you — no model shopping."
)

OLLAMA_HOST = "127.0.0.1"
OLLAMA_PORT = 11434
OLLAMA_BASE = f"http://{OLLAMA_HOST}:{OLLAMA_PORT}"
OPENAI_COMPAT_BASE = f"{OLLAMA_BASE}/v1"

# User-local Ollama install (no sudo). System packages take precedence.
_RIFF_OLLAMA_DIR = os.path.join(config.DATA_DIR, "ollama")
_RIFF_OLLAMA_BIN = os.path.join(_RIFF_OLLAMA_DIR, "bin", "ollama")
_RIFF_OLLAMA_MODELS = os.path.join(_RIFF_OLLAMA_DIR, "models")

_DOWNLOAD_URLS = {
    "x86_64": "https://ollama.com/download/ollama-linux-amd64.tgz",
    "amd64": "https://ollama.com/download/ollama-linux-amd64.tgz",
    "aarch64": "https://ollama.com/download/ollama-linux-arm64.tgz",
    "arm64": "https://ollama.com/download/ollama-linux-arm64.tgz",
}

_serve_proc: subprocess.Popen | None = None


@dataclass(frozen=True)
class LocalAiStatus:
    """Snapshot for the Settings UI."""

    ollama_bin: str | None
    server_up: bool
    model_ready: bool
    detail: str

    @property
    def ready(self) -> bool:
        return bool(self.ollama_bin and self.server_up and self.model_ready)


def ollama_env() -> dict[str, str]:
    """Environment for riff-managed Ollama (models stay under XDG data)."""
    env = os.environ.copy()
    env["OLLAMA_HOST"] = f"{OLLAMA_HOST}:{OLLAMA_PORT}"
    # Always pin models dir when we own the binary; also fine for system ollama
    # when the user never set OLLAMA_MODELS themselves.
    if os.path.isfile(_RIFF_OLLAMA_BIN) or not env.get("OLLAMA_MODELS"):
        env["OLLAMA_MODELS"] = _RIFF_OLLAMA_MODELS
    return env


def find_ollama() -> str | None:
    """Path to an ollama binary, or None."""
    if os.path.isfile(_RIFF_OLLAMA_BIN) and os.access(_RIFF_OLLAMA_BIN, os.X_OK):
        return _RIFF_OLLAMA_BIN
    return shutil.which("ollama")


def server_up(timeout: float = 1.5) -> bool:
    try:
        with urllib.request.urlopen(f"{OLLAMA_BASE}/api/tags", timeout=timeout) as resp:
            return 200 <= resp.status < 300
    except Exception:  # noqa: BLE001
        return False


def list_models() -> list[str]:
    """Installed model names (e.g. ``qwen2.5:3b``). Empty if server down."""
    try:
        with urllib.request.urlopen(f"{OLLAMA_BASE}/api/tags", timeout=5) as resp:
            data = json.load(resp)
    except Exception:  # noqa: BLE001
        return []
    out = []
    for m in data.get("models") or []:
        name = m.get("name") or m.get("model") or ""
        if name:
            out.append(name)
    return out


def model_installed(model: str = MODEL_ID) -> bool:
    """True if ``model`` is present (exact tag or a longer Ollama name)."""
    for name in list_models():
        if name == model or name.startswith(model + "-") or name.startswith(model + "@"):
            return True
    return False


def status() -> LocalAiStatus:
    binary = find_ollama()
    up = server_up()
    ready = bool(up and model_installed())
    if not binary:
        detail = "Ollama is not installed yet"
    elif not up:
        detail = "Ollama is installed but not running"
    elif not ready:
        detail = f"{MODEL_LABEL} is not downloaded yet ({MODEL_SIZE_HINT})"
    else:
        detail = f"Ready — {MODEL_LABEL} on this machine"
    return LocalAiStatus(
        ollama_bin=binary, server_up=up, model_ready=ready, detail=detail)


def install_ollama_binary(progress=None) -> str:
    """Download Ollama into the user data dir (no sudo). Returns binary path.

    ``progress(message: str)`` is optional and called from this thread.
    """
    def report(msg: str) -> None:
        log.info("%s", msg)
        if progress:
            progress(msg)

    machine = platform.machine().lower()
    url = _DOWNLOAD_URLS.get(machine)
    if not url:
        raise RuntimeError(
            f"No Ollama build for this CPU ({machine}). "
            "Install Ollama from https://ollama.com and try again.")

    os.makedirs(_RIFF_OLLAMA_DIR, exist_ok=True)
    report("Downloading Ollama…")
    with tempfile.TemporaryDirectory(prefix="riff-ollama-") as tmp:
        tgz = os.path.join(tmp, "ollama.tgz")
        _download(url, tgz, progress)
        report("Installing Ollama…")
        with tarfile.open(tgz, "r:gz") as tar:
            # tarball usually contains a single `ollama` binary at root or bin/
            try:
                tar.extractall(tmp, filter="data")
            except TypeError:
                tar.extractall(tmp)
        binary_src = None
        for root, _dirs, files in os.walk(tmp):
            if "ollama" in files:
                candidate = os.path.join(root, "ollama")
                if os.path.isfile(candidate) and os.access(candidate, os.X_OK):
                    binary_src = candidate
                    break
                if os.path.isfile(candidate):
                    binary_src = candidate
                    break
        if binary_src is None:
            # some archives are just the binary named differently
            raise RuntimeError("Downloaded Ollama archive looked unexpected")
        dest_dir = os.path.dirname(_RIFF_OLLAMA_BIN)
        os.makedirs(dest_dir, exist_ok=True)
        shutil.copy2(binary_src, _RIFF_OLLAMA_BIN)
        os.chmod(_RIFF_OLLAMA_BIN, 0o755)
    report("Ollama installed")
    return _RIFF_OLLAMA_BIN


def _download(url: str, dest: str, progress=None) -> None:
    req = urllib.request.Request(url, headers={"User-Agent": "Riff-Player"})
    with urllib.request.urlopen(req, timeout=120) as resp, open(dest, "wb") as out:
        total = int(resp.headers.get("Content-Length") or 0)
        read = 0
        while True:
            chunk = resp.read(1024 * 256)
            if not chunk:
                break
            out.write(chunk)
            read += len(chunk)
            if progress and total:
                pct = min(99, int(100 * read / total))
                progress(f"Downloading Ollama… {pct}%")


def ensure_server(progress=None) -> None:
    """Make sure ``ollama serve`` is reachable; start it if needed."""
    def report(msg: str) -> None:
        log.info("%s", msg)
        if progress:
            progress(msg)

    if server_up():
        return

    binary = find_ollama()
    if not binary:
        binary = install_ollama_binary(progress=progress)

    report("Starting Ollama…")
    global _serve_proc
    # If a previous child died, clear it.
    if _serve_proc is not None and _serve_proc.poll() is not None:
        _serve_proc = None

    if _serve_proc is None:
        os.makedirs(_RIFF_OLLAMA_MODELS, exist_ok=True)
        try:
            _serve_proc = subprocess.Popen(
                [binary, "serve"],
                env=ollama_env(),
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                start_new_session=True,
            )
        except OSError as exc:
            raise RuntimeError(f"Couldn't start Ollama: {exc}") from exc

    # Wait for readiness
    for _ in range(40):
        if server_up():
            return
        if _serve_proc is not None and _serve_proc.poll() is not None:
            raise RuntimeError(
                "Ollama exited immediately — is another install conflicting "
                f"on port {OLLAMA_PORT}?")
        time.sleep(0.25)
    raise RuntimeError("Ollama did not become ready in time")


def pull_model(model: str = MODEL_ID, progress=None) -> None:
    """Pull ``model`` via the Ollama HTTP API (streaming progress)."""
    def report(msg: str) -> None:
        log.info("%s", msg)
        if progress:
            progress(msg)

    ensure_server(progress=progress)
    if model_installed(model):
        report(f"{model} already installed")
        return

    report(f"Downloading {MODEL_LABEL} ({MODEL_SIZE_HINT})…")
    body = json.dumps({"name": model, "stream": True}).encode()
    req = urllib.request.Request(
        f"{OLLAMA_BASE}/api/pull",
        data=body,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=600) as resp:
            for raw in resp:
                line = raw.decode("utf-8", errors="replace").strip()
                if not line:
                    continue
                try:
                    event = json.loads(line)
                except ValueError:
                    continue
                status = event.get("status") or ""
                completed = event.get("completed")
                total = event.get("total")
                if completed and total:
                    pct = min(99, int(100 * completed / total))
                    report(f"{status or 'Downloading'}… {pct}%")
                elif status:
                    report(status)
    except urllib.error.HTTPError as exc:
        raise RuntimeError(f"Model download failed (HTTP {exc.code})") from exc
    except urllib.error.URLError as exc:
        raise RuntimeError(f"Couldn't reach Ollama: {exc.reason}") from exc

    if not model_installed(model):
        # tags endpoint can lag briefly after pull
        time.sleep(0.5)
    if not model_installed(model):
        raise RuntimeError(f"Download finished but {model} is not listed yet")
    report(f"{MODEL_LABEL} is ready")


def install_local_ai(progress=None) -> LocalAiStatus:
    """Full one-shot: Ollama binary + server + recommended model."""
    pull_model(MODEL_ID, progress=progress)
    return status()


def apply_local_settings() -> None:
    """Point AI Mix settings at the local stack."""
    config.settings.set("ai_provider", "local")
    config.settings.set("openai_base_url", OPENAI_COMPAT_BASE)
    config.settings.set("openai_model", MODEL_ID)
    # Local Ollama does not need a key; leave openai_api_key alone.
