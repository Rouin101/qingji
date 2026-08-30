"""Application paths and runtime settings."""

from __future__ import annotations

import os
import re
from collections.abc import MutableMapping
from dataclasses import dataclass
from pathlib import Path


BASE_DIR = Path(__file__).resolve().parent.parent

_ENV_KEY = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


def _load_dotenv(
    path: Path | None = None,
    *,
    environ: MutableMapping[str, str] | None = None,
) -> None:
    """Load local ``.env`` values without overriding real environment values.

    The project intentionally keeps this small instead of making a runtime
    dependency mandatory.  It supports ordinary ``KEY=value`` lines, optional
    ``export`` prefixes and quoted values.  Malformed lines are ignored so a
    local comment or an unfinished value never prevents the app from starting.
    """

    target = environ if environ is not None else os.environ
    env_path = path or (BASE_DIR / ".env")
    try:
        lines = env_path.read_text(encoding="utf-8-sig").splitlines()
    except FileNotFoundError:
        return

    for raw_line in lines:
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[7:].lstrip()
        key, separator, value = line.partition("=")
        key = key.strip()
        if not separator or not _ENV_KEY.fullmatch(key) or key in target:
            continue
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
            value = value[1:-1]
        else:
            value = value.split(" #", 1)[0].rstrip()
        target[key] = value


_load_dotenv()


@dataclass(frozen=True)
class Settings:
    data_dir: Path
    database_path: Path
    raw_dir: Path
    redacted_dir: Path
    runs_path: Path
    demo_mode: bool

    @classmethod
    def from_env(cls) -> "Settings":
        configured = os.getenv("QINGJI_DATA_DIR", "data")
        data_dir = Path(configured)
        if not data_dir.is_absolute():
            data_dir = BASE_DIR / data_dir
        data_dir = data_dir.resolve()
        return cls(
            data_dir=data_dir,
            database_path=data_dir / "qingji.db",
            raw_dir=data_dir / "raw",
            redacted_dir=data_dir / "redacted",
            runs_path=data_dir / "agent_runs.jsonl",
            demo_mode=os.getenv("QINGJI_DEMO_MODE", "true").lower()
            not in {"0", "false", "no"},
        )

    def ensure_directories(self) -> None:
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.raw_dir.mkdir(parents=True, exist_ok=True)
        self.redacted_dir.mkdir(parents=True, exist_ok=True)


settings = Settings.from_env()


@dataclass(frozen=True)
class LLMSettings:
    """Opt-in configuration for the v1.1 model-assistance layer.

    The default is deliberately disabled. The model is contacted only during
    user-triggered, consent-gated generation or review actions.
    """

    enabled: bool
    base_url: str
    api_key: str
    model: str
    timeout_seconds: float
    max_context_chars: int
    provider: str = "openai_compatible"

    @classmethod
    def from_env(cls) -> "LLMSettings":
        enabled = os.getenv("QINGJI_LLM_ENABLED", "false").lower() in {
            "1",
            "true",
            "yes",
            "on",
        }
        try:
            timeout_seconds = float(os.getenv("QINGJI_LLM_TIMEOUT_SECONDS", "30"))
        except ValueError:
            timeout_seconds = 30.0
        timeout_seconds = min(max(timeout_seconds, 5.0), 120.0)
        try:
            max_context_chars = int(os.getenv("QINGJI_LLM_MAX_CONTEXT_CHARS", "12000"))
        except ValueError:
            max_context_chars = 12000
        max_context_chars = min(max(max_context_chars, 1000), 50000)
        return cls(
            enabled=enabled,
            base_url=os.getenv("QINGJI_LLM_BASE_URL", "https://api.openai.com/v1").strip(),
            api_key=os.getenv("QINGJI_LLM_API_KEY", "").strip(),
            model=os.getenv("QINGJI_LLM_MODEL", "").strip(),
            timeout_seconds=timeout_seconds,
            max_context_chars=max_context_chars,
            provider=(
                os.getenv("QINGJI_LLM_PROVIDER", "openai_compatible").strip()
                or "openai_compatible"
            ),
        )

    @property
    def configured(self) -> bool:
        """Whether an explicit opt-in has all required connection settings."""

        return bool(self.enabled and self.base_url and self.api_key and self.model)


llm_settings = LLMSettings.from_env()
