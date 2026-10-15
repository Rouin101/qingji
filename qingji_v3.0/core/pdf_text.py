"""只提取PDF的可复制文字，不做OCR，不继承排版或运行附件。"""
from __future__ import annotations

import io

from core.review import ReviewError, MAX_MATERIAL_CHARS

MAX_PDF_PAGES = 80
MAX_PAGE_STREAM_BYTES = 8 * 1024 * 1024
MAX_TOTAL_STREAM_BYTES = 32 * 1024 * 1024
MAX_DECOMPRESSED_BYTES = 8 * 1024 * 1024


def read_pdf_text(content: bytes) -> tuple[str, tuple[str, ...]]:
    try:
        from pypdf import PdfReader
        from pypdf import filters
    except ImportError:
        raise ReviewError("PDF读取组件尚未安装，请先使用DOCX或粘贴正文。") from None
    try:
        # pypdf提供展开限额，先限制解压，再检查整页与整份内容。
        filters.ZLIB_MAX_OUTPUT_LENGTH = min(filters.ZLIB_MAX_OUTPUT_LENGTH, MAX_DECOMPRESSED_BYTES)
        filters.LZW_MAX_OUTPUT_LENGTH = min(filters.LZW_MAX_OUTPUT_LENGTH, MAX_DECOMPRESSED_BYTES)
        filters.RUN_LENGTH_MAX_OUTPUT_LENGTH = min(filters.RUN_LENGTH_MAX_OUTPUT_LENGTH, MAX_DECOMPRESSED_BYTES)
        reader = PdfReader(io.BytesIO(content), strict=True)
        if reader.is_encrypted:
            raise ReviewError("这份PDF需要密码，请先导出不加密的版本或粘贴正文。")
        count = len(reader.pages)
        if not count or count > MAX_PDF_PAGES:
            raise ReviewError("PDF请控制在80页以内；本次不会截断后声称整篇检查。")
        blocks, unreadable = [], []
        total_stream = 0
        for number, page in enumerate(reader.pages, 1):
            streams = page.get_contents()
            if streams is not None:
                size = len(streams.get_data())
                total_stream += size
                if size > MAX_PAGE_STREAM_BYTES or total_stream > MAX_TOTAL_STREAM_BYTES:
                    raise ReviewError("PDF展开内容过大，请导出文字版本或粘贴正文。")
            text = page.extract_text() or ""
            if not text.strip():
                unreadable.append(number)
                continue
            blocks.append(f"[第{number}页]\n{text.strip()}")
            if sum(map(len, blocks)) > MAX_MATERIAL_CHARS:
                raise ReviewError("PDF提取文字超过48,000字，请分开项目；不会自动截断。")
        if not blocks:
            raise ReviewError("PDF没有可读取的文字，可能是扫描件。请转换为可复制文字后再上传。")
        notes = ["已提取PDF可复制文字；未读取图片或进行OCR，不保留原排版，表格与多栏的顺序需要核对。"]
        if unreadable:
            pages = "、".join(map(str, unreadable))
            notes.append(f"第{pages}页没有提取到文字，可能为空白或扫描页；本次结果不覆盖这些页，请补充文字后核对。")
        return "\n\n".join(blocks), tuple(notes)
    except ReviewError:
        raise
    except Exception:
        raise ReviewError("无法读取这份PDF，请确认文件完整，或导出DOCX／粘贴正文。") from None
