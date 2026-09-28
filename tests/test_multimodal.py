"""多模态视觉增强特性单元测试。"""

import asyncio
import unittest
from types import SimpleNamespace

from savagereply.multimodal import (
    QUOTED_IMAGE_NOTICE,
    QUOTE_IMAGE_CAPTION_BASE_PROMPT,
    build_enhanced_caption_prompt,
    optimize_quoted_image_input,
)
from savagereply.presets import (
    PRESET_DEFINITIONS,
    PRESET_METADATA,
    diff_preset,
    get_preset_defaults,
    resolve_effective_config,
)


class TestMultimodalEnhancement(unittest.TestCase):
    def test_caption_prompt_building(self):
        # 基础无上下文
        p1 = build_enhanced_caption_prompt("请描述图片")
        self.assertEqual(p1, "请描述图片")

        # 带有用户问题
        p2 = build_enhanced_caption_prompt("请描述图片", user_prompt="这个化验单里的白细胞是多少？")
        self.assertIn("<image_caption_context>", p2)
        self.assertIn("用户当前问题：这个化验单里的白细胞是多少？", p2)

        # 带有用户问题与引用文本
        p3 = build_enhanced_caption_prompt(
            "请描述图片",
            user_prompt="这是什么病？",
            quoted_text="医生昨天的诊断记录",
        )
        self.assertIn("用户当前问题：这是什么病？", p3)
        self.assertIn("被引用消息文本：医生昨天的诊断记录", p3)

    def test_quoted_image_input_optimization(self):
        async def run_test():
            # 模拟含 Reply 且附带图片的事件
            reply_comp = SimpleNamespace(type="Reply", id="1001", images=["http://example.com/test.jpg"])
            event = SimpleNamespace(
                message_obj=SimpleNamespace(message=[reply_comp]),
            )
            req = SimpleNamespace(prompt="请帮我看看这张图", image_urls=[])

            optimized = await optimize_quoted_image_input(event, req)
            self.assertTrue(optimized)
            self.assertEqual(req.image_urls, ["http://example.com/test.jpg"])
            self.assertIn("当前消息引用了 1 张图片，已作为本轮视觉输入提供。", req.prompt)

        asyncio.run(run_test())

    def test_presets_multimodal_keys(self):
        # 确保全部预设都正确声明了多模态视觉新配置
        keys = [item["key"] for item in PRESET_METADATA]
        self.assertIn("enhance_quoted_image_input", keys)
        self.assertIn("optimize_image_caption", keys)

        for name in ("natural", "lively", "visual", "humanoid", "instant"):
            defs = get_preset_defaults(name)
            self.assertTrue(defs.get("enhance_quoted_image_input"))
            self.assertTrue(defs.get("optimize_image_caption"))

        cfg = {"config_preset": "natural"}
        self.assertTrue(resolve_effective_config(cfg, "enhance_quoted_image_input", False))
        self.assertTrue(resolve_effective_config(cfg, "optimize_image_caption", False))


if __name__ == "__main__":
    unittest.main()
