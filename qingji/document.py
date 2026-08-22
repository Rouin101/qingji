"""Local text extraction for supported material upload formats."""

from __future__ import annotations

from io import BytesIO
from zipfile import BadZipFile, ZipFile
from xml.etree import ElementTree

from pypdf import PdfReader


class DocumentImportError(ValueError):
    """Raised when an uploaded document cannot be converted to plain text."""


_WORD_NS = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
_WORD_TAG = f"{{{_WORD_NS}}}"


def _extract_docx_text(payload: bytes) -> str:
    try:
        with ZipFile(BytesIO(payload)) as archive:
            document_xml = archive.read("word/document.xml")
    except (BadZipFile, KeyError, OSError) as exc:
        raise DocumentImportError(
            "Word 文件无法读取，请确认它是未加密的 .docx 文件。"
        ) from exc

    try:
        root = ElementTree.fromstring(document_xml)
    except ElementTree.ParseError as exc:
        raise DocumentImportError("Word 文件内容损坏，无法读取正文。") from exc

    paragraphs: list[str] = []
    for paragraph in root.iter(f"{_WORD_TAG}p"):
        parts: list[str] = []
        for node in paragraph.iter():
            if node.tag == f"{_WORD_TAG}t":
                parts.append(node.text or "")
            elif node.tag == f"{_WORD_TAG}tab":
                parts.append("\t")
            elif node.tag in {f"{_WORD_TAG}br", f"{_WORD_TAG}cr"}:
                parts.append("\n")
        paragraphs.append("".join(parts))
    return "\n".join(paragraphs)


def _extract_pdf_text(payload: bytes) -> str:
    try:
        reader = PdfReader(BytesIO(payload), strict=False)
        if reader.is_encrypted:
            try:
                unlocked = reader.decrypt("")
            except Exception as exc:
                raise DocumentImportError(
                    "PDF 文件已加密，暂时无法读取正文。"
                ) from exc
            if not unlocked:
                raise DocumentImportError("PDF 文件已加密，暂时无法读取正文。")
        if not reader.pages:
            raise DocumentImportError("PDF 文件没有可读取的页面。")
        page_texts = [(page.extract_text() or "").rstrip() for page in reader.pages]
    except DocumentImportError:
        raise
    except Exception as exc:
        raise DocumentImportError(
            "PDF 文件无法读取，请确认文件未损坏或使用了受支持的文本编码。"
        ) from exc
    return "\n\n".join(page_texts)


def extract_uploaded_text(filename: str, payload: bytes) -> str:
    """Decode a supported upload into plain text without external services."""

    suffix = (filename.rsplit(".", 1)[-1] if "." in filename else "").lower()
    if suffix in {"txt", "md"}:
        try:
            return payload.decode("utf-8-sig")
        except UnicodeDecodeError as exc:
            raise DocumentImportError(
                "文字文件不是 UTF-8 编码，请转换编码后重试。"
            ) from exc
    if suffix == "docx":
        return _extract_docx_text(payload)
    if suffix == "pdf":
        return _extract_pdf_text(payload)
    raise DocumentImportError(
        "仅支持 UTF-8 的 .txt/.md、未加密的 .docx 和可提取文本的 .pdf 文件。"
    )
