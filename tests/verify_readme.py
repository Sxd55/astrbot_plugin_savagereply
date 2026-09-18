"""Verify savagereply README/config/panel claims against code."""

import json
import pathlib
import re
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
README = (ROOT / "README.md").read_text(encoding="utf-8")
SCHEMA = json.loads((ROOT / "_conf_schema.json").read_text(encoding="utf-8"))
MAIN = (ROOT / "main.py").read_text(encoding="utf-8")
CONFIG = (ROOT / "savagereply" / "config.py").read_text(encoding="utf-8")

issues: list[str] = []


def check(name: str, ok: bool, detail: str = ""):
    print(("OK   " if ok else "FAIL ") + name + (f" -- {detail}" if detail and not ok else ""))
    if not ok:
        issues.append(name)


# 1. README config table keys vs schema + ReplyOptions defaults.
# README uses Chinese labels; map every schema key to its row label fragment.
LABEL = {
    "enabled": "总开关", "only_llm": "仅处理 LLM 回复", "platform_exclude": "跳过的平台",
    "session_blacklist": "会话黑名单", "min_total_chars": "最短分段字数",
    "max_total_chars": "最长分段字数", "segment_min_chars": "分段最短长度",
    "segment_max_chars": "分段最长长度", "segment_hard_max_chars": "分段硬上限",
    "max_segments": "最大分段数", "short_tail_chars": "短尾合并阈值",
    "paragraph_max_chars": "超长回复的段落目标长度",
    "keep_punct": "保留句尾标点", "delay_enabled": "打字延迟",
    "delay_base_seconds": "打字基础延迟", "delay_per_char_seconds": "每字打字时间",
    "delay_punct_bonus_seconds": "句末标点停顿", "delay_jitter": "延迟随机抖动",
    "delay_max_seconds": "单条延迟上限", "delay_total_max_seconds": "总延迟上限",
    "read_delay_min_seconds": "首条前读消息停顿下限",
    "read_delay_max_seconds": "首条前读消息停顿上限",
    "typing_enabled": "打字状态", "marker_enabled": "边界标记", "strip_markdown_marks": "去掉 ** 加粗标记",
    "marker_prompt": "边界标记规范文本", "protect_code_block": "保护代码块",
    "force_non_streaming": "本会话关闭流式输出",
    "protect_table": "保护代码块", "protect_math": "保护代码块",
    "debug_log": "调试日志", "verify_enabled": "风险扫描",
    "verify_log_only": "风险扫描仅记录", "verify_suffix_text": "不确定提示后缀",
    "verify_absolute_words": "可疑承诺词表",
    "active_reply_enabled": "免@主动接话总开关",
    "active_reply_mode": "接话模式",
    "active_reply_probability": "接话基础概率",
    "active_reply_keywords": "触发关键词",
    "active_reply_bot_names": "称呼白名单",
    "active_reply_cooldown": "群接话冷却时间",
    "active_reply_daily_limit": "单群每日接话上限",
    "active_reply_unanswered_break": "问句冷场打破",
    "active_reply_unanswered_seconds": "冷场等待秒数",
    "active_reply_quiet_hours": "夜间免打扰时段",
    "active_reply_groups": "生效群白名单",
}
table = README.split("## 五、配置项")[1].split("\n---\n")[0]
for key in sorted(SCHEMA):
    check(f"schema key {key} documented", LABEL.get(key, key) in table, "missing row")
m = re.search(r"(\d+) 个测试", README)
check("test count line present", bool(m))
check("test count line present", bool(m))
if m:
    import subprocess

    out = subprocess.run(
        [sys.executable, "tests/test_core.py"], capture_output=True, text=True, cwd=str(ROOT)
    ).stderr
    found = re.search(r"Ran (\d+) tests", out)
    check(
        "test count matches",
        found and int(found.group(1)) == int(m.group(1)),
        f"README={m.group(1)} actual={found.group(1) if found else '?'}",
    )

# 2. README quoted defaults vs schema defaults
pairs = [
    ("min_total_chars", "40"), ("max_total_chars", "600"),
    ("segment_min_chars", "15"), ("segment_max_chars", "50"),
    ("segment_hard_max_chars", "120"), ("max_segments", "6"),
    ("short_tail_chars", "8"), ("delay_base_seconds", "0.4"),
    ("delay_per_char_seconds", "0.08"), ("delay_punct_bonus_seconds", "0.25"),
    ("delay_jitter", "0.2"), ("delay_max_seconds", "4.0"),
    ("delay_total_max_seconds", "10.0"),
]
for key, expect in pairs:
    actual = str(SCHEMA[key]["default"])
    check(f"default {key}=={expect}", actual == expect, f"schema={actual}")
    check(f"README quotes {key} {expect}", expect in table)

# 3. page whitelist vs schema bool keys
m = re.search(r"BOOL_CONFIG_KEYS = \((.*?)\)", MAIN, re.S)
whitelist = re.findall(r'"(\w+)"', m.group(1))
for key in whitelist:
    check(f"whitelist {key} in schema", key in SCHEMA)
    check(f"whitelist {key} is bool default", isinstance(SCHEMA[key]["default"], bool))
check("whitelist count documented", f"{len(whitelist)} 个布尔开关" in README, f"{len(whitelist)}")

# 4. ReplyOptions fields vs schema keys (config.py must read every schema key it owns)
for key in SCHEMA:
    check(f"ReplyOptions reads {key}", f'data.get("{key}")' in CONFIG)

# 5. versions
ver_readme = re.search(r"当前版本 `v([^`]+)`", README).group(1)
ver_init = re.search(r'__version__ = "([^"]+)"', (ROOT / "savagereply" / "__init__.py").read_text(encoding="utf-8")).group(1)
ver_meta = re.search(r"version: v([^\s]+)", (ROOT / "metadata.yaml").read_text(encoding="utf-8")).group(1)
for where, ver in (("__init__", ver_init), ("metadata", ver_meta)):
    check(f"version {where}=={ver_readme}", ver == ver_readme, f"{ver} vs {ver_readme}")
soak = (ROOT / "SOAK.md").read_text(encoding="utf-8")
check("SOAK version", f"v{ver_readme}" in soak.splitlines()[0])

# 6. hooks exist in real flow
for hook in ("on_decorating_result", "on_llm_request"):
    check(f"hook {hook}", f"filter.{hook}(" in MAIN)

print()
if issues:
    print(f"{len(issues)} MISMATCHES")
    sys.exit(1)
print("ALL CHECKS PASSED")
