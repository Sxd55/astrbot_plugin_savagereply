"""Integration tests against the real AstrBot framework package.

Needs `astrbot` installed:

    <venv>/Scripts/python tests/test_integration.py -v

Without astrbot the whole module is skipped, so `test_core.py` stays
dependency-free. Uses REAL AstrMessageEvent / MessageEventResult /
ProviderRequest / TextPart objects with a stubbed Context, driving the real
`on_decorating_result` / `on_llm_request` handlers and panel APIs.
"""

from __future__ import annotations

import asyncio
import json
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

# AstrBot import has a side effect: it creates ./data in CWD.
# Keep the repo clean by running from a scratch dir (all paths here are absolute).
import os
import tempfile

_IT_WORKDIR = os.path.join(tempfile.gettempdir(), "astrbot-it-workdir")
os.makedirs(_IT_WORKDIR, exist_ok=True)
os.chdir(_IT_WORKDIR)

try:
    from astrbot.api.event import (
        AstrMessageEvent,
        MessageEventResult,
        ResultContentType,
    )
    from astrbot.api.message_components import At, Image, Plain, Reply
    from astrbot.api.provider import ProviderRequest
    from astrbot.core.platform.astrbot_message import (
        AstrBotMessage,
        MessageMember,
        MessageType,
    )
    from astrbot.core.platform.platform_metadata import PlatformMetadata

    import main as plugin_main

    HAS_ASTRBOT = True
except Exception:  # noqa: BLE001
    HAS_ASTRBOT = False


class FakeContext:
    def __init__(self):
        self.routes: dict[str, tuple] = {}
        self.sent: list = []
        self.astrbot_config: dict = {}

    def get_all_stars(self):
        return []

    def get_all_providers(self):
        return []

    def get_all_embedding_providers(self):
        return []

    @property
    def provider_manager(self):
        return SimpleNamespace(inst_map={})

    def get_provider_by_id(self, _pid):
        return None

    def get_config(self):
        return dict(self.astrbot_config)

    def register_web_api(self, route, handler, methods, *args, **kwargs):
        self.routes[route] = (handler, methods)

    async def send_message(self, umo, chain):
        self.sent.append((umo, chain))


class FakeRequest:
    class Query(dict):
        def get(self, key, default=None, type=None):  # noqa: A002
            value = super().get(key, default)
            if type is not None and value is not default:
                try:
                    return type(value)
                except (TypeError, ValueError):
                    return default
            return value

    def __init__(self, query=None, body=None):
        self.query = FakeRequest.Query(query or {})
        self._body = body or {}

    async def json(self, default=None):
        return self._body if self._body is not None else (default or {})


class FakeBot:
    def __init__(self, fail=False):
        self.calls: list[tuple] = []
        self.fail = fail

    async def call_action(self, action, **kwargs):
        self.calls.append((action, kwargs))
        if self.fail:
            raise RuntimeError("platform down")
        return True


def make_event(text, sid="u1", name="阿U", group="1", platform="aiocqhttp"):
    msg = AstrBotMessage()
    msg.type = MessageType.GROUP_MESSAGE if group else MessageType.FRIEND_MESSAGE
    msg.self_id = "bot1"
    msg.sender = MessageMember(user_id=sid, nickname=name)
    msg.message = [Plain(text)]
    msg.message_str = text
    msg.message_id = "10001"
    if group:
        msg.group_id = group
    meta = PlatformMetadata(name=platform, description="test", id=platform)
    return AstrMessageEvent(text, msg, meta, group or sid)


def make_result(text, model=True):
    result = MessageEventResult().message(text)
    result.result_content_type = (
        ResultContentType.LLM_RESULT if model else ResultContentType.GENERAL_RESULT
    )
    return result


def chain_text(chain):
    return "".join(getattr(c, "text", "") or "" for c in (chain or []))


def _json(resp):
    return json.loads(resp.body.decode("utf-8"))


