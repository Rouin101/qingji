"""Streamlit AppTest smoke tests — every page must load without exceptions.

The data directory is redirected to a temporary folder before any Qingji
module is imported.  ``unittest discover`` loads this module first
alphabetically, which lets the environment variable win for the whole process
without touching the developer's real ``data/`` folder.

Pages are visited through the real multi-page entry point so ``st.page_link``
and ``st.switch_page`` resolve like they do inside the running app.
"""

from __future__ import annotations

import os
import tempfile
import unittest

_TEST_DATA_DIR = tempfile.mkdtemp(prefix="qingji_apptest_")
os.environ["QINGJI_DATA_DIR"] = _TEST_DATA_DIR

from streamlit.testing.v1 import AppTest  # noqa: E402

PAGES = [
    "pages/1_材料与证据.py",
    "pages/2_结论核验.py",
    "pages/3_成果与缺口.py",
]


class AppPageSmokeTest(unittest.TestCase):
    def test_all_pages_load_without_exceptions(self) -> None:
        app = AppTest.from_file("app.py", default_timeout=30)
        app.run()
        self.assertEqual(
            app.exception,
            [],
            f"app.py raised: {app.exception}",
        )
        for path in PAGES:
            with self.subTest(page=path):
                app.switch_page(path)
                app.run()
                self.assertEqual(
                    app.exception,
                    [],
                    f"{path} raised: {app.exception}",
                )


if __name__ == "__main__":
    unittest.main()
