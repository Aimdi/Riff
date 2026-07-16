"""Local AI for AI Mix — one GGUF model, loaded in-process.

No Ollama, no background server. Install downloads:
  1. a private Python venv with ``llama-cpp-python``
  2. a small GGUF Riff chose for you

Inference loads the model into Riff's process (or a short-lived helper
process using that venv) only while AI Mix runs.
"""

from __future__ import annotations

import json
import logging
import os
import shutil
import subprocess
import sys
import urllib.error
import urllib.request
from dataclasses import dataclass

from .. import config
from . import ai as ai_mod
from .models import Track

log = logging.getLogger("riff.local_ai")

# Riff's pick: small, instruct-tuned, solid JSON for its size.
# Q4_K_M quant ≈ 1 GB on disk, ~1.5 GB RAM — fine on a laptop CPU.
MODEL_FILENAME = "qwen2.5-1.5b-instruct-q4_k_m.gguf"
MODEL_LABEL = "Qwen 2.5 · 1.5B"
MODEL_SIZE_HINT = "~1 GB"
MODEL_WHY = (
    "A small on-device model — no account, no server, nothing leaves your "
    "PC. Riff picks this size so install and AI Mix stay practical."
)
# Official Qwen GGUF on Hugging Face (LFS redirect works with urllib).
MODEL_URL = (
    "https://huggingface.co/Qwen/Qwen2.5-1.5B-Instruct-GGUF/resolve/main/"
    + MODEL_FILENAME
)

_MODELS_DIR = os.path.join(config.DATA_DIR, "models")
_MODEL_PATH = os.path.join(_MODELS_DIR, MODEL_FILENAME)
_VENV_DIR = os.path.join(config.DATA_DIR, "ai-venv")
_VENV_PY = os.path.join(
    _VENV_DIR, "bin", "python" if os.name != "nt" else "python.exe")

# Kept alive for the process after first AI Mix (cold load is the slow part).
_llm = None


@dataclass(frozen=True)
class LocalAiStatus:
    """Snapshot for the Settings UI."""

    runtime_ready: bool  # llama-cpp-python importable from the venv
    model_ready: bool    # GGUF file present
    detail: str

    @property
    def ready(self) -> bool:
        return self.runtime_ready and self.model_ready


def model_path() -> str:
    return _MODEL_PATH


def model_file_ready() -> bool:
    try:
        return os.path.isfile(_MODEL_PATH) and os.path.getsize(_MODEL_PATH) > 50_000_000
    except OSError:
        return False


def runtime_ready() -> bool:
    """True when the riff ai-venv can import llama_cpp."""
    if not os.path.isfile(_VENV_PY):
        return False
    try:
        subprocess.run(
            [_VENV_PY, "-c", "import llama_cpp"],
            check=True,
            capture_output=True,
            timeout=60,
        )
        return True
    except (OSError, subprocess.CalledProcessError, subprocess.TimeoutExpired):
        return False


def status() -> LocalAiStatus:
    has_runtime = runtime_ready()
    has_model = model_file_ready()
    if has_runtime and has_model:
        detail = f"Ready — {MODEL_LABEL} on this machine (no server)"
    elif not has_runtime and not has_model:
        detail = (
            f"Not installed — one click downloads the engine + "
            f"{MODEL_LABEL} ({MODEL_SIZE_HINT})"
        )
    elif not has_runtime:
        detail = "Model file present, but the local engine is not installed yet"
    else:
        detail = f"{MODEL_LABEL} not downloaded yet ({MODEL_SIZE_HINT})"
    return LocalAiStatus(
        runtime_ready=has_runtime, model_ready=has_model, detail=detail)


def apply_local_settings() -> None:
    config.settings.set("ai_provider", "local")


def _download(url: str, dest: str, progress=None, label: str = "Downloading") -> None:
    os.makedirs(os.path.dirname(dest) or ".", exist_ok=True)
    tmp = dest + ".part"
    req = urllib.request.Request(url, headers={"User-Agent": "Riff-Player"})
    try:
        with urllib.request.urlopen(req, timeout=120) as resp, open(tmp, "wb") as out:
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
                    mb = read / (1024 * 1024)
                    progress(f"{label}… {pct}% ({mb:.0f} MB)")
                elif progress and read and read % (10 * 1024 * 1024) < 256 * 1024:
                    progress(f"{label}… {read / (1024 * 1024):.0f} MB")
    except urllib.error.HTTPError as exc:
        try:
            os.remove(tmp)
        except OSError:
            pass
        raise RuntimeError(f"Download failed (HTTP {exc.code})") from exc
    except urllib.error.URLError as exc:
        try:
            os.remove(tmp)
        except OSError:
            pass
        raise RuntimeError(f"Download failed: {exc.reason}") from exc
    os.replace(tmp, dest)


