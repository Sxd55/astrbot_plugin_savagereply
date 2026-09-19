"""Offline tests for Savage's Reply: policy, segment, pacing, config.

Run: python tests/test_core.py -v
"""

from __future__ import annotations

import asyncio
import random
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from savagereply.config import ReplyOptions  # noqa: E402
from savagereply.marker import build_marker_prompt, parse_marker  # noqa: E402
from savagereply.pacing import read_delay, segment_delay  # noqa: E402
from savagereply.policy import MODE_BYPASS, MODE_SPLIT, decide, is_markdown_table  # noqa: E402
from savagereply.segment import segments_from_marked, split_text, strip_emphasis  # noqa: E402
from savagereply.typing_status import set_input_status, should_show_typing  # noqa: E402
from savagereply.verify import scan_risks  # noqa: E402


def opts(**overrides) -> ReplyOptions:
    base = {
        "segment_min_chars": 8,
        "segment_max_chars": 40,
        "segment_hard_max_chars": 80,
        "max_segments": 5,
        "short_tail_chars": 6,
        "keep_punct": True,
        "delay_enabled": True,
    }
    base.update(overrides)
    return ReplyOptions(**base).clamped()


class ConfigTest(unittest.TestCase):
    def test_defaults(self):
        options = ReplyOptions.from_config({})
        self.assertTrue(options.enabled)
        self.assertTrue(options.delay_enabled)
        self.assertEqual(options.segment_min_chars, 15)
        self.assertEqual(options.segment_max_chars, 50)
        self.assertIn("qq_official", options.platform_exclude)

    def test_type_coercion_and_clamp(self):
        options = ReplyOptions.from_config(
            {
                "segment_min_chars": "20",
                "segment_max_chars": 10,
                "max_segments": -3,
                "delay_per_char_seconds": "0.05",
            }
        )
        self.assertEqual(options.segment_min_chars, 20)
        self.assertEqual(options.segment_max_chars, 20)
        self.assertEqual(options.segment_hard_max_chars, 120)
        self.assertEqual(options.max_segments, 1)
        self.assertAlmostEqual(options.delay_per_char_seconds, 0.05)

    def test_list_coercion(self):
        options = ReplyOptions.from_config({"platform_exclude": "a, b\nc"})
        self.assertEqual(options.platform_exclude, ["a", "b", "c"])
        options = ReplyOptions.from_config({"platform_exclude": None})
        self.assertIn("dingtalk", options.platform_exclude)


class PolicyTest(unittest.TestCase):
    def test_code_block_bypass(self):
        decision = decide("看这段：\n```py\nprint(1)\n```", opts())
        self.assertEqual(decision.mode, MODE_BYPASS)
        self.assertEqual(decision.reason, "code_block")

    def test_table_bypass(self):
        decision = decide("| a | b |\n| c | d |", opts())
        self.assertEqual(decision.reason, "table")

    def test_math_bypass(self):
        decision = decide("公式：$$x^2 + y^2 = z^2$$", opts())
        self.assertEqual(decision.reason, "math")
        self.assertTrue(decide("行内 $x$ 公式", opts(min_total_chars=5)).mode == MODE_SPLIT)

    def test_too_long_bypass(self):
        options = opts(max_total_chars=50)
        decision = decide("好。" * 40, options)
        self.assertEqual(decision.reason, "long")
        self.assertEqual(decision.mode, MODE_SPLIT)

    def test_way_too_long_still_bypass(self):
        options = opts(max_total_chars=50)
        decision = decide("好。" * 300, options)
        self.assertEqual(decision.reason, "too_long")
        self.assertEqual(decision.mode, MODE_BYPASS)

    def test_too_short_bypass(self):
        options = opts(min_total_chars=10)
        decision = decide("好的", options)
        self.assertEqual(decision.reason, "too_short")

    def test_split(self):
        options = opts(min_total_chars=10, max_total_chars=500)
        decision = decide("我今天去书店买了两本小说。一本科幻一本推理。", options)
        self.assertEqual(decision.mode, MODE_SPLIT)

    def test_table_detection(self):
        self.assertTrue(is_markdown_table("| a | b |\n| - | - |"))
        self.assertFalse(is_markdown_table("| a | b |"))
        self.assertFalse(is_markdown_table("普通文本 | 带管道"))

    def test_structured_analysis_bypass(self):
        text_list = (
            "本月数据表现分析如下：\n"
            "1. 整体可用率维持在 99.98% 以上\n"
            "2. 平均延迟降低 15ms，吞吐提升 30%\n"
            "3. 慢查询总量较上月缩减 80%"
        )
        decision = decide(text_list, opts(min_total_chars=10))
        self.assertEqual(decision.mode, MODE_BYPASS)
        self.assertEqual(decision.reason, "structured_data")

        # 关掉开关后正常走 split
        decision_off = decide(text_list, opts(min_total_chars=10, protect_structured_data=False))
        self.assertEqual(decision_off.mode, MODE_SPLIT)


