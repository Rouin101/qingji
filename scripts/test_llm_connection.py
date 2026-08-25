"""Run a no-project-data smoke test against the configured model provider."""

from __future__ import annotations

import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from qingji.config import llm_settings
from qingji.llm import LLMError, probe_llm_connection


def main() -> int:
    if not llm_settings.configured:
        print(
            "[FAIL] model configuration is incomplete; "
            "set QINGJI_LLM_ENABLED, QINGJI_LLM_API_KEY and QINGJI_LLM_MODEL"
        )
        return 2
    try:
        model = probe_llm_connection()
    except LLMError as exc:
        print(f"[FAIL] model probe failed: {exc}")
        return 1
    print(f"[OK] model provider responded: {model}")
    print("[OK] probe contained no project material")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

