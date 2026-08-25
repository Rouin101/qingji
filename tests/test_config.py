from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from qingji.config import _load_dotenv


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


if __name__ == "__main__":
    unittest.main()