@unittest.skipUnless(HAS_ASTRBOT, "astrbot package not installed")
class ReplyIntegrationTest(unittest.TestCase):
    def setUp(self):
        import tempfile

        self.tmp = tempfile.TemporaryDirectory()
        self.ctx = FakeContext()
        self.plugin = plugin_main.SavageReplyPlugin(self.ctx, self._config())

    def tearDown(self):
        self.tmp.cleanup()

    def _config(self):
        return {
            "delay_base_seconds": 0.0,
            "delay_per_char_seconds": 0.0,
            "delay_jitter": 0.0,
            "delay_punct_bonus_seconds": 0.0,
            "typing_enabled": False,
            "read_delay_min_seconds": 0.0,
            "read_delay_max_seconds": 0.0,
        }

    def _decorate(self, text, group="1", platform="aiocqhttp", model=True, fail_on=()):
        event = make_event(text, group=group, platform=platform)
        result = make_result(text, model=model)
        event.set_result(result)
        sent: list[str] = []
        calls = {"n": 0}

        async def fake_send(chain):
            calls["n"] += 1
            if calls["n"] in fail_on:
                raise RuntimeError("send down")
            sent.append(chain_text(chain.chain if hasattr(chain, "chain") else chain))

        event.send = fake_send
        asyncio.run(self.plugin.on_decorating_result(event))
        return event, result, sent

    # -- load ----------------------------------------------------------

    def test_plugin_loads_and_config(self):
        self.assertIn("/astrbot_plugin_savagereply/config", self.ctx.routes)
        self.assertIn("/astrbot_plugin_savagereply/config/save", self.ctx.routes)
        asyncio.run(self.plugin.initialize())
        plugin_main.request = FakeRequest()
        try:
            data = _json(asyncio.run(self.plugin.page_config()))
            self.assertTrue(data["values"]["enabled"])
            self.assertEqual(data["values"]["max_segments"], 6)
        finally:
            plugin_main.request = FakeRequest()

    # -- marker injection ------------------------------------------------

    def test_marker_prompt_injected(self):
        event = make_event("你好", group="1")
        req = ProviderRequest(prompt="你好", session_id="x")
        asyncio.run(self.plugin.on_llm_request(event, req))
        parts = list(req.extra_user_content_parts or [])
        self.assertTrue(parts)
        self.assertIn("[[next]]", parts[0].text)

    def test_marker_injection_respects_switches(self):
        self.plugin.config["marker_enabled"] = False
        event = make_event("你好", group="1")
        req = ProviderRequest(prompt="你好", session_id="x")
        asyncio.run(self.plugin.on_llm_request(event, req))
        self.assertEqual(list(req.extra_user_content_parts or []), [])

        self.plugin.config["marker_enabled"] = True
        self.plugin.config["platform_exclude"] = ["aiocqhttp"]
        req = ProviderRequest(prompt="你好", session_id="x")
        asyncio.run(self.plugin.on_llm_request(event, req))
        self.assertEqual(list(req.extra_user_content_parts or []), [])

    # -- streaming override ----------------------------------------------

    def test_streaming_disabled_for_managed_session(self):
        event = make_event("你好", group="1")
        asyncio.run(self.plugin.on_message(event))
        self.assertIs(event.get_extra("enable_streaming"), False)

    def test_streaming_override_respects_switches(self):
        self.plugin.config["force_non_streaming"] = False
        event = make_event("你好", group="1")
        asyncio.run(self.plugin.on_message(event))
        self.assertIsNone(event.get_extra("enable_streaming"))

        self.plugin.config["force_non_streaming"] = True
        self.plugin.config["enabled"] = False
        event = make_event("你好", group="1")
        asyncio.run(self.plugin.on_message(event))
        self.assertIsNone(event.get_extra("enable_streaming"))

        self.plugin.config["enabled"] = True
        self.plugin.config["platform_exclude"] = ["aiocqhttp"]
        event = make_event("你好", group="1")
        asyncio.run(self.plugin.on_message(event))
        self.assertIsNone(event.get_extra("enable_streaming"))

        self.plugin.config["platform_exclude"] = []
        event = make_event("你好", group="1")
        asyncio.run(self.plugin.on_message(event))
        self.assertIs(event.get_extra("enable_streaming"), False)

    def test_streaming_override_survives_bad_event(self):
        class Broken:
            def get_platform_name(self):
                raise RuntimeError("boom")

        asyncio.run(self.plugin.on_message(Broken()))

    # -- framework typing -------------------------------------------------

    def test_framework_typing_detection(self):
        from astrbot.core.platform.astr_message_event import AstrMessageEvent as BaseEvent

        class Plain:
            def get_platform_name(self):
                return "telegram"

        Plain.send_typing = BaseEvent.send_typing
        self.assertFalse(self.plugin._framework_typing_available(Plain()))

        class Typing(Plain):
            async def send_typing(self):  # pragma: no cover - 探测用
                return None

        self.assertTrue(self.plugin._framework_typing_available(Typing()))

        class WebchatTyping(Typing):
            def get_platform_name(self):
                return "webchat"

        self.assertFalse(self.plugin._framework_typing_available(WebchatTyping()))

    def test_framework_typing_calls(self):
        class Typing:
            def __init__(self):
                self.sent = 0
                self.stopped = 0

            async def send_typing(self):
                self.sent += 1

            async def stop_typing(self):
                self.stopped += 1

        event = Typing()
        asyncio.run(self.plugin._framework_typing(event, True))
        asyncio.run(self.plugin._framework_typing(event, False))
        self.assertEqual((event.sent, event.stopped), (1, 1))

        class Broken(Typing):
            async def send_typing(self):
                raise RuntimeError("no typing api")

        asyncio.run(self.plugin._framework_typing(Broken(), True))

    # -- split flow -------------------------------------------------------

    def test_long_reply_splits_all_segments(self):
        text = "我今天下午去了一趟书店，买了两本小说。一本是科幻，一本是推理，都很喜欢。你要不要借去看？"
        _event, result, sent = self._decorate(text)
        # 末尾问句不再并进上一条，单独作为最后一条（P0）。
        self.assertEqual(len(sent), 3)
        self.assertIn("买了两本小说", sent[0])
        self.assertNotIn("[[next]]", sent[0])
        self.assertEqual(sent[-1], "你要不要借去看？")
        self.assertEqual(result.chain, [])
        self.assertTrue(getattr(result, "_savagereply_processed", False))

    def test_long_reply_uses_paragraph_path(self):
        para = "这是一段比较长的说明文字，用来验证超长回复会按空行段落切分。"
        text = "\n\n".join([para] * 4)
        self.plugin.config.update(
            {"max_total_chars": 60, "paragraph_max_chars": 60, "max_segments": 8}
        )
        _event, result, sent = self._decorate(text)
        self.assertGreaterEqual(len(sent), 1)
        joined = "".join(sent) + chain_text(result.chain)
        self.assertIn("超长回复", joined)
        self.assertNotIn("[[next]]", joined)

    def test_bypass_paths_keep_chain(self):
        _event, result, sent = self._decorate("```python\nprint(1)\n```\n说明文字也在这里")
        self.assertEqual(sent, [])
        self.assertIn("print(1)", chain_text(result.chain))
        _event, result, sent = self._decorate("好的")
        self.assertEqual(sent, [])
        self.assertEqual(chain_text(result.chain), "好的")

    def test_non_plain_chain_bypassed(self):
        event = make_event("看图", group="1")
        result = make_result("看图")
        result.chain = [Plain("看图"), Image(file="http://x/y.png")]
        event.set_result(result)
        event.send = lambda chain: (_ for _ in ()).throw(AssertionError("must not send"))
        asyncio.run(self.plugin.on_decorating_result(event))
        self.assertEqual(len(result.chain), 2)

    def test_non_llm_result_skipped(self):
        event = make_event("x", group="1")
        res = make_result("我今天下午去了一趟书店，买了两本小说。一本是科幻。", model=False)
        event.set_result(res)
        event.send = lambda chain: (_ for _ in ()).throw(AssertionError("must not send"))
        asyncio.run(self.plugin.on_decorating_result(event))
        self.assertEqual(chain_text(res.chain), "我今天下午去了一趟书店，买了两本小说。一本是科幻。")

    def test_streaming_result_skipped(self):
        event = make_event("x", group="1")
        res = make_result("我今天下午去了一趟书店，买了两本小说。一本是科幻。")
        res.result_content_type = ResultContentType.STREAMING_RESULT
        event.set_result(res)
        asyncio.run(self.plugin.on_decorating_result(event))
        self.assertEqual(len(res.chain), 1)

    # -- marker paths (regression: no leak on bypass) ----------------------

    def test_marker_split_and_stripped(self):
        text = "第一条消息内容足够长了。[[next]]第二条消息内容也足够长了。[[next]]第三条也足够长了。"
        _event, result, sent = self._decorate(text)
        self.assertEqual(len(sent), 3)
        for chunk in sent:
            self.assertNotIn("[[next]]", chunk)
        self.assertEqual(result.chain, [])

    def test_marker_leak_on_bypass_is_fixed(self):
        self.plugin.config["marker_enabled"] = False
        _event, result, sent = self._decorate("短句。[[next]]另一短句。")
        full = "".join(sent) + chain_text(result.chain)
        self.assertNotIn("[[next]]", full)

    def test_fence_marker_ignored(self):
        text = "看代码。\n```python\nprint(1)  # [[next]]\n```\n说明文字足够长可以分段用。"
        _event, result, sent = self._decorate(text)
        full = "".join(sent) + chain_text(result.chain)
        self.assertIn("print(1)", full)

    # -- failure fallback ----------------------------------------------------

    def test_send_failure_falls_back_to_single(self):
        text = "我今天下午去了一趟书店，买了两本小说。一本是科幻，一本是推理，都很喜欢。你要不要借去看？"
        _event, result, sent = self._decorate(text, fail_on=(1,))
        self.assertEqual(sent, [])
        tail = chain_text(result.chain)
        self.assertIn("买了两本小说", tail)
        self.assertIn("借去看", tail)

    def test_builtin_segmented_sends_all(self):
        self.ctx.astrbot_config = {"platform_settings": {"segmented_reply": {"enable": True}}}
        text = "我今天下午去了一趟书店，买了两本小说。一本是科幻，一本是推理，都很喜欢。你要不要借去看？"
        _event, result, sent = self._decorate(text)
        self.assertEqual(len(sent), 3)
        self.assertEqual(result.chain, [])

    # -- framework reply headers（引用 / @ / 回复前缀） -----------------------

    def _decorate_chains(self, text, platform_settings, group="1"):
        self.ctx.astrbot_config = {"platform_settings": platform_settings}
        event = make_event(text, group=group)
        result = make_result(text)
        event.set_result(result)
        sent = []

        async def fake_send(chain):
            sent.append(chain)

        event.send = fake_send
        asyncio.run(self.plugin.on_decorating_result(event))
        return event, result, sent

    def test_quote_only_on_first_segment(self):
        text = "我今天下午去了一趟书店，买了两本小说。一本是科幻，一本是推理，都很喜欢。你要不要借去看？"
        _event, result, sent = self._decorate_chains(text, {"reply_with_quote": True})
        self.assertGreaterEqual(len(sent), 2)
        self.assertIsInstance(sent[0].chain[0], Reply)
        self.assertEqual(sent[0].chain[0].id, "10001")
        for chain in sent[1:]:
            self.assertTrue(all(not isinstance(comp, Reply) for comp in chain.chain))
        self.assertEqual(result.chain, [])

    def test_mention_only_on_first_segment(self):
        text = "我今天下午去了一趟书店，买了两本小说。一本是科幻，一本是推理，都很喜欢。你要不要借去看？"
        _event, _result, sent = self._decorate_chains(text, {"reply_with_mention": True})
        self.assertGreaterEqual(len(sent), 2)
        self.assertIsInstance(sent[0].chain[0], At)
        self.assertTrue(sent[0].chain[1].text.startswith("\n"))
        for chain in sent[1:]:
            self.assertTrue(all(not isinstance(comp, At) for comp in chain.chain))

    def test_mention_skipped_in_private_chat(self):
        text = "我今天下午去了一趟书店，买了两本小说。一本是科幻，一本是推理，都很喜欢。你要不要借去看？"
        _event, _result, sent = self._decorate_chains(text, {"reply_with_mention": True}, group="")
        self.assertTrue(sent)
        for chain in sent:
            self.assertTrue(all(not isinstance(comp, At) for comp in chain.chain))

    def test_reply_prefix_only_on_first_segment(self):
        text = "我今天下午去了一趟书店，买了两本小说。一本是科幻，一本是推理，都很喜欢。你要不要借去看？"
        _event, _result, sent = self._decorate_chains(text, {"reply_prefix": "【铃】"})
        self.assertGreaterEqual(len(sent), 2)
        self.assertTrue(sent[0].chain[0].text.startswith("【铃】"))
        for chain in sent[1:]:
            self.assertFalse(chain.chain[0].text.startswith("【铃】"))

    def test_quote_and_mention_order_matches_framework(self):
        text = "我今天下午去了一趟书店，买了两本小说。一本是科幻，一本是推理，都很喜欢。你要不要借去看？"
        _event, _result, sent = self._decorate_chains(
            text, {"reply_with_quote": True, "reply_with_mention": True}
        )
        kinds = [type(comp).__name__ for comp in sent[0].chain]
        self.assertEqual(kinds[:2], ["Reply", "At"])
        self.assertTrue(sent[0].chain[2].text.startswith("\n"))

    def test_tts_segments_skip_framework_headers(self):
        provider = self._voice_provider()
        restore = self._with_tts(provider)
        try:
            self.ctx.astrbot_config["platform_settings"] = {"reply_with_quote": True}
            text = "第一段话要写长一点点，凑够最短分段字数的要求。第二段话也写长一些，确保能被算成候选。"
            event = make_event(text, group="1")
            result = make_result(text)
            event.set_result(result)
            sent = []

            async def fake_send(chain):
                sent.append(chain)

            event.send = fake_send
            asyncio.run(self.plugin.on_decorating_result(event))
            self.assertGreaterEqual(len(sent), 2)
            for chain in sent:
                self.assertTrue(all(not isinstance(comp, Reply) for comp in chain.chain))
            self.assertEqual(result.chain, [])
        finally:
            restore()

    # -- tts -------------------------------------------------------------------

    def _with_tts(self, provider, probability=1.0):
        """装上假的 TTS provider / 会话开关，返回还原函数。"""
        import astrbot.core.star.session_llm_manager as manager_mod

        manager = manager_mod.SessionServiceManager
        self.ctx.astrbot_config = {
            "provider_tts_settings": {"enable": True, "trigger_probability": probability},
        }

        async def fake_should_process(_event):
            return True

        old_should = getattr(manager, "should_process_tts_request", None)
        setattr(manager, "should_process_tts_request", staticmethod(fake_should_process))

        async def fake_provider(_umo):
            return provider

        self.ctx.get_using_tts_provider_async = fake_provider

        def restore():
            if old_should is not None:
                setattr(manager, "should_process_tts_request", old_should)
            if hasattr(self.ctx, "get_using_tts_provider_async"):
                delattr(self.ctx, "get_using_tts_provider_async")

        return restore

    @staticmethod
    def _voice_provider(audio_path="/tmp/fake.mp3", fail=False):
        class Provider:
            def __init__(self):
                self.calls = []

            async def get_audio(self, text):
                self.calls.append(text)
                if fail:
                    raise RuntimeError("tts down")
                return audio_path

        return Provider()

    def test_tts_synthesizes_each_segment(self):
        from astrbot.api.message_components import Record

        provider = self._voice_provider()
        restore = self._with_tts(provider)
        try:
            text = "第一段话要写长一点点，凑够最短分段字数的要求。第二段话也写长一些，确保能被算成候选。第三段话同样要够长，这样才能切成三条。"
            event = make_event(text, group="1")
            result = make_result(text)
            event.set_result(result)
            sent = []

            async def fake_send(chain):
                sent.append(chain)

            event.send = fake_send
            asyncio.run(self.plugin.on_decorating_result(event))

            self.assertEqual(len(sent), 3)
            self.assertEqual(len(provider.calls), 3)
            for chain in sent:
                kinds = [type(comp).__name__ for comp in chain.chain]
                self.assertIn("Record", kinds)
            self.assertEqual(result.chain, [])
        finally:
            restore()

    def test_tts_failure_falls_back_to_text(self):
        provider = self._voice_provider(fail=True)
        restore = self._with_tts(provider)
        try:
            text = "第一段话要写长一点点，凑够最短分段字数的要求。第二段话也写长一些，确保能被算成候选。"
            event = make_event(text, group="1")
            result = make_result(text)
            event.set_result(result)
            sent = []

            async def fake_send(chain):
                sent.append(chain)

            event.send = fake_send
            asyncio.run(self.plugin.on_decorating_result(event))

            self.assertEqual(len(sent), 2)
            for chain in sent:
                self.assertEqual(len(chain.chain), 1)
                self.assertIsInstance(chain.chain[0], Plain)
                self.assertTrue(chain.chain[0].text.strip())
        finally:
            restore()

    def test_tts_probability_zero_keeps_text_flow(self):
        provider = self._voice_provider()
        restore = self._with_tts(provider, probability=0.0)
        try:
            text = "第一段话要写长一点点，凑够最短分段字数的要求。第二段话也写长一些，确保能被算成候选。"
            event = make_event(text, group="1")
            result = make_result(text)
            event.set_result(result)
            sent = []

            async def fake_send(chain):
                sent.append(chain)

            event.send = fake_send
            asyncio.run(self.plugin.on_decorating_result(event))

            self.assertEqual(provider.calls, [])
            self.assertEqual(len(sent), 2)
            self.assertIn("第二段话", "".join(chain_text(chain.chain) for chain in sent))
            self.assertEqual(result.chain, [])
        finally:
            restore()

    # -- 单层方括号标记（实机踩过：模型写了 [next]，插件只认 [[next]]） ----

    def test_single_bracket_marker_splits_live(self):
        text = "嘴上带刺。[next]底下是软的。[next]还有一句。"
        _event, result, sent = self._decorate(text)
        self.assertEqual(len(sent), 3)
        joined = "".join(sent)
        self.assertNotIn("[next]", joined)
        self.assertIn("底下是软的", joined)

    def test_single_bracket_marker_stripped_when_disabled(self):
        self.plugin.config["marker_enabled"] = False
        text = "嘴上带刺。[next]底下是软的。[next]还有一句。"
        _event, result, sent = self._decorate(text)
        joined = "".join(sent) + chain_text(result.chain)
        self.assertNotIn("[next]", joined)

    def test_debris_and_marker_mix(self):
        text = "第一句先垫一下字数。[[]]第二句内容也够长。[next]第三句收尾。"
        _event, result, sent = self._decorate(text)
        joined = "".join(sent) + chain_text(result.chain)
        self.assertNotIn("[[]]", joined)
        self.assertNotIn("[next]", joined)
        self.assertIn("第三句收尾", joined)

    def test_markdown_marks_stripped(self):
        text = "这是**加粗的重点**，后面还有普通内容要继续说下去。再来一句收尾的话。"
        _event, result, sent = self._decorate(text)
        joined = "".join(sent) + chain_text(result.chain)
        self.assertNotIn("**", joined)
        self.assertIn("加粗的重点", joined)

    def test_markdown_marks_kept_when_disabled(self):
        self.plugin.config["strip_markdown_marks"] = False
        text = "这是**加粗的重点**，后面还有普通内容要继续说下去。再来一句收尾的话。"
        _event, result, sent = self._decorate(text)
        joined = "".join(sent) + chain_text(result.chain)
        self.assertIn("**", joined)

    # -- typing ------------------------------------------------------------------

    def test_typing_status_private_only(self):
        self.plugin.config.update(
            {
                "typing_enabled": True,
                "delay_base_seconds": 0.01,
                "delay_per_char_seconds": 0.0,
                "delay_jitter": 0.0,
                "delay_punct_bonus_seconds": 0.0,
            }
        )
        text = "我今天下午去了一趟书店，买了两本小说。一本是科幻，一本是推理，都很喜欢。你要不要借去看？"
        event = make_event(text, sid="12345", name="阿U", group="")  # 私聊：数字 QQ 号才能调输入状态
        bot = FakeBot()
        event.bot = bot
        result = make_result(text)
        event.set_result(result)
        sent: list[str] = []

        async def fake_send(chain):
            sent.append(chain_text(chain.chain if hasattr(chain, "chain") else chain))

        event.send = fake_send
        asyncio.run(self.plugin.on_decorating_result(event))
        kinds = [kwargs.get("event_type") for _action, kwargs in bot.calls]
        self.assertIn(1, kinds)
        self.assertIn(0, kinds)
        self.assertEqual(kinds[-1], 0)

        bot2 = FakeBot()
        group_event = make_event(text, group="1")
        group_event.bot = bot2
        result2 = make_result(text)
        group_event.set_result(result2)
        group_event.send = fake_send
        asyncio.run(self.plugin.on_decorating_result(group_event))
        self.assertEqual(bot2.calls, [])

    # -- verify --------------------------------------------------------------------

    def test_verify_suffix_and_log_only(self):
        self.plugin.config.update({"verify_enabled": True, "verify_log_only": False})
        text = "这个方法保证成功，绝对有效，我用了都说好。据统计有效率百分之百，你快试试吧效果很好。"
        _event, result, sent = self._decorate(text)
        full = "".join(sent) + chain_text(result.chain)
        self.assertIn("不太确定", full)
        self.plugin.config["verify_log_only"] = True
        _event, result, sent = self._decorate(text)
        full = "".join(sent) + chain_text(result.chain)
        self.assertNotIn("不太确定", full)

    def test_session_blacklist(self):
        event = make_event("我今天下午去了一趟书店，买了两本小说。一本是科幻。", group="1")
        self.plugin.config["session_blacklist"] = [event.unified_msg_origin]
        result = make_result("我今天下午去了一趟书店，买了两本小说。一本是科幻。")
        event.set_result(result)
        event.send = lambda chain: (_ for _ in ()).throw(AssertionError("must not send"))
        asyncio.run(self.plugin.on_decorating_result(event))
        self.assertEqual(len(result.chain), 1)

    # -- panel apis ------------------------------------------------------------------

    def test_page_config_save_whitelist(self):
        plugin_main.request = FakeRequest(
            body={"values": {"delay_enabled": False, "delay_base_seconds": 99, "nope": 1}}
        )
        try:
            data = json.loads(asyncio.run(self.plugin.page_config_save()).body.decode("utf-8"))
            self.assertFalse(data["changed"]["delay_enabled"])
            self.assertNotIn("delay_base_seconds", data["changed"])
            self.assertNotIn("nope", data["changed"])
            self.assertEqual(self.plugin.config["delay_base_seconds"], 0.0)
        finally:
            plugin_main.request = FakeRequest()
        plugin_main.request = FakeRequest(body={"nope": 1})
        try:
            self.assertEqual(asyncio.run(self.plugin.page_config_save()).status_code, 400)
        finally:
            plugin_main.request = FakeRequest()


if __name__ == "__main__":
    unittest.main()
