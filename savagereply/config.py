"""配置归一化：把 AstrBotConfig 的原始 dict 收紧成 ReplyOptions。"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

DEFAULT_PLATFORM_EXCLUDE = [
    "qq_official",
    "qq_official_webhook",
    "weixin_official_account",
    "dingtalk",
]

DEFAULT_ABSOLUTE_WORDS = [
    "100%",
    "百分之百",
    "绝对能",
    "绝对会",
    "绝对不可能",
    "包治",
    "稳赚",
    "零风险",
    "保证成功",
    "保证有效",
]


def _as_bool(value: Any, default: bool) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        lowered = value.strip().lower()
        if lowered in {"1", "true", "yes", "on"}:
            return True
        if lowered in {"0", "false", "no", "off"}:
            return False
    if isinstance(value, (int, float)):
        return bool(value)
    return default


def _as_int(value: Any, default: int) -> int:
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return default


def _as_float(value: Any, default: float) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _as_str_list(value: Any, default: list[str]) -> list[str]:
    if isinstance(value, str):
        items: list[str] = []
        for line in value.replace("\r", "").split("\n"):
            items.extend(part.strip() for part in line.split(","))
        return [item for item in items if item]
    if isinstance(value, (list, tuple)):
        return [str(item).strip() for item in value if str(item).strip()]
    return list(default)


def _as_str(value: Any, default: str) -> str:
    if isinstance(value, str):
        return value
    if value is None:
        return default
    return str(value)


@dataclass
class ReplyOptions:
    enabled: bool = True
    only_llm: bool = True
    platform_exclude: list[str] = field(default_factory=lambda: list(DEFAULT_PLATFORM_EXCLUDE))
    session_blacklist: list[str] = field(default_factory=list)
    min_total_chars: int = 40
    max_total_chars: int = 600
    segment_min_chars: int = 15
    segment_max_chars: int = 50
    segment_hard_max_chars: int = 120
    max_segments: int = 6
    short_tail_chars: int = 8
    keep_punct: bool = True
    delay_enabled: bool = True
    delay_base_seconds: float = 0.4
    delay_per_char_seconds: float = 0.08
    delay_punct_bonus_seconds: float = 0.25
    delay_jitter: float = 0.2
    delay_max_seconds: float = 4.0
    delay_total_max_seconds: float = 10.0
    typing_enabled: bool = True
    marker_enabled: bool = True
    marker_prompt: str = ""
    protect_code_block: bool = True
    protect_table: bool = True
    protect_math: bool = True
    debug_log: bool = False
    verify_enabled: bool = False
    verify_log_only: bool = True
    verify_suffix_text: str = "（这条细节我不太确定，你用到时再核实一下）"
    verify_absolute_words: list[str] = field(default_factory=lambda: list(DEFAULT_ABSOLUTE_WORDS))

    @classmethod
    def from_config(cls, raw: Any) -> ReplyOptions:
        data = raw if isinstance(raw, dict) else {}
        options = cls(
            enabled=_as_bool(data.get("enabled"), True),
            only_llm=_as_bool(data.get("only_llm"), True),
            platform_exclude=_as_str_list(data.get("platform_exclude"), DEFAULT_PLATFORM_EXCLUDE),
            session_blacklist=_as_str_list(data.get("session_blacklist"), []),
            min_total_chars=_as_int(data.get("min_total_chars"), 40),
            max_total_chars=_as_int(data.get("max_total_chars"), 600),
            segment_min_chars=_as_int(data.get("segment_min_chars"), 15),
            segment_max_chars=_as_int(data.get("segment_max_chars"), 50),
            segment_hard_max_chars=_as_int(data.get("segment_hard_max_chars"), 120),
            max_segments=_as_int(data.get("max_segments"), 6),
            short_tail_chars=_as_int(data.get("short_tail_chars"), 8),
            keep_punct=_as_bool(data.get("keep_punct"), True),
            delay_enabled=_as_bool(data.get("delay_enabled"), True),
            delay_base_seconds=_as_float(data.get("delay_base_seconds"), 0.4),
            delay_per_char_seconds=_as_float(data.get("delay_per_char_seconds"), 0.08),
            delay_punct_bonus_seconds=_as_float(data.get("delay_punct_bonus_seconds"), 0.25),
            delay_jitter=_as_float(data.get("delay_jitter"), 0.2),
            delay_max_seconds=_as_float(data.get("delay_max_seconds"), 4.0),
            delay_total_max_seconds=_as_float(data.get("delay_total_max_seconds"), 10.0),
            typing_enabled=_as_bool(data.get("typing_enabled"), True),
            marker_enabled=_as_bool(data.get("marker_enabled"), True),
            marker_prompt=_as_str(data.get("marker_prompt"), ""),
            protect_code_block=_as_bool(data.get("protect_code_block"), True),
            protect_table=_as_bool(data.get("protect_table"), True),
            protect_math=_as_bool(data.get("protect_math"), True),
            debug_log=_as_bool(data.get("debug_log"), False),
            verify_enabled=_as_bool(data.get("verify_enabled"), False),
            verify_log_only=_as_bool(data.get("verify_log_only"), True),
            verify_suffix_text=_as_str(
                data.get("verify_suffix_text"),
                "（这条细节我不太确定，你用到时再核实一下）",
            ),
            verify_absolute_words=_as_str_list(
                data.get("verify_absolute_words"),
                DEFAULT_ABSOLUTE_WORDS,
            ),
        )
        return options.clamped()

    def clamped(self) -> ReplyOptions:
        self.segment_min_chars = max(2, self.segment_min_chars)
        self.segment_max_chars = max(self.segment_min_chars, self.segment_max_chars)
        self.segment_hard_max_chars = max(self.segment_max_chars, self.segment_hard_max_chars)
        self.max_segments = max(1, self.max_segments)
        self.short_tail_chars = max(0, self.short_tail_chars)
        self.min_total_chars = max(0, self.min_total_chars)
        self.max_total_chars = max(0, self.max_total_chars)
        self.delay_base_seconds = max(0.0, self.delay_base_seconds)
        self.delay_per_char_seconds = max(0.0, self.delay_per_char_seconds)
        self.delay_punct_bonus_seconds = max(0.0, self.delay_punct_bonus_seconds)
        self.delay_jitter = min(max(0.0, self.delay_jitter), 0.9)
        self.delay_max_seconds = max(0.0, self.delay_max_seconds)
        self.delay_total_max_seconds = max(0.0, self.delay_total_max_seconds)
        return self
