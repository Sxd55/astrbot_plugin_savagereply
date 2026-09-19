"""Savage's Reply 场景预设（Preset）系统与内存 Overlay 引擎。

设计哲学：
1. 内存遮罩（Overlay）：预设只在运行时接管关键交互/风控超参数，绝不覆写或擦除磁盘上的 config.json；
2. 随时无损切回：随时选择「custom（专家自定义）」，用户在磁盘配置的所有值 100% 恢复；
3. 开箱即用：
   - natural（日常拟人档，推荐默认）：拟人打字分段、标点停顿与打字状态、代码块保护，关闭主动接话（防炸群）；
   - lively（群聊气氛组档）：拟人分段 + 开启真人群聊智能接话（概率 5%）+ 开启 25 秒冷场打破；
   - instant（极速直答档）：单条极速秒回、不分段、无延时、关打字状态，适合客服与效率问答；
   - custom（专家自定义）：所有参数完全由用户配置决定。
"""

from __future__ import annotations

from typing import Any, Mapping

PRESET_DEFINITIONS: dict[str, dict[str, Any]] = {
    "natural": {
        "delay_enabled": True,
        "typing_enabled": True,
        "marker_enabled": True,
        "force_non_streaming": True,
        "active_reply_enabled": False,
    },
    "lively": {
        "delay_enabled": True,
        "typing_enabled": True,
        "marker_enabled": True,
        "force_non_streaming": True,
        "active_reply_enabled": True,
        "active_reply_mode": "smart",
        "active_reply_unanswered_break": True,
    },
    "instant": {
        "delay_enabled": False,
        "typing_enabled": False,
        "marker_enabled": False,
        "force_non_streaming": True,
        "active_reply_enabled": False,
        "min_total_chars": 999999,
    },
    "custom": {},
}

PRESET_NAMES: dict[str, str] = {
    "natural": "日常拟人（推荐平衡档）",
    "lively": "群聊气氛组（真人群聊智能接话）",
    "instant": "极速直答（单条秒回不分段）",
    "custom": "专家自定义（手动自由微调）",
}

PRESET_METADATA: list[dict[str, Any]] = [
    {
        "key": "enabled",
        "name": "总开关",
        "desc": "插件功能主开关",
        "type": "bool",
    },
    {
        "key": "delay_enabled",
        "name": "打字延时",
        "desc": "按字数与标点模拟人类打字停顿",
        "type": "bool",
    },
    {
        "key": "typing_enabled",
        "name": "打字状态",
        "desc": "发送前触发客户端「正在输入」",
        "type": "bool",
    },
    {
        "key": "marker_enabled",
        "name": "模型断句标记",
        "desc": "Prompt 注入 [[next]] 引导模型语义断句",
        "type": "bool",
    },
    {
        "key": "active_reply_enabled",
        "name": "真人群聊接话",
        "desc": "免@群聊智能接话与话轮判定",
        "type": "bool",
    },
    {
        "key": "active_reply_mode",
        "name": "接话模式",
        "desc": "接话判定策略（smart/judge/keyword/probability）",
        "type": "str",
    },
    {
        "key": "active_reply_probability",
        "name": "接话概率",
        "desc": "基础随机接话概率",
        "type": "float",
        "unit": "%",
    },
    {
        "key": "active_reply_cooldown",
        "name": "接话群冷却",
        "desc": "同群接话冷却间隔",
        "type": "int",
        "unit": "秒",
    },
    {
        "key": "active_reply_daily_limit",
        "name": "单群日限",
        "desc": "单个群聊每天主动接话上限",
        "type": "int",
        "unit": "次",
    },
    {
        "key": "active_reply_unanswered_break",
        "name": "冷场打破",
        "desc": "群友提问无人理睬时延迟救场",
        "type": "bool",
    },
    {
        "key": "max_segments",
        "name": "最大分段数",
        "desc": "单条回复切分的最大条数上限",
        "type": "int",
        "unit": "条",
    },
    {
        "key": "min_total_chars",
        "name": "起切字数",
        "desc": "文本超过该字数才触发分段",
        "type": "int",
        "unit": "字",
    },
]

SUPPORTED_PRESETS = tuple(PRESET_DEFINITIONS.keys())


def get_preset_defaults(preset_name: str) -> dict[str, Any]:
    """获取指定预设的默认参数集合。"""
    normalized = str(preset_name or "natural").strip().lower()
    return dict(PRESET_DEFINITIONS.get(normalized, PRESET_DEFINITIONS["natural"]))


