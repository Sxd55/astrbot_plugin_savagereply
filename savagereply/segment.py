"""纯函数分段引擎：保护区扫描 + 区间断点 + 短尾合并 + 段数上限。"""

from __future__ import annotations

from .config import ReplyOptions

STRONG_PUNCT = set("。？！?!…~～")
WEAK_PUNCT = set("，,、；;：:")
TRIM_TAIL = STRONG_PUNCT | WEAK_PUNCT
OPEN_CHARS = set("（(【[《「『{“‘")
PAIR_MAP = {
    "（": "）",
    "(": ")",
    "【": "】",
    "[": "]",
    "《": "》",
    "「": "」",
    "『": "』",
    "{": "}",
    "“": "”",
    "‘": "’",
}


class _Splitter:
    def __init__(self, options: ReplyOptions):
        self.options = options
        self.segments: list[str] = []
        self.stack: list[str] = []
        self._buf: list[str] = []
        self._weight = 0

    @property
    def weight(self) -> int:
        return self._weight

    def add(self, chunk: str) -> None:
        if not chunk:
            return
        self._buf.append(chunk)
        for char in chunk:
            if not char.isspace():
                self._weight += 1

    def cut(self) -> None:
        chunk = "".join(self._buf).strip()
        self._buf = []
        self._weight = 0
        if not chunk:
            return
        if not self.options.keep_punct:
            chunk = chunk.rstrip("".join(sorted(TRIM_TAIL))).rstrip()
        if chunk:
            self.segments.append(chunk)


def split_text(text: str, options: ReplyOptions) -> list[str]:
    """把一段文本切成若干短句。保护区内绝不切断。"""
    source = (text or "").replace("\r\n", "\n").replace("\r", "\n").strip()
    if not source:
        return []

    splitter = _Splitter(options)
    protect_fence = options.protect_code_block
    protect_math = options.protect_math
    min_chars = options.segment_min_chars
    max_chars = options.segment_max_chars
    hard_max = options.segment_hard_max_chars
    n = len(source)
    i = 0

    while i < n:
        # 1) 代码块：``` 到下一个 ```（或结尾）
        if protect_fence and source.startswith("```", i):
            end = source.find("```", i + 3)
            end = end + 3 if end != -1 else n
            splitter.add(source[i:end])
            i = end
            continue

        char = source[i]

        # 2) 行内代码：同一行内成对的 `
        if char == "`":
            end = source.find("`", i + 1)
            if end != -1 and "\n" not in source[i:end]:
                splitter.add(source[i : end + 1])
                i = end + 1
                continue

        # 3) 公式：$$ 块级 与 $ 行内（限长且同一行）
        if protect_math and source.startswith("$$", i):
            end = source.find("$$", i + 2)
            if end != -1:
                splitter.add(source[i : end + 2])
                i = end + 2
                continue
        if protect_math and char == "$":
            end = source.find("$", i + 1)
            if end != -1 and "\n" not in source[i:end] and end - i <= 60:
                splitter.add(source[i : end + 1])
                i = end + 1
                continue

        # 4) 思维链块
        if source.startswith("<think>", i):
            end = source.find("</think>", i + 7)
            end = end + 8 if end != -1 else n
            splitter.add(source[i:end])
            i = end
            continue

        # 5) URL：整个 token 保护，避免 ? ! 等被当断点
        if char in "hH" and (source.startswith("http://", i) or source.startswith("https://", i)):
            j = i
            while j < n and source[j] not in " \t\n。？！，、；：“”‘’（）【】《》「」『』":
                j += 1
            splitter.add(source[i:j])
            i = j
            continue

        # 6) 表格行：行首 | 起整行保护
        if char == "|" and (i == 0 or source[i - 1] == "\n"):
            end = source.find("\n", i)
            end = end if end != -1 else n
            splitter.add(source[i:end])
            i = end
            continue

        # 7) 断点（成对符号内部不切）
        if not splitter.stack:
            if char == "\n":
                j = i
                while j < n and source[j] in " \t\n":
                    j += 1
                splitter.add(source[i:j])
                if ("\n\n" in source[i:j] and splitter.weight >= 2) or splitter.weight >= min_chars:
                    splitter.cut()
                i = j
                continue
            if char in STRONG_PUNCT:
                j = i
                while j < n and source[j] in STRONG_PUNCT:
                    j += 1
                splitter.add(source[i:j])
                if splitter.weight >= min_chars:
                    splitter.cut()
                i = j
                continue
            if char in WEAK_PUNCT:
                j = i
                while j < n and source[j] in WEAK_PUNCT:
                    j += 1
                splitter.add(source[i:j])
                if splitter.weight >= max_chars:
                    splitter.cut()
                i = j
                continue

        # 8) 弹性延伸上限：走到这里说明当前是普通字符、无标点可切，强制落刀
        if not splitter.stack and splitter.weight >= hard_max:
            splitter.cut()

        # 9) 普通字符：维护成对符号栈
        if char in OPEN_CHARS:
            splitter.stack.append(char)
        elif splitter.stack and char == PAIR_MAP.get(splitter.stack[-1]):
            splitter.stack.pop()
        splitter.add(char)
        i += 1

    splitter.cut()
    segments = splitter.segments
    if not segments:
        return []

    segments = _merge_tiny_segments(segments)

    if (
        len(segments) >= 2
        and options.short_tail_chars > 0
        and len(segments[-1]) <= options.short_tail_chars
    ):
        tail = segments.pop()
        segments[-1] = segments[-1] + tail

    if options.max_segments > 0 and len(segments) > options.max_segments:
        merged = "".join(segments[options.max_segments - 1 :])
        segments = segments[: options.max_segments - 1] + [merged]

    return segments


def _merge_tiny_segments(segments: list[str], min_len: int = 2) -> list[str]:
    """合并极端短段（1 个字符），避免单独发一条。"""
    compacted: list[str] = []
    for segment in segments:
        if len(segment) < min_len and compacted:
            compacted[-1] = compacted[-1] + segment
        else:
            compacted.append(segment)
    if len(compacted) >= 2 and len(compacted[0]) < min_len:
        compacted[1] = compacted[0] + compacted[1]
        compacted.pop(0)
    return compacted


def segments_from_marked(parts: list[str], options: ReplyOptions) -> list[str]:
    """模型标记段：每段内部仍受保护区引擎约束，然后套用段数上限。"""
    segments: list[str] = []
    for part in parts:
        segments.extend(split_text(part, options))
    segments = [segment for segment in segments if segment.strip()]
    if options.max_segments > 0 and len(segments) > options.max_segments:
        merged = "".join(segments[options.max_segments - 1 :])
        segments = segments[: options.max_segments - 1] + [merged]
    return segments
