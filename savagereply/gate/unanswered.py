"""冷场打破与问句延时检测任务调度。"""

from __future__ import annotations

import asyncio
import time
from typing import Any, Callable, Coroutine

from .turn import TurnTracker


class UnansweredScheduler:
    """问句冷场打破调度器：同群仅维护最新一个 pending task。"""

    def __init__(self, turn_tracker: TurnTracker):
        self._turn_tracker = turn_tracker
        self._pending_tasks: dict[str, asyncio.Task] = {}

    def schedule(
        self,
        group_id: str,
        delay_seconds: float,
        asker_id: str,
        callback: Callable[[], Coroutine[Any, Any, None]],
    ) -> None:
        if not group_id or delay_seconds <= 0:
            return

        # 同群若已有 pending 任务，取消并替换为最新问题
        self.cancel(group_id)

        since_ts = time.time()

        async def _runner():
            try:
                await asyncio.sleep(delay_seconds)
                # 检查此期间是否已有其他人发言
                if not self._turn_tracker.has_subsequent_activity(
                    group_id, since_ts=since_ts, asker_id=asker_id
                ):
                    # 依然冷场，执行打破冷场回调
                    await callback()
            except asyncio.CancelledError:
                pass
            finally:
                self._pending_tasks.pop(group_id, None)

        task = asyncio.create_task(_runner())
        self._pending_tasks[group_id] = task

    def cancel(self, group_id: str) -> None:
        task = self._pending_tasks.pop(group_id, None)
        if task and not task.done():
            task.cancel()

    def clear(self) -> None:
        for task in self._pending_tasks.values():
            if not task.done():
                task.cancel()
        self._pending_tasks.clear()