class SegmentTest(unittest.TestCase):
    def test_simple_split(self):
        text = "我今天去书店买了两本小说。一本科幻，一本推理。"
        segments = split_text(text, opts())
        self.assertEqual(
            segments,
            ["我今天去书店买了两本小说。", "一本科幻，一本推理。"],
        )

    def test_short_tail_merge(self):
        text = "我们今天下午一起去公园散步。好的。"
        segments = split_text(text, opts(short_tail_chars=6))
        self.assertEqual(len(segments), 1)
        self.assertEqual(segments[0], "我们今天下午一起去公园散步。好的。")

    def test_max_segments(self):
        text = "这是第一句话内容。这是第二句话内容。这是第三句话内容。这是第四句话内容。"
        segments = split_text(text, opts(max_segments=3))
        self.assertEqual(len(segments), 3)
        self.assertEqual(
            segments[-1],
            "这是第三句话内容。\n这是第四句话内容。",
        )

    def test_keep_punct_false(self):
        text = "你好吗？今天天气真不错啊。我打算出门走走。"
        segments = split_text(text, opts(keep_punct=False))
        self.assertEqual(segments, ["你好吗？今天天气真不错啊", "我打算出门走走"])

    def test_code_fence_protected(self):
        text = "看这段代码。\n```python\nprint('你好。世界')\n```\n就这样。"
        segments = split_text(text, opts(short_tail_chars=0))
        self.assertEqual(len(segments), 2)
        self.assertIn("```python\nprint('你好。世界')\n```", segments[0])

    def test_inline_code_protected(self):
        text = "试试 `a。b` 这个写法，然后再看看效果如何。"
        segments = split_text(text, opts(short_tail_chars=0))
        joined = "".join(segments)
        self.assertIn("`a。b`", joined)

    def test_pair_protection(self):
        text = "他说（你真的很厉害。真的。）然后。"
        segments = split_text(text, opts())
        self.assertEqual(len(segments), 1)
        self.assertIn("你真的很厉害。真的。", segments[0])

    def test_quote_pair_protection(self):
        text = "他回了一句“别急。马上到。”就先忙去了。"
        segments = split_text(text, opts(short_tail_chars=0))
        self.assertEqual(len(segments), 1)
        self.assertIn("别急。马上到。", segments[0])

    def test_hard_max_force_cut(self):
        text = "啊" * 30 + "。"
        segments = split_text(
            text,
            opts(segment_min_chars=5, segment_max_chars=10, segment_hard_max_chars=12, short_tail_chars=0),
        )
        self.assertEqual(len(segments), 3)
        self.assertEqual(len(segments[0]), 12)
        self.assertEqual(len(segments[1]), 12)

    def test_hard_max_keeps_punct_with_segment(self):
        text = "啊" * 11 + "。" + "啊" * 20
        segments = split_text(
            text,
            opts(segment_min_chars=5, segment_max_chars=10, segment_hard_max_chars=12, short_tail_chars=0),
        )
        self.assertTrue(segments[0].endswith("。"))
        for segment in segments:
            self.assertFalse(segment.startswith("。"))

    def test_weak_punct_fallback(self):
        text = "这是一句非常非常长的话，后面还有很多内容。"
        segments = split_text(text, opts(segment_max_chars=8, short_tail_chars=0))
        self.assertEqual(len(segments), 2)
        self.assertTrue(segments[0].endswith("，"))

    def test_newline_split(self):
        text = "今天去爬山了\n山上风很大\n不过很开心"
        segments = split_text(text, opts(segment_min_chars=5, short_tail_chars=0))
        # 「不过很开心」是上一句的转折接续，不该单独成条（P0 衔接守卫）。
        self.assertEqual(segments, ["今天去爬山了", "山上风很大\n不过很开心"])

    def test_think_block_protected(self):
        text = "<think>这里有很多标点。不应该切开。真的！</think>回答是好的。"
        segments = split_text(text, opts(short_tail_chars=0))
        self.assertEqual(len(segments), 1)
        self.assertIn("</think>", segments[0])

    def test_table_row_not_broken(self):
        text = "| 名称 | 数量 |\n| 苹果 | 3 |"
        segments = split_text(text, opts(segment_min_chars=5, short_tail_chars=0))
        self.assertEqual(segments, ["| 名称 | 数量 |", "| 苹果 | 3 |"])

    def test_url_stays_whole(self):
        text = "参考这个链接 https://example.com/a/b?c=1&d=2 就行了。"
        segments = split_text(text, opts(short_tail_chars=0))
        self.assertEqual(len(segments), 1)
        self.assertIn("https://example.com/a/b?c=1&d=2", segments[0])

    def test_no_empty_segments(self):
        segments = split_text("。！？\n\n。", opts())
        for segment in segments:
            self.assertTrue(segment.strip())

    def test_emoji_line_not_alone(self):
        text = "今天聊得很开心。\n\n🙂\n\n下次再聊点别的吧。"
        segments = split_text(text, opts(short_tail_chars=0))
        self.assertEqual(len(segments), 2)
        for segment in segments:
            self.assertGreaterEqual(len(segment), 2)
        self.assertIn("🙂", segments[1])

    def test_tiny_segment_merged(self):
        text = "晚安，做个好梦。\n\n🙂"
        segments = split_text(text, opts(short_tail_chars=0))
        self.assertEqual(len(segments), 1)
        self.assertIn("🙂", segments[0])

    def test_english_without_chinese_punct_not_split(self):
        text = "This is a long English sentence without Chinese punctuation and it stays whole."
        segments = split_text(text, opts())
        self.assertEqual(len(segments), 1)

    # -- Markdown 加粗（实机踩过：用户看到 **） ---------------------------

    def test_strip_emphasis_pairs(self):
        self.assertEqual(strip_emphasis("这是**加粗**的话。"), "这是加粗的话。")
        self.assertEqual(strip_emphasis("__下划线加粗__也要处理。"), "下划线加粗也要处理。")

    def test_strip_emphasis_keeps_code_and_singles(self):
        self.assertEqual(strip_emphasis("算式 2*3*4 不能动。"), "算式 2*3*4 不能动。")
        self.assertEqual(strip_emphasis("行内 `a**b` 不动。"), "行内 `a**b` 不动。")
        self.assertEqual(strip_emphasis("```py\nx = a ** b\n```"), "```py\nx = a ** b\n```")
        self.assertEqual(strip_emphasis("只有一个**星号。"), "只有一个**星号。")

    def test_split_does_not_break_emphasis_pair(self):
        text = "前面铺垫一些字，**加粗里也有逗号，而且很长很长，长到超过分段上限**，后面继续。"
        options = opts(
            segment_max_chars=30,
            segment_hard_max_chars=60,
            strip_markdown_marks=False,
            short_tail_chars=0,
        )
        segments = split_text(text, options)
        for segment in segments:
            self.assertNotEqual(segment.count("**"), 1, segment)
        self.assertEqual(sum(segment.count("**") for segment in segments), 2)

    # -- P0 增补 ---------------------------------------------------------

    def test_hard_max_keeps_english_word_whole(self):
        text = "啊" * 10 + "HelloWorld" + "啊" * 20
        segments = split_text(
            text,
            opts(segment_min_chars=5, segment_max_chars=10, segment_hard_max_chars=12, short_tail_chars=0),
        )
        self.assertTrue(any("HelloWorld" in segment for segment in segments))
        for segment in segments:
            self.assertNotIn("Hello", segment.replace("HelloWorld", ""))

    def test_hard_max_keeps_number_whole(self):
        text = "啊" * 10 + "20260915" + "啊" * 20
        segments = split_text(
            text,
            opts(segment_min_chars=5, segment_max_chars=10, segment_hard_max_chars=12, short_tail_chars=0),
        )
        self.assertTrue(any("20260915" in segment for segment in segments))

    def test_hard_max_keeps_digit_measure_word_together(self):
        text = "字" * 11 + "3个" + "字" * 20
        segments = split_text(
            text,
            opts(segment_min_chars=5, segment_max_chars=10, segment_hard_max_chars=12, short_tail_chars=0),
        )
        joined = "|".join(segments)
        self.assertIn("3个", joined)
        self.assertNotIn("|3个", joined)

    def test_continuation_guard_no_split_before_conjunction(self):
        text = "我想点杯咖啡和蛋糕，因为下午还要加班。"
        segments = split_text(text, opts(segment_max_chars=8, short_tail_chars=0))
        for segment in segments:
            self.assertFalse(segment.startswith(("和", "因为", "所以", "但是")))

    def test_anaphora_guard_no_split_before_pronoun(self):
        text = "刚买的书到了，它的封面特别好看。"
        segments = split_text(text, opts(segment_max_chars=8, short_tail_chars=0))
        for segment in segments:
            self.assertFalse(segment.startswith("它"))

    def test_long_reply_splits_by_paragraphs(self):
        para = "这是一段比较长的说明文字，用来验证超长回复会按空行段落切分。"
        text = "\n\n".join([para] * 4)
        options = opts(max_total_chars=60, paragraph_max_chars=60, max_segments=8, short_tail_chars=0)
        segments = split_text(text, options)
        self.assertGreater(len(segments), 1)
        self.assertEqual(segments[0], para)
        self.assertTrue(all(len(segment) <= 60 for segment in segments))

    def test_long_reply_merges_short_paragraphs(self):
        text = "\n\n".join(["第一点说明到了。", "第二点也在这里。", "第三点是最后。"] * 6)
        options = opts(max_total_chars=50, paragraph_max_chars=200, max_segments=8, short_tail_chars=0)
        segments = split_text(text, options)
        self.assertLess(len(segments), 6)
        for segment in segments:
            self.assertLessEqual(len(segment), 200)

    def test_question_tail_not_merged(self):
        text = "这个方法你可以试试看效果如何。要不要我现在就发给你？"
        segments = split_text(text, opts(short_tail_chars=20))
        self.assertTrue(segments[-1].endswith("？"))
        self.assertNotIn("这个方法", segments[-1])

    def test_question_tail_kept_without_punct(self):
        segments = split_text("先把文件发我一下。要现在发吗", opts(keep_punct=False, short_tail_chars=20))
        self.assertEqual(len(segments), 2)
        self.assertEqual(segments[-1], "要现在发吗")

    def test_unbalanced_bracket_does_not_block_splitting(self):
        # 验证单边未闭合括号（如「（笑」）不会让整个长文本的分段引擎瘫痪
        text = "前面是一句话（笑。后面是一句很长很长的话，这里有句号。还有第三句很长很长的话！最后收尾。"
        segments = split_text(text, opts(segment_max_chars=20, segment_hard_max_chars=40, short_tail_chars=0))
        self.assertGreater(len(segments), 1)


