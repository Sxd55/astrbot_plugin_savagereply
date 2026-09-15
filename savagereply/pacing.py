"""纯函数打字延迟模型。"""

from __future__ import annotations

import random

from .config import ReplyOptions

STRONG_TAIL = set("。？！?!…~～")


def read_delay(options: ReplyOptions, rng: random.Random | None = None) -> float:
    """发送第一条之前的「读消息 + 组织语言」停顿（不含打字时间）。

    真人不会秒回；研究（CHI 2026 / IJHCI 2025）显示极短延迟反而被评价为"不用心"，
    0.5–1.5 秒是聊天场景的舒适区。总预算由调用方统一管理。
    """
    if not options.delay_enabled:
        return 0.0
    low = max(0.0, options.read_delay_min_seconds)
    high = max(low, options.read_delay_max_seconds)
    if high <= 0:
        return 0.0
    rng = rng or random
    return rng.uniform(low, high)


def segment_delay(text: str, options: ReplyOptions, rng: random.Random | None = None) -> float:
    """计算发送下一段之前应等待的秒数（按下一段文本长度模拟打字）。

    返回值已应用单条上限与随机抖动；总上限由调用方管理。
    """
    if not options.delay_enabled:
        return 0.0
    body = (text or "").strip()
    if not body:
        return 0.0
    rng = rng or random
    delay = options.delay_base_seconds + len(body) * options.delay_per_char_seconds
    if body[-1] in STRONG_TAIL:
        delay += options.delay_punct_bonus_seconds
    if options.delay_jitter > 0:
        delay *= 1.0 + rng.uniform(-options.delay_jitter, options.delay_jitter)
    if options.delay_max_seconds > 0:
        delay = min(delay, options.delay_max_seconds)
    return max(0.0, delay)
