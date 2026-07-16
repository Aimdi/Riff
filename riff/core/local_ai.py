"""Local AI for AI Mix — GGUF models loaded in-process (no Ollama server).

Install downloads:
  1. a private Python venv with ``llama-cpp-python``
  2. one of Riff's curated GGUF models (user picks; one is recommended)

Inference loads the model into memory only while AI Mix needs it.
"""

from __future__ import annotations

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

_MODELS_DIR = os.path.join(config.DATA_DIR, "models")
_VENV_DIR = os.path.join(config.DATA_DIR, "ai-venv")
_VENV_PY = os.path.join(
    _VENV_DIR, "bin", "python" if os.name != "nt" else "python.exe")

# Kept alive after first AI Mix; swapped when the user changes model.
_llm = None
_llm_model_id: str | None = None


@dataclass(frozen=True)
class LocalModel:
    """One on-device model Riff is willing to install for you."""

    id: str
    label: str
    size_hint: str
    blurb: str
    filename: str
    url: str
    min_bytes: int = 50_000_000
    recommended: bool = False

    @property
    def path(self) -> str:
        return os.path.join(_MODELS_DIR, self.filename)

    @property
    def combo_label(self) -> str:
        mark = " ★" if self.recommended else ""
        return f"{self.label} · {self.size_hint}{mark}"


# Curated only — not a full HF browser. Order: fast → recommended → better.
MODELS: tuple[LocalModel, ...] = (
    LocalModel(
        id="qwen2.5-1.5b",
        label="Qwen 2.5 · 1.5B",
        size_hint="~1 GB",
        blurb="Fastest. Fine for light mixes on slower laptops.",
        filename="qwen2.5-1.5b-instruct-q4_k_m.gguf",
        url=(
            "https://huggingface.co/Qwen/Qwen2.5-1.5B-Instruct-GGUF/"
            "resolve/main/qwen2.5-1.5b-instruct-q4_k_m.gguf"
        ),
        min_bytes=800_000_000,
    ),
    LocalModel(
        id="gemma2-2b",
        label="Gemma 2 · 2B",
        size_hint="~1.6 GB",
        blurb="Google's small instruct model — compact and capable.",
        filename="gemma-2-2b-it-Q4_K_M.gguf",
        url=(
            "https://huggingface.co/bartowski/gemma-2-2b-it-GGUF/"
            "resolve/main/gemma-2-2b-it-Q4_K_M.gguf"
        ),
        min_bytes=1_200_000_000,
    ),
    LocalModel(
        id="qwen2.5-3b",
        label="Qwen 2.5 · 3B",
        size_hint="~2 GB",
        blurb="Best balance of quality and speed for AI Mix. Recommended.",
        filename="qwen2.5-3b-instruct-q4_k_m.gguf",
        url=(
            "https://huggingface.co/Qwen/Qwen2.5-3B-Instruct-GGUF/"
            "resolve/main/qwen2.5-3b-instruct-q4_k_m.gguf"
        ),
        min_bytes=1_500_000_000,
        recommended=True,
    ),
    LocalModel(
        id="llama3.2-3b",
        label="Llama 3.2 · 3B",
        size_hint="~2 GB",
        blurb="Meta's small instruct model — strong alternative to Qwen 3B.",
        filename="Llama-3.2-3B-Instruct-Q4_K_M.gguf",
        url=(
            "https://huggingface.co/bartowski/Llama-3.2-3B-Instruct-GGUF/"
            "resolve/main/Llama-3.2-3B-Instruct-Q4_K_M.gguf"
        ),
        min_bytes=1_500_000_000,
    ),
    LocalModel(
        id="qwen2.5-7b",
        label="Qwen 2.5 · 7B",
        size_hint="~4.5 GB",
        blurb="Noticeably smarter curation. Heavier download and slower on CPU.",
        filename="Qwen2.5-7B-Instruct-Q4_K_M.gguf",
        url=(
            "https://huggingface.co/bartowski/Qwen2.5-7B-Instruct-GGUF/"
            "resolve/main/Qwen2.5-7B-Instruct-Q4_K_M.gguf"
        ),
        min_bytes=3_500_000_000,
    ),
)

_MODELS_BY_ID = {m.id: m for m in MODELS}
DEFAULT_MODEL_ID = next(m.id for m in MODELS if m.recommended)

# Back-compat aliases for code/tests that still reference old constants.
MODEL_LABEL = _MODELS_BY_ID[DEFAULT_MODEL_ID].label
MODEL_SIZE_HINT = _MODELS_BY_ID[DEFAULT_MODEL_ID].size_hint
MODEL_WHY = (
    "Pick a model below — Riff downloads it onto this PC and runs it "
    "inside the app. Nothing leaves your machine. The ★ option is the "
    "default Riff recommends."
)


@dataclass(frozen=True)
class LocalAiStatus:
    """Snapshot for the Settings UI."""

    runtime_ready: bool
    model_ready: bool
    model: LocalModel
    detail: str

    @property
    def ready(self) -> bool:
        return self.runtime_ready and self.model_ready


def get_model(model_id: str | None = None) -> LocalModel:
    """Resolve a catalog entry; unknown ids fall back to the recommended one."""
    mid = model_id or str(
        config.settings.get("local_ai_model", DEFAULT_MODEL_ID) or DEFAULT_MODEL_ID
    )
    return _MODELS_BY_ID.get(mid) or _MODELS_BY_ID[DEFAULT_MODEL_ID]