def ensure_runtime(progress=None) -> None:
    """Create the private venv and install llama-cpp-python if needed."""
    def report(msg: str) -> None:
        log.info("%s", msg)
        if progress:
            progress(msg)

    if runtime_ready():
        return

    report("Setting up local AI engine…")
    os.makedirs(config.DATA_DIR, exist_ok=True)
    if not os.path.isfile(_VENV_PY):
        subprocess.run(
            [sys.executable, "-m", "venv", _VENV_DIR],
            check=True,
            capture_output=True,
            timeout=120,
        )

    # Prefer prebuilt CPU wheels when available; fall back to default index.
    pip = [_VENV_PY, "-m", "pip", "install", "--upgrade", "pip", "wheel"]
    report("Updating pip…")
    subprocess.run(pip, check=True, capture_output=True, timeout=300)

    report("Installing llama.cpp bindings (CPU)… this may take a minute")
    install_cmds = [
        [
            _VENV_PY, "-m", "pip", "install", "--upgrade",
            "llama-cpp-python",
            "--extra-index-url",
            "https://abetlen.github.io/llama-cpp-python/whl/cpu",
        ],
        [
            _VENV_PY, "-m", "pip", "install", "--upgrade", "llama-cpp-python",
        ],
    ]
    last_err = None
    for cmd in install_cmds:
        try:
            subprocess.run(cmd, check=True, capture_output=True, timeout=1800)
            last_err = None
            break
        except subprocess.CalledProcessError as exc:
            last_err = exc
            log.warning("pip install failed: %s", exc.stderr[-500:] if exc.stderr else exc)
        except subprocess.TimeoutExpired as exc:
            last_err = exc

    if last_err is not None or not runtime_ready():
        raise RuntimeError(
            "Couldn't install the local AI engine (llama-cpp-python). "
            "You need a working C++ toolchain, or try: "
            f"{_VENV_PY} -m pip install llama-cpp-python"
        ) from last_err

    report("Local AI engine ready")


def ensure_model(progress=None) -> None:
    def report(msg: str) -> None:
        log.info("%s", msg)
        if progress:
            progress(msg)

    if model_file_ready():
        return
    os.makedirs(_MODELS_DIR, exist_ok=True)
    report(f"Downloading {MODEL_LABEL} ({MODEL_SIZE_HINT})…")
    _download(MODEL_URL, _MODEL_PATH, progress=progress, label=f"Downloading {MODEL_LABEL}")
    if not model_file_ready():
        raise RuntimeError("Model download finished but the file looks incomplete")
    report(f"{MODEL_LABEL} downloaded")


def install_local_ai(progress=None) -> LocalAiStatus:
    """One-shot: engine + model file. No server."""
    ensure_runtime(progress=progress)
    ensure_model(progress=progress)
    return status()


def _site_packages() -> str | None:
    if not os.path.isdir(_VENV_DIR):
        return None
    lib = os.path.join(_VENV_DIR, "lib")
    if not os.path.isdir(lib):
        return None
    for name in os.listdir(lib):
        if name.startswith("python"):
            site = os.path.join(lib, name, "site-packages")
            if os.path.isdir(site):
                return site
    return None


def _load_llm(progress=None):
    """Import llama_cpp from the riff venv and load the GGUF once."""
    global _llm
    if _llm is not None:
        return _llm

    if not model_file_ready():
        raise RuntimeError("Local model is not installed — use Settings → Install")
    site = _site_packages()
    if not site:
        raise RuntimeError("Local AI engine is not installed — use Settings → Install")
    if site not in sys.path:
        sys.path.insert(0, site)

    try:
        from llama_cpp import Llama
    except ImportError as exc:
        raise RuntimeError(
            "Local AI engine missing — open Settings and press Install"
        ) from exc

    if progress:
        progress("Loading model into memory…")
    log.info("loading local model from %s", _MODEL_PATH)
    n_threads = max(1, (os.cpu_count() or 4) - 1)
    _llm = Llama(
        model_path=_MODEL_PATH,
        n_ctx=4096,
        n_threads=n_threads,
        n_gpu_layers=0,  # pure CPU; GPU would need a CUDA build
        verbose=False,
    )
    return _llm


def unload() -> None:
    """Drop the in-memory model (frees RAM). Next AI Mix reloads it."""
    global _llm
    _llm = None


def suggest_songs(recent: list[Track], favorites: list[Track],
                  count: int = 20, **context) -> list[tuple[str, str]]:
    """Blocking in-process generation. Same return shape as cloud providers."""
    llm = _load_llm()
    system = (
        ai_mod._SYSTEM
        + ' Respond ONLY with a JSON object of the form '
          '{"songs": [{"title": "...", "artist": "..."}]} — no other text.'
    )
    # Slightly fewer songs on-device keeps latency and quality better.
    count = min(count, 16)
    user = ai_mod.build_prompt(recent, favorites, count, **context)

    try:
        result = llm.create_chat_completion(
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            temperature=0.7,
            max_tokens=2048,
            # stop if the model starts babbling after JSON
        )
    except Exception as exc:  # noqa: BLE001
        log.exception("local generation failed")
        raise RuntimeError(f"Local model failed: {exc}") from exc

    try:
        text = result["choices"][0]["message"]["content"] or ""
    except (KeyError, IndexError, TypeError) as exc:
        raise RuntimeError("Unexpected response from the local model") from exc

    try:
        return ai_mod.parse_suggestions(text)
    except (ValueError, KeyError) as exc:
        raise RuntimeError(
            "Couldn't parse the local model's suggestions — try again"
        ) from exc


def remove_install() -> None:
    """Optional cleanup: delete model + venv (not wired in UI yet)."""
    unload()
    if os.path.isfile(_MODEL_PATH):
        os.remove(_MODEL_PATH)
    if os.path.isdir(_VENV_DIR):
        shutil.rmtree(_VENV_DIR, ignore_errors=True)
