"""Application paths and runtime settings."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


BASE_DIR = Path(__file__).resolve().parent.parent


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