def resolve_effective_config(config: Mapping[str, Any] | None, key: str, default: Any = None) -> Any:
    """解析运行期生效的配置值（内存 Overlay 机制）。"""
    cfg = config or {}
    raw_preset = cfg.get("config_preset")
    if not raw_preset:
        return cfg.get(key, default)
    preset_name = str(raw_preset).strip().lower()

    # 1. custom 模式：完全尊重用户配置
    if preset_name == "custom":
        return cfg.get(key, default)

    # 2. 预设模式：托管参数由预设接管
    preset_values = get_preset_defaults(preset_name)
    if key in preset_values:
        return preset_values[key]

    # 3. 未被当前预设托管的个性化配置项（如黑白名单、Bot 称呼等），直接回退用户配置
    return cfg.get(key, default)


def diff_preset(current_config: Mapping[str, Any] | None, target_preset: str) -> list[dict[str, Any]]:
    """比对当前生效配置与目标预设之间的参数差异。"""
    cfg = current_config or {}
    cur_preset_name = str(cfg.get("config_preset") or "natural").strip().lower()
    tgt_preset_name = str(target_preset or "natural").strip().lower()
    target_defaults = get_preset_defaults(tgt_preset_name)

    diffs: list[dict[str, Any]] = []

    for meta in PRESET_METADATA:
        key = meta["key"]
        cur_val = resolve_effective_config(cfg, key, meta.get("default"))

        if tgt_preset_name == "custom":
            tgt_val = cfg.get(key, meta.get("default", cur_val))
        else:
            tgt_val = target_defaults.get(key, cur_val)

        changed = (cur_val != tgt_val)

        direction = "same"
        symbol = "➖"
        if changed:
            if isinstance(cur_val, (int, float)) and isinstance(tgt_val, (int, float)):
                if tgt_val > cur_val:
                    direction = "up"
                    symbol = "🔼"
                else:
                    direction = "down"
                    symbol = "🔽"
            else:
                direction = "toggle"
                symbol = "🔄"

        diffs.append({
            "key": key,
            "name": meta["name"],
            "desc": meta["desc"],
            "type": meta["type"],
            "current_value": cur_val,
            "target_value": tgt_val,
            "current_display": _format_value(cur_val, meta),
            "target_display": _format_value(tgt_val, meta),
            "changed": changed,
            "direction": direction,
            "symbol": symbol,
        })

    return diffs


def _format_value(val: Any, meta: dict[str, Any]) -> str:
    if val is None:
        return "默认"
    if isinstance(val, bool):
        return "开启" if val else "关闭"
    unit = meta.get("unit", "")
    if unit == "%" and isinstance(val, (int, float)):
        return f"{int(val * 100)}%"
    return f"{val}{unit}"


def format_preset_diff_text(
    current_preset: str,
    target_preset: str,
    diffs: list[dict[str, Any]],
    is_applied: bool = False,
) -> str:
    """将参数差异格式化为群聊/私聊友好的文本报告。"""
    cur_name = PRESET_NAMES.get(current_preset, current_preset)
    tgt_name = PRESET_NAMES.get(target_preset, target_preset)

    lines = []
    if is_applied:
        lines.append(f"✅【预设切换成功】已生效为：{tgt_name}")
        lines.append(f"📊 从 [{cur_name}] 切换至 [{tgt_name}] 参数明细：")
    else:
        lines.append("📋【预设变更清单预览】")
        lines.append(f"当前：{cur_name}")
        lines.append(f"目标：{tgt_name}")

    lines.append("─────────────────────────────")

    changed_count = 0
    for idx, d in enumerate(diffs, 1):
        if d["changed"]:
            changed_count += 1
            lines.append(f"{idx:2d}. {d['name']} ({d['key']}): {d['current_display']} ➔ {d['target_display']} [{d['symbol']} 变动]")
        else:
            lines.append(f"{idx:2d}. {d['name']} ({d['key']}): {d['current_display']} [{d['symbol']} 保持一致]")

    lines.append("─────────────────────────────")

    if not is_applied:
        lines.append(f"💡 变动统计：共 {len(diffs)} 项核心算法参数，{changed_count} 项发生变更。")
        lines.append("🛡️ 安全机制：预设采用内存 Overlay 遮罩，绝不擦除或覆盖您手动修改过的配置。")
        lines.append(f"👉 确认应用此预设请执行：「/sreply preset apply {target_preset}」")
    else:
        lines.append("💡 提示：随时输入「/sreply preset custom」即可 100% 恢复所有手动自定义值。")

    return "\n".join(lines)