class PacingTest(unittest.TestCase):
    def test_formula_no_jitter(self):
        options = opts(
            delay_base_seconds=1.0,
            delay_per_char_seconds=0.1,
            delay_punct_bonus_seconds=0.5,
            delay_jitter=0.0,
            delay_max_seconds=10.0,
        )
        self.assertAlmostEqual(segment_delay("你好。", options), 1.8)
        self.assertAlmostEqual(segment_delay("你好", options), 1.2)

    def test_jitter_bounds(self):
        options = opts(
            delay_base_seconds=1.0,
            delay_per_char_seconds=0.1,
            delay_punct_bonus_seconds=0.0,
            delay_jitter=0.2,
            delay_max_seconds=10.0,
        )
        rng = random.Random(42)
        for _ in range(50):
            delay = segment_delay("你好世界", options, rng=rng)
            self.assertGreaterEqual(delay, 1.4 * 0.8)
            self.assertLessEqual(delay, 1.4 * 1.2 + 1e-9)

    def test_max_cap(self):
        options = opts(
            delay_base_seconds=1.0,
            delay_per_char_seconds=0.1,
            delay_punct_bonus_seconds=0.5,
            delay_jitter=0.0,
            delay_max_seconds=2.0,
        )
        self.assertAlmostEqual(segment_delay("字" * 200 + "。", options), 2.0)

    def test_empty(self):
        self.assertEqual(segment_delay("", opts()), 0.0)
        self.assertEqual(segment_delay("   ", opts()), 0.0)

    def test_delay_disabled(self):
        self.assertEqual(segment_delay("你好。", opts(delay_enabled=False)), 0.0)

    def test_read_delay_range(self):
        options = opts(read_delay_min_seconds=0.5, read_delay_max_seconds=1.5)
        rng = random.Random(7)
        for _ in range(50):
            delay = read_delay(options, rng=rng)
            self.assertGreaterEqual(delay, 0.5)
            self.assertLessEqual(delay, 1.5)

    def test_read_delay_disabled_and_zero(self):
        self.assertEqual(read_delay(opts(delay_enabled=False)), 0.0)
        self.assertEqual(read_delay(opts(read_delay_min_seconds=0, read_delay_max_seconds=0)), 0.0)

    def test_read_delay_clamped(self):
        options = ReplyOptions.from_config({"read_delay_min_seconds": 2.0, "read_delay_max_seconds": 1.0})
        self.assertAlmostEqual(options.read_delay_min_seconds, 2.0)
        self.assertAlmostEqual(options.read_delay_max_seconds, 2.0)


