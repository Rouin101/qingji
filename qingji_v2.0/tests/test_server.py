import base64
import json
import threading
import unittest
import urllib.error
import urllib.request
from server import EXAMPLE_REPLACEMENTS, Handler, LocalHTTPServer


class ServerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server = LocalHTTPServer(("127.0.0.1", 0), Handler)
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()
        cls.base = f"http://127.0.0.1:{cls.server.server_port}"

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()
        cls.thread.join(timeout=2)

    def call(self, path, body=None, headers=None):
        headers = headers or {}
        data = None
        if body is not None:
            data = json.dumps(body).encode()
            headers.setdefault("Content-Type", "application/json")
        request = urllib.request.Request(self.base + path, data=data, headers=headers)
        try:
            response = urllib.request.urlopen(request, timeout=5)
        except urllib.error.HTTPError as error:
            response = error
        with response:
            return response.status, json.loads(response.read())

    def test_uploaded_text_is_read_without_ai(self):
        status, result = self.call("/api/document", {"name": "报告.txt", "content": base64.b64encode("实践记录。".encode()).decode()})
        self.assertEqual(status, 200)
        self.assertEqual(result["text"], "实践记录。")
        status, result = self.call("/api/review", {"report": result})
        self.assertEqual(status, 200)
        self.assertEqual(result["result"]["mode"], "preliminary")

    def test_example_quotes_are_located_and_recheck_removes_applied_issue(self):
        status, result = self.call("/api/example")
        self.assertEqual(status, 200)
        self.assertEqual(len(result["result"]["issues"]), 2)
        report = result["result"]["report"]
        before, after = EXAMPLE_REPLACEMENTS[0]
        report["text"] = report["text"].replace(before, after)
        status, updated = self.call("/api/review", {"report": report, "mode": "example"})
        self.assertEqual(status, 200)
        self.assertEqual(len(updated["result"]["issues"]), 1)
        self.assertEqual(updated["result"]["coverage"], "curated_example_only")

    def test_arbitrary_text_is_not_fabricated_as_curated_example(self):
        status, result = self.call("/api/review", {"report": {"text": "任意报告。"}, "mode": "example"})
        self.assertEqual(status, 400)
        self.assertIn("本地预检", result["error"])

    def test_ai_request_without_processing_confirmation_is_rejected(self):
        status, result = self.call("/api/review", {"report": {"text": "实践报告。"}, "mode": "ai"})
        self.assertEqual(status, 400)
        self.assertIn("处理范围", result["error"])

    def test_example_followup_uses_selected_issue(self):
        _, data = self.call("/api/example")
        status, reply = self.call("/api/chat", {"report": data["result"]["report"], "materials": data["materials"], "issue": data["result"]["issues"][0], "question": "还需要补充什么依据？", "mode": "example"})
        self.assertEqual(status, 200)
        self.assertIn("覆盖情况", reply["answer"])
        self.assertEqual(reply["label"], "示例说明")

    def test_other_origin_and_source_files_are_not_exposed(self):
        status, _ = self.call("/api/status", headers={"Origin": "https://other.example"})
        self.assertEqual(status, 403)
        status, _ = self.call("/../core/review.py")
        self.assertEqual(status, 404)

    def test_invalid_document_request_has_controlled_error(self):
        status, result = self.call("/api/document", {"name": "bad.txt", "content": "not base64"})
        self.assertEqual(status, 400)
        self.assertIn("error", result)

    def test_second_server_cannot_share_running_port(self):
        with self.assertRaises(OSError):
            duplicate = LocalHTTPServer(("127.0.0.1", self.server.server_port), Handler)
            duplicate.server_close()


if __name__ == "__main__":
    unittest.main()
