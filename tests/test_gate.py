"""单元测试：验证 savagereply 群聊活跃与接话门禁系统（When）功能。"""

import asyncio
import datetime
import pathlib
import sys
import unittest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

from savagereply.gate.active import (
    ActiveReplyRateLimiter,
    in_targets,
    is_quiet_time,
    is_question,
    is_usable_text,
    match_keywords,
    match_names,
)
from savagereply.gate.turn import TurnTracker
from savagereply.gate import ActiveGate


class TestActiveGateComponents(unittest.TestCase):
    def test_text_usable(self):
        self.assertEqual(is_usable_text("")[0], False)
        self.assertEqual(is_usable_text("a")[0], False)
        self.assertEqual(is_usable_text("/help")[0], False)
        self.assertEqual(is_usable_text("!status")[0], False)
        self.assertEqual(is_usable_text("你好呀")[0], True)

    def test_is_question(self):
        self.assertTrue(is_question("今天天气怎么样？"))
        self.assertTrue(is_question("有人在吗"))
        self.assertTrue(is_question("能不能帮我看一下这个代码"))
        self.assertFalse(is_question("今天天气真好。"))
        self.assertFalse(is_question("我先去吃饭了"))

    def test_quiet_time(self):
        # 跨零点测试：23:00 - 07:00
        t_night = datetime.datetime(2026, 1, 1, 23, 30)
        t_morning_early = datetime.datetime(2026, 1, 1, 6, 30)
        t_day = datetime.datetime(2026, 1, 1, 14, 0)

        self.assertTrue(is_quiet_time("23:00-07:00", t_night))
        self.assertTrue(is_quiet_time("23:00-07:00", t_morning_early))
        self.assertFalse(is_quiet_time("23:00-07:00", t_day))

    def test_names_and_keywords(self):
        self.assertTrue(match_names("小助手在吗", ["小助手"])[0])
        self.assertTrue(match_names("Hello savage!", ["savage"])[0])
        self.assertFalse(match_names("今天吃啥", ["小助手"])[0])

        self.assertTrue(match_keywords("谁有激活码呀", ["激活码", "求助"])[0])
        self.assertFalse(match_keywords("今天天气不错", ["激活码", "求助"])[0])

    def test_rate_limiter(self):
        limiter = ActiveReplyRateLimiter()
        group = "group_1001"

        # 初始状态允许
        ok, _ = limiter.check(group, cooldown=10.0, daily_limit=2)
        self.assertTrue(ok)

        # 触发一次
        limiter.record_fired(group, now_ts=100.0)
        self.assertEqual(limiter.get_today_count(group), 1)

        # 冷却未过拦截
        ok, reason = limiter.check(group, cooldown=10.0, daily_limit=2, now_ts=105.0)
        self.assertFalse(ok)
        self.assertIn("cooldown", reason)

        # 冷却过后允许
        ok, _ = limiter.check(group, cooldown=10.0, daily_limit=2, now_ts=111.0)
        self.assertTrue(ok)

        # 触发第二次达到上限
        limiter.record_fired(group, now_ts=112.0)
        self.assertEqual(limiter.get_today_count(group), 2)

        # 超出日上限拦截
        ok, reason = limiter.check(group, cooldown=1.0, daily_limit=2, now_ts=120.0)
        self.assertFalse(ok)
        self.assertIn("daily_limit_reached", reason)

    def test_turn_tracker_private_dialogue_avoidance(self):
        tracker = TurnTracker(max_history=10)
        group = "group_1002"
        bot_id = "bot_999"

        # 1. 艾特别人：判定非开放话轮
        ok, reason = tracker.is_turn_open(group, "user_A", ["user_B"], bot_id)
        self.assertFalse(ok)
        self.assertIn("addressed_to_other", reason)

        # 2. 艾特 Bot：开放话轮
        ok, _ = tracker.is_turn_open(group, "user_A", [bot_id], bot_id)
        self.assertTrue(ok)

        # 3. 艾特全体成员：开放话轮
        ok, _ = tracker.is_turn_open(group, "user_A", ["all"], bot_id)
        self.assertTrue(ok)

        # 4. 两人高频对线氛围测试
        import time
        now = time.time()
        tracker.record_turn(group, "user_A", "你在干嘛", [], False)
        tracker.record_turn(group, "user_B", "在写代码", [], False)
        tracker.record_turn(group, "user_A", "写的怎么样了", [], False)

        # 第三人未艾特插入，检测到 A 与 B 在密集交谈
        ok, reason = tracker.is_turn_open(group, "user_C", [], bot_id)
        self.assertFalse(ok)
        self.assertEqual(reason, "private_dialogue_active")