class VerifyTest(unittest.TestCase):
    def test_disabled_returns_empty(self):
        self.assertEqual(scan_risks("这个方法100%有效", opts(verify_enabled=False)), [])

    def test_absolute_word(self):
        risks = scan_risks("这个方法100%有效", opts(verify_enabled=True))
        self.assertTrue(any(risk.kind == "absolute" for risk in risks))

    def test_vague_source(self):
        risks = scan_risks("根据最新研究显示，这样做更好", opts(verify_enabled=True))
        self.assertTrue(any(risk.kind == "vague_source" for risk in risks))

    def test_unmentioned_url(self):
        risks = scan_risks(
            "可以参考 https://fake-example.com/doc 里的说法",
            opts(verify_enabled=True),
            user_text="给我个链接",
        )
        self.assertTrue(any(risk.kind == "unmentioned_url" for risk in risks))

    def test_mentioned_url_not_flagged(self):
        risks = scan_risks(
            "参考 https://example.com/doc",
            opts(verify_enabled=True),
            user_text="看看 example.com 上怎么说",
        )
        self.assertFalse(any(risk.kind == "unmentioned_url" for risk in risks))

    def test_clean_text_no_risk(self):
        self.assertEqual(scan_risks("今天天气不错，出去走走？", opts(verify_enabled=True)), [])

    def test_risk_cap(self):
        text = "100%有效，根据研究显示，见 https://a.com https://b.com https://c.com https://d.com"
        risks = scan_risks(text, opts(verify_enabled=True))
        self.assertLessEqual(len(risks), 3)


