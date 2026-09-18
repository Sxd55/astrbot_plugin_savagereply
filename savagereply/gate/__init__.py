"""群聊活跃接话子系统：何时回复（When）中枢。"""

from __future__ import annotations

import random
import time
from typing import Any, Callable, Coroutine, Iterable

from .active import (
    ActiveReplyRateLimiter,
    in_targets,
    is_quiet_time,
    is_question,
    is_usable_text,
    match_keywords,
    match_names,
    parse_targets,
)
from .turn import TurnTracker
from .unanswered import UnansweredScheduler


class ActiveGate:
    """群聊活跃接话总门禁。"""

    def __init__(self):
        self.turn_tracker = TurnTracker()
        self.rate_limiter = ActiveReplyRateLimiter()
        self.unanswered_scheduler = UnansweredScheduler(self.turn_tracker)

    def record_turn(
        self,
        group_id: str,
        sender_id: str,
        text: str,
        target_ids: Iterable[str] = (),
        is_at_bot: bool = False,
    ) -> None:
        self.turn_tracker.record_turn(
            group_id=group_id,
            sender_id=sender_id,
            text=text,
            target_ids=target_ids,
            is_at_bot=is_at_bot,
        )

    def evaluate(
        self,
        *,
        enabled: bool,
        is_group: bool,
        group_id: str,
        sender_id: str,
        text: str,
        target_ids: Iterable[str],
        bot_id: str,
        bot_names: Iterable[str],
        mode: str,
        probability: float,
        keywords: Iterable[str],
        groups_whitelist: Iterable[str],
        quiet_hours: str,
        cooldown: float,
        daily_limit: int,
        already_handled: bool = False,
        is_self: bool = False,
        now_ts: float | None = None,
    ) -> tuple[bool, str]:
        """主动接话综合判定。返回 (是否接话, 判定原因)。"""
        if not enabled:
            return False, "disabled"
        if not is_group or not group_id:
            return False, "not_group"
        if is_self:
            return False, "bot_self"
        if already_handled:
            return False, "already_handled"

        # 1. 夜间免打扰时段
        if is_quiet_time(quiet_hours):
            return False, "quiet_hours"

        # 2. 群白名单
        if not in_targets(group_id, set(groups_whitelist)):
            return False, "group_not_allowed"

        # 3. 文本有效性
        usable, usable_reason = is_usable_text(text, min_chars=2)
        if not usable:
            return False, usable_reason

        # 4. 频控：冷却时间与每日上限
        freq_ok, freq_reason = self.rate_limiter.check(
            group_id=group_id,
            cooldown=cooldown,
            daily_limit=daily_limit,
            now_ts=now_ts,
        )
        if not freq_ok:
            return False, freq_reason

        # 5. 称呼匹配（叫到了名字，越过话轮判定直接放行）
        name_ok, name_reason = match_names(text, bot_names)
        if name_ok:
            return True, name_reason

        # 6. 话轮与防插嘴判定
        turn_open, turn_reason = self.turn_tracker.is_turn_open(
            group_id=group_id,
            sender_id=sender_id,
            target_ids=target_ids,
            bot_id=bot_id,
        )
        if not turn_open:
            return False, turn_reason

        # 7. 模式判定
        normalized_mode = (mode or "smart").strip().lower()
        if normalized_mode == "keywords":
            kw_ok, kw_reason = match_keywords(text, keywords)
            if kw_ok:
                return True, kw_reason
            return False, "keywords_miss"

        if normalized_mode == "probability":
            prob = max(0.0, min(1.0, float(probability or 0.05)))
            if random.random() < prob:
                return True, "probability_hit"
            return False, "probability_miss"

        # smart 模式（默认）：问句感知 + 适度概率 + 关键词
        # 关键词有配置则优先尝试
        kw_ok, kw_reason = match_keywords(text, keywords)
        if kw_ok:
            return True, kw_reason

        base_prob = max(0.01, min(1.0, float(probability or 0.05)))
        # 如果是问句，适度增加接话概率（3倍加权，上限 0.35）
        if is_question(text):
            prob = min(0.35, base_prob * 3.0)
            if random.random() < prob:
                return True, "smart_question_hit"
            return False, "smart_question_miss"

        # 普通陈述发言，按基础概率
        if random.random() < base_prob:
            return True, "smart_prob_hit"

        return False, "smart_miss"

    def mark_fired(self, group_id: str, now_ts: float | None = None) -> None:
        """标记接话成功，重置冷却并增加计数。"""
        self.rate_limiter.record_fired(group_id, now_ts)
        # 既然接话了，同群 pending 的冷场打破任务取消
        self.unanswered_scheduler.cancel(group_id)

    def schedule_unanswered(
        self,
        group_id: str,
        delay_seconds: float,
        asker_id: str,
        callback: Callable[[], Coroutine[Any, Any, None]],
    ) -> None:
        self.unanswered_scheduler.schedule(
            group_id=group_id,
            delay_seconds=delay_seconds,
            asker_id=asker_id,
            callback=callback,
        )

    def is_question_candidate(self, text: str) -> bool:
        return is_question(text)
