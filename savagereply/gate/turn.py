"""群聊话轮与上下文追踪：轻量内存环形队列，智能防止抢话插嘴。"""

from __future__ import annotations

import time
from collections import deque
from dataclasses import dataclass
from typing import Any, Iterable


@dataclass
class ChatTurn:
    sender_id: str
    text: str
    timestamp: float
    target_ids: set[str]  # 艾特或引用的目标 ID
    is_at_bot: bool


class TurnTracker:
    """基于内存 deque 的群聊话轮追踪器，无数据库依赖。"""

    def __init__(self, max_history: int = 30):
        self._max_history = max(10, max_history)
        self._history: dict[str, deque[ChatTurn]] = {}

    def record_turn(
        self,
        group_id: str,
        sender_id: str,
        text: str,
        target_ids: Iterable[str] = (),
        is_at_bot: bool = False,
    ) -> None:
        if not group_id:
            return
        if group_id not in self._history:
            self._history[group_id] = deque(maxlen=self._max_history)
        self._history[group_id].append(
            ChatTurn(
                sender_id=str(sender_id or ""),
                text=str(text or ""),
                timestamp=time.time(),
                target_ids={str(t) for t in target_ids if t},
                is_at_bot=bool(is_at_bot),
            )
        )

    def is_turn_open(
        self,
        group_id: str,
        sender_id: str,
        target_ids: Iterable[str],
        bot_id: str,
    ) -> tuple[bool, str]:
        """判断当前发言是否属于开放话轮（是否可以插话）。

        规则：
        1. 如果发言显式艾特/引用了他人（且不是 Bot、不是全体成员），说明是定向私聊对线，不插嘴。
        2. 如果发言显式艾特了 Bot，开放。
        3. 如果群内最近 12 秒内有另外两个人在高频互回对线，且本条没有艾特，降低插嘴倾向。
        """
        targets = {str(t) for t in target_ids if t}
        own_id = str(bot_id or "")

        # 规则 1：检查是否艾特了除 Bot 和全体成员之外的人
        other_targets = [t for t in targets if t not in {own_id, "all", ""}]
        if other_targets:
            return False, f"addressed_to_other:{other_targets[0]}"

        # 规则 2：检查群内近期对话对线氛围
        recent = self.get_recent(group_id, limit=4)
        now = time.time()
        active_recent = [t for t in recent if now - t.timestamp < 12.0]
        if len(active_recent) >= 2:
            senders = {t.sender_id for t in active_recent}
            # 如果最近高频对话仅在两个人之间来回且不包含当前发言者或不包含 Bot
            if len(senders) == 2 and own_id not in senders and str(sender_id) not in senders:
                return False, "private_dialogue_active"

        return True, "open"

    def has_subsequent_activity(
        self, group_id: str, since_ts: float, asker_id: str
    ) -> bool:
        """检查自 since_ts 之后，群内是否有其他人发言（用于冷场打破判定）。"""
        recent = self.get_recent(group_id, limit=10)
        for turn in reversed(recent):
            if turn.timestamp <= since_ts:
                break
            # 有其他人发言了
            if turn.sender_id and str(turn.sender_id) != str(asker_id):
                return True
        return False

    def get_recent(self, group_id: str, limit: int = 5) -> list[ChatTurn]:
        if group_id not in self._history:
            return []
        q = self._history[group_id]
        return list(q)[-limit:]

    def clear(self) -> None:
        self._history.clear()