class TestActiveGateIntegration(unittest.TestCase):
    def setUp(self):
        self.gate = ActiveGate()

    def test_evaluate_basic_filters(self):
        # 1. 未启用
        fire, reason = self.gate.evaluate(
            enabled=False,
            is_group=True,
            group_id="g1",
            sender_id="u1",
            text="你好",
            target_ids=[],
            bot_id="bot1",
            bot_names=["小助手"],
            mode="smart",
            probability=0.05,
            keywords=[],
            groups_whitelist=[],
            quiet_hours="",
            cooldown=60.0,
            daily_limit=10,
        )
        self.assertFalse(fire)
        self.assertEqual(reason, "disabled")

        # 2. 叫到名字必定放行
        fire, reason = self.gate.evaluate(
            enabled=True,
            is_group=True,
            group_id="g1",
            sender_id="u1",
            text="小助手今天天气如何",
            target_ids=[],
            bot_id="bot1",
            bot_names=["小助手"],
            mode="smart",
            probability=0.05,
            keywords=[],
            groups_whitelist=[],
            quiet_hours="",
            cooldown=60.0,
            daily_limit=10,
        )
        self.assertTrue(fire)
        self.assertIn("name:小助手", reason)

        # 3. 关键词模式命中
        fire, reason = self.gate.evaluate(
            enabled=True,
            is_group=True,
            group_id="g1",
            sender_id="u1",
            text="这个软件怎么升级",
            target_ids=[],
            bot_id="bot1",
            bot_names=[],
            mode="keywords",
            probability=0.05,
            keywords=["升级", "下载"],
            groups_whitelist=[],
            quiet_hours="",
            cooldown=60.0,
            daily_limit=10,
        )
        self.assertTrue(fire)
        self.assertIn("keyword:升级", reason)


class TestUnansweredSchedulerAsync(unittest.IsolatedAsyncioTestCase):
    async def test_cold_break_scheduler(self):
        gate = ActiveGate()
        group = "test_cold_group"
        asker = "user_lonely"

        fired = []

        async def callback():
            fired.append(True)

        # 调度 0.1 秒后触发冷场接话
        gate.schedule_unanswered(group, delay_seconds=0.1, asker_id=asker, callback=callback)
        self.assertEqual(len(fired), 0)

        # 等待 0.15 秒，无人应答，应该成功触发
        await asyncio.sleep(0.15)
        self.assertEqual(len(fired), 1)

    async def test_cold_break_cancelled_on_activity(self):
        gate = ActiveGate()
        group = "test_active_group"
        asker = "user_asker"

        fired = []

        async def callback():
            fired.append(True)

        gate.schedule_unanswered(group, delay_seconds=0.15, asker_id=asker, callback=callback)

        # 在 0.05 秒时其他群友回复了
        await asyncio.sleep(0.05)
        gate.record_turn(group, "user_helper", "我知道这个问题的答案！", [], False)

        # 等待到 0.2 秒
        await asyncio.sleep(0.15)
        # 应该被静默阻止，没有触发 Bot 救场
        self.assertEqual(len(fired), 0)


class TestSavageDoctor(unittest.TestCase):
    def test_build_doctor_report(self):
        class MockContext:
            def get_all_stars(self):
                class StarA:
                    name = "astrbot_plugin_savagemode"
                    version = "v0.2.1"
                class StarB:
                    name = "astrbot_plugin_savagetype"
                    version = "v5.5.0"
                    config = {"config_preset": "frugal"}
                return [StarA(), StarB()]

            def get_config(self):
                return {}

            def register_web_api(self, *args, **kwargs):
                pass

        import sys
        import pathlib
        sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
        try:
            from main import SavageReplyPlugin
        except ImportError:
            raise unittest.SkipTest("astrbot not installed in current environment")

        plugin = SavageReplyPlugin(MockContext(), config={"active_reply_enabled": True})
        report = plugin._build_doctor_report()
        self.assertIn("Savage 插件生态健康体检卡", report)
        self.assertIn("savagemode: ✅ 正常运行", report)
        self.assertIn("savagetype: ✅ 正常运行", report)
        self.assertIn("预设: frugal", report)
        self.assertIn("双端协同握手避让已生效", report)


if __name__ == "__main__":
    unittest.main()
