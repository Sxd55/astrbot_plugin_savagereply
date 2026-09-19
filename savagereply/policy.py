"""纯规则分流：决定一条回复是原样发送还是进入分段引擎。"""

from __future__ import annotations

import re
from dataclasses import dataclass

from .config import ReplyOptions

MODE_BYPASS = "bypass"
MODE_SPLIT = "split"

# 超长回复在 4 倍上限内改用段落切；再长（多半是粘贴/代码/数据）仍然整条放行。
LONG_SPLIT_FACTOR = 4

_BLOCK_MATH = re.compile(r"\$\$.+?\$\$", re.DOTALL)


@dataclass
class Decision:
    mode: str
    reason: str


def decide(text: str, options: ReplyOptions) -> Decision:
    """按固定优先级给出分流结论。顺序即优先级，见 CLAUDE.md。"""
    stripped = (text or "").strip()
    if not stripped:
        return Decision(MODE_BYPASS, "empty")
    if options.protect_code_block and "```" in stripped:
        return Decision(MODE_BYPASS, "code_block")
    if options.protect_table and is_markdown_table(stripped):
        return Decision(MODE_BYPASS, "table")
    if options.protect_math and _BLOCK_MATH.search(stripped):
        return Decision(MODE_BYPASS, "math")
    if getattr(options, "protect_structured_data", True) and is_structured_analysis(stripped):
        return Decision(MODE_BYPASS, "structured_data")
    length = len(stripped)
    if options.max_total_chars > 0 and length > options.max_total_chars:
        if length <= options.max_total_chars * LONG_SPLIT_FACTOR:
            # 超长不再整篇放行：交给段落引擎切成多条（P0）。
            return Decision(MODE_SPLIT, "long")
        return Decision(MODE_BYPASS, "too_long")
    if length < options.min_total_chars:
        return Decision(MODE_BYPASS, "too_short")
    return Decision(MODE_SPLIT, "ok")


def is_markdown_table(text: str) -> bool:
    """连续两行以上以 | 开头且含列分隔的文本视为 Markdown 表格。"""
    run = 0
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith("|") and stripped.count("|") >= 2:
            run += 1
            if run >= 2:
                return True
        else:
            run = 0
    return False


_LIST_ITEM_RE = re.compile(
    r"^\s*(?:\d+[\.、\)]|\(\d+\)|[①②③④⑤⑥⑦⑧⑨⑩]|[-*•]\s+).+"
)
_KEY_VALUE_RE = re.compile(
    r"^\s*[-*•]?\s*[\u4e00-\u9fa5\w]{2,16}\s*[:：]\s*.+"
)
_HEADER_SECTION_RE = re.compile(
    r"(?:^|\n)(?:#{1,4}\s+|【(?:分析|数据|统计|报告|汇总|排查|总结)[^】]*】)"
)


def is_structured_analysis(text: str) -> bool:
    """判断是否为数据密集型或结构化多点分析回复。
    
    规则：
    1. 包含 3 项及以上有效列表项（1. 2. 3. 或 - 条目等）；
    2. 或包含 3 行及以上指标键值对（指标名: 数值）；
    3. 或包含结构化分析/数据小标题，且伴随至少 2 项列表/指标。
    """
    lines = [line.strip() for line in (text or "").splitlines() if line.strip()]
    if len(lines) < 3:
        return False

    list_items = 0
    kv_items = 0
    for line in lines:
        if _LIST_ITEM_RE.match(line):
            if len(line) >= 4:
                list_items += 1
        elif _KEY_VALUE_RE.match(line):
            kv_items += 1

    if list_items >= 3 or kv_items >= 3:
        return True

    if _HEADER_SECTION_RE.search(text) and (list_items >= 2 or kv_items >= 2):
        return True

    return False

