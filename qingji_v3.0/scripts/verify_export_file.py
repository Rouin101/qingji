"""Verification utility for exported files (DOCX, TXT, MD).
Performs character-for-character comparison against snapshot text,
extracts docx XML paragraphs, and computes SHA-256 digests.
"""
from __future__ import annotations

import hashlib
import json
import re
import sys
import zipfile
from pathlib import Path
from xml.etree import ElementTree as ET

W = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"


def compute_sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def extract_docx_paragraphs(docx_path: str | Path) -> str:
    with zipfile.ZipFile(docx_path) as z:
        xml_content = z.read("word/document.xml")
    root = ET.fromstring(xml_content)
    body = root.find(f"{{{W}}}body")
    if body is None:
        return ""
    paragraphs = []
    for p in body.findall(f"{{{W}}}p"):
        parts = []
        for child in p.iter():
            tag = child.tag.rsplit("}", 1)[-1]
            if tag == "t":
                parts.append(child.text or "")
            elif tag == "tab":
                parts.append("\t")
        paragraphs.append("".join(parts))
    return "\n".join(paragraphs)


def verify_file(file_path: str, expected_text: str, extra_checks: dict | None = None) -> dict:
    p = Path(file_path)
    if not p.exists():
        return {"status": "error", "error": f"File does not exist: {file_path}"}
    
    file_bytes = p.read_bytes()
    sha256 = compute_sha256(file_bytes)
    extra_checks = extra_checks or {}
    result = {
        "status": "passed",
        "file": str(p),
        "size": len(file_bytes),
        "sha256": sha256,
        "format": p.suffix.lower().lstrip("."),
    }

    norm_expected = expected_text.replace("\r\n", "\n").replace("\r", "\n")

    if p.suffix.lower() == ".docx":
        extracted = extract_docx_paragraphs(p)
        norm_extracted = extracted.replace("\r\n", "\n").replace("\r", "\n")
        if norm_extracted != norm_expected:
            result["status"] = "failed"
            result["error"] = "DOCX text mismatch with snapshot"
            result["extracted"] = norm_extracted
            result["expected"] = norm_expected
        else:
            result["exact_match"] = True
    elif p.suffix.lower() == ".txt":
        content = file_bytes.decode("utf-8")
        norm_content = content.replace("\r\n", "\n").replace("\r", "\n")
        if norm_content != norm_expected:
            result["status"] = "failed"
            result["error"] = "TXT text mismatch with snapshot"
            result["extracted"] = norm_content
            result["expected"] = norm_expected
        else:
            result["exact_match"] = True
    elif p.suffix.lower() == ".md":
        content = file_bytes.decode("utf-8")
        norm_content = content.replace("\r\n", "\n").replace("\r", "\n")
        marker = "\n\n## 当前正文\n\n"
        idx = norm_content.find(marker)
        if idx == -1:
            marker_start = "## 当前正文\n\n"
            if norm_content.startswith(marker_start):
                body_text = norm_content[len(marker_start):]
            else:
                result["status"] = "failed"
                result["error"] = "Markdown missing ## 当前正文 section"
                return result
        else:
            body_text = norm_content[idx + len(marker):]

        if body_text != norm_expected:
            result["status"] = "failed"
            result["error"] = "Markdown ## 当前正文 mismatch with snapshot"
            result["extracted"] = body_text
            result["expected"] = norm_expected
        else:
            result["exact_match"] = True
        
        # Check required extra strings (e.g. notices, mode)
        for check_key, val in extra_checks.items():
            items = val if isinstance(val, list) else [val]
            for expected_str in items:
                if str(expected_str) not in norm_content:
                    result["status"] = "failed"
                    result["error"] = f"Markdown missing expected {check_key}: '{expected_str}'"
                    break
    else:
        result["status"] = "unknown_format"

    return result


if __name__ == "__main__":
    if len(sys.argv) < 3:
        print("Usage: verify_export_file.py <file_path> <expected_text_or_file> [extra_checks_json]")
        sys.exit(1)
    target = sys.argv[1]
    expected_arg = sys.argv[2]
    expected_p = Path(expected_arg)
    if expected_p.exists():
        expected_str = expected_p.read_text(encoding="utf-8")
    else:
        expected_str = expected_arg
    extra = json.loads(sys.argv[3]) if len(sys.argv) > 3 else {}
    res = verify_file(target, expected_str, extra)
    print(json.dumps(res, ensure_ascii=False, indent=2))
    sys.exit(0 if res["status"] == "passed" else 1)
