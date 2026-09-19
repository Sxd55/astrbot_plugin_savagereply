import asyncio
import os
import sys
import unittest
from pathlib import Path
from unittest.mock import patch, MagicMock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from astrbot.api.message_components import Image, Plain
from savagereply.config import ReplyOptions
from savagereply.t2i import (
    find_browser_executable,
    markdown_to_antigravity_html,
    render_markdown_to_image,
    render_markdown_to_image_sync,
    should_render_as_image,
)


class TestT2IModule(unittest.TestCase):
    def test_find_browser(self):
        browser = find_browser_executable()
        # Windows 环境下 Edge 默认存在
        self.assertIsNotNone(browser)
        self.assertTrue(os.path.isfile(browser))

    def test_markdown_to_html_styling(self):
        sample = (
            "# 标题\n\n"
            "这是一段包含 **加粗重点** 和 `inline_keyword` 标红的测试。\n\n"
            "> 引用说明\n\n"
            "| 列1 | 列2 |\n"
            "| --- | --- |\n"
            "| 数据A | 数据B |\n"
        )
        html = markdown_to_antigravity_html(sample)
        # 必须包含关键 1:1 Antigravity 样式与语义元素
        self.assertIn("#f9f9f9", html)  # 沉浸式浅灰背景
        self.assertIn("#a31515", html)  # 关键词/行内代码深暗红高亮
        self.assertIn("#efefef", html)  # 浅灰无框底色
        self.assertIn("#f3f3f3", html)  # 引用框纯浅灰平底
        self.assertIn("<strong>加粗重点</strong>", html)
        self.assertIn("<code>inline_keyword</code>", html)
        self.assertIn("<blockquote>", html)
        self.assertIn("<table>", html)

    def test_render_markdown_to_image_sync(self):
        text = (
            "## 核心特性评估报告\n\n"
            "经过严谨测试，各项指标表现如下：\n\n"
            "- `Pacing` 拟人延迟：**优异**\n"
            "- `Integrity` 完整性：**100% 保护**\n\n"
            "> 注：长回复已无缝转为卡片长图回复。\n"
        )
        out_path = render_markdown_to_image_sync(text)
        self.assertIsNotNone(out_path)
        self.assertTrue(os.path.exists(out_path))
        self.assertTrue(out_path.endswith(".png"))
        self.assertGreater(os.path.getsize(out_path), 1000)

        # 清理临时生成的文件
        try:
            os.remove(out_path)
        except OSError:
            pass

    def test_render_markdown_to_image_async(self):
        async def _run():
            text = "### 异步渲染测试\n\n这是通过 `asyncio` 线程池异步执行的图片渲染测试。"
            return await render_markdown_to_image(text)

        out_path = asyncio.run(_run())
        self.assertIsNotNone(out_path)
        self.assertTrue(os.path.exists(out_path))
        try:
            os.remove(out_path)
        except OSError:
            pass

    def test_should_render_as_image_conditions(self):
        options = ReplyOptions(
            t2i_detailed_reply_enabled=True,
            t2i_min_chars=200,
        )
        # 短闲聊文本：不触发
        self.assertFalse(should_render_as_image("你好呀，今天天气真不错！", options))

        # 开关关闭：即使很长也不触发
        disabled_options = ReplyOptions(
            t2i_detailed_reply_enabled=False,
            t2i_min_chars=200,
        )
        self.assertFalse(
            should_render_as_image("很长的一段文字" * 50, disabled_options)
        )

        # 结构化数据或表格：即使短也触发长图渲染
        self.assertTrue(
            should_render_as_image("数据报告", options, decision_reason="structured_data")
        )
        self.assertTrue(
            should_render_as_image("表格内容", options, decision_reason="table")
        )

        # 超过 200 字的长回复：触发
        long_text = "详细分析内容：" + "关键指标说明测试。" * 25
        self.assertTrue(should_render_as_image(long_text, options))

    def test_browser_not_found_fallback(self):
        options = ReplyOptions(t2i_detailed_reply_enabled=True)
        with patch("savagereply.t2i.find_browser_executable", return_value=None):
            # 没有浏览器时 should_render_as_image 返回 False
            self.assertFalse(should_render_as_image("超长文字" * 50, options))
            # 同步渲染直接返回 None
            self.assertIsNone(render_markdown_to_image_sync("测试"))


class TestT2IDecorateIntegration(unittest.IsolatedAsyncioTestCase):
    async def test_decorate_renders_image_for_detailed_reply(self):
        from main import SavageReplyPlugin

        plugin = SavageReplyPlugin(
            context=MagicMock(),
            config={
                "enabled": True,
                "t2i_detailed_reply_enabled": True,
                "t2i_min_chars": 50,
            },
        )

        # 构造一个符合详细输出的事件
        event = MagicMock()
        event.get_platform_name.return_value = "aiocqhttp"
        event.unified_msg_origin = "test_origin"

        # 模拟模型回复一个包含数据清单的回复
        text_content = (
            "### 详细参数报告\n\n"
            "1. 指标 A：`98.5%` 通过率\n"
            "2. 指标 B：`0.08s` 延迟\n"
            "3. 指标 C：**完整性 100% 保护**\n\n"
            "> 总结：整体运行稳定健康。"
        )
        result = MagicMock()
        result.chain = [Plain(text_content)]
        result._savagereply_processed = False
        result.is_model_result.return_value = True
        event.get_result.return_value = result

        await plugin._decorate(event)

        # 验证 result.chain 被替换为 Image 组件
        self.assertEqual(len(result.chain), 1)
        comp = result.chain[0]
        self.assertIsInstance(comp, Image)
        img_file = getattr(comp, "path", None) or getattr(comp, "file", "")
        if img_file.startswith("file:///"):
            img_file = img_file[8:]
        self.assertTrue(os.path.exists(img_file))
        try:
            os.remove(img_file)
        except OSError:
            pass

    async def test_decorate_fallback_on_render_failure(self):
        from main import SavageReplyPlugin

        plugin = SavageReplyPlugin(
            context=MagicMock(),
            config={
                "enabled": True,
                "t2i_detailed_reply_enabled": True,
                "t2i_min_chars": 50,
            },
        )

        event = MagicMock()
        event.get_platform_name.return_value = "aiocqhttp"
        event.unified_msg_origin = "test_origin"

        text_content = (
            "### 详细参数报告\n\n"
            "1. 指标 A：`98.5%` 通过率\n"
            "2. 指标 B：`0.08s` 延迟\n"
            "3. 指标 C：**完整性 100% 保护**\n"
        )
        result = MagicMock()
        result.chain = [Plain(text_content)]
        result._savagereply_processed = False
        result.is_model_result.return_value = True
        event.get_result.return_value = result

        # 模拟渲染函数抛出异常或返回 None
        with patch("main.render_markdown_to_image", return_value=None):
            await plugin._decorate(event)

            # 优雅降级：不能抛异常，且仍有 Plain 输出，内容完整保留
            self.assertEqual(len(result.chain), 1)
            comp = result.chain[0]
            self.assertIsInstance(comp, Plain)
            self.assertIn("指标 A", comp.text)


if __name__ == "__main__":
    unittest.main()
