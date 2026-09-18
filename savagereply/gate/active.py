"""活跃接话判定引擎：负责冷却、频次风控、称呼与意图分析。"""

from __future__ import annotations

import datetime
import random
import time
from typing import Any, Iterable

COMMAND_PREFIXES = ("/", "／", "!", "！", "#", "$")
QUESTION_MARKERS = (
    "？",
    "?",
    "吗",
    "怎么",
    "为什么",
    "为啥",
    "能不能",
    "可不可以",
    "是否",
    "啥",
    "多少",
    "几点",
    "谁",
    "哪里",
    "哪儿",
    "如何",
)


def parse_targets(raw: Any) -> set[str]:
    """解析白名单群列表：支持逗号/换行分隔。"""
    if isinstance(raw, (list, tuple, set)):
        items: Iterable[Any] = raw
    else:
        items = str(raw or "").replace("\n", ",").split(",")
    return {str(item).strip() for item in items if str(item).strip()}


def in_targets(group_id: str, targets: set[str]) -> bool:
    """空白名单 = 全群生效；否则群号在 targets 中或互为子串即算命中。"""
    if not targets:
        return True
    tag = str(group_id or "").strip()
    if not tag:
        return False
    if tag in targets:
        return True
    return any(t and (t in tag or tag in t) for t in targets)


def is_usable_text(text: str, min_chars: int = 2) -> tuple[bool, str]:
    """基本文本有效性检查。"""
    s = (text or "").strip()
    if len(s) < max(1, min_chars):
        return False, "too_short"
    if s.startswith(COMMAND_PREFIXES):
        return False, "command"
    if not any(ch.isalnum() or "\u4e00" <= ch <= "\u9fff" for ch in s):
        return False, "no_content"
    return True, ""


def is_question(text: str) -> bool:
    """判断是否为问句。"""
    s = (text or "").strip()
    if not s:
        return False
    if s.endswith(("？", "?")):
        return True
    return any(marker in s for marker in QUESTION_MARKERS)


def parse_quiet_ranges(raw: str) -> list[tuple[int, int]]:
    """解析免打扰时段，例如 "23:00-07:00;12:00-13:00" -> 分钟元组列表。"""
    ranges: list[tuple[int, int]] = []
    for chunk in str(raw or "").replace("\n", ";").replace(",", ";").split(";"):
        piece = chunk.strip()
        if not piece or "-" not in piece:
            continue
        start_str, _, end_str = piece.partition("-")
        s = _to_minutes(start_str)
        e = _to_minutes(end_str)
        if s is not None and e is not None and s != e:
            ranges.append((s, e))
    return ranges


def _to_minutes(val: str) -> int | None:
    text = str(val or "").strip().replace("：", ":")
    if not text:
        return None
    if ":" in text:
        h, _, m = text.partition(":")
        try:
            hour, minute = int(h), int(m or 0)
        except (TypeError, ValueError):
            return None
    else:
        try:
            hour, minute = int(text), 0
        except (TypeError, ValueError):
            return None
    if not (0 <= hour <= 24 and 0 <= minute <= 59):
        return None
    return hour * 60 + minute


def is_quiet_time(quiet_ranges_str: str, now_dt: datetime.datetime | None = None) -> bool:
    """判断当前时间是否处于免打扰区间。"""
    ranges = parse_quiet_ranges(quiet_ranges_str)
    if not ranges:
        return False
    now = now_dt or datetime.datetime.now()
    cur_minutes = now.hour * 60 + now.minute
    for s, e in ranges:
        if s < e:
            if s <= cur_minutes < e:
                return True
        else:  # 跨零点情况，例如 23:00 - 07:00
            if cur_minutes >= s or cur_minutes < e:
                return True
    return False


def match_names(text: str, names: Iterable[str]) -> tuple[bool, str]:
    """称呼白名单匹配：发言中叫到了 Bot 昵称。"""
    s = (text or "").casefold()
    for n in names:
        target = str(n or "").strip()
        if len(target) >= 2 and target.casefold() in s:
            return True, f"name:{target}"
    return False, "name_miss"


def match_keywords(text: str, keywords: Iterable[str]) -> tuple[bool, str]:
    """触发关键词匹配。"""
    s = text or ""
    for kw in keywords:
        k = str(kw or "").strip()
        if k and k in s:
            return True, f"keyword:{k}"
    return False, "keyword_miss"


class ActiveReplyRateLimiter:
    """轻量群主动接话频控记录器（冷却时间 + 每日上限）。"""

    def __init__(self):
        self._last_reply_ts: dict[str, float] = {}
        # group_id -> (date_str, count)
        self._daily_counts: dict[str, tuple[str, int]] = {}

    def check(
        self,
        group_id: str,
        cooldown: float,
        daily_limit: int,
        now_ts: float | None = None,
    ) -> tuple[bool, str]:
        if not group_id:
            return True, "ok"
        now = now_ts or time.time()

        # 冷却时间校验
        if cooldown > 0:
            last = self._last_reply_ts.get(group_id, 0.0)
            if (now - last) < cooldown:
                return False, f"cooldown:{int(cooldown - (now - last))}s_left"

        # 每日上限校验
        if daily_limit > 0:
            today_str = datetime.date.today().isoformat()
            rec_date, count = self._daily_counts.get(group_id, (today_str, 0))
            if rec_date == today_str and count >= daily_limit:
                return False, f"daily_limit_reached:{count}/{daily_limit}"

        return True, "ok"

    def record_fired(self, group_id: str, now_ts: float | None = None) -> None:
        if not group_id:
            return
        now = now_ts or time.time()
        self._last_reply_ts[group_id] = now
        today_str = datetime.date.today().isoformat()
        rec_date, count = self._daily_counts.get(group_id, (today_str, 0))
        if rec_date == today_str:
            self._daily_counts[group_id] = (today_str, count + 1)
        else:
            self._daily_counts[group_id] = (today_str, 1)

    def get_today_count(self, group_id: str) -> int:
        today_str = datetime.date.today().isoformat()
        rec_date, count = self._daily_counts.get(group_id, (today_str, 0))
        return count if rec_date == today_str else 0

    def clear(self) -> None:
        self._last_reply_ts.clear()
        self._daily_counts.clear()
