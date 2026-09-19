"""模型端边界标记：让模型用 [[next]] 自己决定在哪里断句。

解析规则：
- 标记只作为提示，是否使用由模型决定；
- ``` 围栏代码块内的标记不生效、不移除（防止切坏代码）；
- 代码块外的标记会被移除并按位置切分；
- 切分结果不足 2 段视为未使用标记；
- 容错：模型少写一层方括号（[next]）或用全角括号（【next】／［next］）、
  大小写混写（[NEXT]）都按标记处理，避免标记直接漏给用户。
"""

from __future__ import annotations

import re

MARKER = "[[next]]"

# 容错匹配：[[next]] / [next] / 【next】 / ［next］，忽略大小写与内部空格；
# 括号层数写歪或漏写收尾括号（[[next / [[next] / [[next]]] / [[[next]]]）也整段吃掉，
# 不留 [ 或 ] 碎片。必须包含 next 词。
MARKER_RE = re.compile(
    r"(?:"
    r"\[{2,3}\s*next\s*\]{0,3}"
    r"|\[\s*next\s*\]{0,2}"
    r"|【{1,2}\s*next\s*】{0,2}"
    r"|［{1,2}\s*next\s*］{0,2}"
    r")",
    re.IGNORECASE,
)

# 标记空壳残渣：只匹配双层以上方括号残渣（[[]]），用于模型漏写 next 时的容错清理。
# 绝不匹配单层 [] / 【】 / ［］，避免误杀 Markdown 复选框 `- [ ]`、空列表和常规括号代码。
DEBRIS_RE = re.compile(r"\[{2,3}\s*\]{2,3}")

DEFAULT_PROMPT = (
    "【输出格式与表达规范】\n"
    "1. 拟人分段：如果属于日常闲聊，想把回复分成多条短消息发送，请在需要断开的位置插入标记 {marker}（一条回复最多 {limit} 处），插在标点之后。"
    "标记请完整写出两层方括号，不要只写一层。代码块、表格、引用块内部禁止出现该标记。不需要分条时不要使用。\n"
    "2. Antigravity 架构化逻辑（拒绝流水账）：若属于事件复盘、长篇总结、技术指导或专业报告，严禁通篇大白话堆砌长段落，必须呈现顶级架构师的逻辑风骨：\n"
    "   - 提纲挈领：首句用干练的一句话定性全局主题或核心脉络；\n"
    "   - 模块拆解：按逻辑推进分项展开，主大项使用「1. **核心概念/阶段**」或「### 标题」，下属细节使用缩进列表「- **要点导引**：阐述具体事实与数据」；\n"
    "   - 画龙点睛：对核心金句、重要洞察或风险警示，独立使用引用块（> **核心洞察/金句**：...）收尾升华；\n"
    "3. 视觉节律与高亮规范（1:1 对齐 Antigravity 原生排版）：\n"
    "   - 核心重点加厚：中文重要结论与小项导引词一律使用 **加粗**；\n"
    "   - 精准暗红标红（极其关键）：仅对真正的代码指令、英文专有名词、核心参数名与数据规格（如 `seed`, `negative`, `Gemini AI Pro`, `VPS`, `28%`, `--ar 16:9`）使用单反引号包裹（`参数`），严禁对整句中文大白话滥用反引号；\n"
    "   - 对比维度与清单：多维度对比或步骤明细优先使用 Markdown 表格展现。"
)


def build_marker_prompt(limit: int, marker: str = MARKER) -> str:
    return DEFAULT_PROMPT.format(marker=marker, limit=max(1, int(limit)))


def _has_marker(source: str, marker: str = MARKER) -> bool:
    if marker == MARKER:
        return bool(MARKER_RE.search(source) or DEBRIS_RE.search(source))
    return marker in source


def _marker_len(source: str, index: int, marker: str = MARKER) -> int:
    """在 index 处匹配标记（或双层残渣），返回长度；不是标记返回 0。"""
    if marker == MARKER:
        match = MARKER_RE.match(source, index) or DEBRIS_RE.match(source, index)
        return match.end() - index if match else 0
    if source.startswith(marker, index):
        return len(marker)
    return 0


def parse_marker(text: str, marker: str = MARKER) -> tuple[str, list[str] | None]:
    """解析边界标记。

    Returns:
        (切分后的完整文本, 分段列表或 None)。未有效使用标记时第二项为 None，
        第一项可能等于原文（标记只在代码块内或不存在）。
    """
    source = text or ""
    if not _has_marker(source, marker):
        return source, None

    parts: list[str] = []
    buf: list[str] = []
    in_fence = False
    used = False
    i = 0
    n = len(source)

    while i < n:
        if source.startswith("```", i):
            in_fence = not in_fence
            buf.append("```")
            i += 3
            continue
        if source[i] == "`":
            # 行内代码：同一行内成对的 ` 之间不认标记（与分段引擎规则一致）。
            end = source.find("`", i + 1)
            if end != -1 and "\n" not in source[i:end]:
                buf.append(source[i : end + 1])
                i = end + 1
                continue
        if not in_fence:
            length = _marker_len(source, i, marker)
            if length:
                used = True
                parts.append("".join(buf))
                buf = []
                i += length
                continue
        buf.append(source[i])
        i += 1
    parts.append("".join(buf))

    if not used:
        return source, None

    cleaned = [part.strip() for part in parts]
    cleaned = [part for part in cleaned if part]
    if not cleaned:
        return source, None
    if len(cleaned) == 1:
        return cleaned[0], None
    return "".join(cleaned), cleaned