class MarkerTest(unittest.TestCase):
    def test_basic_split(self):
        text, parts = parse_marker("你好。[[next]]在吗？")
        self.assertEqual(parts, ["你好。", "在吗？"])
        self.assertEqual(text, "你好。在吗？")

    def test_no_marker(self):
        text, parts = parse_marker("普通文本")
        self.assertIsNone(parts)
        self.assertEqual(text, "普通文本")

    def test_marker_inside_code_fence_ignored(self):
        source = "看代码：\n```py\nprint('[[next]]')\n```\n就这样"
        text, parts = parse_marker(source)
        self.assertIsNone(parts)
        self.assertEqual(text, source)

    def test_marker_outside_code_fence(self):
        source = "第一句。[[next]]\n```py\nprint(1)\n```"
        text, parts = parse_marker(source)
        self.assertEqual(parts, ["第一句。", "```py\nprint(1)\n```"])

    def test_single_effective_segment(self):
        text, parts = parse_marker("[[next]]只有一段")
        self.assertIsNone(parts)
        self.assertEqual(text, "只有一段")

    def test_empty_segments_filtered(self):
        text, parts = parse_marker("第一。[[next]][[next]]第二。")
        self.assertEqual(parts, ["第一。", "第二。"])

    def test_marker_inside_inline_code_ignored(self):
        text, parts = parse_marker("用 `a[[next]]b` 再说")
        self.assertIsNone(parts)
        self.assertEqual(text, "用 `a[[next]]b` 再说")

    # -- 容错：模型少写一层括号 / 全角 / 大小写（实机踩过） ----------------

    def test_single_bracket_marker(self):
        text, parts = parse_marker("第一段。[next]第二段。[next]第三段。")
        self.assertEqual(parts, ["第一段。", "第二段。", "第三段。"])
        self.assertEqual(text, "第一段。第二段。第三段。")

    def test_single_bracket_with_newlines(self):
        text, parts = parse_marker("嘴上带刺。[next]\n\n底下是软的。\n[next]\n还有一句。")
        self.assertEqual(parts, ["嘴上带刺。", "底下是软的。", "还有一句。"])
        self.assertNotIn("[next]", text)

    def test_fullwidth_markers(self):
        text, parts = parse_marker("甲。【next】乙。［next］丙。")
        self.assertEqual(parts, ["甲。", "乙。", "丙。"])

    def test_case_insensitive_marker(self):
        text, parts = parse_marker("甲。[NEXT]乙。[Next]")
        self.assertEqual(parts, ["甲。", "乙。"])

    def test_mixed_variants(self):
        text, parts = parse_marker("一。[[next]]二。[next]三。【next】四。")
        self.assertEqual(parts, ["一。", "二。", "三。", "四。"])

    def test_single_bracket_inside_code_ignored(self):
        source = "```js\nconst a = b[next];\n```\n正文"
        text, parts = parse_marker(source)
        self.assertIsNone(parts)
        self.assertEqual(text, source)

    def test_word_containing_next_not_marker(self):
        text, parts = parse_marker("next 是下一个的意思，[next] 才是标记。")
        self.assertEqual(parts, ["next 是下一个的意思，", "才是标记。"])

    def test_build_prompt(self):
        prompt = build_marker_prompt(5)
        self.assertIn("[[next]]", prompt)
        self.assertIn("5", prompt)
        self.assertIn("两层方括号", prompt)

    # -- 标记空壳 / 括号残渣（实机踩过：用户看到 [[]]） --------------------

    def test_empty_debris_removed(self):
        for source in ("甲。[[]]乙。", "甲。[[]] 乙。", "甲。[[  ]]乙。"):
            text, parts = parse_marker(source)
            self.assertNotIn("[[]]", text)
            self.assertEqual(text, "甲。乙。", source)

    def test_single_bracket_and_checkbox_preserved(self):
        # 验证单层空括号、Markdown 复选框、空列表不会被误当 marker 残渣吃掉
        for source in ("- [ ] 待办事项", "arr = []", "请在【】中填写"):
            text, parts = parse_marker(source)
            self.assertIsNone(parts)
            self.assertEqual(text, source)

    def test_unbalanced_marker_fully_consumed(self):
        for source in ("甲。[[next]乙。", "甲。[[next]]]乙。", "甲。[[[next]]]乙。", "甲。[[next乙。"):
            text, parts = parse_marker(source)
            self.assertEqual(text, "甲。乙。", source)
            self.assertNotIn("[", text)

    def test_debris_inside_code_kept(self):
        source = "```py\narr = x[[]]\n```\n正文"
        text, parts = parse_marker(source)
        self.assertEqual(text, source)

    def test_segments_from_marked_respects_limit(self):
        options = opts(max_segments=2, short_tail_chars=0)
        parts = ["第一段内容足够长。", "第二段内容足够长。", "第三段内容足够长。"]
        segments = segments_from_marked(parts, options)
        self.assertEqual(len(segments), 2)


