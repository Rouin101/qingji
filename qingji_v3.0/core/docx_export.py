"""将当前传入稿导出为基础 Word 文档，不读取或继承原文件版式。"""
from __future__ import annotations

import io
import re
import zipfile
from xml.etree import ElementTree as ET

from core.review import MAX_REPORT_CHARS, ReviewError

W = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
CP = "http://schemas.openxmlformats.org/package/2006/metadata/core-properties"
DC = "http://purl.org/dc/elements/1.1/"
XML_SPACE = "{http://www.w3.org/XML/1998/namespace}space"
ET.register_namespace("w", W)
ET.register_namespace("cp", CP)
ET.register_namespace("dc", DC)

INVALID_XML = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\ud800-\udfff\ufffe\uffff]")
HEADING = re.compile(r"^\s*(?:#{1,6}[ \t]+|[一二三四五六七八九十百]+[、.．]|第[一二三四五六七八九十百0-9]+[章节]|[（(][一二三四五六七八九十百]+[）)])")


def _element(parent, name, attributes=None):
    return ET.SubElement(parent, f"{{{W}}}{name}", {f"{{{W}}}{k}": str(v) for k, v in (attributes or {}).items()})


def _xml(root):
    return ET.tostring(root, encoding="utf-8", xml_declaration=True)


def _paragraph(parent, line, style=None):
    paragraph = _element(parent, "p")
    if style:
        properties = _element(paragraph, "pPr")
        _element(properties, "pStyle", {"val": style})
    if not line:
        return
    # 每个输入行对应一个段落；真实 tab 用 Word 的 tab 元素表示。
    for index, part in enumerate(line.split("\t")):
        if index:
            _element(_element(paragraph, "r"), "tab")
        if part:
            text = _element(_element(paragraph, "r"), "t")
            text.set(XML_SPACE, "preserve")
            text.text = part


def _styles():
    root = ET.Element(f"{{{W}}}styles")
    for ident, label, half_points, bold in (("Normal", "正文", 24, False),
                                            ("Title", "标题", 40, True),
                                            ("Heading1", "标题 1", 32, True)):
        style = _element(root, "style", {"type": "paragraph", "styleId": ident, **({"default": "1"} if ident == "Normal" else {})})
        _element(style, "name", {"val": label})
        if ident != "Normal":
            _element(style, "basedOn", {"val": "Normal"})
            _element(style, "next", {"val": "Normal"})
        paragraph = _element(style, "pPr")
        _element(paragraph, "spacing", {"before": 0 if ident == "Normal" else 160,
                                         "after": 0 if ident == "Normal" else 120,
                                         "line": 360, "lineRule": "auto"})
        if ident != "Normal":
            _element(paragraph, "keepNext")
        if ident == "Heading1":
            _element(paragraph, "outlineLvl", {"val": 0})
        run = _element(style, "rPr")
        _element(run, "rFonts", {"ascii": "Times New Roman", "hAnsi": "Times New Roman", "eastAsia": "宋体"})
        _element(run, "sz", {"val": half_points})
        _element(run, "szCs", {"val": half_points})
        if bold:
            _element(run, "b")
    return _xml(root)


def export_report_docx(name: str, text: str) -> bytes:
    """导出全部文字与空段落；CRLF/CR 统一为段落换行，不新增正文标题。"""
    if not isinstance(name, str) or not name.strip() or len(name) > 200:
        raise ReviewError("导出报告名称不完整或过长。")
    if not isinstance(text, str) or not text.strip():
        raise ReviewError("请先准备包含文字的当前报告，再导出 Word。")
    if len(text) > MAX_REPORT_CHARS:
        raise ReviewError("当前 Word 导出支持 24000 字以内的报告；不会自动截断正文。")
    if INVALID_XML.search(name) or INVALID_XML.search(text):
        raise ReviewError("报告含 Word 无法保存的控制字符，请清理后重新导出；正文未被自动删改。")
    normalized = text.replace("\r\n", "\n").replace("\r", "\n")
    basename = re.split(r"[\\/]", name)[-1]
    title = re.sub(r"\.(?:docx?|pdf|txt|md)$", "", basename, flags=re.IGNORECASE).strip()
    root = ET.Element(f"{{{W}}}document")
    body = _element(root, "body")
    first_nonempty = True
    for line in normalized.split("\n"):
        style = None
        stripped = line.strip()
        if stripped:
            if first_nonempty and len(stripped) <= 100 and (stripped in {name.strip(), basename.strip(), title} or stripped.startswith("# ")):
                style = "Title"
            elif len(stripped) <= 100 and HEADING.match(line):
                style = "Heading1"
            first_nonempty = False
        _paragraph(body, line, style)
    section = _element(body, "sectPr")
    _element(section, "pgSz", {"w": 11906, "h": 16838})  # A4 portrait
    _element(section, "pgMar", {"top": 1134, "right": 1134, "bottom": 1134, "left": 1134,
                                 "header": 567, "footer": 567, "gutter": 0})
    core = ET.Element(f"{{{CP}}}coreProperties")
    ET.SubElement(core, f"{{{DC}}}title").text = name
    app = ET.Element("Properties", xmlns="http://schemas.openxmlformats.org/officeDocument/2006/extended-properties")
    ET.SubElement(app, "Application").text = "青迹 3.0"
    parts = {
        "[Content_Types].xml": b'''<?xml version="1.0" encoding="UTF-8"?>
<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">
<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>
<Default Extension="xml" ContentType="application/xml"/>
<Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/>
<Override PartName="/word/styles.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.styles+xml"/>
<Override PartName="/docProps/core.xml" ContentType="application/vnd.openxmlformats-package.core-properties+xml"/>
<Override PartName="/docProps/app.xml" ContentType="application/vnd.openxmlformats-officedocument.extended-properties+xml"/>
</Types>''',
        "_rels/.rels": b'''<?xml version="1.0" encoding="UTF-8"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="word/document.xml"/>
<Relationship Id="rId2" Type="http://schemas.openxmlformats.org/package/2006/relationships/metadata/core-properties" Target="docProps/core.xml"/>
<Relationship Id="rId3" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/extended-properties" Target="docProps/app.xml"/>
</Relationships>''',
        "word/_rels/document.xml.rels": b'''<?xml version="1.0" encoding="UTF-8"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
<Relationship Id="rIdStyles" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/styles" Target="styles.xml"/>
</Relationships>''',
        "word/document.xml": _xml(root), "word/styles.xml": _styles(),
        "docProps/core.xml": _xml(core), "docProps/app.xml": _xml(app),
    }
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w") as archive:
        for path, content in parts.items():
            info = zipfile.ZipInfo(path, date_time=(1980, 1, 1, 0, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            archive.writestr(info, content)
    return output.getvalue()
