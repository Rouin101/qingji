"""Test-package setup that prevents unit tests from calling real providers."""

from __future__ import annotations

import os


# A developer's local .env may legitimately enable an API key.  The test suite
# must stay deterministic and never send fixture material to that provider.
os.environ["QINGJI_LLM_ENABLED"] = "false"
