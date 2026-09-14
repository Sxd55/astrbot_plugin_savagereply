"""模型端边界标记：让模型用 [[next]] 自己决定在哪里断句。

解析规则：
- 标记只作为提示，是否使用由模型决定；
- ``` 围栏代码块内的标记不生效、不移除（防止切坏代码）；
- 代码块外的标记会被移除并按位置切分；
- 切分结果不足 2 段视为未使用标记。
"""

from __future__ import annotations

MARKER = "[[next]]"

DEFAULT_PROMPT = (
    "【输出格式约定】如果你想把回复分成多条消息发送，"
    "请在需要断开的位置插入标记 {marker}（一条回复最多 {limit} 处），插在标点之后。"
    "是否使用、用在哪里由你判断；不需要分条时不要使用。"
    "代码块、表格、引用块内部禁止出现该标记。"
)


def build_marker_prompt(limit: int, marker: str = MARKER) -> str:
    return DEFAULT_PROMPT.format(marker=marker, limit=max(1, int(limit)))


def parse_marker(text: str, marker: str = MARKER) -> tuple[str, list[str] | None]:
    """解析边界标记。

    Returns:
        (切分后的完整文本, 分段列表或 None)。未有效使用标记时第二项为 None，
        第一项可能等于原文（标记只在代码块内或不存在）。
    """
    source = text or ""
    if marker not in source:
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
        if not in_fence and source.startswith(marker, i):
            used = True
            parts.append("".join(buf))
            buf = []
            i += len(marker)
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
