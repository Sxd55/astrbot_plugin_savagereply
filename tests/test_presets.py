"""Unit tests for Savage's Reply preset overlay system."""

from __future__ import annotations

import pathlib
import sys
import unittest

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from savagereply.config import ReplyOptions
from savagereply.presets import (
    PRESET_DEFINITIONS,
    PRESET_NAMES,
    SUPPORTED_PRESETS,
    diff_preset,
    format_preset_diff_text,
    get_preset_defaults,
    resolve_effective_config,
)


class PresetsTest(unittest.TestCase):
    def test_supported_presets(self):
        self.assertIn("natural", SUPPORTED_PRESETS)
        self.assertIn("lively", SUPPORTED_PRESETS)
        self.assertIn("instant", SUPPORTED_PRESETS)
        self.assertIn("custom", SUPPORTED_PRESETS)
        self.assertEqual(len(SUPPORTED_PRESETS), 4)

    def test_get_preset_defaults(self):
        natural = get_preset_defaults("natural")
        self.assertTrue(natural["delay_enabled"])
        self.assertFalse(natural["active_reply_enabled"])

        lively = get_preset_defaults("lively")
        self.assertTrue(lively["delay_enabled"])
        self.assertTrue(lively["active_reply_enabled"])
        self.assertEqual(lively["active_reply_mode"], "smart")
        self.assertTrue(lively["active_reply_unanswered_break"])

        instant = get_preset_defaults("instant")
        self.assertFalse(instant["delay_enabled"])
        self.assertFalse(instant["typing_enabled"])
        self.assertFalse(instant["marker_enabled"])
        self.assertEqual(instant["min_total_chars"], 999999)

        custom = get_preset_defaults("custom")
        self.assertEqual(custom, {})

        fallback = get_preset_defaults("non_existent_preset")
        self.assertEqual(fallback, natural)

    def test_resolve_effective_config(self):
        # 1. 未指定 config_preset 时保持用户原样
        cfg_plain = {"delay_enabled": True, "max_segments": 10}
        self.assertEqual(resolve_effective_config(cfg_plain, "max_segments"), 10)
        self.assertTrue(resolve_effective_config(cfg_plain, "delay_enabled"))

        # 2. custom 档位完全尊重用户输入
        cfg_custom = {"config_preset": "custom", "delay_enabled": False, "max_segments": 8}
        self.assertFalse(resolve_effective_config(cfg_custom, "delay_enabled"))
        self.assertEqual(resolve_effective_config(cfg_custom, "max_segments"), 8)

        # 3. instant 档位接管延迟与分段参数，但保留非托管用户参数
        cfg_instant = {"config_preset": "instant", "max_segments": 5}
        self.assertFalse(resolve_effective_config(cfg_instant, "delay_enabled"))
        self.assertFalse(resolve_effective_config(cfg_instant, "typing_enabled"))
        self.assertEqual(resolve_effective_config(cfg_instant, "min_total_chars"), 999999)
        self.assertEqual(resolve_effective_config(cfg_instant, "max_segments"), 5)

        # 4. lively 档位开启主动接话
        cfg_lively = {"config_preset": "lively"}
        self.assertTrue(resolve_effective_config(cfg_lively, "active_reply_enabled"))
        self.assertEqual(resolve_effective_config(cfg_lively, "active_reply_mode"), "smart")

    def test_diff_preset(self):
        current_cfg = {
            "config_preset": "natural",
            "active_reply_enabled": False,
        }
        diffs = diff_preset(current_cfg, "lively")
        changed_keys = [d["key"] for d in diffs if d["changed"]]
        self.assertIn("active_reply_enabled", changed_keys)

        # 同档位对比无变更
        same_diffs = diff_preset(current_cfg, "natural")
        changed_same = [d["key"] for d in same_diffs if d["changed"]]
        self.assertEqual(len(changed_same), 0)

    def test_format_preset_diff_text(self):
        current_cfg = {"config_preset": "natural"}
        diffs = diff_preset(current_cfg, "instant")
        text_preview = format_preset_diff_text("natural", "instant", diffs, is_applied=False)
        self.assertIn("极速直答", text_preview)
        self.assertIn("打字延时", text_preview)
        self.assertIn("确认应用此预设请执行", text_preview)

        text_applied = format_preset_diff_text("natural", "instant", diffs, is_applied=True)
        self.assertIn("预设切换成功", text_applied)

    def test_reply_options_integration(self):
        # 默认使用 natural
        opts_default = ReplyOptions.from_config({})
        self.assertTrue(opts_default.delay_enabled)
        self.assertFalse(opts_default.active_reply_enabled)

        # 选 instant 一键秒回且不分段
        opts_instant = ReplyOptions.from_config({"config_preset": "instant"})
        self.assertFalse(opts_instant.delay_enabled)
        self.assertFalse(opts_instant.typing_enabled)
        self.assertFalse(opts_instant.marker_enabled)
        self.assertEqual(opts_instant.min_total_chars, 999999)

        # 选 lively 开启气氛组
        opts_lively = ReplyOptions.from_config({"config_preset": "lively"})
        self.assertTrue(opts_lively.active_reply_enabled)
        self.assertEqual(opts_lively.active_reply_mode, "smart")
        self.assertTrue(opts_lively.active_reply_unanswered_break)

        # 选 custom 完全受控
        opts_custom = ReplyOptions.from_config({
            "config_preset": "custom",
            "active_reply_enabled": True,
            "delay_enabled": False,
        })
        self.assertTrue(opts_custom.active_reply_enabled)
        self.assertFalse(opts_custom.delay_enabled)


if __name__ == "__main__":
    unittest.main()
