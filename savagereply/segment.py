"""纯函数分段引擎：保护区扫描 + 区间断点 + 短尾合并 + 段数上限。

P0 增补：
- 硬落刀前把英文/数字 token 挪到下一段，绝不切在 token 内部；
- 断点后紧跟「和/以及/因为/所以…」或强指代（它/其/该/此）时不切，避免句子被切断；
- 超长回复改按段落切，不再整篇放行；
- 问句不被并走，单独成条。
"""

from __future__ import annotations

import re

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

# 词内字符：硬落刀不能切在它们中间（12|34、hel|lo、3.1|4）。
WORDISH = set(
    "0123456789"
    "abcdefghijklmnopqrstuvwxyz"
    "ABCDEFGHIJKLMNOPQRSTUVWXYZ"
    ".,:%+-_/#@$&"
)
_CJK_RE = re.compile(r"[\u3400-\u4dbf\u4e00-\u9fff\uf900-\ufaff]")

# 断点后紧跟这些词 = 上一句的续接/并列，另起一条会读断。
CONTINUATION_RE = re.compile(
    r"^\s*(?:和|以及|或者|或|还有|跟|与|及|因为|所以|但是|不过|而且|并且|然后|但|而|却|甚至|比如|例如)"
)
# 断点后紧跟强指代 = 上一句的延续，另起一条会指代落空。
ANAPHORA_RE = re.compile(r"^\s*(?:它|它们|其|该|此|前者|后者|上述|这种|这点)")

QUESTION_TAIL_RE = re.compile(r"[?？]\s*$")
QUESTION_TAG_RE = re.compile(
    r"(?:吗|呢|吧|么|好不好|行不行|要不要|可以吗|对吗|是吧|怎么样|如何)[?？]?\s*$"
)


def is_question(segment: str) -> bool:
    """判断一段文本是不是「问句」（送节尾标点后仍能识别语气词）。"""
    text = (segment or "").strip()
    if not text:
        return False
    if QUESTION_TAIL_RE.search(text):
        return True
    core = text.rstrip("。！!…~～ \t\"'”’")
    return bool(QUESTION_TAG_RE.search(core))


def _weight_of(text: str) -> int:
    return sum(1 for char in text if not char.isspace())


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
        self._weight += _weight_of(chunk)

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


# 硬落刀允许为了保住一个 token 最多溢出多少字符（超过就认了，避免长串失控）。
TOKEN_OVERFLOW_LIMIT = 32


def _inside_token(source: str, index: int) -> bool:
    """硬落刀位置是否落在英文/数字 token 内部（12|34、hel|lo、3|个）。"""
    if index <= 0 or index >= len(source):
        return False
    prev_char = source[index - 1]
    next_char = source[index]
    if prev_char not in WORDISH:
        return False
    return next_char in WORDISH or bool(_CJK_RE.match(next_char))


def _starts_with_binder(source: str, index: int) -> bool:
    rest = source[index:]
    if not rest.strip():
        return False
    return bool(CONTINUATION_RE.match(rest) or ANAPHORA_RE.match(rest))


def split_text(text: str, options: ReplyOptions) -> list[str]:
    """把一段文本切成若干短句。保护区内绝不切断；超长走段落切。"""
    source = (text or "").replace("\r\n", "\n").replace("\r", "\n").strip()
    if not source:
        return []
    if options.max_total_chars > 0 and len(source) > options.max_total_chars:
        return _split_paragraphs(source, options)
    return _split_sentences(source, options)


def _split_sentences(source: str, options: ReplyOptions) -> list[str]:
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

        # 7) 断点（成对符号内部不切；后接续接词/指代也不切）
        if not splitter.stack:
            if char == "\n":
                j = i
                while j < n and source[j] in " \t\n":
                    j += 1
                splitter.add(source[i:j])
                if (
                    ("\n\n" in source[i:j] and splitter.weight >= 2) or splitter.weight >= min_chars
                ) and not _starts_with_binder(source, j):
                    splitter.cut()
                i = j
                continue
            if char in STRONG_PUNCT:
                j = i
                while j < n and source[j] in STRONG_PUNCT:
                    j += 1
                splitter.add(source[i:j])
                if splitter.weight >= min_chars and not _starts_with_binder(source, j):
                    splitter.cut()
                i = j
                continue
            if char in WEAK_PUNCT:
                j = i
                while j < n and source[j] in WEAK_PUNCT:
                    j += 1
                splitter.add(source[i:j])
                if splitter.weight >= max_chars and not _starts_with_binder(source, j):
                    splitter.cut()
                i = j
                continue

        # 8) 弹性延伸上限：走到这里说明当前是普通字符、无标点可切，强制落刀
        #    （落刀点若在英文/数字 token 内部，先让一段，别把单词/数字切成两半）
        if not splitter.stack and splitter.weight >= hard_max:
            if splitter.weight >= hard_max + TOKEN_OVERFLOW_LIMIT or not _inside_token(source, i):
                splitter.cut()

        # 9) 普通字符：维护成对符号栈
        if char in OPEN_CHARS:
            splitter.stack.append(char)
        elif splitter.stack and char == PAIR_MAP.get(splitter.stack[-1]):
            splitter.stack.pop()
        splitter.add(char)
        i += 1

    splitter.cut()
    return _finalize_segments(splitter.segments, options)


def _split_paragraphs(source: str, options: ReplyOptions) -> list[str]:
    """超长回复：按空行分段后合并到目标长度，避免整篇放行或切碎。"""
    paragraphs = [part.strip() for part in re.split(r"\n\s*\n+", source) if part.strip()]
    if not paragraphs:
        paragraphs = [source.strip()]
    target = max(40, int(options.paragraph_max_chars or 0))
    chunks: list[str] = []
    for para in paragraphs:
        if len(para) > target:
            chunks.extend(_split_sentences(para, options))
            continue
        if (
            chunks
            and len(chunks[-1]) + len(para) + 1 <= target
            and not is_question(chunks[-1])
            and not _starts_with_binder(para, 0)
        ):
            chunks[-1] = f"{chunks[-1]}\n{para}"
        else:
            chunks.append(para)
    return _finalize_segments(chunks, options)


def _finalize_segments(segments: list[str], options: ReplyOptions) -> list[str]:
    if not segments:
        return []

    segments = _merge_tiny_segments(segments)

    if (
        len(segments) >= 2
        and options.short_tail_chars > 0
        and len(segments[-1]) <= options.short_tail_chars
        and not is_question(segments[-1])
    ):
        tail = segments.pop()
        segments[-1] = segments[-1] + tail

    if options.max_segments > 0 and len(segments) > options.max_segments:
        merged = "\n".join(segments[options.max_segments - 1 :])
        segments = segments[: options.max_segments - 1] + [merged]

    return segments


def _merge_tiny_segments(segments: list[str], min_len: int = 2) -> list[str]:
    """合并极端短段（1 个字符），避免单独发一条；问句保留独立。"""
    compacted: list[str] = []
    for segment in segments:
        if len(segment) < min_len and compacted and not is_question(segment):
            compacted[-1] = compacted[-1] + segment
        else:
            compacted.append(segment)
    if len(compacted) >= 2 and len(compacted[0]) < min_len and not is_question(compacted[0]):
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
        merged = "\n".join(segments[options.max_segments - 1 :])
        segments = segments[: options.max_segments - 1] + [merged]
    return segments