class TypingTest(unittest.TestCase):
    def test_should_show_typing(self):
        self.assertTrue(should_show_typing("aiocqhttp", False))
        self.assertFalse(should_show_typing("aiocqhttp", True))
        self.assertFalse(should_show_typing("telegram", False))

    def test_set_input_status_without_bot(self):
        self.assertFalse(asyncio.run(set_input_status(None, "123", 1)))

    def test_set_input_status_bad_id(self):
        class Bot:
            async def call_action(self, *args, **kwargs):
                raise AssertionError("should not be called")

        self.assertFalse(asyncio.run(set_input_status(Bot(), "abc", 1)))

    def test_set_input_status_ok(self):
        calls = []

        class Bot:
            async def call_action(self, action, **kwargs):
                calls.append((action, kwargs))

        self.assertTrue(asyncio.run(set_input_status(Bot(), "10001", 1)))
        self.assertEqual(calls[0][0], "set_input_status")
        self.assertEqual(calls[0][1]["user_id"], 10001)
        self.assertEqual(calls[0][1]["event_type"], 1)

    def test_set_input_status_swallows_errors(self):
        class Bot:
            async def call_action(self, action, **kwargs):
                raise RuntimeError("napcat offline")

        self.assertFalse(asyncio.run(set_input_status(Bot(), "10001", 0)))


if __name__ == "__main__":
    unittest.main()
