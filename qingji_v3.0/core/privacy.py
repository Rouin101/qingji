"""本地常见隐私遮盖；沿用1.0的匹配思路，保留字符长度以维持原文定位。"""
import re

PATTERN = re.compile(
    r"(?<![0-9A-Za-z])(?:\d{17}[\dXx]|\d{15})(?![0-9A-Za-z])"
    r"|(?<![A-Za-z0-9._%+-])[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}(?![A-Za-z0-9._%+-])"
    r"|(?<!\d)1[3-9]\d{9}(?!\d)"
)

def redacted(text: str) -> str:
    return PATTERN.sub(lambda match: "＊" * len(match.group()), text)
