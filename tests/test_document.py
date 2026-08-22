"""Tests for local extraction of supported material upload formats."""

from __future__ import annotations

from io import BytesIO
from zipfile import ZipFile

import unittest

from qingji.document import DocumentImportError, extract_uploaded_text


class DocumentImportTests(unittest.TestCase):
    @staticmethod
    def _docx_payload() -> bytes:
        xml = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">
  <w:body>
    <w:p><w:r><w:t>第一段</w:t></w:r></w:p>
    <w:p><w:r><w:t>第二段</w:t><w:tab/><w:t>带制表符</w:t><w:br/><w:t>换行</w:t></w:r></w:p>
  </w:body>
</w:document>"""
        output = BytesIO()
        with ZipFile(output, "w") as archive:
            archive.writestr("word/document.xml", xml)
        return output.getvalue()

    @staticmethod
    def _pdf_payload() -> bytes:
        content = b"BT /F1 12 Tf 72 720 Td (PDF text) Tj ET\n"
        objects = [
            b"<< /Type /Catalog /Pages 2 0 R >>",
            b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
            (
                b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] "
                b"/Resources << /Font << /F1 5 0 R >> >> /Contents 4 0 R >>"
            ),
            b"<< /Length "
            + str(len(content)).encode()
            + b" >>\nstream\n"
            + content
            + b"endstream",
            b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
        ]
        payload = bytearray(b"%PDF-1.4\n")
        offsets = [0]
        for number, obj in enumerate(objects, start=1):
            offsets.append(len(payload))
            payload.extend(f"{number} 0 obj\n".encode())
            payload.extend(obj)
            payload.extend(b"\nendobj\n")
        xref_offset = len(payload)
        payload.extend(f"xref\n0 {len(objects) + 1}\n".encode())
        payload.extend(b"0000000000 65535 f \n")
        for offset in offsets[1:]:
            payload.extend(f"{offset:010d} 00000 n \n".encode())
        payload.extend(
            f"trailer\n<< /Root 1 0 R /Size {len(objects) + 1} >>\n"
            f"startxref\n{xref_offset}\n%%EOF\n".encode()
        )
        return bytes(payload)

    def test_utf8_text_and_markdown_are_supported(self) -> None:
        self.assertEqual(
            extract_uploaded_text("记录.txt", "带 BOM 的文字".encode("utf-8-sig")),
            "带 BOM 的文字",
        )
        self.assertEqual(
            extract_uploaded_text("记录.md", "# 标题".encode("utf-8")),
            "# 标题",
        )

    def test_docx_extracts_paragraphs_tabs_and_line_breaks(self) -> None:
        self.assertEqual(
            extract_uploaded_text("记录.docx", self._docx_payload()),
            "第一段\n第二段\t带制表符\n换行",
        )

    def test_pdf_extracts_text(self) -> None:
        self.assertIn(
            "PDF text",
            extract_uploaded_text("记录.pdf", self._pdf_payload()),
        )

    def test_invalid_or_unsupported_upload_is_rejected(self) -> None:
        with self.assertRaises(DocumentImportError):
            extract_uploaded_text("记录.docx", b"not a zip")
        with self.assertRaises(DocumentImportError):
            extract_uploaded_text("记录.pdf", b"content")


if __name__ == "__main__":
    unittest.main()
