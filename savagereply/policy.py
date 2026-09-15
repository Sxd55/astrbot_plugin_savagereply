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