def selected_model() -> LocalModel:
    return get_model()


def set_selected_model(model_id: str) -> LocalModel:
    """Persist selection and drop a loaded model if it no longer matches."""
    model = get_model(model_id)
    config.settings.set("local_ai_model", model.id)
    global _llm, _llm_model_id
    if _llm is not None and _llm_model_id != model.id:
        unload()
    return model


def model_path(model: LocalModel | None = None) -> str:
    return (model or selected_model()).path


def model_file_ready(model: LocalModel | None = None) -> bool:
    m = model or selected_model()
    try:
        return os.path.isfile(m.path) and os.path.getsize(m.path) > m.min_bytes
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


def status(model: LocalModel | None = None) -> LocalAiStatus:
    m = model or selected_model()
    has_runtime = runtime_ready()
    has_model = model_file_ready(m)
    if has_runtime and has_model:
        detail = f"Ready — {m.label} on this machine (no server)"
    elif not has_runtime and not has_model:
        detail = (
            f"Not installed — Install downloads the engine + "
            f"{m.label} ({m.size_hint})"
        )
    elif not has_runtime:
        detail = "Model file present, but the local engine is not installed yet"
    else:
        detail = f"{m.label} not downloaded yet ({m.size_hint})"
    return LocalAiStatus(
        runtime_ready=has_runtime,
        model_ready=has_model,
        model=m,
        detail=detail,
    )


def apply_local_settings() -> None:
    config.settings.set("ai_provider", "local")
    # Ensure a valid model id is stored.
    set_selected_model(selected_model().id)


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
            log.warning(
                "pip install failed: %s",
                (exc.stderr or b"")[-500:],
            )
        except subprocess.TimeoutExpired as exc:
            last_err = exc

    if last_err is not None or not runtime_ready():
        raise RuntimeError(
            "Couldn't install the local AI engine (llama-cpp-python). "
            "You need a working C++ toolchain, or try: "
            f"{_VENV_PY} -m pip install llama-cpp-python"
        ) from last_err

    report("Local AI engine ready")


def ensure_model(progress=None, model: LocalModel | None = None) -> None:
    m = model or selected_model()

    def report(msg: str) -> None:
        log.info("%s", msg)
        if progress:
            progress(msg)

    if model_file_ready(m):
        return
    os.makedirs(_MODELS_DIR, exist_ok=True)
    report(f"Downloading {m.label} ({m.size_hint})…")
    _download(m.url, m.path, progress=progress, label=f"Downloading {m.label}")
    if not model_file_ready(m):
        raise RuntimeError("Model download finished but the file looks incomplete")
    report(f"{m.label} downloaded")


def install_local_ai(progress=None, model_id: str | None = None) -> LocalAiStatus:
    """One-shot: engine + selected (or given) model file. No server."""
    if model_id:
        set_selected_model(model_id)
    m = selected_model()
    ensure_runtime(progress=progress)
    ensure_model(progress=progress, model=m)
    return status(m)


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
    """Import llama_cpp from the riff venv and load the selected GGUF."""
    global _llm, _llm_model_id
    m = selected_model()
    if _llm is not None and _llm_model_id == m.id:
        return _llm
    if _llm is not None:
        unload()

    if not model_file_ready(m):
        raise RuntimeError(
            f"{m.label} is not installed — pick it in Settings and press Install"
        )
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
        progress(f"Loading {m.label} into memory…")
    log.info("loading local model %s from %s", m.id, m.path)
    n_threads = max(1, (os.cpu_count() or 4) - 1)
    # 7B needs a bit more context room for long mix prompts; 4k is enough.
    _llm = Llama(
        model_path=m.path,
        n_ctx=4096,
        n_threads=n_threads,
        n_gpu_layers=0,
        verbose=False,
    )
    _llm_model_id = m.id
    return _llm


def unload() -> None:
    """Drop the in-memory model (frees RAM). Next AI Mix reloads it."""
    global _llm, _llm_model_id
    _llm = None
    _llm_model_id = None


def suggest_songs(recent: list[Track], favorites: list[Track],
                  count: int = 20, **context) -> list[tuple[str, str]]:
    """Blocking in-process generation. Same return shape as cloud providers."""
    llm = _load_llm()
    m = selected_model()
    system = (
        ai_mod._SYSTEM
        + ' Respond ONLY with a JSON object of the form '
          '{"songs": [{"title": "...", "artist": "..."}]} — no other text.'
    )
    # Smaller models get fewer songs so JSON stays reliable.
    if m.id.endswith("1.5b") or m.id.endswith("2b"):
        count = min(count, 12)
    else:
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


def remove_install(model_id: str | None = None) -> None:
    """Delete one model file, or the whole engine + all models."""
    unload()
    if model_id:
        m = get_model(model_id)
        if os.path.isfile(m.path):
            os.remove(m.path)
        return
    if os.path.isdir(_MODELS_DIR):
        shutil.rmtree(_MODELS_DIR, ignore_errors=True)
    if os.path.isdir(_VENV_DIR):
        shutil.rmtree(_VENV_DIR, ignore_errors=True)
