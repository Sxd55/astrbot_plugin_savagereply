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
    "2. Antigravity 架构化逻辑与层级排版（1:1 原生规范，拒绝流水账）：若属于技术分析、长篇总结、故障复盘或专业指导，必须严格遵循顶级架构师风骨：\n"
    "   - 提纲挈领：首句干练定性全局核心结论；\n"
    "   - 阶梯式次级缩进（极度关键）：主大项使用「1. **核心大项**：」或「### 标题」，下属展开细节必须缩进 4 个空格并使用「    - 在...」或「    - **小项导引**：事实与分析」，严禁次级小项不缩进导致平铺；\n"
    "   - 画龙点睛：重要洞察或核心警示独立使用引用块（> **核心洞察**：...）收尾；\n"
    "3. 字体加粗与高亮视觉规范（严格对齐 Antigravity 真实排版）：\n"
    "   - 黑色加粗（视觉重心与定性锚点）：所有核心结论、量化数据、重要检查结果必须使用 **黑色加粗**（例如：`    - 全量运行 147 项测试：**106 项通过，41 项跳过，0 失败**。`、`    - **账号层异常**：**全拉取失败**，会话被服务端踢掉。`）；\n"
    "   - 暗红标红（极度克制，严禁滥用）：仅允许真正的代码文件路径（如 `tests/test_t2i.py`）、程序命令参数（如 `--port 8080`）或代码函数名使用单反引号包裹；严禁对普通英文缩写（如 QQ、IP、WS、INFO、connected 等）、常规数字或整段中文大白话滥用反引号，保持版面干净高级；\n"
    "   - 对比维度优先使用 Markdown 表格展现。"
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
