"""输入状态（"对方正在输入"）。

仅 aiocqhttp（NapCat）私聊有效：OneBot 扩展 API `set_input_status`。
群聊没有输入状态的展示位；其他平台没有该扩展。全部失败静默。
"""

from __future__ import annotations

from typing import Any

TYPING_EVENT_TYPE = 1
STOP_EVENT_TYPE = 0


def should_show_typing(platform_name: str, is_group: bool) -> bool:
    """只有 aiocqhttp 私聊才有"对方正在输入"的展示位。"""
    return platform_name == "aiocqhttp" and not is_group


async def set_input_status(bot: Any, user_id: str, event_type: int) -> bool:
    """调用 OneBot set_input_status，失败静默返回 False。"""
    if bot is None or not user_id:
        return False
    call = getattr(bot, "call_action", None)
    if not callable(call):
        return False
    try:
        target = int(str(user_id))
    except (TypeError, ValueError):
        return False
    try:
        await call("set_input_status", user_id=target, event_type=event_type)
        return True
    except Exception:  # noqa: BLE001
        return False
