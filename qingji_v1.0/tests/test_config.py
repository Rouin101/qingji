from __future__ import annotations

import tempfile
import unittest
import os
from unittest.mock import patch
from pathlib import Path

from qingji.config import LLMSettings, _load_dotenv


class DotenvLoadingTests(unittest.TestCase):
    def test_loads_valid_values_without_overriding_environment(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_dir:
            env_path = Path(temporary_dir) / ".env"
            env_path.write_text(
                "# comment\n"
                "QINGJI_LLM_ENABLED=true\n"
                "QINGJI_LLM_MODEL='deepseek-chat'\n"
                "QINGJI_LLM_API_KEY=local-key # local comment\n"
                "BROKEN LINE\n",
                encoding="utf-8",
            )
            environment = {"QINGJI_LLM_MODEL": "system-model"}

            _load_dotenv(env_path, environ=environment)

        self.assertEqual(environment["QINGJI_LLM_ENABLED"], "true")
        self.assertEqual(environment["QINGJI_LLM_API_KEY"], "local-key")
        self.assertEqual(environment["QINGJI_LLM_MODEL"], "system-model")

    def test_llm_settings_load_provider_for_run_auditing(self) -> None:
        with patch.dict(
            os.environ,
            {
                "QINGJI_LLM_ENABLED": "true",
                "QINGJI_LLM_PROVIDER": "deepseek",
                "QINGJI_LLM_BASE_URL": "https://api.deepseek.com",
                "QINGJI_LLM_API_KEY": "test-key",
                "QINGJI_LLM_MODEL": "test-model",
            },
        ):
            configured = LLMSettings.from_env()

        self.assertTrue(configured.configured)
        self.assertEqual(configured.provider, "deepseek")


if __name__ == "__main__":
    unittest.main()
