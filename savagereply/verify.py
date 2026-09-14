"""轻量风险扫描：零成本、零阻塞的出口安检。

只做三件纯规则的事，命中仅记录（可选在结尾追加不确定提示）：
1. 可信度承诺（100%、包治、稳赚……）
2. 无出处的统计声明（据 xx 统计 / 研究 / 报告）
3. 用户没提过的链接（疑似编造 URL）
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from urllib.parse import urlparse

from .config import ReplyOptions

_VAGUE_SOURCE = re.compile(r"(据|根据)[^，。！？；\n]{0,12}(统计|调查|研究|报告|数据显示)")
_URL = re.compile(r"https?://[^\s。，、；！？\u3000（）【】《》「」]+")
MAX_RISKS = 3
SNIPPET_PAD = 12


@dataclass
class Risk:
    kind: str
    snippet: str


def scan_risks(text: str, options: ReplyOptions, user_text: str = "") -> list[Risk]:
    """返回命中的风险列表；永不抛异常、永不修改文本。"""
    if not options.verify_enabled or not text:
        return []
    risks: list[Risk] = []

    for word in options.verify_absolute_words:
        pos = text.find(word)
        if pos != -1:
            risks.append(Risk("absolute", _snippet(text, pos, word)))
            break

    match = _VAGUE_SOURCE.search(text)
    if match:
        risks.append(Risk("vague_source", match.group(0)))

    for match in _URL.finditer(text):
        url = match.group(0)
        domain = _domain(url)
        if domain and domain not in (user_text or ""):
            risks.append(Risk("unmentioned_url", url))
            break

    return risks[:MAX_RISKS]


def _snippet(text: str, pos: int, word: str) -> str:
    start = max(0, pos - SNIPPET_PAD)
    end = min(len(text), pos + len(word) + SNIPPET_PAD)
    return text[start:end].replace("\n", " ")


def _domain(url: str) -> str:
    try:
        return (urlparse(url).hostname or "").lower().rstrip(".")
    except ValueError:
        return ""
