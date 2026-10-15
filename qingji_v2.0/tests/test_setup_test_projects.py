import unittest
import tempfile
from pathlib import Path
from scripts.setup_test_projects import setup, ROOT

class TestSetupTestProjectsGuards(unittest.TestCase):
    def test_reject_production_path(self):
        with self.assertRaises(ValueError) as ctx:
            setup("data/projects.sqlite3")
        self.assertIn("production database path", str(ctx.exception))

    def test_reject_outside_qa_directory(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            outside_db = Path(tmpdir) / "test.sqlite3"
            with self.assertRaises(ValueError) as ctx:
                setup(str(outside_db))
            self.assertIn("must reside within QA root directory", str(ctx.exception))

    def test_reject_existing_database_file(self):
        qa_root = (ROOT / ".browser-test-output").resolve()
        qa_root.mkdir(parents=True, exist_ok=True)
        dummy_existing = qa_root / "_guard_test_existing.sqlite3"
        dummy_existing.write_text("existing", encoding="utf-8")
        try:
            with self.assertRaises(FileExistsError) as ctx:
                setup(str(dummy_existing))
            self.assertIn("already exists", str(ctx.exception))
        finally:
            if dummy_existing.exists():
                dummy_existing.unlink()

if __name__ == "__main__":
    unittest.main()
